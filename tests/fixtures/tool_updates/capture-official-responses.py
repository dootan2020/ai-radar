"""Capture candidate official responses; failures never become fixtures."""
import concurrent.futures
import datetime
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
SOURCES = {
    "claude-code.atom": "https://github.com/anthropics/claude-code/releases.atom",
    "claude-code-static-feed.xml": "https://raw.githubusercontent.com/anthropics/claude-code/main/feed.xml",
    "claude-code-changelog.md": "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md",
    "codex.atom": "https://github.com/openai/codex/releases.atom",
    "codex-changelog.html": "https://developers.openai.com/codex/changelog",
    "gemini-cli.atom": "https://github.com/google-gemini/gemini-cli/releases.atom",
    "ollama.atom": "https://github.com/ollama/ollama/releases.atom",
    "cursor.xml": "https://cursor.com/changelog/rss.xml",
    "copilot.xml": "https://github.blog/changelog/label/copilot/feed/",
    "vscode.xml": "https://code.visualstudio.com/feed.xml",
    "antigravity.html": "https://antigravity.google/changelog",
    "antigravity-docs.html": "https://www.antigravity.google/docs/changelog",
}


def capture(item):
    filename, url = item
    observed = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record = {"file": filename, "url": url, "captured_at": observed}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "AI-Radar-source-verification/1.0"})
        with urllib.request.urlopen(request, timeout=35) as response:
            body = response.read()
            record.update(status=response.status, final_url=response.url,
                          content_type=response.headers.get("Content-Type"),
                          response_date=response.headers.get("Date"),
                          source_bytes=len(body), source_sha256=hashlib.sha256(body).hexdigest())
            (ROOT / filename).write_bytes(body)
            record.update(fixture_bytes=len(body), fixture_sha256=record["source_sha256"], extraction="Full response body; unchanged bytes.")
    except urllib.error.HTTPError as error:
        record.update(status=error.code, error=str(error))
    except Exception as error:
        record.update(status=None, error=str(error))
    return record


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        records = list(executor.map(capture, SOURCES.items()))
    (ROOT / "manifest.json").write_bytes((json.dumps(records, indent=2) + "\n").encode())
    print(json.dumps(records, indent=2))
