"""One reviewed configuration surface for independent publisher-evidence fields."""

import hashlib
import json
import re
from datetime import timedelta

from radar.items import instant

MIN_STARS = 100
FIELD_LIMIT = 20
RETENTION_DAYS = 35
CLASSIFIER_VERSION = "publisher-description-v3"
MIN_RANKED = 5
# Conservative SPDX allow-list, not a legal audit; unknown/custom licenses stay excluded.
OSS_LICENSES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0", "Zlib",
                          "GPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0", "GPL-3.0-only", "GPL-3.0-or-later",
                          "LGPL-2.1", "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0", "LGPL-3.0-only", "LGPL-3.0-or-later",
                          "AGPL-3.0", "AGPL-3.0-only", "AGPL-3.0-or-later", "Unlicense", "BSL-1.0", "EPL-2.0"})


def license_eligible(repo):
    license_ = repo.get("license") if isinstance(repo, dict) else None
    return isinstance(license_, dict) and isinstance(license_.get("spdx_id"), str) and license_["spdx_id"] in OSS_LICENSES

# Topic spellings are discovery hypotheses; per-topic diagnostics expose live coverage.
FIELDS = (
    ("coding", "Coding", ("code-generation", "coding-agent", "ai-coding", "ai-code-review"),
     r"\b(?:cod(?:e|ing) (?:agent|assistant|generation|review|completion)|(?:generat\w*|edit\w*|review\w*|writ\w*|test\w*) (?:source )?code|software engineer\w*)\b"),
    ("video", "Video", ("text-to-video", "image-to-video", "video-generation"),
     r"\b(?:(?:video|film) (?:generat\w*|edit\w*|creat\w*|synthes\w*)|(?:generat\w*|edit\w*|creat\w*) (?:\w+ ){0,2}videos?|text.to.video|image.to.video)\b"),
    ("images", "Images", ("text-to-image", "image-generation", "image-editing"),
     r"\b(?:(?:image|picture) (?:generat\w*|edit\w*|synthes\w*|inpaint\w*)|(?:generat\w*|edit\w*) (?:\w+ ){0,2}images?|text.to.image|image.to.image)\b"),
    ("audio", "Audio / voice", ("text-to-speech", "tts", "speech-recognition", "voice-cloning"),
     r"\b(?:text.to.speech|speech.to.text|(?:voice|speech|audio) (?:clon\w*|generat\w*|recogni\w*|synthes\w*|convert\w*|design)|transcri\w*|tts|asr)\b"),
    ("animation", "Animation", ("motion-generation", "character-animation", "text-to-3d", "3d-generation"),
     r"\b(?:text.to.motion|motion (?:generat\w*|graphics)|(?:character|procedural|programmatic) animation|(?:generat\w*|creat\w*|edit\w*) (?:\w+ ){0,2}animations?)\b"),
    ("translation", "Translation", ("machine-translation", "speech-translation", "subtitle-translation"),
     r"\b(?:(?:machine|neural|speech|language|document|video|subtitle|pdf) translat\w*|translat\w* (?:\w+ ){0,2}(?:languages?|documents?|subtitles?|books?|pdfs?)|translation (?:tool|engine|model|system))\b"),
    ("agents", "Agents & automation", ("ai-agents", "agent-framework", "browser-automation", "computer-use", "rpa", "android-automation", "workflow-automation"),
     r"\b(?:ai agents?|agent(?:ic)? (?:framework|orchestrat\w*|workflow|automation)|(?:build\w*|run\w*) (?:\w+ ){0,2}agents?|browser (?:agent|automation)|computer.use|robotic process automation|rpa|(?:android|workflow) automation|(?:automat(?:e|es|ing)|automation of) (?:\w+ ){0,2}(?:workflows?|browsers?|android))\b"),
    ("mcp", "MCP & agent tooling", ("mcp", "mcp-server", "model-context-protocol"),
     r"\b(?:mcp (?:server|client|tool|integration|gateway)|model context protocol|(?:tools?|tooling) for (?:ai )?agents?)\b"),
    ("rag", "RAG & search", ("rag", "retrieval-augmented-generation", "vector-database"),
     r"\b(?:retrieval.augmented generation|rag (?:framework|pipeline|system|engine)|(?:semantic|vector|neural) (?:search|database)|retriev\w* (?:\w+ ){0,2}(?:documents?|knowledge))\b"),
    ("evaluation", "Model evaluation", ("llm-evaluation", "evals"),
     r"\b(?:(?:evaluat\w*|benchmark\w*) (?:\w+ ){0,2}(?:models?|llms?|agents?)|(?:model|llm|agent) (?:evaluat\w*|benchmark\w*)|llm evals)\b"),
    ("local-models", "Local model running", ("local-llm", "llm-inference", "gguf"),
     r"\b(?:(?:local|on.device|offline) (?:\w+ ){0,2}(?:llms?|models?|inference)|(?:run\w*|serv\w*) (?:\w+ ){0,2}(?:llms?|models?) (?:locally|offline)|llm inference|inference (?:engine|server|runtime))\b"),
    ("training", "Training & fine-tuning", ("fine-tuning", "lora", "rlhf"),
     r"\b(?:fine.tun\w*|(?:train\w*|align\w*) (?:\w+ ){0,2}(?:llms?|language models?|neural models?)|(?:llm|model) (?:train\w*|align\w*)|rlhf|low.rank adaptation)\b"),
    ("music", "Music", ("music-generation", "text-to-music"),
     r"\b(?:text.to.music|music (?:generat\w*|synthes\w*|compos\w*)|(?:generat\w*|compos\w*) (?:\w+ ){0,2}music)\b"),
    ("ocr", "OCR & documents", ("ocr", "document-parsing", "pdf-parsing"),
     r"\b(?:ocr|optical character recognition|(?:document|pdf) (?:pars\w*|extract\w*|understand\w*)|(?:extract\w*|pars\w*) (?:\w+ ){0,2}(?:documents?|pdfs?))\b"),
    ("robotics", "Robotics & embodied AI", ("robotics", "embodied-ai", "robot-learning"),
     r"\b(?:robot (?:learn\w*|policy|policies)|embodied (?:ai|intelligence|agents?)|(?:train\w*|learn\w*) (?:\w+ ){0,2}robots?|ai (?:robotics|robot control))\b"),
    ("trading", "Trading & finance", ("algorithmic-trading", "quantitative-finance", "backtesting"),
     r"\b(?:(?:algorithmic|automated|ai|quantitative) (?:trading|finance)|backtest\w*|(?:trading|financial) (?:agents?|models?|strategies|analysis))\b"),
    ("games", "Games & game AI", ("game-ai", "ai-game", "npc", "procedural-generation", "game-development", "reinforcement-learning"),
     r"\b(?:game ai|ai (?:games?|players?|npcs?)|(?:intelligent|autonomous) npcs?|(?:game|npc) (?:agents?|intelligence)|(?:procedural|ai) (?:\w+ ){0,2}(?:game|level) generation|(?:learn\w*|train\w*) (?:\w+ ){0,2}(?:play games?|game agents?))\b"),
)
EXCLUDED = re.compile(r"(?:^|[^a-z])(?:awesome(?:-list)?|tutorials?|courses?|books?|surveys?|papers|cheatsheets?)(?:$|[^a-z])", re.I)
LIST_PURPOSE = re.compile(r"\b(?:curated (?:list|collection)|(?:list|collection|survey) of (?:\w+[ -]+){0,12}(?:tools|projects|papers|resources|repositories|skills|prompts)|system prompts of (?:\w+[ -]+){0,8}tools|(?:book|survey) (?:about|of|on|for|covering)|tutorial|(?<!of )course|textbook)\b", re.I)
AI_SIGNAL = re.compile(r"\b(?:ai|llm|neural|diffusion|generative|machine.learning|deep.learning|artificial.intelligence)\b", re.I)


def configuration_fingerprint():
    value = dict(fields=FIELDS, classifier=CLASSIFIER_VERSION, min_stars=MIN_STARS,
                 field_limit=FIELD_LIMIT, minimum_ranked=MIN_RANKED, licenses=sorted(OSS_LICENSES),
                 exclusions=[EXCLUDED.pattern, LIST_PURPOSE.pattern], ai_signal=AI_SIGNAL.pattern,
                 selection="stars-discovery-v2")
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def classify(repo, now):
    """Topics nominate; an independent task statement admits each field."""
    if not isinstance(repo, dict) or repo.get("archived") is not False or repo.get("fork") is not False or not license_eligible(repo):
        return {}
    if type(repo.get("id")) is not int or repo["id"] <= 0:
        return {}
    name, description = repo.get("full_name"), repo.get("description") or ""
    topics = repo.get("topics")
    pushed = instant(repo.get("pushed_at"))
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name)
            or not isinstance(description, str) or not isinstance(topics, list)
            or not all(isinstance(t, str) for t in topics)
            or type(repo.get("stargazers_count")) is not int or repo["stargazers_count"] < MIN_STARS
            or pushed is None or not timedelta(0) <= now - pushed <= timedelta(days=30)):
        return {}
    topics = set(t.lower() for t in topics)
    if EXCLUDED.search(name.split("/", 1)[1] + " " + " ".join(topics)) or LIST_PURPOSE.search(description):
        return {}
    matches = {}
    for field, _, candidates, purpose in FIELDS:
        hits = sorted(topics.intersection(candidates))
        evidence = re.search(purpose, description, re.I)
        # Generic video/image editing needs an AI signal; animation intentionally includes programmatic tools.
        independent_ai = field not in {"trading", "games"} or AI_SIGNAL.search(description)
        if hits and evidence and independent_ai and (field not in {"coding", "video", "images"} or AI_SIGNAL.search(description + " " + " ".join(topics))):
            matches[field] = dict(matched_topics=hits, description_evidence=evidence.group(0),
                                  evidence_kind="publisher_description", classifier_version=CLASSIFIER_VERSION,
                                  ai_scope="ai_or_programmatic_animation" if field == "animation" else "ai_task")
    return matches
