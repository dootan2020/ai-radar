"""Curation and evaluation of trending GitHub repositories and Hugging Face models."""

import concurrent.futures
from datetime import datetime, timezone
import json
import math
import os
import re
from urllib.parse import quote

from radar.common import clean_text, iso_date, number

CATEGORIES = {
    "video": "Video và hình ảnh bằng code/AI",
    "agent-code": "Agent lập trình và điều phối",
    "quant": "Quant trading và tài chính",
    "local": "Chạy model trên máy",
    "fine-tune": "Tinh chỉnh model",
    "rag": "Dữ liệu cho RAG và bộ nhớ agent",
    "voice": "Giọng nói và âm thanh",
    "browser-mcp": "Agent trình duyệt, MCP, tự động hoá",
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

CATEGORY_PATTERNS = [
    ("video", re.compile(
        r"\b(?:video|animation|ffmpeg|remotion|text-to-video|image-to-video|text-to-image|image-to-image|"
        r"image-generation|hyperframes|motion-graphics|generative-video|video-generation|video-editing|creative-code)\b",
        re.I
    )),
    ("agent-code", re.compile(
        r"\b(?:coding[- ]agents?|code[- ]generation|developer[- ]tools|coding[- ]assistant|ai[- ]coder|"
        r"\bade\b|claude[- ]code|codex|agent[- ]ide|openhands|\bcline\b|copilot|cursor|devin|swe[- ]bench|"
        r"code[- ]interpreter|agentic skills|agent skills|software development methodology|"
        r"ai-driven development|runtime for.*agents?|network of agents|senior dev|skills for.*engineers?|"
        r"context window optimization|stablyai/orca)\b",
        re.I
    )),
    ("browser-mcp", re.compile(
        r"\b(?:browser[- ]automation|\bmcp\b|model[- ]context[- ]protocol|browser[- ]use|playwright|"
        r"computer[- ]use|browser[- ]agent|web-scraping-agent|puppeteer|entire internet)\b",
        re.I
    )),
    ("quant", re.compile(
        r"\b(?:trading|quant|finance|backtest|backtesting|algorithmic[- ]trading|stock|financial|"
        r"hedge[- ]fund|tradingagents|qlib|freqtrade)\b",
        re.I
    )),
    ("local", re.compile(
        r"\b(?:llm[- ]inference|\bgguf\b|\blocal\b|ollama|llama\.cpp|\bvllm\b|\bmlx\b|local[- ]ai|"
        r"local[- ]llm|inference in c|inference engine|edge[- ]ai)\b",
        re.I
    )),
    ("fine-tune", re.compile(
        r"\b(?:fine[- ]tuning|finetune|fine[- ]tune|\blora\b|\bsft\b|\brlhf\b|\bqlora\b|\bpeft\b|"
        r"unsloth|llamafactory|llama-factory|axolotl|post[- ]training|distillation)\b",
        re.I
    )),
    ("rag", re.compile(
        r"\b(?:\brag\b|document[- ]parsing|\bpdf\b|\bretrieval\b|vector[- ]database|vector[- ]db|"
        r"embeddings|knowledge[- ]graph|graphrag|\bmem0\b|docling|crawl4ai|firecrawl|"
        r"document understanding|\bocr\b)\b",
        re.I
    )),
    ("voice", re.compile(
        r"\b(?:\btts\b|\bspeech\b|voice[- ]cloning|\basr\b|\bvoice\b|\baudio\b|speech[- ]to[- ]text|"
        r"text[- ]to[- ]speech|voice[- ]agent|chatterbox|f5[- ]tts|whisper|bark)\b",
        re.I
    )),
]

INSTALL_PATTERNS = [
    r"pip\s+install\s+(?:-(?:U|-upgrade)\s+)?(?!-r\b|-e\b|\.\b)[a-zA-Z0-9_\-\[\]]+",
    r"uv\s+add\s+[a-zA-Z0-9_\-\[\]]+",
    r"uv\s+pip\s+install\s+[a-zA-Z0-9_\-\[\]]+",
    r"npx\s+(?:-y\s+)?[a-zA-Z0-9_\-@\/]+(?:@[a-zA-Z0-9_\-\.]+)?",
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


def extract_install_command(readme_text, repo=None):
    """Extract single-line package installation or source installation command."""
    if not readme_text or not isinstance(readme_text, str):
        return None, None
    repo_short = repo.split("/")[-1].lower() if repo else ""
    candidates = []
    for pattern in INSTALL_PATTERNS:
        for match in re.finditer(r"(?:(?:^|\n)[ \t]*[$>]?[ \t]*(`{1,3})?|`+)(" + pattern + r")(`{1,3})?", readme_text, re.IGNORECASE):
            cmd = match.group(2).strip()
            cmd = re.split(r"[\r\n`]", cmd)[0].strip()
            candidates.append(cmd)
    DEV_RUNNERS = re.compile(r"\b(?:promptfoo|pytest|jest|vitest|eslint|prettier)\b", re.I)
    candidates = [c for c in candidates if not DEV_RUNNERS.search(c)]
    if candidates:
        if repo_short:
            for c in candidates:
                if repo_short in c.lower() and not c.lower().startswith("npx skills add"):
                    return c, "binary"
            for c in candidates:
                if repo_short in c.lower():
                    return c, "binary"
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


def score_github_repo(repo_info, readme_text="", license_name=None, release_info=None, contents=None, pushed_at=None, now=None):
    """Score GitHub repository based on measurable D1-D5, X1-X4, and N1-N3 rules."""
    now = now or datetime.now(timezone.utc)
    d_score = 0
    x_score = 0
    signals = {}

    # D1 / D1' install command
    cmd, itype = extract_install_command(readme_text, repo=repo_info.get("repo"))
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

    # D2, D3 release status
    release_info = release_info or {}
    published_at_str = release_info.get("published_at") or release_info.get("created_at")
    assets = release_info.get("assets", [])
    tag = release_info.get("tag_name")
    signals["release_tag"] = tag

    release_days = None
    if published_at_str:
        try:
            pub_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
            release_days = max(0, int((now - pub_date).total_seconds() / 86400))
            signals["release_days_ago"] = release_days
            if release_days <= 90:
                d_score += 10
                signals["d2"] = 10
        except Exception:
            signals["release_days_ago"] = None
    else:
        signals["release_days_ago"] = None

    if assets and len(assets) >= 1:
        d_score += 15
        signals["d3"] = 15
        signals["has_binary_assets"] = True
    else:
        signals["has_binary_assets"] = False

    # D4 demo
    has_demo = False
    if readme_text:
        if any(h in readme_text for h in ["huggingface.co/spaces", "colab.research.google.com", "replicate.com"]):
            has_demo = True
    homepage = repo_info.get("homepage")
    if homepage and not any(h in homepage for h in ["github.com", "arxiv.org"]):
        has_demo = True
    signals["has_demo"] = has_demo
    if has_demo:
        d_score += 10
        signals["d4"] = 10

    # D5 Dockerfile
    has_docker = False
    contents = contents or []
    if any(c.lower().startswith("dockerfile") or c.lower().startswith("docker-compose") or c.lower() == "docker" for c in contents):
        has_docker = True
    elif readme_text and ("docker run" in readme_text or "docker compose" in readme_text):
        has_docker = True
    signals["has_docker"] = has_docker
    if has_docker:
        d_score += 5
        signals["d5"] = 5

    # X1 License
    lic_lower = (license_name or "").lower()
    signals["license"] = license_name
    license_flag = None
    if lic_lower in PERMISSIVE_LICENSES:
        x_score += 15
        signals["x1"] = 15
    elif any(lic_lower.startswith(c) for c in COPYLEFT_LICENSES):
        x_score += 5
        signals["x1_prime"] = 5
        license_flag = "copyleft"
    elif lic_lower in {"noassertion", "none", "", "other"}:
        license_flag = "license riêng, đọc trước khi dùng thương mại"
    else:
        if any(p in lic_lower for p in ["mit", "apache", "bsd", "isc", "mpl"]):
            x_score += 15
            signals["x1"] = 15
        else:
            license_flag = "license riêng, đọc trước khi dùng thương mại"

    # X2 Examples
    has_examples = False
    if any(c.lower() in {"examples", "example", "templates", "notebooks", "cookbook"} for c in contents):
        has_examples = True
    elif readme_text and re.search(r"(?:^|\n)#{1,3}\s+(?:examples|example|notebooks|cookbook)\b", readme_text, re.I):
        has_examples = True
    signals["has_examples"] = has_examples
    if has_examples:
        x_score += 10
        signals["x2"] = 10

    # X3 Quickstart heading
    has_quickstart = False
    if readme_text and re.search(r"(?:^|\n)#{1,3}\s+(?:quick\s*start|getting\s+started|usage|examples|installation)\b", readme_text, re.I):
        has_quickstart = True
    signals["has_quickstart"] = has_quickstart
    if has_quickstart:
        x_score += 10
        signals["x3"] = 10

    # X4 Pushed at
    pushed_days = None
    if pushed_at:
        try:
            p_date = datetime.fromisoformat(pushed_at.replace("Z", "+00:00")) if isinstance(pushed_at, str) else pushed_at
            pushed_days = max(0, int((now - p_date).total_seconds() / 86400))
            signals["pushed_days_ago"] = pushed_days
            if pushed_days <= 30:
                x_score += 5
                signals["x4"] = 5
        except Exception:
            signals["pushed_days_ago"] = None
    else:
        signals["pushed_days_ago"] = None

    # N1 Paper reference
    has_paper = False
    desc = repo_info.get("description") or ""
    if (homepage and "arxiv.org" in homepage) or re.search(r"^(?:Official )?(?:PyTorch )?(?:code|implementation) (?:for|of)", desc, re.I):
        has_paper = True
    elif readme_text and ("arxiv.org" in readme_text or "BibTeX" in readme_text or "@article" in readme_text):
        has_paper = True
    signals["has_paper"] = has_paper

    # N2 Manifest penalty
    manifests = {"pyproject.toml", "setup.py", "package.json", "cargo.toml", "go.mod", "cmakelists.txt"}
    has_manifest = any(c.lower() in manifests for c in contents)
    signals["has_manifest"] = has_manifest
    if not has_manifest and itype != "binary":
        d_score -= 15
        signals["n2_penalty"] = -15

    # N3 Non-commercial / restriction
    has_nc = False
    if readme_text and re.search(r"\b(?:non-commercial|cc-by-nc|research purposes only|example only)\b", readme_text, re.I):
        has_nc = True
        license_flag = "⚠ trọng số phi thương mại"
    signals["non_commercial"] = has_nc

    is_archived = repo_info.get("archived", False)
    is_fork = repo_info.get("fork", False)
    if pushed_days is not None and pushed_days > 365:
        is_archived = True

    # Label assignment
    if not is_archived and not is_fork and d_score >= 35:
        label = "dung-ngay"
    elif not is_archived and not is_fork and x_score >= 25 and license_name and lic_lower not in {"none", "null", ""}:
        label = "xao-nau"
    else:
        label = "nghien-cuu"

    signals["d_score"] = d_score
    signals["x_score"] = x_score

    # Construct "why" string
    parts = []
    parts.append(LABEL_NAMES[label])
    if cmd:
        parts.append(f"cài: `{cmd}`")
    if tag:
        rel_str = f"bản {tag}"
        if release_days is not None:
            rel_str += " ra hôm nay" if release_days == 0 else f" ra {release_days} ngày trước"
        if signals.get("has_binary_assets"):
            rel_str += ", có bản dựng sẵn"
        parts.append(rel_str)
    if license_name:
        lic_str = license_name
        if license_flag and "license riêng" in license_flag:
            lic_str += " (license riêng)"
        parts.append(lic_str)

    stars_today = repo_info.get("stars_today")
    stars_week = repo_info.get("stars_this_week")
    if stars_week:
        parts.append(f"+{stars_week:,} sao tuần này")
    elif stars_today:
        parts.append(f"+{stars_today:,} sao hôm nay")

    if has_demo:
        parts.append("có demo")
    if has_examples:
        parts.append("có thư mục examples")
    if has_paper and label != "dung-ngay":
        parts.append("kèm paper")
    if has_nc:
        parts.append("⚠ trọng số phi thương mại")

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
    details = model_details or {}
    gated = details.get("gated", model_info.get("gated", False))
    library_name = details.get("library_name", model_info.get("library_name"))
    pipeline_tag = details.get("pipeline_tag", model_info.get("pipeline_tag"))
    tags = details.get("tags") or model_info.get("tags") or []

    card_data = details.get("cardData") or {}
    license_name = card_data.get("license") or model_info.get("license")
    if not license_name:
        for t in tags:
            if t.startswith("license:"):
                license_name = t.split(":", 1)[1]
                break

    spaces = details.get("spaces")
    spaces_count = len(spaces) if isinstance(spaces, list) else (spaces if isinstance(spaces, int) else 0)

    children = details.get("childrenModelCount") or {}
    quantized_count = children.get("quantized", 0)
    finetune_count = children.get("finetune", 0)

    inference_provider = bool(details.get("inferenceProviderMapping") or model_info.get("availableInferenceProviders"))

    likes = model_info.get("likes", details.get("likes"))
    downloads = model_info.get("downloads", details.get("downloads"))

    signals = {
        "gated": gated,
        "library_name": library_name,
        "pipeline_tag": pipeline_tag,
        "license": license_name,
        "spaces_count": spaces_count,
        "quantized_count": quantized_count,
        "finetune_count": finetune_count,
        "inference_provider": inference_provider,
        "likes": likes,
        "downloads": downloads
    }

    # License flag
    license_flag = None
    lic_lower = (license_name or "").lower()
    if any(nc in lic_lower for nc in ["nc", "non-commercial", "research"]):
        license_flag = "⚠ phi thương mại"
    elif lic_lower in ["other", "custom"]:
        license_flag = "license riêng, đọc trước khi dùng thương mại"

    is_gguf = (library_name in {"gguf", "mlx"} or any("gguf" in t.lower() for t in tags)
               or "gguf" in model_info.get("id", "").lower())

    # Classification rules
    if not gated and (inference_provider or is_gguf or quantized_count >= 1):
        label = "dung-ngay"
    elif not gated and (library_name in {"transformers", "diffusers", "sentence-transformers", "nemo", "timm", "peft"}
                        or spaces_count >= 3 or finetune_count >= 1):
        if license_flag == "⚠ phi thương mại" and spaces_count < 1:
            label = "nghien-cuu"
        else:
            label = "xao-nau"
    else:
        label = "nghien-cuu"

    label_vn = LABEL_NAMES[label]
    parts = [label_vn]
    if inference_provider:
        parts.append("gọi được qua API")
    if is_gguf:
        parts.append("định dạng GGUF chạy máy")
    elif quantized_count >= 1:
        parts.append(f"có {quantized_count} bản lượng tử")
    elif library_name:
        parts.append(f"thư viện {library_name}")

    if license_name:
        parts.append(license_name)
    if spaces_count > 0:
        parts.append(f"{spaces_count} demo Spaces" if spaces_count > 1 else "có demo Space")
    if finetune_count >= 1:
        parts.append(f"{finetune_count} model con phái sinh")
    if likes is not None and likes > 0:
        parts.append(f"+{likes:,} likes")
    if license_flag:
        parts.append(license_flag)
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


def _safe_fetch(fetcher, url, source_id=None):
    if fetcher is None:
        return None
    try:
        if hasattr(fetcher, "__call__"):
            try:
                return fetcher(url, source_id=source_id)
            except TypeError:
                return fetcher(url)
    except Exception:
        return None


def _enrich_github_item(repo_info, fetcher, weekly_stars, now):
    repo = repo_info["repo"]
    readme_text = ""
    lic_name = None
    release_info = None
    contents = []
    pushed_at = None
    api_enriched = False
    api_fallback_reason = None

    # Check weekly stars
    w_stars = weekly_stars.get(repo)
    if w_stars:
        repo_info["stars_this_week"] = w_stars

    # 1. Fetch README (always available via raw.githubusercontent.com)
    readme_url = f"https://raw.githubusercontent.com/{repo}/HEAD/README.md"
    readme_resp = _safe_fetch(fetcher, readme_url, source_id="github-trending")
    if readme_resp:
        readme_text = str(readme_resp)

    # 2. Try GitHub REST API if GITHUB_TOKEN is available or API is usable
    token = os.environ.get("GITHUB_TOKEN")
    api_base = f"https://api.github.com/repos/{repo}"
    repo_json = _safe_fetch(fetcher, api_base, source_id="github-trending")
    if repo_json:
        try:
            data = json.loads(repo_json)
            if isinstance(data, dict) and "id" in data:
                api_enriched = True
                pushed_at = data.get("pushed_at")
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

    if api_enriched:
        # Fetch latest release and contents
        rel_json = _safe_fetch(fetcher, f"{api_base}/releases/latest", source_id="github-trending")
        if rel_json:
            try:
                rel_data = json.loads(rel_json)
                if isinstance(rel_data, dict):
                    release_info = rel_data
            except Exception:
                pass
        cnt_json = _safe_fetch(fetcher, f"{api_base}/contents/", source_id="github-trending")
        if cnt_json:
            try:
                cnt_data = json.loads(cnt_json)
                if isinstance(cnt_data, list):
                    contents = [row.get("name", "") for row in cnt_data if isinstance(row, dict)]
            except Exception:
                pass
    else:
        api_fallback_reason = "GitHub API rate limit or no GITHUB_TOKEN; evaluated from README and metadata"
        # Try fetching raw LICENSE
        for lic_file in ["LICENSE", "LICENSE.md", "LICENSE.txt"]:
            lic_resp = _safe_fetch(fetcher, f"https://raw.githubusercontent.com/{repo}/HEAD/{lic_file}", source_id="github-trending")
            if lic_resp:
                txt = str(lic_resp)
                if "Apache License" in txt:
                    lic_name = "Apache-2.0"
                elif "MIT License" in txt:
                    lic_name = "MIT"
                elif "General Public License" in txt:
                    lic_name = "GPL-3.0"
                elif "BSD" in txt:
                    lic_name = "BSD-3-Clause"
                elif "Mozilla Public License" in txt:
                    lic_name = "MPL-2.0"
                elif "ISC License" in txt:
                    lic_name = "ISC"
                break

        # Check releases.atom for latest release tag and date
        rel_atom = _safe_fetch(fetcher, f"https://github.com/{repo}/releases.atom", source_id="github-trending")
        if rel_atom:
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(str(rel_atom))
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                entry = root.find("atom:entry", ns)
                if entry is not None:
                    title = entry.find("atom:title", ns)
                    updated = entry.find("atom:updated", ns)
                    content = entry.find("atom:content", ns)
                    tag_name = title.text.strip() if title is not None and title.text else None
                    pub_at = updated.text.strip() if updated is not None and updated.text else None
                    cnt_text = content.text if content is not None and content.text else ""
                    has_bin = bool(re.search(r"\.(?:zip|tar\.gz|tgz|whl|exe|dmg|pkg|deb|rpm)\b", cnt_text, re.I))
                    release_info = {
                        "tag_name": tag_name,
                        "published_at": pub_at,
                        "assets": [{"name": "binary"}] if has_bin else []
                    }
            except Exception:
                pass

        # Check commits.atom for latest commit activity (pushed_at)
        com_atom = _safe_fetch(fetcher, f"https://github.com/{repo}/commits.atom", source_id="github-trending")
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
        now=now
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

    stars_7d = repo_info.get("stars_this_week")

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
        "stars_gained_7d": stars_7d,
        "signals": evaluated["signals"],
        "source": "github-trending"
    }


def _enrich_hf_item(model_info, fetcher, now):
    model_id = model_info["id"]
    model_details = None

    url = (f"https://huggingface.co/api/models/{quote(model_id, safe='/')}"
           "?expand[]=library_name&expand[]=pipeline_tag&expand[]=gated&expand[]=cardData"
           "&expand[]=spaces&expand[]=childrenModelCount&expand[]=inferenceProviderMapping"
           "&expand[]=tags&expand[]=downloads&expand[]=likes")
    resp = _safe_fetch(fetcher, url, source_id="hf-trending")
    if resp:
        try:
            data = json.loads(str(resp))
            if isinstance(data, dict):
                model_details = data
        except Exception:
            pass

    evaluated = score_hf_model(model_info, model_details=model_details, now=now)
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
        "signals": evaluated["signals"],
        "source": "hf"
    }


def curate_repos(github_trending, hf_trending, fetcher=None, now=None):
    """Enrich, score, categorize, and rank GitHub repositories and Hugging Face models."""
    now = now or datetime.now(timezone.utc)
    if not github_trending and not hf_trending:
        return []

    weekly_stars = {}
    weekly_html = _safe_fetch(fetcher, "https://github.com/trending?since=weekly", source_id="github-trending")
    if weekly_html:
        for article in re.findall(r"<article\b[^>]*>.*?</article>", str(weekly_html), flags=re.S | re.I):
            href_m = re.search(r'href="/([\w.-]+/[\w.-]+)"', article)
            stars_m = re.search(r"([\d,]+)\s+stars?\s+this\s+week", article, re.I)
            if href_m and stars_m:
                weekly_stars[href_m.group(1)] = number(stars_m.group(1))

    results = []
    hf_models = [row for row in hf_trending if row.get("type") == "model"] if hf_trending else []

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        gh_futures = [executor.submit(_enrich_github_item, dict(r), fetcher, weekly_stars, now) for r in (github_trending or [])]
        hf_futures = [executor.submit(_enrich_hf_item, dict(m), fetcher, now) for m in hf_models]

        for fut in concurrent.futures.as_completed(gh_futures + hf_futures):
            try:
                item = fut.result()
                if item:
                    results.append(item)
            except Exception:
                pass

    # Sort priorities: dung-ngay (0) -> xao-nau (1) -> nghien-cuu (2)
    # Secondary: momentum/stars
    priority_order = {"dung-ngay": 0, "xao-nau": 1, "nghien-cuu": 2}

    def sort_key(row):
        lbl_order = priority_order.get(row.get("label"), 9)
        stars = row.get("stars") or 0
        stars_7d = row.get("stars_gained_7d") or 0
        sig = row.get("signals") or {}
        d_score = sig.get("d_score", 0)
        x_score = sig.get("x_score", 0)
        score = d_score + x_score + min(20.0, 5.0 * math.log10(1 + max(0, stars_7d)))
        return (lbl_order, -score, -stars, row.get("id"))

    results.sort(key=sort_key)
    return results
