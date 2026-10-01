"""Manual fixture refresh; never imported or run by the offline test suite."""

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent / "fixtures"
URLS = {
    "openai.xml": "https://openai.com/news/rss.xml",
    "github.html": "https://github.com/trending",
    "hf-trending.json": "https://huggingface.co/api/trending",
    "hf-releases.json": "https://huggingface.co/api/models?author=deepseek-ai&sort=createdAt&direction=-1&limit=3",
}


def main():
    ROOT.mkdir(exist_ok=True)
    manifest_path = ROOT / "sources.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for name, url in URLS.items():
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "AI-Radar-Fixture-Capture/1.0"})
            with urllib.request.urlopen(request, timeout=25) as response:
                text = response.read().decode("utf-8")
            method = "Unmodified response"
            if name.endswith(".xml"):
                root = ET.fromstring(text)
                channel = root.find("channel")
                for item in list(channel.findall("item"))[3:]:
                    channel.remove(item)
                text = ET.tostring(root, encoding="unicode")
                method = "First 3 RSS items, serialized with stdlib ElementTree"
            elif name == "github.html":
                text = "\n".join(re.findall(r'<article\b[^>]*class="Box-row"[^>]*>.*?</article>', text, re.S)[:3])
                if not text:
                    raise ValueError("No real GitHub repository articles captured")
                method = "First 3 unmodified article elements"
            elif name == "hf-trending.json":
                body = json.loads(text)
                if isinstance(body, dict):
                    for key, value in body.items():
                        if isinstance(value, list):
                            body[key] = value[:3]
                elif isinstance(body, list):
                    body = body[:3]
                text = json.dumps(body, ensure_ascii=False, indent=2)
                method = "First 3 entries per list, serialized with stdlib JSON"
            (ROOT / name).write_bytes(text.encode("utf-8"))
            manifest[name] = {"url": url, "captured_at": datetime.now(timezone.utc).isoformat(), "method": method}
            print(name, len(text), "saved")
        except Exception as exc:
            print(name, type(exc).__name__, str(exc))
    (ROOT / "sources.json").write_bytes(json.dumps(manifest, indent=2).encode())


if __name__ == "__main__":
    main()
