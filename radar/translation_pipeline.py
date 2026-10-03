"""Prefer validated whole-field Gemini output, then bounded legacy NLLB fallback."""

import re
import threading
import time

from radar import translate as nllb
from radar import translation_gemini as gemini
from radar.translation_budget import reserve, rotate_sources

QUOTED = re.compile(r'"[^"\n]+"|(?<!\w)\'[^\'\n]+\'(?!\w)|`[^`\n]+`')
# Distinctive positions reveal unknown identities without freezing every Title Case word.
IDENTITY = re.compile(r"(?:\b(?:Introducing|Announcing|Launching|called|named|using|with)\s+)"
                      r"([A-Z][A-Za-z0-9_.+-]*(?:\s+[A-Z][A-Za-z0-9_.+-]*){0,3}"
                      r"(?:\s+[0-9][A-Za-z0-9_.+-]*)?)")


def protected_names(source, names):
    names = nllb._names(source, names)
    names.update(match.group(1) for match in IDENTITY.finditer(source))
    head = nllb.HEAD_NAME.match(source)
    if head:
        names.add(head.group().rstrip().rstrip(":"))
    for quote in QUOTED.findall(source):
        body = quote[1:-1]
        if quote.startswith("`") or re.fullmatch(r"[A-Z][A-Za-z0-9_.+-]*", body):
            names.add(body)
    return names


def validated(source, text, names):
    if not isinstance(text, str):
        return None
    output = nllb.apply_glossary(source, nllb.normalize(text), protected_names=names)
    if nllb.rejection(source, output, protected_names=names):
        return None
    # Paired-span matching alone misses a newly added, unmatched delimiter.
    if any(source.count(mark) != output.count(mark) for mark in ('"', '`')):
        return None
    if [quote[0] for quote in QUOTED.findall(source)] != [quote[0] for quote in QUOTED.findall(output)]:
        return None
    return output


def _request(items, config, transport, timeout):
    """A hung/trickling transport cannot overrun the pipeline deadline."""
    state = {}

    def work():
        try:
            response = transport(gemini.request_body(items), config.api_key, timeout)
            state["outputs"] = gemini.parse_response(response, {item["id"] for item in items})
        except gemini.ProviderError as error:
            code = str(error)
            state["error"] = code if code in {
                "http_401", "http_403", "http_429", "http_error", "transport_error",
                "malformed_response", "response_too_large", "invalid_response"} else "provider_error"
        except Exception:
            state["error"] = "provider_error"

    worker = threading.Thread(target=work, daemon=True, name="radar-gemini")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return {}, "timeout", True
    return state.get("outputs", {}), state.get("error"), False


def translate_payload(payload, nllb_cache, gemini_cache, *, config=None, transport=None,
                      ledger_path=None, factory=None, budget=600, clock=time.monotonic,
                      now=time.time, provider="auto"):
    started = clock()
    config = config or gemini.config_from_env()
    transport = transport or gemini.transport
    nllb.clear_translations(payload)
    rows, groups = nllb.targets(payload), {}
    names = nllb.payload_names(payload)
    kept = 0
    for obj, src, dst in rows:
        obj.pop(dst, None)
        if not nllb.needs_translation(obj[src]):
            kept += 1
            continue
        source = nllb.normalize(obj[src])
        group = groups.setdefault(source, dict(rows=[], names=set(), roles=set()))
        group["rows"].append((obj, src, dst))
        group["names"].update(protected_names(source, names | nllb.object_names(obj)))
        group["roles"].add(src)

    accepted, api_alive = {}, False
    api = dict(model=gemini.MODEL_ID, status="disabled", requests=0, cache_hits=0, translated=0, error=None)
    if provider != "nllb":
        for source, group in groups.items():
            output = validated(source, gemini_cache.get(source), group["names"])
            if output:
                accepted[source] = (output, "gemini")
                api["cache_hits"] += 1
            elif source in gemini_cache:
                del gemini_cache[source]
        missing = [source for source in rotate_sources(ledger_path, list(groups)) if source not in accepted]
        if not missing:
            api["status"] = "cache"
        elif not config.api_key:
            api["error"] = "missing_key"
        elif not config.confirmed:
            api["error"] = "free_tier_unconfirmed"
        elif not config.max_requests or not config.batch_size or not config.max_chars or not config.timeout:
            api["error"] = "request_limit"
        elif clock() - started >= budget:
            api["error"] = "time_budget"
        else:
            items, chars = [], 0
            for source in missing:
                if len(source) > config.max_chars:
                    continue
                if len(items) >= config.batch_size or chars + len(source) > config.max_chars:
                    break
                items.append(dict(id=str(len(items)), text=source, roles=sorted(groups[source]["roles"]),
                                  protected_names=sorted(groups[source]["names"])))
                chars += len(source)
            if not items:
                api["error"] = "input_limit"
            else:
                api["error"] = reserve(ledger_path, config.daily_limit, now(), last_source=items[-1]["text"])
                if not api["error"]:
                    remaining = min(config.timeout, max(0, budget - (clock() - started)))
                    if remaining <= 0:
                        api["error"] = "time_budget"
                    else:
                        api["requests"] = 1
                        outputs, api["error"], api_alive = _request(items, config, transport, remaining)
                        for item in items:
                            source = item["text"]
                            output = validated(source, outputs.get(item["id"]), groups[source]["names"])
                            if output:
                                gemini_cache[source] = output
                                accepted[source] = (output, "gemini")
                                api["translated"] += 1
                        if not api["error"] and api["translated"] != len(items):
                            api["error"] = "validation_rejected"
                        api["status"] = "failed" if api["error"] else "ok"
                        if api["error"] and api["translated"]:
                            api["status"] = "partial"

    # Full strings unresolved by Gemini become independent fallback rows. The
    # legacy segment cache remains exclusively NLLB and cannot block upgrades.
    fallback_rows = [dict(title=source) for source in groups if source not in accepted]
    fallback = dict(stories=fallback_rows, sources=payload.get("sources", []))
    remaining = max(0, budget - (clock() - started))
    # A zero budget may still apply existing NLLB cache, but must not load a model.
    if remaining <= 0:
        counts, _ = nllb.apply(fallback, nllb_cache)
        fallback_stats, alive = dict(**counts, model_loaded=False, new_segments=0, error="time_budget"), False
    else:
        fallback_stats, alive = nllb.translate_payload(fallback, nllb_cache, factory=factory,
                                                       budget=remaining, clock=clock)
    for row in fallback_rows:
        source = row["title"]
        output = validated(source, row.get("title_vi"), groups[source]["names"])
        if output:
            accepted[source] = (output, "nllb")
    provider_counts = {name: sum(v[1] == name for v in accepted.values()) for name in ("gemini", "nllb")}
    providers = [name for name, count in provider_counts.items() if count]
    for source, (output, _) in accepted.items():
        for obj, _, dst in groups[source]["rows"]:
            obj[dst] = output
    pending = len(groups) - len(accepted)
    actual = providers[0] if len(providers) == 1 else "mixed" if providers else "original"
    stats = dict(requested_provider=provider, provider=actual, providers=providers, provider_counts=provider_counts,
                 model=gemini.MODEL_ID if actual == "gemini" else nllb.MODEL_ID if actual == "nllb" else None,
                 models={name: gemini.MODEL_ID if name == "gemini" else nllb.MODEL_ID for name in providers},
                 license=nllb.MODEL_LICENSE if "nllb" in providers else None,
                 status="ok" if not pending else "partial" if accepted else "failed",
                 strings=len(groups), translated=len(accepted), pending=pending, kept_original=kept,
                 rejected=fallback_stats.get("rejected", 0), rejected_examples=[], gemini=api,
                 model_loaded=fallback_stats.get("model_loaded", False), new_segments=fallback_stats.get("new_segments", 0),
                 seconds=round(clock() - started, 1),
                 error="fallback_error" if fallback_stats.get("error") and pending else None,
                 error_vi="Một số nội dung giữ nguyên bản gốc vì chưa có bản dịch hợp lệ." if pending else None)
    payload["translation"] = stats
    return stats, alive or api_alive
