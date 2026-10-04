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
):
    """Generate an AI illustration for a story and save it under site/assets/ai/{story_id}.jpg.

    Returns dict `{"src": "assets/ai/{story_id}.jpg", "via": "ai", "kind": "photo", "verified": True}`
    or None if generation is disallowed, fails, or credentials are absent.

    New generation also requires the UTC clock to be inside the daily window
    (GENERATION_WINDOW_UTC_HOUR) and the run to have PER_RUN_NEURON_BUDGET left
    (`run_budget`, default: the process-wide one). Reusing an image already on disk
    costs nothing and is allowed at any time.
    """
    story_id = story.get("id")
    if not story_id:
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
        return {"src": rel_src, "via": "ai", "kind": "photo", "verified": True}

    # Lost-ledger bound: new generation only inside the fixed daily UTC hour. Checked
    # before the ledger so a closed window never writes a "stopped" day record.
    if not generation_window_open(now):
        return None

    # Verify quota and circuit breaker
    can_gen, reason = ledger.can_generate(story_id, cost=cost, now=now)
    if not can_gen:
        return None

    # Credentials resolution (never print or log values)
    account_id = account_id or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    api_token = api_token or os.environ.get("CLOUDFLARE_AI_API_TOKEN")

    # Offline safety: never call without both env vars unless an offline transport is injected
    if transport is None and (not account_id or not api_token):
        return None

    # Per-run bound, independent of the ledger: reserved when the request is sent so
    # a failed or unusable response (possibly billed) still counts against the run.
    if run_budget is None:
        run_budget = process_run_budget()
    if not run_budget.try_reserve(cost):
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
        "width": width,
        "height": height,
    }).encode("utf-8")

    status, ct, resp_bytes = 0, "", b""
    if transport is not None:
        try:
            try:
                status, ct, resp_bytes = transport(endpoint, headers=headers, data=body_data)
            except TypeError:
                status, ct, resp_bytes = transport(endpoint, headers, body_data)
        except Exception:
            return None
    else:
        req = urllib.request.Request(endpoint, data=body_data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=_ssl_ctx, timeout=timeout) as resp:
                status = resp.status
                ct = resp.headers.get("Content-Type", "")
                resp_bytes = resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 429:
                ledger.record_stop("HTTP 429 Too Many Requests (rate limit or daily quota)", now=now)
                return None
            if err.code in (400, 403):
                # Check for quota message in error payload
                err_body = err.read() if hasattr(err, "read") else b""
                if b"quota" in err_body.lower() or b"limit" in err_body.lower():
                    ledger.record_stop(f"HTTP {err.code} Quota Exceeded", now=now)
            return None
        except Exception:
            return None

    # Handle rate limit or quota exceeded
    if status == 429:
        ledger.record_stop("HTTP 429 Too Many Requests", now=now)
        return None
    if status != 200:
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
            return None

    # Verify that decoded bytes look like valid JPEG / PNG / WebP
    if not img_bytes or not img_bytes.startswith((b"\xff\xd8\xff", b"\x89PNG", b"RIFF")):
        return None

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
        return None

    # Record generation in ledger
    ledger.record_generation(story_id, cost=cost, now=now)

    return {"src": rel_src, "via": "ai", "kind": "photo", "verified": True}
