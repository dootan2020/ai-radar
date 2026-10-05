"""AI image generation provider using Cloudflare Workers AI flux-1-schnell.

Provides an honest, labelled abstract illustration for stories lacking source-published images.
Strictly enforced boundaries:
- Model: @cf/black-forest-labs/flux-1-schnell via Workers AI REST API.
- Free allocation only: hard daily cap at 150 images per UTC day in a persisted ledger.
- Lost-ledger bound: new generation only inside one fixed UTC hour, with a per-run neuron budget
  (see GENERATION_WINDOW_UTC_HOUR / PER_RUN_NEURON_BUDGET), so the day stays bounded without the ledger.
- Circuit breaker: stops for the day when cap or HTTP 429 / quota error is hit.
- Once per story: saves static image under site/assets/ai/{story_id}.jpg and reuses across runs.
- Prompt rules: abstract editorial illustration, no real people, faces, logos, brand marks, product renders or text.
- Offline tests stay offline: no live network call without both environment variables.
"""

import base64
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request

from radar.pipeline import write_atomic

MODEL_ID = "@cf/black-forest-labs/flux-1-schnell"
DAILY_NEURON_BUDGET = 8000.0
DAILY_CAP = DAILY_NEURON_BUDGET  # Backward-compatibility alias
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_STEPS = 4

TILE_SIZE = 512
COST_PER_TILE = 4.80
COST_PER_STEP_PER_TILE = 9.60

# --- Lost-ledger spend bound -------------------------------------------------
# The ledger (data/ai-image-ledger.json) survives between runs only through a
# GitHub Actions cache restore marked continue-on-error. A missed restore means
# a run starts with an empty ledger, and the workflow starts a run every ~20-30
# minutes, so the ledger alone cannot bound the day. These constants bound it
# WITHOUT the ledger (the ledger stays as the normal guard on top):
#   * generation is only allowed while the UTC clock is inside ONE fixed hour
#     per day (GENERATION_WINDOW_UTC_HOUR), so only runs active in that hour
#     can spend anything;
#   * each run (process) may spend at most PER_RUN_NEURON_BUDGET neurons,
#     counted when a request is sent, whatever its outcome;
#   * PER_RUN_NEURON_BUDGET * ASSUMED_MAX_RUNS_IN_WINDOW <= DAILY_NEURON_BUDGET,
#     where ASSUMED_MAX_RUNS_IN_WINDOW covers every run that can be active in the
#     window: 5 scheduled starts (GitHub cron 7,37 + scheduler/ cron */20 at
#     :00,:20,:40), 1 scheduled start delayed in from the previous hour, 1 run
#     started before the window still running into it (the concurrency group
#     serialises runs, so at most one), and 3 manual dispatches or re-runs.
# 02:00-02:59 UTC (09:00-09:59 in Vietnam) keeps the whole window inside one
# UTC day and lets the free allocation reset at 00:00 UTC before it is used.
GENERATION_WINDOW_UTC_HOUR = 2
ASSUMED_MAX_RUNS_IN_WINDOW = 10
PER_RUN_NEURON_BUDGET = 800.0  # 4 images of 172.80 = 691.20 actually spendable


def compute_neuron_cost(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, steps=DEFAULT_STEPS):
    """Compute the Cloudflare Workers AI neuron cost for flux-1-schnell.

    Cloudflare charges per 512x512 tile:
    - 4.80 neurons per tile base
    - 9.60 neurons per step per tile
    Total cost = num_tiles * 4.80 + num_tiles * steps * 9.60
    """
    tiles_w = max(1, math.ceil(width / TILE_SIZE))
    tiles_h = max(1, math.ceil(height / TILE_SIZE))
    num_tiles = tiles_w * tiles_h
    return round(num_tiles * COST_PER_TILE + num_tiles * steps * COST_PER_STEP_PER_TILE, 4)


def story_recency_key(story):
    """Sort key for ordering stories newest first (descending).

    Returns a sortable tuple: (timestamp_float, iso_string, story_id).
    """
    if not isinstance(story, dict):
        return (0.0, "", "")

    candidates = []
    pub = story.get("published_at")
    if pub:
        candidates.append(str(pub))
    for item in story.get("coverage") or []:
        if isinstance(item, dict):
            for k in ("published_at", "start_at", "created_at"):
                v = item.get(k)
                if v:
                    candidates.append(str(v))

    best_ts = 0.0
    best_str = ""
    for c in candidates:
        if c > best_str:
            best_str = c
        try:
            clean = c.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = dt.timestamp()
            if ts > best_ts:
                best_ts = ts
        except Exception:
            pass

    return (best_ts, best_str, str(story.get("id") or ""))

# Known brand and organization names to filter out of prompts
BRAND_TERMS = {
    "openai", "chatgpt", "anthropic", "claude", "google", "deepmind", "deep mind", "gemini",
    "meta", "facebook", "instagram", "llama", "microsoft", "copilot", "windows",
    "apple", "siri", "nvidia", "amazon", "aws", "mistral", "mistralai", "mistral ai", "mixtral",
    "xai", "grok", "twitter", "deepseek", "qwen", "alibaba", "baidu", "tencent",
    "bytedance", "tiktok", "huggingface", "hugging face", "github", "reddit", "youtube", "lobsters",
    "hackernews", "hacker news", "techcrunch", "the verge", "verge", "ars technica",
    "wired", "bloomberg", "reuters", "cohere", "midjourney", "runway", "sora",
    "stable diffusion", "stability ai", "elevenlabs", "perplexity", "scale ai",
    "falcon", "gemma", "whisper", "devin", "black forest labs",
}

# Known public figures in AI/tech to filter out of prompts
PERSON_TERMS = {
    "sam altman", "altman", "elon musk", "musk", "dario amodei", "amodei",
    "demis hassabis", "hassabis", "yann lecun", "lecun", "jensen huang", "huang",
    "geoffrey hinton", "hinton", "ilya sutskever", "sutskever", "andrej karpathy",
    "karpathy", "satya nadella", "nadella", "sundar pichai", "pichai",
    "mark zuckerberg", "zuckerberg", "greg brockman", "brockman", "mira murati",
    "murati", "fei-fei li", "andrew ng", "yoshua bengio", "bengio", "mustafa suleyman",
    "suleyman", "arthur mensch", "noam shazeer", "clement delangue", "lex fridman",
    "joe rogan",
}

_ssl_ctx = ssl.create_default_context()


def _utc_now():
    """Current UTC time; a single seam so tests can place a run inside or outside the window."""
    return datetime.now(timezone.utc)


def generation_window_open(now=None):
    """True only while the UTC clock is inside the single daily generation hour."""
    moment = now if now is not None else _utc_now()
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.hour == GENERATION_WINDOW_UTC_HOUR


class RunBudget:
    """Neurons one run (process) may spend, independent of the persisted ledger.

    The ledger can be lost between runs; this object cannot, because it lives and
    dies with the process. Spend is reserved when a request is about to be sent,
    so failed or unusable responses (which the provider may still bill) count too.
    """

    def __init__(self, budget=PER_RUN_NEURON_BUDGET):
        self.budget = float(budget)
        self.spent = 0.0
        self._lock = threading.Lock()

    def try_reserve(self, cost):
        """Reserve `cost` neurons; refuse (and reserve nothing) if it would pass the budget."""
        with self._lock:
            if round(self.spent + float(cost), 4) > self.budget:
                return False
            self.spent = round(self.spent + float(cost), 4)
            return True


_PROCESS_RUN_BUDGET = RunBudget()


def process_run_budget():
    """The budget shared by every generation call in this process (one workflow run)."""
    return _PROCESS_RUN_BUDGET


def reset_process_run_budget():
    """Start a fresh process-wide budget (tests only; production gets one per process)."""
    global _PROCESS_RUN_BUDGET
    _PROCESS_RUN_BUDGET = RunBudget()
    return _PROCESS_RUN_BUDGET


class AIImageLedger:
    """Persisted ledger tracking daily AI image generation count, neuron cost, and quota circuit breaker."""

    def __init__(self, ledger_path=None, daily_budget=DAILY_NEURON_BUDGET, daily_cap=None):
        root = Path(__file__).resolve().parent.parent
        self.ledger_path = Path(ledger_path) if ledger_path else root / "data" / "ai-image-ledger.json"
        if daily_cap is not None:
            self.daily_budget = float(daily_cap)
        else:
            self.daily_budget = float(daily_budget)
        self.data = {
            "_meta": {
                "daily_budget": self.daily_budget,
                "model": MODEL_ID,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "days": {},
        }
        self.load()

    @property
    def daily_cap(self):
        return self.daily_budget

    def load(self):
        """Load ledger data from disk if present."""
        if self.ledger_path.is_file():
            try:
                loaded = json.loads(self.ledger_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and "days" in loaded:
                    self.data = loaded
                    meta = self.data.get("_meta", {})
                    if "daily_budget" in meta:
                        self.daily_budget = float(meta["daily_budget"])
                    elif "daily_cap" in meta:
                        self.daily_budget = float(meta["daily_cap"])
            except Exception:
                pass

    def save(self):
        """Save ledger data atomically to disk."""
        self.data.setdefault("_meta", {})
        self.data["_meta"]["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.data["_meta"]["daily_budget"] = self.daily_budget
        self.data["_meta"]["daily_cap"] = self.daily_budget
        self.data["_meta"]["model"] = MODEL_ID
        write_atomic(self.data, self.ledger_path)

    def _day_key(self, now=None):
        now_dt = now or datetime.now(timezone.utc)
        return now_dt.strftime("%Y-%m-%d")

    def get_day(self, now=None):
        """Get or initialize record for the specified UTC day."""
        key = self._day_key(now)
        days = self.data.setdefault("days", {})
        if key not in days:
            days[key] = {
                "count": 0,
                "neurons_spent": 0.0,
                "stopped": False,
                "stop_reason": None,
                "generated_stories": [],
            }
        else:
            days[key].setdefault("count", 0)
            days[key].setdefault("neurons_spent", 0.0)
            days[key].setdefault("stopped", False)
            days[key].setdefault("stop_reason", None)
            days[key].setdefault("generated_stories", [])
        return days[key]

    def is_story_generated(self, story_id):
        """Check if this story ID has already been generated on any day."""
        if not story_id:
            return False
        for day in self.data.get("days", {}).values():
            if story_id in day.get("generated_stories", []):
                return True
        return False

    def can_generate(self, story_id=None, cost=None, now=None):
        """Check if generation is permitted under daily neuron budget and circuit breaker."""
        if story_id and self.is_story_generated(story_id):
            return False, "already_generated"
        day = self.get_day(now)
        if day.get("stopped"):
            return False, f"stopped_for_day: {day.get('stop_reason')}"
        req_cost = cost if cost is not None else compute_neuron_cost()
        current_spent = day.get("neurons_spent", 0.0)
        if round(current_spent + req_cost, 4) > self.daily_budget:
            day["stopped"] = True
            day["stop_reason"] = "daily_budget_exceeded"
            self.save()
            return False, "daily_budget_exceeded"
        return True, "ok"

    def record_generation(self, story_id, cost=None, now=None):
        """Record a successful image generation, tracking count and neurons spent."""
        day = self.get_day(now)
        day["count"] = day.get("count", 0) + 1
        req_cost = cost if cost is not None else compute_neuron_cost()
        day["neurons_spent"] = round(day.get("neurons_spent", 0.0) + float(req_cost), 4)
        if story_id and story_id not in day.get("generated_stories", []):
            day.setdefault("generated_stories", []).append(story_id)
        if round(day["neurons_spent"] + compute_neuron_cost(), 4) > self.daily_budget:
            day["stopped"] = True
            day["stop_reason"] = "daily_budget_reached"
        self.save()

    def record_stop(self, reason="rate_limit_or_quota_exceeded", now=None):
        """Circuit breaker: stop generation for the rest of the UTC day (e.g. on 429)."""
        day = self.get_day(now)
        day["stopped"] = True
        day["stop_reason"] = str(reason)
        self.save()


def sanitize_topic_text(title):
    """Strip brand names, product names, person names, and hype keywords from title."""
    if not title:
        return "artificial intelligence technology"

    text = title.strip()

    # Strip version strings like GPT-4, v1.2, 3.5, etc.
    text = re.sub(r"\b(?:gpt|claude|gemini|llama|qwen|deepseek)[-\s]?[0-9a-zA-Z.]*\b", "", text, flags=re.I)
    text = re.sub(r"\bv?\d+(?:\.\d+)+\b", "", text)

    # Strip person terms (multi-word first, then single word)
    for person in sorted(PERSON_TERMS, key=len, reverse=True):
        pattern = r"\b" + re.escape(person) + r"\b"
        text = re.sub(pattern, "", text, flags=re.I)

    # Strip brand terms (multi-word first, then single word)
    for brand in sorted(BRAND_TERMS, key=len, reverse=True):
        pattern = r"\b" + re.escape(brand) + r"\b"
        text = re.sub(pattern, "", text, flags=re.I)

    # Strip common journalistic / news verbs and punctuation noise
    noise_patterns = [
        r"\b(?:announces?|releases?|unveils?|launches?|introduces?|says?|reports?|claims?|breaks?)\b",
        r"\b(?:exclusive|interview|breaking|update|review|analysis|opinion|leak)\b",
        r"\b(?:partnership with|partner with|teams up with|acquires?)\b",
        r"[:\-\–\—\|]",
    ]
    for np in noise_patterns:
        text = re.sub(np, " ", text, flags=re.I)

    # Normalize whitespace
    words = [w for w in text.split() if len(w) > 1 and w.isalpha()]
    cleaned = " ".join(words)

    if not cleaned or len(cleaned) < 5:
        return "artificial intelligence conceptual research"
    return cleaned


def build_ai_prompt(title, kind=None):
    """Construct an abstract editorial illustration prompt from story title and kind.

    Enforces prompt rules:
    - Abstract editorial digital illustration
    - Built from title and kind
    - Strictly no real people, faces, logos, brand marks, product renders or text.
    """
    topic = sanitize_topic_text(title)
    kind_descriptor = {
        "model": "neural architecture and algorithmic model structures",
        "repository": "computational logic, code structures and modular engineering",
        "paper": "scientific discovery, theoretical concepts and mathematical foundations",
        "video": "multimedia information synthesis and digital signals",
        "event": "collaborative innovation and technology exchange",
    }.get(kind, "advanced computational technology and intelligent systems")

    prompt = (
        f"Abstract editorial digital illustration representing {topic} and {kind_descriptor}. "
        "Clean modern geometric composition, subtle atmospheric gradients, metaphorical visual elements, "
        "fine art aesthetic, sophisticated contemporary digital artwork. "
        "No people, no human faces, no portraits, no human figures, no text, no words, no letters, "
        "no typography, no logos, no brand marks, no realistic product renders, no commercial packaging."
    )
    for term in sorted(BRAND_TERMS | PERSON_TERMS, key=len, reverse=True):
        pattern = r"\b" + re.escape(term) + r"\b"
        prompt = re.sub(pattern, "", prompt, flags=re.I)
    prompt = re.sub(r"\s+", " ", prompt).strip()
    return prompt


def _sanitize_secrets(text, account_id=None, api_token=None):
    """Redact tokens, account IDs, and sensitive URLs from any text or log output."""
    if not text:
        return ""
    text = str(text)
    if api_token:
        text = text.replace(api_token, "[REDACTED]")
    env_token = os.environ.get("CLOUDFLARE_AI_API_TOKEN")
    if env_token:
        text = text.replace(env_token, "[REDACTED]")
    if account_id:
        text = text.replace(account_id, "[REDACTED]")
    env_acc = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if env_acc:
        text = text.replace(env_acc, "[REDACTED]")
    text = re.sub(r"/accounts/[^/]+/", "/accounts/[REDACTED]/", text)
    text = re.sub(r"Bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED]", text)
    return text


def _parse_cloudflare_error(body_bytes, status, account_id=None, api_token=None):
    """Extract clean error code and message from Cloudflare response, stripping secrets."""
    err_code = None
    err_msg = ""
    if body_bytes:
        try:
            raw_text = body_bytes.decode("utf-8", errors="ignore")
            data = json.loads(raw_text)
            if isinstance(data, dict):
                errors = data.get("errors")
                if isinstance(errors, list) and errors:
                    first = errors[0]
                    if isinstance(first, dict):
                        err_code = first.get("code")
                        err_msg = first.get("message") or ""
                    elif isinstance(first, str):
                        err_msg = first
                elif data.get("error"):
                    err_msg = str(data.get("error"))
                elif data.get("messages") and isinstance(data.get("messages"), list):
                    err_msg = "; ".join(str(m) for m in data.get("messages"))
        except Exception:
            pass
        if not err_msg:
            text = body_bytes.decode("utf-8", errors="ignore").strip()
            if "<html" in text.lower():
                m = re.search(r"<title>(.*?)</title>", text, re.I)
                err_msg = m.group(1).strip() if m else f"HTTP {status}"
            else:
                err_msg = text[:120].strip()
    if not err_msg:
        err_msg = f"HTTP {status}"
    err_msg = _sanitize_secrets(err_msg, account_id, api_token)
    return err_code, err_msg


def read_image_dimensions(data):
    """Read pixel dimensions (width, height) from JPEG, PNG or WebP bytes using standard library only.

    Returns (width, height) tuple of ints if found, or (None, None) if unrecognized/invalid.
    """
    if not data or len(data) < 24:
        return None, None

    # PNG: signature (8 bytes) + IHDR chunk (4 bytes len + 4 bytes 'IHDR' + 8 bytes w/h)
    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\x89PNG"):
        ihdr_idx = data.find(b"IHDR")
        if ihdr_idx != -1 and len(data) >= ihdr_idx + 12:
            try:
                width, height = struct.unpack(">II", data[ihdr_idx + 4 : ihdr_idx + 12])
                if width > 0 and height > 0:
                    return width, height
            except struct.error:
                pass
        return None, None

    # JPEG: starts with SOI marker 0xFF 0xD8
    if data.startswith(b"\xff\xd8"):
        # Header area is bounded by SOS (Start of Scan 0xFF 0xDA)
        sos_idx = data.find(b"\xff\xda")
        header_data = data[:sos_idx] if sos_idx != -1 else data

        # Search for SOF markers (SOF0=0xC0, SOF2=0xC2, SOF1=0xC1, etc.)
        for m in (0xC0, 0xC2, 0xC1, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            target = bytes([0xFF, m])
            idx = 0
            while True:
                idx = header_data.find(target, idx)
                if idx == -1:
                    break
                if idx + 9 <= len(data):
                    try:
                        seg_len = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
                        if seg_len >= 8:
                            precision = data[idx + 4]
                            if precision in (8, 12, 16):
                                h, w = struct.unpack(">HH", data[idx + 5 : idx + 9])
                                if w > 0 and h > 0:
                                    return w, h
                    except Exception:
                        pass
                idx += 2
        return None, None

    # WebP: RIFF ... WEBP
    if data.startswith(b"RIFF") and len(data) >= 30 and data[8:12] == b"WEBP":
        chunk = data[12:16]
        try:
            if chunk == b"VP8 " and len(data) >= 30:
                w, h = struct.unpack("<HH", data[26:30])
                w, h = w & 0x3FFF, h & 0x3FFF
                if w > 0 and h > 0:
                    return w, h
            elif chunk == b"VP8L" and len(data) >= 25:
                b0, b1, b2, b3 = data[21:25]
                w = 1 + (((b1 & 0x3F) << 8) | b0)
                h = 1 + (((b3 & 0x0F) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
                if w > 0 and h > 0:
                    return w, h
            elif chunk == b"VP8X" and len(data) >= 30:
                w = 1 + struct.unpack("<I", data[24:27] + b"\x00")[0]
                h = 1 + struct.unpack("<I", data[27:30] + b"\x00")[0]
                if w > 0 and h > 0:
                    return w, h
        except Exception:
            pass

    return None, None


def safe_image_filename(story_id):
    """Derive safe filename from story id."""
    cleaned = re.sub(r"[^\w.-]", "_", str(story_id or "unnamed"))
    return f"{cleaned}.jpg"


def generate_ai_illustration(
    story,
    site_root=None,
    ledger=None,
    ledger_path=None,
    account_id=None,
    api_token=None,
    timeout=10,
    transport=None,
    now=None,
    width=DEFAULT_WIDTH,
    height=DEFAULT_HEIGHT,
    steps=DEFAULT_STEPS,
    run_budget=None,
    ignore_window=False,
    outcome=None,
):
    """Generate an AI illustration for a story and save it under site/assets/ai/{story_id}.jpg.

    Returns dict `{"src": "assets/ai/{story_id}.jpg", "via": "ai", "kind": "photo", "verified": True}`
    or None if generation is disallowed, fails, or credentials are absent.

    New generation also requires the UTC clock to be inside the daily window
    (GENERATION_WINDOW_UTC_HOUR) and the run to have PER_RUN_NEURON_BUDGET left
    (`run_budget`, default: the process-wide one). Reusing an image already on disk
    costs nothing and is allowed at any time.
    """
    story_id = story.get("id") if isinstance(story, dict) else None
    if not story_id:
        if outcome is not None:
            outcome.update(action="skipped", reason="missing_story_id", bytes_received=0, cost=0.0)
        return None

    root = Path(__file__).resolve().parent.parent
    site_dir = Path(site_root) if site_root else root / "site"
    dest_dir = site_dir / "assets" / "ai"
    filename = safe_image_filename(story_id)
    dest_path = dest_dir / filename
    rel_src = f"assets/ai/{filename}"

    if ledger is None:
        ledger = AIImageLedger(ledger_path=ledger_path)

    cost = compute_neuron_cost(width=width, height=height, steps=steps)

    # Once per story: if file exists on disk, reuse immediately without calling API
    if dest_path.is_file():
        if not ledger.is_story_generated(story_id):
            ledger.record_generation(story_id, cost=0.0, now=now)
        real_w, real_h = None, None
        try:
            real_w, real_h = read_image_dimensions(dest_path.read_bytes())
        except Exception:
            pass
        if outcome is not None:
            outcome.update(
                action="reused",
                status=200,
                bytes_received=dest_path.stat().st_size if dest_path.exists() else 0,
                cost=0.0,
                width=real_w,
                height=real_h,
            )
        return {"src": rel_src, "via": "ai", "kind": "photo", "verified": True}

    # Lost-ledger bound: new generation only inside the fixed daily UTC hour. Checked
    # before the ledger so a closed window never writes a "stopped" day record.
    if not ignore_window and not generation_window_open(now):
        if outcome is not None:
            outcome.update(action="skipped", reason="window_closed", bytes_received=0, cost=0.0)
        return None

    # Verify quota and circuit breaker
    can_gen, reason = ledger.can_generate(story_id, cost=cost, now=now)
    if not can_gen:
        if outcome is not None:
            outcome.update(action="refused", reason=reason, bytes_received=0, cost=0.0)
        return None

    # Credentials resolution (never print or log values)
    account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    api_token = api_token or os.environ.get("CLOUDFLARE_AI_API_TOKEN")

    missing_creds = []
    if not account_id:
        missing_creds.append("CLOUDFLARE_ACCOUNT_ID")
    if not api_token:
        missing_creds.append("CLOUDFLARE_AI_API_TOKEN")

    # Offline safety: never call without both env vars unless an offline transport is injected
    if transport is None and missing_creds:
        if outcome is not None:
            outcome.update(action="skipped", reason=f"missing {', '.join(missing_creds)}", bytes_received=0, cost=0.0)
        return None

    # Per-run bound, independent of the ledger: reserved when the request is sent so
    # a failed or unusable response (possibly billed) still counts against the run.
    if run_budget is not None or not ignore_window:
        if run_budget is None:
            run_budget = process_run_budget()
        if not run_budget.try_reserve(cost):
            if outcome is not None:
                outcome.update(action="refused", reason="run_budget_exceeded", bytes_received=0, cost=0.0)
            return None

    prompt = build_ai_prompt(story.get("title", ""), story.get("kind"))
    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL_ID}"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body_data = json.dumps({
        "prompt": prompt,
        "steps": steps,
    }).encode("utf-8")

    status, ct, resp_bytes = 0, "", b""
    if transport is not None:
        try:
            try:
                status, ct, resp_bytes = transport(endpoint, headers=headers, data=body_data)
            except TypeError:
                status, ct, resp_bytes = transport(endpoint, headers, body_data)
        except Exception as err:
            err_msg = _sanitize_secrets(str(err), account_id, api_token)
            if outcome is not None:
                outcome.update(action="failed", status=0, error=err_msg, bytes_received=0, cost=0.0)
            return None
    else:
        req = urllib.request.Request(endpoint, data=body_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout) as resp:
                status = resp.status
                ct = resp.headers.get("Content-Type", "")
                resp_bytes = resp.read()
        except urllib.error.HTTPError as err:
            err_body = err.read() if hasattr(err, "read") else b""
            status = err.code
            err_code, err_msg = _parse_cloudflare_error(err_body, status, account_id, api_token)
            if status == 429:
                ledger.record_stop("HTTP 429 Too Many Requests (rate limit or daily quota)", now=now)
            elif status in (400, 403):
                # Check for quota message in error payload
                if b"quota" in err_body.lower() or b"limit" in err_body.lower():
                    ledger.record_stop(f"HTTP {status} Quota Exceeded", now=now)
            if outcome is not None:
                outcome.update(action="failed", status=status, error=err_msg, error_code=err_code, bytes_received=len(err_body), cost=0.0)
            return None
        except urllib.error.URLError as err:
            err_msg = _sanitize_secrets(str(err.reason), account_id, api_token)
            if outcome is not None:
                outcome.update(action="failed", status=0, error=err_msg, bytes_received=0, cost=0.0)
            return None
        except Exception as err:
            err_msg = _sanitize_secrets(str(err), account_id, api_token)
            if outcome is not None:
                outcome.update(action="failed", status=0, error=err_msg, bytes_received=0, cost=0.0)
            return None

    # Handle rate limit or quota exceeded
    if status == 429:
        ledger.record_stop("HTTP 429 Too Many Requests", now=now)
        err_code, err_msg = _parse_cloudflare_error(resp_bytes, status, account_id, api_token)
        if outcome is not None:
            outcome.update(action="failed", status=429, error=err_msg, error_code=err_code, bytes_received=len(resp_bytes), cost=0.0)
        return None

    if status != 200:
        err_code, err_msg = _parse_cloudflare_error(resp_bytes, status, account_id, api_token)
        if status in (400, 403) and (b"quota" in resp_bytes.lower() or b"limit" in resp_bytes.lower()):
            ledger.record_stop(f"HTTP {status} Quota Exceeded", now=now)
        if outcome is not None:
            outcome.update(action="failed", status=status, error=err_msg, error_code=err_code, bytes_received=len(resp_bytes), cost=0.0)
        return None

    # Extract image bytes
    img_bytes = b""
    ct_lower = ct.lower()
    if ct_lower.startswith("image/") or resp_bytes.startswith((b"\xff\xd8\xff", b"\x89PNG", b"RIFF")):
        img_bytes = resp_bytes
    else:
        try:
            payload = json.loads(resp_bytes.decode("utf-8", errors="ignore"))
            b64_str = (payload.get("result", {}) or {}).get("image") or payload.get("image")
            if b64_str and isinstance(b64_str, str):
                img_bytes = base64.b64decode(b64_str)
        except Exception:
            pass

    # Verify that decoded bytes look like valid JPEG / PNG / WebP
    if not img_bytes or not img_bytes.startswith((b"\xff\xd8\xff", b"\x89PNG", b"RIFF")):
        if outcome is not None:
            outcome.update(action="failed", status=status, error="Invalid or missing image bytes in response", bytes_received=len(resp_bytes), cost=0.0)
        return None

    # Read real pixel dimensions from returned image bytes (standard library only)
    real_w, real_h = read_image_dimensions(img_bytes)
    measured_w = real_w if real_w is not None else width
    measured_h = real_h if real_h is not None else height
    real_cost = compute_neuron_cost(width=measured_w, height=measured_h, steps=steps)

    # Store image file atomically under published site
    dest_dir.mkdir(parents=True, exist_ok=True)
    temp_path = dest_dir / f".tmp_{filename}_{time.time_ns()}"
    try:
        temp_path.write_bytes(img_bytes)
        temp_path.replace(dest_path)
    except Exception:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass
        if outcome is not None:
            outcome.update(action="failed", status=status, error="Failed to write image to disk", bytes_received=len(img_bytes), cost=0.0)
        return None

    # Record generation in ledger with cost computed from real dimensions
    ledger.record_generation(story_id, cost=real_cost, now=now)

    # Adjust run budget if real cost differs from the assumed upper bound
    active_budget = run_budget if run_budget is not None else (process_run_budget() if not ignore_window else None)
    if active_budget is not None:
        diff = round(real_cost - cost, 4)
        active_budget.spent = round(active_budget.spent + diff, 4)

    # If the real dimensions would cost more than the bound assumed,
    # stop generation for the day (the same way a 429 does) and print why.
    oversize = real_cost > cost
    if oversize:
        stop_reason = (
            f"image dimensions {measured_w}x{measured_h} cost {real_cost:.1f} neurons "
            f"exceeding assumed bound {cost:.1f}"
        )
        ledger.record_stop(stop_reason, now=now)
        print(f"AI image generation stopped for day: {stop_reason}")

    if outcome is not None:
        outcome.update(
            action="generated",
            status=status,
            bytes_received=len(img_bytes),
            cost=real_cost,
            width=measured_w,
            height=measured_h,
            oversize=oversize,
        )

    return {"src": rel_src, "via": "ai", "kind": "photo", "verified": True}


def probe(
    ledger_path=None,
    site_root=None,
    account_id=None,
    api_token=None,
    timeout=15,
    transport=None,
    now=None,
    width=DEFAULT_WIDTH,
    height=DEFAULT_HEIGHT,
    steps=DEFAULT_STEPS,
):
    """Make exactly one generation request outside the daily window with strict ledger safety.

    - Bounded to exactly one request per invocation.
    - Counts against the ledger daily budget and refuses if stopped or over budget.
    - Prints the outcome: status, error code or message, bytes received, neuron cost.
    - Never prints tokens, account IDs, or URLs containing account IDs.
    - Returns 0 on success, 1 on refusal or failure.
    """
    import tempfile

    account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    api_token = api_token or os.environ.get("CLOUDFLARE_AI_API_TOKEN")

    missing = []
    if not account_id:
        missing.append("CLOUDFLARE_ACCOUNT_ID")
    if not api_token:
        missing.append("CLOUDFLARE_AI_API_TOKEN")

    if transport is None and missing:
        print(f"AI image probe: refused (missing {', '.join(missing)}), 0 bytes received, 0.0 neurons spent")
        return 1

    ledger = AIImageLedger(ledger_path=ledger_path)
    cost = compute_neuron_cost(width=width, height=height, steps=steps)
    can_gen, reason = ledger.can_generate(cost=cost, now=now)
    if not can_gen:
        print(f"AI image probe: refused ({reason}), 0 bytes received, 0.0 neurons spent")
        return 1

    probe_id = f"ai-probe-{(now or _utc_now()).strftime('%Y%m%d%H%M%S')}"
    probe_story = {
        "id": probe_id,
        "title": "Artificial intelligence foundational reasoning and algorithmic architectures",
        "kind": "model",
    }

    outcome = {}
    with tempfile.TemporaryDirectory() as tmp_site:
        site_target = site_root if site_root is not None else tmp_site
        res = generate_ai_illustration(
            probe_story,
            site_root=site_target,
            ledger=ledger,
            account_id=account_id,
            api_token=api_token,
            timeout=timeout,
            transport=transport,
            now=now,
            width=width,
            height=height,
            steps=steps,
            ignore_window=True,
            outcome=outcome,
        )

    action = outcome.get("action")
    status = outcome.get("status", 0)
    bytes_rcvd = outcome.get("bytes_received", 0)
    neurons = outcome.get("cost", 0.0)
    error = outcome.get("error")
    err_code = outcome.get("error_code")
    reason = outcome.get("reason")

    w = outcome.get("width")
    h = outcome.get("height")
    dim_str = f", {w}x{h}" if (w and h) else ""

    if action == "generated":
        print(f"AI image probe: HTTP {status}{dim_str}, {bytes_rcvd} bytes received, {neurons:.1f} neurons spent")
        return 0
    elif action == "failed":
        err_detail = f"code {err_code}: {error}" if err_code else (error or f"HTTP {status}")
        print(f"AI image probe: HTTP {status}, error: {err_detail}, {bytes_rcvd} bytes received, {neurons:.1f} neurons spent")
        return 1
    elif action == "refused":
        print(f"AI image probe: refused ({reason}), {bytes_rcvd} bytes received, {neurons:.1f} neurons spent")
        return 1
    elif action == "skipped":
        print(f"AI image probe: skipped ({reason}), {bytes_rcvd} bytes received, {neurons:.1f} neurons spent")
        return 1
    else:
        print(f"AI image probe: HTTP {status}{dim_str}, {bytes_rcvd} bytes received, {neurons:.1f} neurons spent")
        return 0 if res else 1


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Cloudflare Workers AI image utility")
    subparsers = parser.add_subparsers(dest="command")
    probe_parser = subparsers.add_parser("probe", help="Run a single-request probe outside the window")
    probe_parser.add_argument("--ledger", default=None, help="Path to ledger file")
    probe_parser.add_argument("--timeout", type=int, default=15, help="Request timeout")

    parsed = parser.parse_args()
    if parsed.command == "probe":
        sys.exit(probe(ledger_path=parsed.ledger, timeout=parsed.timeout))
    else:
        parser.print_help()
        sys.exit(1)
