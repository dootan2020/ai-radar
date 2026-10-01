"""Anonymous Hugging Face repository metadata; no token or inference."""

import json
from urllib.parse import quote

from radar.common import iso_date, number

AUTHORS = {"deepseek": "deepseek-ai", "meta": "meta-llama", "mistral": "mistralai",
           "qwen": "Qwen", "openai": "openai", "google": "google", "xai": "xai-org"}
SOURCES = [dict(id=f"{lab}-hf", name=f"{author} / Hugging Face", lab=lab, kind="hf",
                url=f"https://huggingface.co/api/models?author={author}&sort=createdAt&direction=-1&limit=8")
           for lab, author in AUTHORS.items()]
TRENDING_SOURCE = dict(id="hf-trending", name="Hugging Face Trending", lab="huggingface", kind="hf",
                       url="https://huggingface.co/api/trending")


def _repo_id(value):
    if not isinstance(value, str) or len(value.split("/")) != 2 or any(c.isspace() for c in value):
        return None
    return value if all(part and part not in {".", ".."} for part in value.split("/")) else None


def parse_releases(text, lab):
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("Expected Hugging Face model array")
    result = []
    for row in data:
        if not isinstance(row, dict):
            continue
        repo = _repo_id(row.get("id"))
        created = iso_date(row.get("createdAt"))
        if not repo:
            continue
        result.append(dict(id=repo, lab=lab, url="https://huggingface.co/" + quote(repo, safe="/"),
                           created_at=created, likes=number(row.get("likes")),
                           downloads=number(row.get("downloads")), pipeline_tag=row.get("pipeline_tag")))
    if data and not result:
        raise ValueError("Model array has no usable repository IDs")
    return result[:8]


def parse_trending(text):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("recentlyTrending"), list):
        raise ValueError("Expected Hugging Face recentlyTrending array")
    result, seen = [], set()
    for item in data["recentlyTrending"]:
        if not isinstance(item, dict) or not isinstance(item.get("repoData"), dict):
            continue
        row = item["repoData"]
        repo, kind = _repo_id(row.get("id")), item.get("repoType", row.get("repoType"))
        if not repo or kind not in {"model", "space", "dataset"} or (kind, repo) in seen:
            continue
        seen.add((kind, repo))
        prefix = {"model": "", "space": "spaces/", "dataset": "datasets/"}[kind]
        result.append(dict(id=repo, type=kind, url="https://huggingface.co/" + prefix + quote(repo, safe="/"),
                           likes=number(row.get("likes")), downloads=number(row.get("downloads")),
                           pipeline_tag=row.get("pipeline_tag")))
    if data["recentlyTrending"] and not result:
        raise ValueError("Trending array has no usable repositories")
    return result[:30]
