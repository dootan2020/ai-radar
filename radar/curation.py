"""Curation and evaluation of trending GitHub repositories and Hugging Face models."""

import concurrent.futures
from datetime import datetime, timezone
import json
import os
import re
import time
from urllib.parse import quote, unquote

from radar import github
from radar.common import clean_text, iso_date, number

CATEGORIES = {
    "video": "Video và hình ảnh tạo bằng mã hoặc AI",
    "agent-code": "Tác tử lập trình và điều phối",
    "quant": "Giao dịch định lượng và tài chính",
    "local": "Chạy mô hình trên máy",
    "fine-tune": "Tinh chỉnh mô hình",
    "rag": "Dữ liệu cho RAG và bộ nhớ của tác tử",
    "voice": "Giọng nói và âm thanh",
    "browser-mcp": "Tác tử trình duyệt, MCP, tự động hoá",
}

LABEL_NAMES = {
    "dung-ngay": "Dùng ngay",
    "xao-nau": "Xào nấu được",
    "nghien-cuu": "Nghiên cứu",
}

PERMISSIVE_LICENSES = {
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "mpl-2.0", "unlicense",
    "mit-0", "bsd-3-clause-clear", "openrail", "openrail++", "creativeml-openrail-m"
}
COPYLEFT_LICENSES = {
    "gpl-2.0", "gpl-3.0", "agpl-3.0", "lgpl-2.1", "lgpl-3.0", "gpl", "agpl", "lgpl"
}

# Area rules are generic phrases only. A project, product or company name (a repository the owner once gave as
# an example, a tool's brand) must never decide an area: the rule has to hold for repositories nobody has named
# yet. Each term is a regex fragment matched case-insensitively between word boundaries; "[- ]" accepts the
# hyphenated and spaced spellings.
CATEGORY_TERMS = [
    ("video", [
        r"videos?", r"animations?", r"text[- ]to[- ]video", r"image[- ]to[- ]video", r"text[- ]to[- ]image",
        r"image[- ]to[- ]image", r"image[- ]generation", r"motion[- ]graphics", r"generative[- ]video",
        r"video[- ]generation", r"video[- ]editing", r"creative[- ]cod(?:e|ing)",
    ]),
    ("agent-code", [
        r"coding[- ]agents?", r"code[- ]generation", r"developer[- ]tools", r"coding[- ]assistants?", r"ai[- ]coders?",
        r"ade", r"agent[- ]ide", r"code[- ]interpreter", r"agentic skills", r"agent skills", r"parallel agents",
        r"fleet of agents", r"multi[- ]agent", r"subagents?", r"agent orchestration",
        r"software development methodology", r"ai[- ]driven development", r"runtime for.*agents?",
        r"network of agents", r"senior dev", r"skills for.*engineers?", r"context window optimization",
    ]),
    ("browser-mcp", [
        r"browser[- ]automation", r"mcp", r"model[- ]context[- ]protocol", r"use the browser",
        r"computer[- ]use", r"browser[- ]agents?", r"web[- ]scraping[- ]agents?", r"headless browser",
        r"web automation",
    ]),
    ("quant", [
        r"trading", r"quant", r"quantitative", r"finance", r"backtest", r"backtesting", r"algorithmic[- ]trading",
        r"stocks?", r"financial", r"hedge[- ]funds?", r"portfolio",
    ]),
    ("local", [
        r"llm[- ]inference", r"gguf", r"local", r"locally", r"local[- ]ai", r"local[- ]llms?", r"inference in c",
        r"inference engine", r"edge[- ]ai", r"on[- ]device",
    ]),
    ("fine-tune", [
        r"fine[- ]tuning", r"finetune", r"fine[- ]tune", r"lora", r"sft", r"rlhf", r"qlora", r"peft",
        r"post[- ]training", r"distillation",
    ]),
    ("rag", [
        r"rag", r"document[- ]parsing", r"pdf", r"retrieval", r"vector[- ]database", r"vector[- ]db", r"embeddings",
        r"knowledge[- ]graph", r"graphrag", r"agent memory", r"memory for.*agents?", r"document understanding",
        r"ocr", r"web crawl(?:er|ing)",
    ]),
    ("voice", [
        r"tts", r"speech", r"voice[- ]cloning", r"asr", r"voice", r"audio", r"speech[- ]to[- ]text",
        r"text[- ]to[- ]speech", r"voice[- ]agents?", r"transcription",
    ]),
]
CATEGORY_PATTERNS = [(cat, re.compile(r"\b(?:" + "|".join(terms) + r")\b", re.I)) for cat, terms in CATEGORY_TERMS]

# A repository belongs on an AI radar only when its own name, description or topics say it is about AI.
# Vendor and model-family names are AI by definition, so they count here (unlike in the area rules above).
AI_REPO_TERMS = re.compile(
    r"\b(?:ai|llms?|gpt|chatgpt|genai|agents?|agentic|subagents?|mcp|rag|machine[- ]learning|deep[- ]learning|"
    r"neural|transformers?|diffusion|inference|embeddings?|vector[- ]database|prompts?|chatbots?|generative|"
    r"language[- ]models?|foundation[- ]models?|speech[- ]recognition|text[- ]to[- ](?:speech|image|video)|tts|asr|"
    r"speech|voice[- ]cloning|dubbing|transcription|image[- ]generation|video[- ]generation|computer[- ]use|"
    r"computer[- ]vision|fine[- ]tun(?:e|ing)|lora|model[- ]context[- ]protocol|pytorch|tensorflow|"
    r"hugging[- ]?face|openai|anthropic|claude|gemini|codex|copilot|cursor|deepseek|qwen|llama|mistral|ollama|gguf|"
    r"trí tuệ nhân tạo)\b",
    re.I,
)


def is_ai_repo(name, description="", topics=None, readme_text=None):
    """True when the repository says it is about AI. README is consulted only when the description is too
    short to say anything, so a README that merely mentions AI does not admit an unrelated project."""
    parts = [str(name or "").replace("/", " "), description or ""]
    if topics and isinstance(topics, list):
        parts.extend(str(t) for t in topics)
    if len((description or "").strip()) < 20 and readme_text and isinstance(readme_text, str):
        parts.append(readme_text[:600])
    return bool(AI_REPO_TERMS.search(" ".join(parts)))

INSTALL_PATTERNS = [
    r"pip\s+install\s+(?:-(?:U|-upgrade)\s+)?(?!-r\b|-e\b|\.\b)[a-zA-Z0-9_\-\[\]]+",
    r"uv\s+add\s+[a-zA-Z0-9_\-\[\]]+",
    r"uv\s+pip\s+install\s+[a-zA-Z0-9_\-\[\]]+",
    r"npx\s+(?:-y\s+)?[a-zA-Z0-9_\-@\/]+(?:@[a-zA-Z0-9_\-\.]+)?(?:\s+[^\n`]+)?",
    r"npm\s+i(?:nstall)?\s+-g\s+[a-zA-Z0-9_\-@\/]+",
    r"brew\s+install\s+(?:--cask\s+)?[a-zA-Z0-9_\-\/]+",
    r"winget\s+install\s+[a-zA-Z0-9_\-\.]+",
    r"docker\s+run\s+[^\n`]+",
    r"docker\s+compose\s+[^\n`]*\bup\b[^\n`]*",
    r"curl\s+[^\n`]+(?:install\.sh|\.sh\s*\|\s*(?:bash|sh))"
]

SOURCE_INSTALL_PATTERNS = [
    r"pip\s+install\s+-r\s+requirements\.txt",
    r"pip\s+install\s+(?:-e\s+)?\.",
]


FLAG_CUSTOM = "giấy phép riêng, đọc trước khi dùng thương mại"
FLAG_FSL = "giấy phép FSL, đọc trước khi dùng thương mại"
FLAG_UNMEASURED = "chưa đo được giấy phép"
FLAG_COPYLEFT = "giấy phép buộc mở mã khi phát hành lại"
FLAG_NC = "⚠ hạn chế thương mại"


def license_label(name):
    """How a reader sees a license: SPDX ids are names and stay; GitHub's placeholders become words."""
    if not name:
        return None
    if str(name).lower() in {"noassertion", "other", "none", "custom"}:
        return "giấy phép riêng"
    return str(name)


def vn_int(value):
    """Vietnamese digit grouping: 2.667, not 2,667."""
    return f"{int(value):,}".replace(",", ".")


DEV_RUNNERS = re.compile(r"\b(?:promptfoo|pytest|jest|vitest|eslint|prettier|skills\s+add|playwright)\b", re.I)


def extract_install_command(readme_text, repo=None, package_names=None):
    """Extract single-line package installation or source installation command."""
    if not readme_text or not isinstance(readme_text, str):
        return None, None
    candidates = []
    for pattern in INSTALL_PATTERNS:
        for match in re.finditer(r"(?:(?:^|\n)[ \t]*[$>]?[ \t]*(`{1,3})?|`+)(" + pattern + r")(`{1,3})?", readme_text, re.IGNORECASE):
            cmd = match.group(2).strip()
            cmd = re.split(r"[\r\n`]", cmd)[0].strip()
            candidates.append(cmd)
    candidates = [c for c in candidates if not DEV_RUNNERS.search(c)]
    if candidates:
        if repo:
            repo_short = repo.split("/")[-1].lower()
            valid_names = {
                repo_short,
                repo_short.replace("-", "_"),
                repo_short.replace("_", "-")
            }
            if repo_short.endswith(".cpp"):
                valid_names.add(repo_short[:-4])
            if package_names:
                for p in package_names:
                    if p:
                        pl = p.lower()
                        valid_names.update({pl, pl.replace("-", "_"), pl.replace("_", "-")})
            for c in candidates:
                cl = c.lower()
                if any(v in cl for v in valid_names):
                    return c, "binary"
            # S2: Not matching repo/package name -> do not return candidates[0]
        else:
            return candidates[0], "binary"
    for pattern in SOURCE_INSTALL_PATTERNS:
        match = re.search(r"(?:(?:^|\n)[ \t]*[$>]?[ \t]*(`{1,3})?|`+)(" + pattern + r")(`{1,3})?", readme_text, re.IGNORECASE)
        if match:
            cmd = match.group(2).strip()
            cmd = re.split(r"[\r\n`]", cmd)[0].strip()
            return cmd, "source"
    return None, None


def classify_category(name, description="", topics=None, pipeline_tag=None, tags=None, readme_text=None):
    """Map repository or model signals to one of the 8 agreed categories, or None."""
    pt = (pipeline_tag or "").lower()
    if pt in {"text-to-video", "image-to-video", "text-to-image", "image-to-image"}:
        return "video"
    if pt in {"text-to-speech", "automatic-speech-recognition", "audio-to-audio", "audio-classification"}:
        return "voice"
    if pt in {"document-question-answering", "visual-question-answering", "sentence-similarity", "feature-extraction"}:
        return "rag"

    parts = [name or "", description or ""]
    if topics and isinstance(topics, list):
        parts.extend(topics)
    if tags and isinstance(tags, list):
        parts.extend(tags)
    if readme_text and isinstance(readme_text, str):
        parts.append(readme_text[:1000])
    text = " ".join(parts)

    for cat, pattern in CATEGORY_PATTERNS:
        if pattern.search(text):
            return cat
    return None


def score_github_repo(repo_info, readme_text="", license_name=None, release_info=None, contents=None, pushed_at=None, now=None, license_flag_override=None, package_names=None):
    """Score GitHub repository based on measurable D1-D5, X1-X4, and N1-N3 rules."""
    now = now or datetime.now(timezone.utc)
    d_score = 0
    x_score = 0
    signals = {}

    # B3: Missing README means unmeasured -> label is None
    if not readme_text:
        lic_lower = (license_name or "").lower()
        if lic_lower in PERMISSIVE_LICENSES:
            computed_lic_flag = None
        elif any(lic_lower.startswith(c) for c in COPYLEFT_LICENSES):
            computed_lic_flag = FLAG_COPYLEFT
        elif lic_lower in {"noassertion", "none", "", "other"}:
            computed_lic_flag = FLAG_CUSTOM
        elif license_name:
            if any(p in lic_lower for p in ["mit", "apache", "bsd", "isc", "mpl"]):
                computed_lic_flag = None
            else:
                computed_lic_flag = FLAG_CUSTOM
        else:
            computed_lic_flag = FLAG_UNMEASURED

        return {
            "label": None,
            "d_score": None,
            "x_score": None,
            "license": license_name,
            "license_flag": license_flag_override or computed_lic_flag,
            "signals": {
                "readme_measured": False,
                "install_command": None,
                "install_type": None,
                "release_tag": release_info.get("tag_name") if release_info else None,
                "release_days_ago": None,
                "has_binary_assets": None,
                "has_demo": None,
                "has_product_page": None,
                "has_docker": None,
                "license": license_name,
                "has_examples": None,
                "has_quickstart": None,
                "pushed_days_ago": None,
                "has_paper": None,
                "has_manifest": None,
                "non_commercial": None,
                "d_score": None,
                "x_score": None,
            },
            "why": None
        }

    signals["readme_measured"] = True

    # D1 / D1' install command
    cmd, itype = extract_install_command(readme_text, repo=repo_info.get("repo"), package_names=package_names)
    if itype == "binary":
        d_score += 25
        signals["d1"] = 25
        signals["install_command"] = cmd
        signals["install_type"] = "binary"
    elif itype == "source":
        d_score += 10
        signals["d1_prime"] = 10
        signals["install_command"] = cmd
        signals["install_type"] = "source"
    else:
        signals["install_command"] = None
        signals["install_type"] = None
        signals["d1"] = None
        signals["d1_prime"] = None

    # D2, D3 release status
    if release_info is None:
        signals["release_tag"] = None
        signals["release_days_ago"] = None
        signals["has_binary_assets"] = None
        signals["d2"] = None
        signals["d3"] = None
    else:
        tag = release_info.get("tag_name")
        signals["release_tag"] = tag
        published_at_str = release_info.get("published_at") or release_info.get("created_at")
        if published_at_str:
            try:
                pub_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                release_days = max(0, int((now - pub_date).total_seconds() / 86400))
                signals["release_days_ago"] = release_days
                if release_days <= 90:
                    d_score += 10
                    signals["d2"] = 10
                else:
                    signals["d2"] = None
            except Exception:
                signals["release_days_ago"] = None
                signals["d2"] = None
        else:
            signals["release_days_ago"] = None
            signals["d2"] = None

        assets = release_info.get("assets")
        if assets is None:
            # S3: In fallback or unmeasured assets: D3 = không biết
            signals["has_binary_assets"] = None
            signals["d3"] = None
        elif len(assets) >= 1:
            d_score += 15
            signals["d3"] = 15
            signals["has_binary_assets"] = True
        else:
            signals["has_binary_assets"] = False
            signals["d3"] = None

    # D4 demo & product page
    has_demo = any(h in readme_text for h in ["huggingface.co/spaces", "colab.research.google.com", "replicate.com"])
    homepage = repo_info.get("homepage")
    has_product_page = bool(homepage and not any(h in homepage for h in ["github.com", "arxiv.org"]))
    signals["has_demo"] = has_demo
    signals["has_product_page"] = has_product_page
    if has_demo:
        d_score += 10
        signals["d4"] = 10
    elif has_product_page:
        d_score += 10
        signals["d4"] = 10
    else:
        signals["d4"] = None

    # D5 Dockerfile
    # S6: D5 chỉ tính tệp ở thư mục gốc, không tính "docker run" trong README
    # B3: Bỏ D5 khi chưa biết contents
    if contents is None:
        signals["has_docker"] = None
        signals["d5"] = None
    else:
        has_docker = any(c.lower().startswith("dockerfile") or c.lower().startswith("docker-compose") or c.lower() == "docker" for c in contents)
        signals["has_docker"] = has_docker
        if has_docker:
            d_score += 5
            signals["d5"] = 5
        else:
            signals["d5"] = None

    # X1 License
    lic_lower = (license_name or "").lower()
    signals["license"] = license_name
    license_flag = license_flag_override
    if not license_name:
        if not license_flag:
            license_flag = FLAG_UNMEASURED
        signals["x1"] = None
        signals["x1_prime"] = None
    elif lic_lower in PERMISSIVE_LICENSES:
        x_score += 15
        signals["x1"] = 15
    elif any(lic_lower.startswith(c) for c in COPYLEFT_LICENSES):
        x_score += 5
        signals["x1_prime"] = 5
        license_flag = FLAG_COPYLEFT
    elif lic_lower in {"noassertion", "none", "", "other"}:
        if "fsl" in (readme_text or "").lower():
            license_flag = FLAG_FSL
        else:
            license_flag = FLAG_CUSTOM
        signals["x1"] = None
        signals["x1_prime"] = None
    else:
        if any(p in lic_lower for p in ["mit", "apache", "bsd", "isc", "mpl"]):
            x_score += 15
            signals["x1"] = 15
        else:
            license_flag = FLAG_CUSTOM
            signals["x1"] = None
            signals["x1_prime"] = None

    # X2 Examples
    # B3: Bỏ X2 khi chưa biết contents
    if contents is None:
        if re.search(r"(?:^|\n)#{1,3}\s+(?:examples|example|notebooks|cookbook)\b", readme_text, re.I):
            signals["has_examples"] = True
            x_score += 10
            signals["x2"] = 10
        else:
            signals["has_examples"] = None
            signals["x2"] = None
    else:
        has_examples = any(c.lower() in {"examples", "example", "templates", "notebooks", "cookbook"} for c in contents) or bool(re.search(r"(?:^|\n)#{1,3}\s+(?:examples|example|notebooks|cookbook)\b", readme_text, re.I))
        signals["has_examples"] = has_examples
        if has_examples:
            x_score += 10
            signals["x2"] = 10
        else:
            signals["x2"] = None

    # X3 Quickstart heading
    has_quickstart = bool(re.search(r"(?:^|\n)#{1,3}\s+(?:quick\s*start|getting\s+started|usage|examples|installation)\b", readme_text, re.I))
    signals["has_quickstart"] = has_quickstart
    if has_quickstart:
        x_score += 10
        signals["x3"] = 10
    else:
        signals["x3"] = None

    # X4 Pushed at
    if pushed_at:
        try:
            p_date = datetime.fromisoformat(pushed_at.replace("Z", "+00:00")) if isinstance(pushed_at, str) else pushed_at
            pushed_days = max(0, int((now - p_date).total_seconds() / 86400))
            signals["pushed_days_ago"] = pushed_days
            if pushed_days <= 30:
                x_score += 5
                signals["x4"] = 5
            else:
                signals["x4"] = None
        except Exception:
            signals["pushed_days_ago"] = None
            signals["x4"] = None
    else:
        signals["pushed_days_ago"] = None
        signals["x4"] = None

    # N1 Paper reference
    has_paper = False
    desc = repo_info.get("description") or ""
    if (homepage and "arxiv.org" in homepage) or re.search(r"^(?:Official )?(?:PyTorch )?(?:code|implementation) (?:for|of)", desc, re.I):
        has_paper = True
    elif readme_text and ("arxiv.org" in readme_text or "BibTeX" in readme_text or "@article" in readme_text):
        has_paper = True
    signals["has_paper"] = has_paper

    # N2 Manifest penalty
    # B3: Bỏ N2 khi chưa biết contents
    if contents is None:
        signals["has_manifest"] = None
        signals["n2_penalty"] = None
    else:
        manifests = {"pyproject.toml", "setup.py", "package.json", "cargo.toml", "go.mod", "cmakelists.txt"}
        has_manifest = any(c.lower() in manifests for c in contents)
        signals["has_manifest"] = has_manifest
        if not has_manifest and itype != "binary":
            d_score -= 15
            signals["n2_penalty"] = -15
        else:
            signals["n2_penalty"] = None

    # N3 Non-commercial / restriction
    # Nit 1: "⚠ hạn chế thương mại"
    has_nc = False
    if readme_text and re.search(r"\b(?:non-commercial|cc-by-nc|research purposes only|example only)\b", readme_text, re.I):
        has_nc = True
        license_flag = FLAG_NC
    signals["non_commercial"] = has_nc

    is_archived = repo_info.get("archived", False)
    is_fork = repo_info.get("fork", False)
    pushed_days = signals.get("pushed_days_ago")
    if pushed_days is not None and pushed_days > 365:
        is_archived = True

    # Label assignment
    # Nit 3: NOASSERTION không tính là "có license" cho xao-nau
    if not is_archived and not is_fork and d_score >= 35:
        label = "dung-ngay"
    elif not is_archived and not is_fork and x_score >= 25 and license_name and lic_lower not in {"none", "null", "", "noassertion"}:
        label = "xao-nau"
    else:
        label = "nghien-cuu"

    signals["d_score"] = d_score
    signals["x_score"] = x_score

    # Construct "why" string
    parts = [LABEL_NAMES[label]]
    if cmd:
        parts.append(f"cài: `{cmd}`")
    tag = signals.get("release_tag")
    release_days = signals.get("release_days_ago")
    if tag:
        rel_str = f"bản {tag}"
        if release_days is not None:
            rel_str += " ra hôm nay" if release_days == 0 else f" ra {release_days} ngày trước"
        if signals.get("has_binary_assets"):
            rel_str += ", có bản dựng sẵn"
        parts.append(rel_str)
    if license_name:
        lic_str = license_label(license_name)
        if license_flag == FLAG_FSL:
            lic_str = "giấy phép FSL"
        elif license_flag == FLAG_CUSTOM and lic_str != "giấy phép riêng":
            lic_str += " (giấy phép riêng)"
        parts.append(lic_str)
    elif license_flag:
        parts.append(license_flag)

    # Stars gained are not part of this sentence: each trending window carries its own measured count
    # (`stars_gained`), and one sentence mixing "today" and "this week" was what made the list unreadable.

    if signals.get("has_demo"):
        parts.append("có bản chạy thử")
    elif signals.get("has_product_page"):
        # A homepage alone is a product or docs page, never a demo.
        parts.append("có trang sản phẩm/tài liệu")

    if signals.get("has_examples"):
        parts.append("có thư mục ví dụ")
    if signals.get("has_paper") and label != "dung-ngay":
        parts.append("kèm bài báo khoa học")
    if signals.get("non_commercial"):
        parts.append(FLAG_NC)

    why = " · ".join(parts)
    return {
        "label": label,
        "d_score": d_score,
        "x_score": x_score,
        "license": license_name,
        "license_flag": license_flag,
        "signals": signals,
        "why": why
    }


def score_hf_model(model_info, model_details=None, now=None):
    """Score Hugging Face model based on API accessibility, local formats and community derivatives."""
    if model_details is None:
        # B3: Missing measurement -> label is None, why is None
        return {
            "label": None,
            "license": model_info.get("license"),
            "license_flag": None,
            "signals": {
                "gated": None,
                "library_name": model_info.get("library_name"),
                "pipeline_tag": model_info.get("pipeline_tag"),
                "license": model_info.get("license"),
                "spaces_count": None,
                "spaces_capped": None,
                "quantized_count": None,
                "finetune_count": None,
                "inference_provider": None,
                "likes": model_info.get("likes"),
                "downloads": model_info.get("downloads"),
                "hf_score": None,
                "model_details_measured": False,
            },
            "why": None,
        }

    raw_gated = model_details.get("gated", model_info.get("gated", False))
    # B4: Chuẩn hoá gated: False/None -> False; "auto" -> "auto"; True/"manual" -> "manual"
    if not raw_gated or raw_gated is False:
        norm_gated = False
    elif isinstance(raw_gated, str) and raw_gated.strip().lower() == "auto":
        norm_gated = "auto"
    else:
        norm_gated = "manual"

    library_name = model_details.get("library_name", model_info.get("library_name"))
    pipeline_tag = model_details.get("pipeline_tag", model_info.get("pipeline_tag"))
    tags = model_details.get("tags") or model_info.get("tags") or []

    card_data = model_details.get("cardData") or {}
    license_name = card_data.get("license") or model_info.get("license")
    if not license_name:
        for t in tags:
            if t.startswith("license:"):
                license_name = t.split(":", 1)[1]
                break

    spaces = model_details.get("spaces")
    if isinstance(spaces, list):
        spaces_count = len(spaces)
        spaces_capped = (spaces_count == 100)  # B5: capped at 100
    elif isinstance(spaces, int):
        spaces_count = spaces
        spaces_capped = (spaces_count >= 100)
    else:
        spaces_count = 0
        spaces_capped = False

    children = model_details.get("childrenModelCount") or {}
    quantized_count = children.get("quantized", 0)
    finetune_count = children.get("finetune", 0)

    inference_provider = bool(model_details.get("inferenceProviderMapping") or model_info.get("availableInferenceProviders"))

    likes = model_info.get("likes", model_details.get("likes"))
    downloads = model_info.get("downloads", model_details.get("downloads"))

    # License flag & permissive check
    lic_lower = (license_name or "").lower()
    license_flag = None
    # Nit 2: match token (^|-)nc(-|$) instead of substring
    is_nc = bool(re.search(r"(?:^|[\-_])nc(?:[\-_]|$)|non-commercial|research", lic_lower))
    if is_nc:
        license_flag = FLAG_NC
    elif lic_lower in ["other", "custom"]:
        license_flag = FLAG_CUSTOM

    is_permissive = (lic_lower in PERMISSIVE_LICENSES and not is_nc)

    is_gguf = (library_name in {"gguf", "mlx"} or any("gguf" in t.lower() for t in tags)
               or "gguf" in model_info.get("id", "").lower())
    has_quantized = (quantized_count is not None and quantized_count >= 1)
    is_runnable_or_api = (inference_provider or is_gguf or has_quantized)
    has_library = library_name in {"transformers", "diffusers", "sentence-transformers", "nemo", "timm", "peft"}
    has_spaces_or_finetune = (spaces_count >= 3 or finetune_count >= 1)

    gate_flag = None
    if norm_gated == "auto":
        gate_flag = "cần đồng ý điều khoản trên Hugging Face"
    elif norm_gated == "manual":
        gate_flag = "cần được duyệt điều khoản trên Hugging Face"

    # Classification rules according to B4 & S4
    if norm_gated is False or norm_gated == "auto":
        if is_runnable_or_api:
            label = "dung-ngay"
        elif has_library and is_permissive and has_spaces_or_finetune:
            label = "xao-nau"
        else:
            label = "nghien-cuu"
    else:
        # norm_gated == "manual": trọng số gốc một mình không đủ để ra dung-ngay.
        # Khi có inference_provider hoặc quantized >= 1 thì cho dung-ngay hoặc xao-nau, kèm cờ.
        if inference_provider or has_quantized:
            label = "dung-ngay"
        elif has_library and is_permissive and has_spaces_or_finetune:
            label = "xao-nau"
        else:
            label = "nghien-cuu"

    # S8: Score calculation for HF models on 0-100 scale
    hf_score = 0
    if inference_provider:
        hf_score += 25
    if is_gguf or has_quantized:
        hf_score += 25
    if spaces_count >= 3:
        hf_score += 15
    elif spaces_count >= 1:
        hf_score += 10
    if finetune_count >= 1:
        hf_score += 10
    if has_library:
        hf_score += 10
    if is_permissive:
        hf_score += 15
    elif license_name and not is_nc:
        hf_score += 5

    signals = {
        "gated": norm_gated,
        "library_name": library_name,
        "pipeline_tag": pipeline_tag,
        "license": license_name,
        "spaces_count": spaces_count,
        "spaces_capped": spaces_capped,
        "quantized_count": quantized_count,
        "finetune_count": finetune_count,
        "inference_provider": inference_provider,
        "likes": likes,
        "downloads": downloads,
        "hf_score": hf_score,
        "gate_flag": gate_flag,
        "model_details_measured": True,
    }

    label_vn = LABEL_NAMES[label]
    parts = [label_vn]
    if inference_provider:
        parts.append("gọi được qua API")
    if is_gguf:
        parts.append("định dạng GGUF chạy máy")
    elif quantized_count >= 1:
        parts.append(f"có {vn_int(quantized_count)} bản lượng tử")
    elif library_name:
        parts.append(f"thư viện {library_name}")

    if license_name and license_flag != FLAG_CUSTOM:
        parts.append(license_label(license_name))
    if spaces_capped:
        parts.append("hơn 100 bản chạy thử trên Spaces")
    elif spaces_count > 0:
        parts.append(f"{spaces_count} bản chạy thử trên Spaces" if spaces_count > 1 else "có bản chạy thử trên Spaces")
    if finetune_count >= 1:
        parts.append(f"{vn_int(finetune_count)} mô hình phái sinh")
    if likes is not None and likes > 0:
        parts.append(f"{vn_int(likes)} lượt thích")
    if license_flag:
        parts.append(license_flag)
    if gate_flag:
        parts.append(gate_flag)
    if label == "nghien-cuu" and not library_name and not pipeline_tag:
        parts.append("chưa có bản chạy chuẩn")

    why = " · ".join(parts)
    return {
        "label": label,
        "license": license_name,
        "license_flag": license_flag,
        "signals": signals,
        "why": why
    }


def _fetch_url_with_error(fetcher, url, source_id=None):
    if fetcher is None:
        return None, "no_fetcher"
    try:
        if hasattr(fetcher, "__call__"):
            try:
                resp = fetcher(url, source_id=source_id)
            except TypeError:
                resp = fetcher(url)
            return resp, None
    except Exception as exc:
        status = getattr(exc, "http_status", getattr(exc, "code", None))
        if isinstance(exc, TimeoutError):
            return None, "timeout"
        if status:
            return None, f"HTTP {status}"
        return None, f"{type(exc).__name__}: {exc}"
    return None, "unknown"


def _enrich_github_item(repo_info, fetcher, now):
    repo = repo_info["repo"]
    readme_text = ""
    lic_name = None
    lic_flag_override = None
    release_info = None
    contents = None
    pushed_at = None
    created_at = None
    api_forks = None
    api_enriched = False
    api_fallback_reason = None
    package_names = set()

    # 1. Fetch README (always available via raw.githubusercontent.com)
    readme_url = f"https://raw.githubusercontent.com/{repo}/HEAD/README.md"
    readme_resp, _ = _fetch_url_with_error(fetcher, readme_url, source_id="github-trending")
    if readme_resp:
        readme_text = str(readme_resp)

    # 2. Try GitHub REST API
    api_base = f"https://api.github.com/repos/{repo}"
    repo_json, api_err = _fetch_url_with_error(fetcher, api_base, source_id="github-trending")
    if repo_json:
        try:
            data = json.loads(str(repo_json))
            if isinstance(data, dict) and "id" in data:
                api_enriched = True
                pushed_at = data.get("pushed_at")
                created_at = iso_date(data.get("created_at"))
                api_forks = number(data.get("forks_count"))
                if number(data.get("stargazers_count")) is not None:
                    repo_info["stars"] = number(data.get("stargazers_count"))
                lic = data.get("license") or {}
                lic_name = lic.get("spdx_id")
                if not repo_info.get("description"):
                    repo_info["description"] = data.get("description")
                if not repo_info.get("stars"):
                    repo_info["stars"] = data.get("stargazers_count")
                if data.get("homepage"):
                    repo_info["homepage"] = data.get("homepage")
                if data.get("topics"):
                    repo_info["topics"] = data.get("topics")
                repo_info["archived"] = data.get("archived", False)
                repo_info["fork"] = data.get("fork", False)
        except Exception:
            pass

    if not api_enriched:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            api_fallback_reason = "thiếu GITHUB_TOKEN"
        elif api_err == "timeout":
            api_fallback_reason = "timeout"
        else:
            api_fallback_reason = api_err or "GitHub API request failed"

    if api_enriched:
        rel_json, _ = _fetch_url_with_error(fetcher, f"{api_base}/releases/latest", source_id="github-trending")
        if rel_json:
            try:
                rel_data = json.loads(str(rel_json))
                if isinstance(rel_data, dict):
                    release_info = rel_data
            except Exception:
                pass
        cnt_json, _ = _fetch_url_with_error(fetcher, f"{api_base}/contents/", source_id="github-trending")
        if cnt_json:
            try:
                cnt_data = json.loads(str(cnt_json))
                if isinstance(cnt_data, list):
                    contents = [row.get("name", "") for row in cnt_data if isinstance(row, dict)]
            except Exception:
                pass
    else:
        # B2: In fallback, never invent SPDX (Apache, GPL, BSD). Leave license = None and flag FLAG_UNMEASURED
        lic_name = None
        lic_flag_override = FLAG_UNMEASURED
        # B3: In fallback, contents was not measured
        contents = None

        # Check releases.atom for latest release tag and date
        rel_atom, _ = _fetch_url_with_error(fetcher, f"https://github.com/{repo}/releases.atom", source_id="github-trending")
        if rel_atom:
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(str(rel_atom))
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                entry = root.find("atom:entry", ns)
                if entry is not None:
                    title = entry.find("atom:title", ns)
                    updated = entry.find("atom:updated", ns)
                    tag_name = title.text.strip() if title is not None and title.text else None
                    # The entry title is the release's free-text name (it can be a whole commit message);
                    # the tag is the last segment of the entry's link.
                    link = entry.find("atom:link", ns)
                    tag_m = re.search(r"/releases/tag/([^/?#]+)$", link.get("href", "")) if link is not None else None
                    if tag_m:
                        tag_name = unquote(tag_m.group(1))
                    pub_at = updated.text.strip() if updated is not None and updated.text else None
                    # S3: D3 = không biết; assets = None
                    release_info = {
                        "tag_name": tag_name,
                        "published_at": pub_at,
                        "assets": None,
                        "estimated": True
                    }
            except Exception:
                pass

        # Check commits.atom for latest commit activity (pushed_at)
        com_atom, _ = _fetch_url_with_error(fetcher, f"https://github.com/{repo}/commits.atom", source_id="github-trending")
        if com_atom:
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(str(com_atom))
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                entry = root.find("atom:entry", ns)
                if entry is not None:
                    updated = entry.find("atom:updated", ns)
                    if updated is not None and updated.text:
                        pushed_at = updated.text.strip()
            except Exception:
                pass

    evaluated = score_github_repo(
        repo_info,
        readme_text=readme_text,
        license_name=lic_name,
        release_info=release_info,
        contents=contents,
        pushed_at=pushed_at,
        now=now,
        license_flag_override=lic_flag_override,
        package_names=package_names
    )
    evaluated["signals"]["api_enriched"] = api_enriched
    if api_fallback_reason:
        evaluated["signals"]["api_fallback_reason"] = api_fallback_reason

    category = classify_category(
        repo,
        description=repo_info.get("description", ""),
        topics=repo_info.get("topics"),
        readme_text=readme_text
    )

    gained = {window: repo_info.get("stars_gained", {}).get(window) for window, _, _ in github.WINDOWS}
    # Forks: the API's count when it answered, else the count GitHub printed on the trending card; both are
    # GitHub's own measurement. Neither means unknown, never zero.
    forks, forks_source = (api_forks, "api") if api_forks is not None else (
        (repo_info.get("forks"), "trending_page") if repo_info.get("forks") is not None else (None, None))

    return {
        "id": repo,
        "full_name": repo,
        "url": repo_info["url"],
        "description": repo_info.get("description"),
        "label": evaluated["label"],
        "category": category,
        "why": evaluated["why"],
        "license": evaluated["license"],
        "license_flag": evaluated["license_flag"],
        "stars": repo_info.get("stars"),
        "stars_gained_7d": gained["week"],
        "stars_gained": gained,
        "trending_rank": {window: repo_info.get("trending_rank", {}).get(window) for window, _, _ in github.WINDOWS},
        "forks": forks,
        "forks_source": forks_source,
        "created_at": created_at,
        "ai_related": is_ai_repo(repo, repo_info.get("description") or "", repo_info.get("topics"), readme_text),
        "signals": evaluated["signals"],
        "source": "github-trending"
    }


def _enrich_hf_item(model_info, fetcher, now):
    model_id = model_info["id"]
    model_details = None
    hf_fallback_reason = None

    url = (f"https://huggingface.co/api/models/{quote(model_id, safe='/')}"
           "?expand[]=library_name&expand[]=pipeline_tag&expand[]=gated&expand[]=cardData"
           "&expand[]=spaces&expand[]=childrenModelCount&expand[]=inferenceProviderMapping"
           "&expand[]=tags&expand[]=downloads&expand[]=likes")
    resp, err = _fetch_url_with_error(fetcher, url, source_id="hf-trending")
    if resp:
        try:
            data = json.loads(str(resp))
            if isinstance(data, dict):
                model_details = data
        except Exception as exc:
            hf_fallback_reason = f"JSONDecodeError: {exc}"
    else:
        hf_fallback_reason = err or "HF API unreachable"

    evaluated = score_hf_model(model_info, model_details=model_details, now=now)
    if hf_fallback_reason:
        evaluated["signals"]["api_fallback_reason"] = hf_fallback_reason

    category = classify_category(
        model_id,
        description="",
        pipeline_tag=model_info.get("pipeline_tag") or (model_details.get("pipeline_tag") if model_details else None),
        tags=model_details.get("tags") if model_details else model_info.get("tags")
    )

    return {
        "id": model_id,
        "full_name": model_id,
        "url": model_info["url"],
        "description": None,
        "label": evaluated["label"],
        "category": category,
        "why": evaluated["why"],
        "license": evaluated["license"],
        "license_flag": evaluated["license_flag"],
        "stars": model_info.get("likes"),
        "stars_gained_7d": None,
        "stars_gained": {window: None for window, _, _ in github.WINDOWS},
        "trending_rank": {window: None for window, _, _ in github.WINDOWS},
        "forks": None,
        "forks_source": None,
        "created_at": None,
        "ai_related": True,
        "signals": evaluated["signals"],
        "source": "hf"
    }


WINDOW_NAMES = {"day": "theo ngày", "week": "theo tuần", "month": "theo tháng"}
TRENDING_RETRY_SECONDS = 3


def _trending_windows(daily, fetcher):
    """Collect GitHub Trending's day, week and month pages. A window is measured only by its own page:
    a page that failed, or that printed another window's phrase, leaves that window unmeasured."""
    windows, status = {}, {}
    for window, url, _ in github.WINDOWS:
        rows, error = [], None
        if window == "day":
            rows = list(daily or [])
            if not rows:
                error = "chưa lấy được trang thịnh hành theo ngày"
        else:
            # GitHub renders the week and month pages on demand and answers 504 while it does (measured
            # 03/10 on the month page), so a failed read is retried twice before the window counts as unmeasured.
            for attempt in range(3):
                text, err = _fetch_url_with_error(fetcher, url, source_id="github-trending")
                if text or err in (None, "no_fetcher") or attempt == 2:
                    break
                time.sleep(TRENDING_RETRY_SECONDS)
            if text:
                try:
                    rows = github.parse_trending(str(text))
                except ValueError:
                    error = "trang thịnh hành " + WINDOW_NAMES[window] + " không có thẻ kho mã nào đọc được"
            else:
                error = "chưa tải được trang thịnh hành " + WINDOW_NAMES[window] + (" (" + err + ")" if err and err.startswith("HTTP") else "")
        measured = []
        for rank, row in enumerate(rows, 1):
            if not isinstance(row, dict) or not row.get("repo"):
                continue
            period = row.get("gained_period")
            # Rows from older collectors only carry `stars_today`, which is the day page's own count.
            if period not in (None, window):
                continue
            gain = row.get("stars_gained") if period else (row.get("stars_today") if window == "day" else None)
            measured.append((rank, row, gain))
        if rows and not any(gain is not None for _, _, gain in measured):
            error = error or "trang thịnh hành " + WINDOW_NAMES[window] + " không ghi số sao tăng của khung này"
        windows[window] = measured
        status[window] = {"measured": any(gain is not None for _, _, gain in measured),
                          "count": sum(gain is not None for _, _, gain in measured), "error": error, "url": url}
    return windows, status


def _merge_windows(windows):
    """One candidate per repository, carrying each window's measured gain and page rank."""
    merged = {}
    for window, rows in windows.items():
        for rank, row, gain in rows:
            item = merged.setdefault(row["repo"], dict(row, stars_gained={}, trending_rank={}))
            for key in ("description", "stars", "forks", "language", "url"):
                if item.get(key) in (None, "") and row.get(key) not in (None, ""):
                    item[key] = row[key]
            item["stars_gained"][window] = gain
            item["trending_rank"][window] = rank
            if window == "day" and gain is not None:
                item["stars_today"] = gain
            if window == "week" and gain is not None:
                item["stars_this_week"] = gain
    return list(merged.values())


def _ranked(rows, key):
    measured = [row for row in rows if key(row) is not None]
    return [row["id"] for row in sorted(measured, key=lambda row: (-key(row), -(row.get("stars") or 0), row["id"]))]


def rank_repos(repos):
    """Orderings the page shows. Each is a list of repository ids, measured values only:

    - trending[window]: stars gained in that window, highest first (a repository not measured in the window
      is absent, never placed by another window's count);
    - stars / forks: total count on GitHub, highest first;
    - usable[window]: repositories labelled `dung-ngay`, by stars gained in that window.
    Labels never change the order; they are badges.
    """
    shown = [row for row in repos if row.get("source") == "github-trending" and row.get("label") and row.get("ai_related", True)]
    windows = [window for window, _, _ in github.WINDOWS]

    def gained(window):
        return lambda row: (row.get("stars_gained") or {}).get(window)

    usable = [row for row in shown if row["label"] == "dung-ngay"]
    return {
        "trending": {window: _ranked(shown, gained(window)) for window in windows},
        "stars": _ranked(shown, lambda row: row.get("stars")),
        "forks": _ranked(shown, lambda row: row.get("forks")),
        "usable": {window: _ranked(usable, gained(window)) for window in windows},
    }


def curate_repos(github_trending, hf_trending, fetcher=None, now=None, meta=None):
    """Enrich, score, categorize and rank trending GitHub repositories and Hugging Face models.

    `github_trending` is the day page; the week and month pages are fetched here. Repositories that do not
    say they are about AI are left out and listed in `meta["excluded_non_ai"]`.
    """
    now = now or datetime.now(timezone.utc)
    if not github_trending and not hf_trending:
        return []

    meta_dict = meta if isinstance(meta, dict) else {}
    meta_dict.setdefault("dropped_count", 0)
    meta_dict.setdefault("dropped_items", [])
    meta_dict.setdefault("fallback_count", 0)
    meta_dict.setdefault("fallback_reasons", {})
    meta_dict.setdefault("excluded_non_ai", [])

    windows, status = _trending_windows(github_trending, fetcher)
    candidates = _merge_windows(windows)
    meta_dict["windows"] = status

    results = []
    hf_models = [row for row in hf_trending if row.get("type") == "model"] if hf_trending else []
    meta_dict.setdefault("total_candidates", len(candidates) + len(hf_models))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {}
        for r in candidates:
            fut = executor.submit(_enrich_github_item, dict(r), fetcher, now)
            future_map[fut] = (r.get("repo", "unknown"), "github-trending")
        for m in hf_models:
            fut = executor.submit(_enrich_hf_item, dict(m), fetcher, now)
            future_map[fut] = (m.get("id", "unknown"), "hf")

        for fut in concurrent.futures.as_completed(future_map.keys()):
            item_id, item_source = future_map[fut]
            try:
                item = fut.result()
                if item:
                    if not item.get("ai_related", True):
                        meta_dict["excluded_non_ai"].append(item_id)
                        continue
                    sig = item.get("signals") or {}
                    if not sig.get("api_enriched", True):
                        meta_dict["fallback_count"] += 1
                        fb_reason = sig.get("api_fallback_reason") or "unspecified_fallback"
                        meta_dict["fallback_reasons"][fb_reason] = meta_dict["fallback_reasons"].get(fb_reason, 0) + 1

                    if item.get("label") is None:
                        meta_dict["dropped_count"] += 1
                        reason = sig.get("api_fallback_reason") or "missing_readme_or_details"
                        meta_dict["dropped_items"].append({"id": item_id, "source": item_source, "reason": reason})
                    results.append(item)
            except Exception as exc:
                meta_dict["dropped_count"] += 1
                meta_dict["dropped_items"].append({
                    "id": item_id,
                    "source": item_source,
                    "reason": f"{type(exc).__name__}: {exc}"
                })

    meta_dict["excluded_non_ai"].sort()

    def sort_key(row):
        gained = row.get("stars_gained") or {}
        by_window = tuple(-gained[window] if gained.get(window) is not None else 1 for window in ("week", "day", "month"))
        return by_window + (-(row.get("stars") or 0), row.get("id"))

    results.sort(key=sort_key)
    meta_dict["rankings"] = rank_repos(results)
    return results


