"""Optional machine translation of English headlines into Vietnamese.

The core pipeline stays stdlib-only. This module is a separate, optional step:
it reads a built snapshot, adds `title_vi` / `summary_vi` / `description_vi` next to the
original strings and records what happened under `translation`. The model
(NLLB-200, CC-BY-NC 4.0) is loaded lazily, so a runner without torch or
transformers still produces a valid page with the original titles.

Run: python -m radar.translate --input site/data/radar.json --cache data/translations-vi.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from radar.pipeline import write_atomic
from radar.site_payload import page_path, write_site_snapshot
from radar.translation_names import CATALOG_NAMES, name_pattern, names_in, object_names, payload_names

MODEL_ID = "facebook/nllb-200-distilled-600M"
# refs/pr/45 of the model repo: the only revision that carries model.safetensors
# (main ships pytorch_model.bin only). Pinned so the cached weights never drift.
MODEL_REVISION = "a3e77be725cf30383f1faeb8d2f0b0ea98ac554e"
MODEL_FILES = ["config.json", "generation_config.json", "special_tokens_map.json",
               "tokenizer.json", "tokenizer_config.json", "sentencepiece.bpe.model", "model.safetensors"]
MODEL_LICENSE = "CC-BY-NC-4.0"
CACHE_VERSION = 1
DEFAULT_BUDGET = 600.0
BATCH_SIZE = 16

VIETNAMESE = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹĂÂĐÊÔƠƯ]", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z]+(?:'[a-z]+)?")
# A sentence ends after a lowercase word or digit, never after an abbreviation such as "U.S.".
SENTENCE_END = re.compile(r"(?:(?<=[a-z0-9)\]\"'][.?!])|(?<=[?!]))\s+(?=[A-Z0-9\"'(])")
TAG = re.compile(r"^\[[^\]]{1,30}\]\s*")  # "[AINews] ...": a newsletter label, kept verbatim
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u00a0": " "})
DIGITS = re.compile(r"\d+")
# Names the model must carry through untouched: inner capitals (OpenShell, DevDay, xAI) or acronyms of 3+ letters.
NAME_TOKEN = re.compile(r"\b(?:[A-Za-z]*[a-z][A-Z][A-Za-z0-9]*|[A-Z]{3,})\b")
# Acronyms that are ordinary words with a Vietnamese rendering, not names.
COMMON_ACRONYMS = {"CEO", "CTO", "CFO", "COO", "USA", "FAQ", "DIY"}
# Model, training and data vocabulary: a term like "training" is about AI only next to one of these.
AI_CONTEXT = (r"(?=.*\b(?:AI|LLMs?|models?|neural|MoE|GPUs?|transformers?|parameters?|embeddings?|datasets?|data|"
              r"frontier|pre-?training|post-?training|weights?|inference|agents?|robots?|"
              r"GPT|Claude|Gemini|Grok|Llama|Qwen|Mistral|OpenAI|Anthropic|DeepMind)\b)")
# Digits a faithful translation may add: "September" -> "tháng 9", "Nine" -> "9".
NUMBER_WORDS = {str(i + 1): w for i, w in enumerate(
    "january|february|march|april|may|june|july|august|september|october|november|december".split("|"))}
SMALL_NUMBERS = {str(i): w for i, w in enumerate(
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve".split("|"))}

# Fixed openings are rendered by rule, not by the model, which varies them ("Tạo ra", "Mới thiệu").
PREFIXES = [
    (re.compile(r"^Introducing:?\s+"), "Ra mắt "),
    (re.compile(r"^Announcing:?\s+"), "Công bố "),
    (re.compile(r"^Launching:?\s+"), "Ra mắt "),
    (re.compile(r"^Quoting:?\s+"), "Trích lời "),
]
# What follows "Quoting" is always a person or an organisation.
VERBATIM_AFTER = {"Trích lời "}
# "Memorizon: Training world models": a one- or two-word name before a colon is kept as written.
HEAD_NAME = re.compile(r"^[A-Z][A-Za-z0-9.+_-]*(?: [A-Z0-9][A-Za-z0-9.+_-]*)?:\s+")
# "Why LLMs might hit a wall - Noam Brown": the speaker after a closing dash is kept as written.
TAIL_NAME = re.compile(r"\s+[-\u2013\u2014]\s+[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3}$")

# Post-translation term fixes. A rule fires only when the English source uses the term,
# so "nhân viên" stays "nhân viên" in a layoffs headline that never says "agent".
GLOSSARY = [
    (r"\bagent(s|ic)?\b", [
        (r"(?:đại lý|nhân viên|đặc vụ|tác nhân|người đại diện|điệp viên) (?:trí tuệ nhân tạo|AI)\b", "agent AI"),
        (r"(?:đại lý|nhân viên|đặc vụ|tác nhân|người đại diện|điệp viên)", "agent"),
    ]),
    (r"\bharness(es)?\b", [
        (r"(?:bộ |cái )?(?:vòng xoắn|bộ đeo|dây nịt|dây đeo|dây an toàn|khai thác|bộ khai thác|yên cương)", "khung chạy"),
    ]),
    (r"\bfrontier\b", [
        (r"tình báo biên giới|trí thông minh biên giới|trí tuệ biên giới", "trí tuệ tiên phong"),
        (r"biên giới", "tiên phong"),
    ]),
    (r"\bfine[- ]?tun(e|ed|ing)\b", [
        (r"điều chỉnh tinh tế|điều chỉnh tốt|tinh chỉnh tốt|tinh tế điều chỉnh", "tinh chỉnh"),
    ]),
    (r"\bbenchmarks?\b", [
        (r"(?:các |những )?(?:điểm chuẩn|tiêu chuẩn đánh giá|chuẩn mực|tiêu chuẩn|băng ghế dự bị|băng ghế)", "bài đo chuẩn"),
    ]),
    (r"\bcoding\b", [
        (r"mã hóa|mã hoá", "lập trình"),
    ]),
    (r"\blocal(ly)?\b", [
        (r"tại địa phương|ở địa phương|địa phương", "cục bộ"),
    ]),
    (r"\bopen[- ]source\b", [
        (r"(?<!mã )nguồn mở", "mã nguồn mở"),
    ]),
    (AI_CONTEXT + r".*\bweights?\b", [
        (r"trọng lượng", "trọng số"),
        (r"chỉnh cân trọng số", "trực giao hoá trọng số"),
    ]),
    (r"\bruntime\b", [
        (r"thời gian chạy|thời gian thực hiện", "môi trường chạy"),
    ]),
    (r"\binference\b", [
        (r"suy diễn|sự suy luận", "suy luận"),
        (r"việc định nghĩa", "suy luận"),
    ]),
    (AI_CONTEXT + r".*\b(?:train(?:s|ed|ing)?|pre-?training|post-?training)\b", [
        (r"đào tạo", "huấn luyện"),
    ]),
    (r"\bmodels?\b", [
        (r"(?:những |các )?người mẫu", "mô hình"),
    ]),
    (r"\bpipelines?\b", [
        (r"đường ống(?: dẫn)?", "quy trình"),
    ]),
    (AI_CONTEXT + r".*\bintelligence\b", [
        (r"thông tin tình báo|tình báo|trí thông minh", "trí tuệ"),
    ]),
    (r"\bdecoding\b", [
        (r"mã hóa|mã hoá", "giải mã"),
    ]),
    (r"\bprompts?\b", [
        (r"lời nhắc nhở", "lời nhắc"),
    ]),
    (r"\btokens?\b", [
        (r"mã thông báo|\bthẻ\b", "token"),
    ]),
]
_GLOSSARY = [(re.compile(src, re.IGNORECASE), [(re.compile(vi, re.IGNORECASE), out) for vi, out in fixes])
             for src, fixes in GLOSSARY]


def normalize(text):
    """The cache key and model input: straight quotes, single spaces."""
    return " ".join(str(text).translate(QUOTES).split())


def needs_translation(text):
    """True for an English phrase; False for names, ids and strings already in Vietnamese."""
    text = normalize(text)
    if " " not in text or VIETNAMESE.search(text) or CJK.search(text):
        return False
    plain = [w for w in WORD.findall(text) if len(w) >= 2 and not w.isupper() and not re.search(r"[a-z][A-Z]", w)]
    return len(plain) >= 2


def split_source(text):
    """Return (rule prefix in Vietnamese, [segments for the model], verbatim tail)."""
    text = normalize(text)
    tag = TAG.match(text)
    label = tag.group(0) if tag else ""
    text = text[len(label):]
    prefix = ""
    for pattern, vi in PREFIXES:
        match = pattern.match(text)
        if match:
            prefix, text = vi, text[match.end():]
            break
    if prefix in VERBATIM_AFTER or (prefix and not needs_translation(text)):
        return label + prefix, [], text
    head = HEAD_NAME.match(text)
    if head and needs_translation(text[head.end():]):
        label, text = label + prefix + head.group(0), text[head.end():]
        prefix = ""
    tail = TAIL_NAME.search(text)
    speaker = ""
    if tail and needs_translation(text[:tail.start()]):
        speaker, text = tail.group(0), text[:tail.start()]
    return label + prefix, [part for part in SENTENCE_END.split(text) if part], speaker


def _names(source, protected_names=CATALOG_NAMES):
    return ({name for name in NAME_TOKEN.findall(source) if name not in COMMON_ACRONYMS}
            | names_in(source, protected_names))


def apply_glossary(source, vi, *, protected_names=CATALOG_NAMES):
    """Fix known mistranslations, restore the spelling of names, tidy the edges."""
    for src_pattern, fixes in _GLOSSARY:
        if src_pattern.search(source):
            for vi_pattern, out in fixes:
                vi = vi_pattern.sub(out, vi)
    vi = re.sub(r"\bagent agent\b", "agent", vi)
    for name in sorted(_names(source, protected_names), key=lambda value: (-len(value), value)):
        # Restore spelling only, never guess where a translated or missing name belongs.
        vi = re.sub(name_pattern(name), lambda match: name, vi, flags=re.IGNORECASE)
    vi = " ".join(vi.split())
    if not re.match(r"[-\u2013\u2014*\u2022]", source):
        vi = re.sub(r"^[-\u2013\u2014*\u2022]+\s*", "", vi)  # a dash the source never had
    return vi[:1].upper() + vi[1:] if vi[:1].islower() and source[:1].isupper() else vi


def rejection(source, vi, *, protected_names=CATALOG_NAMES):
    """Why a machine translation must not be shown, or None when it may be."""
    if not vi or not vi.strip():
        return "empty"
    words = vi.lower().split()
    for size in (1, 2, 3):
        grams = [" ".join(words[i:i + size]) for i in range(len(words) - size + 1)]
        for i in range(len(grams) - 2 * size):
            if grams[i] == grams[i + size] == grams[i + 2 * size]:
                return "repetition"
        if size > 1 and any(grams[i] == grams[i + size] for i in range(len(grams) - size)):
            return "repetition"  # "mã hóa mã hóa": a doubled phrase, unlike reduplicated syllables ("từ từ")
    if not VIETNAMESE.search(vi) and needs_translation(vi):
        return "untranslated: the model returned English"
    if len(source) >= 24:
        ratio = len(vi) / len(source)
        if ratio < 0.55:
            return "too short: content dropped"
        if ratio > 3.0:
            return "too long: content added"
    missing = set(DIGITS.findall(source)) - set(DIGITS.findall(vi))
    if missing:
        return "number lost: " + ",".join(sorted(missing))
    source_words = set(re.findall(r"[a-z]+", source.lower()))
    added = {d for d in set(DIGITS.findall(vi)) - set(DIGITS.findall(source))
             if NUMBER_WORDS.get(d) not in source_words and SMALL_NUMBERS.get(d) not in source_words}
    if added:
        return "number added: " + ",".join(sorted(added))
    lost = [name for name in _names(source, protected_names) if not re.search(name_pattern(name), vi)]
    if lost:
        return "name lost: " + ",".join(sorted(lost))
    return None


def compose(source, cache, *, protected_names=CATALOG_NAMES):
    """Vietnamese for `source` from cached segments: (vi, None), (None, reason) or (None, 'pending')."""
    source = normalize(source)
    prefix, segments, tail = split_source(source)
    outputs = []
    for segment in segments:
        if segment not in cache:
            return None, "pending"
        outputs.append(cache[segment])
    body = " ".join(part.strip() for part in outputs if part is not None)
    first = body.split()[0] if body else ""
    if prefix.rstrip().endswith(("Ra mắt", "Công bố")) and first[:1].isupper() and first not in source:
        body = body[0].lower() + body[1:]  # "Ra mắt Khám phá…" -> "Ra mắt khám phá…"; a name from the source keeps its capital
    vi = apply_glossary(source, (prefix + body + tail).strip(), protected_names=protected_names)
    reason = rejection(source, vi, protected_names=protected_names)
    return (None, reason) if reason else (vi, None)


# ---------- which strings, in which order ----------

def _story_ok(story):
    return story.get("kind") != "event" and "event" not in (story.get("groups") or [])


def targets(payload):
    """(object, source field, translated field) in priority order: what a reader sees first goes first."""
    stories = payload.get("stories") or []
    by_id = {story.get("id"): story for story in stories if isinstance(story, dict)}
    ordered, seen = [], set()

    def add_story(story):
        if isinstance(story, dict) and id(story) not in seen and _story_ok(story):
            seen.add(id(story))
            ordered.append((story, "title", "title_vi"))
            ordered.append((story, "summary", "summary_vi"))

    for story in sorted((s for s in stories if isinstance(s, dict) and (s.get("source_count") or 0) >= 2),
                        key=lambda s: s.get("published_at") or "", reverse=True):
        add_story(story)
    sections = payload.get("sections") or {}
    for name in ("hot", "today"):
        for story_id in sections.get(name) or []:
            add_story(by_id.get(story_id))
    repos = [(repo, "description", "description_vi") for repo in payload.get("repos") or []
             if isinstance(repo, dict) and repo.get("description")]
    live = [(item, "title", "title_vi") for item in payload.get("live") or [] if isinstance(item, dict)]
    ordered.extend(repos + live)
    for name in ("listen", "models", "papers", "voices", "community"):
        for story_id in sections.get(name) or []:
            add_story(by_id.get(story_id))
    for story in stories:
        add_story(story)
    for story in stories:
        if isinstance(story, dict) and _story_ok(story):
            ordered.extend((item, "title", "title_vi") for item in story.get("coverage") or [] if isinstance(item, dict))
            ordered.extend((item, "summary", "summary_vi") for item in story.get("coverage") or [] if isinstance(item, dict))
    return [(obj, src, dst) for obj, src, dst in ordered if isinstance(obj.get(src), str)]


def pending_segments(payload, cache):
    out, seen = [], set()
    for obj, src, _ in targets(payload):
        if not needs_translation(obj[src]):
            continue
        for segment in split_source(obj[src])[1]:
            if segment not in cache and segment not in seen:
                seen.add(segment)
                out.append(segment)
    return out


def clear_translations(payload):
    """Drop derived fields even if a source was removed or became an event."""
    rows = list(payload.get("stories") or []) + list(payload.get("live") or [])
    for story in payload.get("stories") or []:
        if isinstance(story, dict):
            rows.extend(story.get("coverage") or [])
    for row in rows:
        if isinstance(row, dict):
            row.pop("title_vi", None)
            row.pop("summary_vi", None)
    for row in payload.get("repos") or []:
        if isinstance(row, dict):
            row.pop("description_vi", None)


def apply(payload, cache):
    """Write translated fields from the cache; remove stale ones. Returns counts and rejected examples."""
    counts = dict(strings=0, translated=0, pending=0, rejected=0, kept_original=0)
    rejected = []
    done = set()
    clear_translations(payload)
    protected_names = payload_names(payload)
    for obj, src, dst in targets(payload):
        obj.pop(dst, None)
        if not needs_translation(obj[src]):
            counts["kept_original"] += 1
            continue
        key = normalize(obj[src])
        first = key not in done
        done.add(key)
        if first:
            counts["strings"] += 1
        vi, reason = compose(obj[src], cache, protected_names=protected_names | object_names(obj))
        if vi:
            obj[dst] = vi
            counts["translated"] += first
        elif reason == "pending":
            counts["pending"] += first
        elif reason.startswith("untranslated"):
            counts["kept_original"] += first  # the model judged it a name ("Grok 4 Fast"); the original is right
        else:
            counts["rejected"] += first
            if first and len(rejected) < 20:
                rejected.append(dict(source=key, reason=reason))
    return counts, rejected


# ---------- cache ----------

def load_cache(path):
    """Segment -> raw model output. A cache from another model or revision is discarded."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        print("Translation cache unreadable, starting empty", file=sys.stderr)
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or data.get("model") != MODEL_ID \
            or data.get("revision") != MODEL_REVISION or not isinstance(data.get("entries"), dict):
        return {}
    return {k: v for k, v in data["entries"].items() if isinstance(k, str) and isinstance(v, str)}


def save_cache(path, cache):
    write_atomic(dict(version=CACHE_VERSION, model=MODEL_ID, revision=MODEL_REVISION,
                      entries=dict(sorted(cache.items()))), path)


# ---------- the model ----------

def nllb_factory():
    """Load NLLB-200 and return `translate(list[str]) -> list[str]`. Imports happen here, never at module load."""
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    path = os.environ.get("RADAR_TRANSLATE_MODEL_DIR")
    if not path:
        from huggingface_hub import snapshot_download
        path = snapshot_download(MODEL_ID, revision=MODEL_REVISION, allow_patterns=MODEL_FILES)
    threads = int(os.environ.get("RADAR_TRANSLATE_THREADS") or os.cpu_count() or 2)
    torch.set_num_threads(max(1, threads))
    tokenizer = AutoTokenizer.from_pretrained(path, src_lang="eng_Latn")
    model = AutoModelForSeq2SeqLM.from_pretrained(path, use_safetensors=True).eval()
    target = tokenizer.convert_tokens_to_ids("vie_Latn")

    def translate(batch):
        with torch.inference_mode():
            encoded = tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=256)
            generated = model.generate(**encoded, forced_bos_token_id=target, num_beams=2,
                                       max_new_tokens=min(256, int(encoded["input_ids"].shape[1] * 2.5) + 10))
        return tokenizer.batch_decode(generated, skip_special_tokens=True)

    return translate


def _batches(segments, size):
    """Keep priority order across windows; sort by length inside a window to cut padding."""
    window = size * 4
    for start in range(0, len(segments), window):
        chunk = sorted(segments[start:start + window], key=len)
        for i in range(0, len(chunk), size):
            yield chunk[i:i + size]


def translate_payload(payload, cache, factory=None, budget=DEFAULT_BUDGET, batch_size=BATCH_SIZE,
                      clock=time.monotonic):
    """Translate what the cache lacks within `budget` seconds, then annotate `payload` in place.

    Never raises for model trouble: a failed import, download, load or batch is recorded in
    `payload["translation"]` and the page keeps its original titles. Returns (stats, worker_alive).
    """
    started = clock()
    factory = factory or nllb_factory  # looked up at call time so a caller (or a test) can swap the model
    todo = pending_segments(payload, cache)
    lock, stop = threading.Lock(), threading.Event()
    state = dict(error=None, new=0, loaded=False)

    def work():
        try:
            translate = factory()
            state["loaded"] = True
            for batch in _batches(todo, batch_size):
                if stop.is_set():
                    return
                outputs = translate(batch)
                if len(outputs) != len(batch):
                    raise RuntimeError(f"model returned {len(outputs)} outputs for {len(batch)} inputs")
                with lock:
                    if stop.is_set():
                        return
                    for segment, out in zip(batch, outputs):
                        cache[segment] = " ".join(str(out).split())
                    state["new"] += len(batch)
        except BaseException as error:  # noqa: BLE001 -- any model failure must leave the page intact
            state["error"] = f"{type(error).__name__}: {error}"

    alive = False
    if todo:
        worker = threading.Thread(target=work, daemon=True, name="radar-translate")
        worker.start()
        worker.join(max(0.0, budget - (clock() - started)))
        stop.set()
        alive = worker.is_alive()
        if alive and state["error"] is None:
            state["error"] = (f"Time budget of {budget:.0f}s exceeded "
                              f"({'while translating' if state['loaded'] else 'while loading the model'})")
    with lock:
        counts, rejected = apply(payload, cache)
    status = "ok" if counts["pending"] == 0 and not state["error"] else ("partial" if counts["translated"] else "failed")
    if not todo and not counts["strings"]:
        status = "ok"
    stats = dict(model=MODEL_ID, revision=MODEL_REVISION, license=MODEL_LICENSE, status=status,
                 new_segments=state["new"], model_loaded=state["loaded"], seconds=round(clock() - started, 1), error=state["error"],
                 error_vi=_error_vi(state["error"], counts), rejected_examples=rejected, **counts)
    payload["translation"] = stats
    return stats, alive


def _error_vi(error, counts):
    if not error:
        return None
    left = f" {counts['pending']} tiêu đề chưa dịch sẽ được dịch ở lần dựng sau." if counts["pending"] else ""
    if error.startswith("Time budget"):
        return "Bước dịch hết thời gian cho phép." + left
    if error.startswith(("ModuleNotFoundError", "ImportError")):
        return "Máy dựng chưa cài thư viện dịch, tiêu đề hiện bản gốc." + left
    return "Không chạy được model dịch, tiêu đề hiện bản gốc." + left


def main(argv=None):
    from radar import translation_gemini as gemini
    from radar import translation_pipeline

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="site/data/radar.json")
    parser.add_argument("--output", help="defaults to --input")
    parser.add_argument("--cache", default="data/translations-vi.json")
    parser.add_argument("--provider", choices=("auto", "nllb"), default="auto")
    parser.add_argument("--gemini-cache", help="defaults to translations-gemini-vi.json beside --cache")
    parser.add_argument("--gemini-ledger", help="defaults to translation-gemini-attempts.json beside --cache")
    parser.add_argument("--budget", type=float, default=float(os.environ.get("RADAR_TRANSLATE_BUDGET") or DEFAULT_BUDGET))
    parser.add_argument("--previous", default=os.environ.get("RADAR_PREVIOUS_SNAPSHOT"),
                        help="defaults to RADAR_PREVIOUS_SNAPSHOT env or None")
    args = parser.parse_args(argv)
    if args.budget <= 0:
        parser.error("--budget must be positive")
    gemini_path = args.gemini_cache or str(Path(args.cache).with_name("translations-gemini-vi.json"))
    ledger_path = args.gemini_ledger or str(Path(args.cache).with_name("translation-gemini-attempts.json"))
    companion = page_path(args.output or args.input).resolve()
    if companion in {Path(path).resolve() for path in (args.input, args.cache, gemini_path, ledger_path)}:
        parser.error("page projection must differ from input, translation caches and ledger")
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    previous = None
    if args.previous:
        try:
            previous = json.loads(Path(args.previous).read_text(encoding="utf-8"))
        except Exception:
            previous = None
    cache = load_cache(args.cache)
    gemini_cache = gemini.load_cache(gemini_path)
    before, gemini_before = dict(cache), dict(gemini_cache)
    try:
        ledger_before = Path(ledger_path).read_bytes()
    except OSError:
        ledger_before = None
    try:
        stats, alive = translation_pipeline.translate_payload(
            payload, cache, gemini_cache, budget=args.budget, provider=args.provider,
            ledger_path=ledger_path, factory=nllb_factory, previous=previous)
    except Exception:  # noqa: BLE001 -- never expose provider exception text or a key
        clear_translations(payload)
        payload["translation"] = dict(model=None, license=None, status="failed",
                                      provider="original", providers=[], error="translation_failed",
                                      error_vi="Bước dịch gặp lỗi, tiêu đề hiện bản gốc.")
        stats, alive = payload["translation"], False
    cache_written = cache != before
    if cache_written:
        try:
            save_cache(args.cache, cache)
        except Exception:
            cache_written = False
            stats.setdefault("persistence_errors", []).append("nllb_cache_write_failed")
    gemini_cache_written = gemini_cache != gemini_before
    if gemini_cache_written:
        try:
            gemini.save_cache(gemini_path, gemini_cache)
        except Exception:
            gemini_cache_written = False
            stats.setdefault("persistence_errors", []).append("gemini_cache_write_failed")
    try:
        ledger_written = Path(ledger_path).read_bytes() != ledger_before
    except OSError:
        ledger_written = False
    if os.environ.get("GITHUB_OUTPUT"):
        try:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"model_ready={str(bool(stats.get('model_loaded'))).lower()}\n"
                             f"cache_written={str(cache_written).lower()}\n"
                             f"gemini_cache_written={str(gemini_cache_written).lower()}\n"
                             f"gemini_ledger_written={str(ledger_written).lower()}\n")
        except OSError:
            stats.setdefault("persistence_errors", []).append("workflow_output_write_failed")
    write_site_snapshot(payload, args.output or args.input)
    published_arg = os.environ.get("RADAR_PUBLISHED_SNAPSHOT")
    if published_arg:
        published_path = Path(published_arg)
        if published_path.is_file():
            try:
                write_atomic(payload, published_path)
            except Exception:
                pass
    print(f"Translation {stats['status']}: {stats.get('translated', 0)}/{stats.get('strings', 0)} strings, "
          f"{stats.get('new_segments', 0)} new segments, {stats.get('pending', 0)} pending, "
          f"{stats.get('rejected', 0)} rejected in {stats.get('seconds', 0)}s"
          + (f" -- {stats['error']}" if stats.get("error") else ""))
    gemini = stats.get("gemini") or {}
    print(f"Gemini translation: {gemini.get('requests', 0)} requests, "
          f"{gemini.get('translated', 0)} strings, {gemini.get('tokens', 0)} tokens"
          + (f" -- {gemini['error']}" if gemini.get("error") else ""))
    sys.stdout.flush()
    if alive:
        os._exit(0)  # the model thread is stuck in native code; everything is written, so leave without joining it
    return 0


if __name__ == "__main__":
    sys.exit(main())
