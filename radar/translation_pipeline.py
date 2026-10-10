"""Prefer validated whole-field Gemini output, then bounded legacy NLLB fallback."""

import json
from pathlib import Path
import re
import threading
import time

from radar import translate as nllb
from radar import translation_gemini as gemini
from radar.translation_budget import reserve, rotate_sources, cooling_sources, record_failures, _source_id
from radar.reader_priority import ordered_stories, load_editor_picks
from radar import gemini_paid_budget

QUOTED = re.compile(r'"[^"\n]+"|(?<!\w)\'[^\'\n]+\'(?!\w)|`[^`\n]+`')
# Distinctive positions reveal unknown identities without freezing every Title Case word.
IDENTITY = re.compile(r"(?:\b(?:Introducing|Announcing|Launching|called|named|using|with)\s+)"
                      r"([A-Z][A-Za-z0-9_.+-]*(?:\s+[A-Z][A-Za-z0-9_.+-]*){0,3}"
                      r"(?:\s+[0-9][A-Za-z0-9_.+-]*)?)")


AI_BRAND = re.compile(r"\b([A-Z][A-Za-z0-9_.+-]*\s+AI)\s+(?:Unveils?|Launches?|Announces?|Raises?|Releases?|Introduces?|Debuts?|Expands?|Partners?|Backs?|Opens?|Signs?|Tests?|Shows?|Pitches?)\b")


def protected_names(source, names):
    names = nllb._names(source, names)
    names.update(match.group(1) for match in IDENTITY.finditer(source))
    names.update(match.group(1) for match in AI_BRAND.finditer(source))
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
            metadata = response.get("usageMetadata", {}) if isinstance(response, dict) else {}
            state["tokens"] = metadata.get("totalTokenCount", 0) if isinstance(metadata, dict) else 0
        except gemini.ProviderError as error:
            code = str(error)
            state["error"] = code if gemini.HTTP_CODE_PATTERN.fullmatch(code) or code in {
                "http_error", "transport_error",
                "malformed_response", "response_too_large", "invalid_response"} else "provider_error"
        except Exception:
            state["error"] = "provider_error"

    worker = threading.Thread(target=work, daemon=True, name="radar-gemini")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return {}, "timeout", True, 0
    return state.get("outputs", {}), state.get("error"), False, state.get("tokens", 0)


def collect_prior_translations(payload, previous=None):
    """Collect valid prior translations (source -> translation) from previous snapshot and/or current payload."""
    priors = {}

    def extract_from(data):
        if isinstance(data, (str, Path)):
            try:
                data = json.loads(Path(data).read_text(encoding="utf-8"))
            except Exception:
                return
        if not isinstance(data, dict):
            return
        for obj, src, dst in nllb.targets(data):
            val = obj.get(dst)
            if isinstance(val, str) and val.strip():
                source = nllb.normalize(obj[src])
                priors[source] = val
        for story in data.get("stories") or []:
            if isinstance(story, dict):
                if isinstance(story.get("title_vi"), str) and story["title_vi"].strip() and story.get("title"):
                    priors.setdefault(nllb.normalize(story["title"]), story["title_vi"])
                if isinstance(story.get("summary_vi"), str) and story["summary_vi"].strip() and story.get("summary"):
                    priors.setdefault(nllb.normalize(story["summary"]), story["summary_vi"])
                for item in story.get("coverage") or []:
                    if isinstance(item, dict):
                        if isinstance(item.get("title_vi"), str) and item["title_vi"].strip() and item.get("title"):
                            priors.setdefault(nllb.normalize(item["title"]), item["title_vi"])
                        if isinstance(item.get("summary_vi"), str) and item["summary_vi"].strip() and item.get("summary"):
                            priors.setdefault(nllb.normalize(item["summary"]), item["summary_vi"])
        for item in data.get("live") or []:
            if isinstance(item, dict) and isinstance(item.get("title_vi"), str) and item["title_vi"].strip() and item.get("title"):
                priors.setdefault(nllb.normalize(item["title"]), item["title_vi"])
        for repo in data.get("repos") or []:
            if isinstance(repo, dict) and isinstance(repo.get("description_vi"), str) and repo["description_vi"].strip() and repo.get("description"):
                priors.setdefault(nllb.normalize(repo["description"]), repo["description_vi"])

    if previous:
        extract_from(previous)
    extract_from(payload)
    return priors


def translate_payload(payload, nllb_cache, gemini_cache, *, config=None, transport=None,
                      ledger_path=None, factory=None, budget=600, clock=time.monotonic,
                      now=time.time, provider="auto", previous=None, editor_picks=None):
    started = clock()
    config = config or gemini.config_from_env()
    transport = transport or gemini.transport
    prior_candidates = collect_prior_translations(payload, previous)
    nllb.clear_translations(payload)
    rows, groups = nllb.targets(payload), {}
    if config.paid:
        ordered, active = ordered_stories(payload, editor_picks if editor_picks is not None else load_editor_picks())
        positions = {id(story): index for index, story in enumerate(ordered)}
        front = {id(story) for story in ordered[:60] if id(story) in active}
        rows.sort(key=lambda row: (0 if id(row[0]) in front and row[1] == "title" else
                                   1 if id(row[0]) in active and row[1] == "title" else
                                   2 if row[1] == "title" else 3,
                                   positions.get(id(row[0]), len(ordered))))
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
        # Restore published and local model cache before spending on upgrades.
        if config.paid:
            for source, group in groups.items():
                if source in accepted:
                    continue
                output = validated(source, prior_candidates.get(source), group["names"])
                if output:
                    accepted[source] = (output, "kept")
                    continue
                output, _ = nllb.compose(source, nllb_cache, protected_names=group["names"])
                output = validated(source, output, group["names"])
                if output:
                    accepted[source] = (output, "nllb")
        cooling = cooling_sources(ledger_path, now())
        api["cooldown_skipped"] = sum(_source_id(source) in cooling for source in groups if source not in accepted)
        sources = list(groups) if config.paid else rotate_sources(ledger_path, list(groups))
        missing = [source for source in sources if source not in accepted and _source_id(source) not in cooling]
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
            for _ in range(config.max_requests):
                items, chars = [], 0
                for source in missing:
                    if source in accepted or len(source) > config.max_chars:
                        continue
                    if len(items) >= config.batch_size or chars + len(source) > config.max_chars:
                        break
                    items.append(dict(id=str(len(items)), text=source, roles=sorted(groups[source]["roles"]),
                                      protected_names=sorted(groups[source]["names"])))
                    chars += len(source)
                if config.paid:
                    headroom = gemini_paid_budget.remaining_tokens(gemini_paid_budget.ledger_path(), "translation", now=now())
                    while items and len(json.dumps(gemini.request_body(items)).encode("utf-8")) + gemini.MAX_OUTPUT_TOKENS > headroom:
                        items.pop()
                if not items:
                    api["error"] = ("paid_translation_daily_tokens" if config.paid else "input_limit") if not api["requests"] else None
                    break
                paid_reservation = None
                if config.paid:
                    body = gemini.request_body(items)
                    estimated_tokens = len(json.dumps(body).encode("utf-8")) + gemini.MAX_OUTPUT_TOKENS
                    api["error"], paid_reservation = gemini_paid_budget.reserve(
                        gemini_paid_budget.ledger_path(), estimated_tokens, now=now(), consumer="translation")
                else:
                    api["error"] = reserve(ledger_path, config.daily_limit, now(), last_source=items[-1]["text"])
                if api["error"]:
                    break
                remaining = min(config.timeout, max(0, budget - (clock() - started)))
                if remaining <= 0:
                    api["error"] = "time_budget"
                    break
                outputs, request_error, request_alive, used_tokens = _request(items, config, transport, remaining)
                api["requests"] += 1
                api["tokens"] = api.get("tokens", 0) + used_tokens
                api_alive = api_alive or request_alive
                if config.paid:
                    gemini_paid_budget.settle(gemini_paid_budget.ledger_path(), paid_reservation,
                                              used_tokens, now=now())
                for item in items:
                    source = item["text"]
                    output = validated(source, outputs.get(item["id"]), groups[source]["names"])
                    if output:
                        gemini_cache[source] = output
                        accepted[source] = (output, "gemini")
                        api["translated"] += 1
                if request_error:
                    api["error"] = request_error
                    break
                rejected = [item["text"] for item in items if item["text"] not in accepted]
                if rejected:
                    persistence_error = record_failures(ledger_path, rejected, now())
                    api["error"] = persistence_error or "validation_rejected"
                    missing = [source for source in missing if source not in rejected]
                    if persistence_error:
                        break
            api["status"] = "failed" if api["error"] and not api["translated"] else "partial" if api["error"] else "ok"

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

    # Retain previously published translations for unresolved strings.
    # Kept translations are NOT saved to gemini_cache or nllb_cache,
    # ensuring subsequent runs can upgrade them when the provider recovers.
    for source, group in groups.items():
        if source not in accepted and source in prior_candidates:
            output = validated(source, prior_candidates[source], group["names"])
            if output:
                accepted[source] = (output, "kept")

    provider_counts = {name: sum(v[1] == name for v in accepted.values()) for name in ("gemini", "nllb", "kept")}
    providers = [name for name, count in provider_counts.items() if count]
    for source, (output, _) in accepted.items():
        for obj, _, dst in groups[source]["rows"]:
            obj[dst] = output
    pending = len(groups) - len(accepted)
    actual = providers[0] if len(providers) == 1 else "mixed" if providers else "original"
    models = {
        name: gemini.MODEL_ID if name == "gemini" else nllb.MODEL_ID if name == "nllb" else "previous"
        for name in providers
    }
    model = gemini.MODEL_ID if actual == "gemini" else nllb.MODEL_ID if actual == "nllb" else "previous" if actual == "kept" else None
    stats = dict(requested_provider=provider, provider=actual, providers=providers, provider_counts=provider_counts,
                 model=model,
                 models=models,
                 license=nllb.MODEL_LICENSE if "nllb" in providers else None,
                 status="ok" if not pending else "partial" if accepted else "failed",
                 strings=len(groups), translated=len(accepted), pending=pending, kept_original=kept,
                 kept_published=provider_counts["kept"],
                 rejected=fallback_stats.get("rejected", 0), rejected_examples=[], gemini=api,
                 model_loaded=fallback_stats.get("model_loaded", False), new_segments=fallback_stats.get("new_segments", 0),
                 seconds=round(clock() - started, 1),
                 error="fallback_error" if fallback_stats.get("error") and pending else None,
                 error_vi="Một số nội dung giữ nguyên bản gốc vì chưa có bản dịch hợp lệ." if pending else None)
    payload["translation"] = stats
    return stats, alive or api_alive
