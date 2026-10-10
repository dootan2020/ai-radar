"""Every word the reader sees is Vietnamese, except names and the original titles of news, papers and repositories.

The rule is applied to two surfaces:
- the page's own text: string literals in site/*.js that reach the screen (HTML fragments, Vietnamese sentences,
  values of UI keys such as `label`/`title`/`note`, the word maps in words.js, toast and error messages) and the
  text, aria-label, title and alt of site/index.html and design/tokens.html (the internal showcase);
- the pipeline's reader-facing text: source names and pause reasons, repository "why" sentences, license flags,
  hot reasons, error wording.

A word passes when it carries a Vietnamese diacritic, is a well-formed unaccented Vietnamese syllable, or is in
EXCEPTIONS below, each with its reason. Text inside <code> and <kbd> is code or a key name, not prose.

`python tests/test_vietnamese_ui.py --rendered <rendered.json>` applies the same rule to the texts collected from
the rendered page by tests/capture_repo_tile.mjs.
"""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Words allowed although they are not Vietnamese. Lower-case; one reason per group.
EXCEPTIONS = {
    # Brand and product names
    **dict.fromkeys(["ai", "radar", "github", "hugging", "face", "huggingface", "youtube", "google", "calendar", "apple",
                     "outlook", "hacker", "news", "lobsters", "algolia", "daily", "papers", "spaces", "space", "docker",
                     "readme", "openai", "anthropic", "claude", "deepmind", "xai", "meta", "mistral", "qwen", "deepseek", "nvidia",
                     "microsoft", "techcrunch", "verge", "ars", "technica", "mit", "technology", "review", "substack",
                     "gftdon", "dwarkesh", "interconnects", "simon", "willison", "priors", "latent", "import",
                     "engineering", "research", "blog", "technical", "llama", "mistralai", "org",
                     "vnexpress", "international", "genk", "register", "ml", "wired", "media", "semafor",
                     "cnbc", "bloomberg", "fedscoop", "nextgov", "technode", "rest", "world", "newsroom",
                     "official", "aws", "machine", "learning", "platform", "studio",
                     "bluesky", "arena", "lmarena",
                     "simonwillison", "ethan", "mollick", "emollick", "bsky", "social", "pandaily", "scmp", "smol"],
                    "tên riêng: thương hiệu, sản phẩm, ấn phẩm, tổ chức trên Hugging Face hoặc nguồn mới"),
    **dict.fromkeys(["the"], "tên riêng: ấn phẩm The Verge; đánh đổi có chủ đích: chữ the đứng riêng sẽ không bị bắt"),
    **dict.fromkeys(["of"], "tên riêng: ấn phẩm Rest of World; chữ of trong tên ấn phẩm"),
    **dict.fromkeys(["translated"], "nhãn bản dịch máy viết tiếng Anh theo yêu cầu của anh Tuấn 03/10 17:49 (“dịch máy” thành “Translated”, màu như Google Dịch); trình đọc màn hình vẫn nghe câu tiếng Việt"),
    **dict.fromkeys(["trending"],"tên riêng: trang GitHub Trending, nguồn của ô kho mã (anh Tuấn 03/10 cho dùng như tên thương hiệu)"),
    **dict.fromkeys(["esc", "enter"], "tên phím trên bàn phím"),
    **dict.fromkeys(["px", "ms"], "đơn vị đo"),
    **dict.fromkeys(["th", "thg"], "viết tắt của tháng (huy hiệu ngày; Intl vi-VN in thg)"),
    **dict.fromkeys(["cookie"], "từ mượn phổ biến cho tệp theo dõi của trình duyệt"),
    **dict.fromkeys(["javascript"], "tên ngôn ngữ và tùy chọn trình duyệt mà hướng dẫn bật lại cần gọi đúng tên"),
    **dict.fromkeys(["bento", "keynote"], "tên riêng: tên ngôn ngữ thiết kế anh Tuấn đã chốt 02/10"),
    **dict.fromkeys(["be", "vietnam", "pro"], "tên riêng: họ phông chữ Be Vietnam Pro"),
    **dict.fromkeys(["nllb", "cc", "by", "nc"], "tên riêng: mô hình dịch NLLB-200 và mã giấy phép CC-BY-NC 4.0"),
    # Acronyms, protocols, units and file formats with no Vietnamese form in use
    **dict.fromkeys(["api", "http", "rss", "xml", "css", "mcp", "rag", "gguf", "mib", "ics", "fsl", "spdx", "html", "json"],
                    "từ viết tắt kỹ thuật, định dạng hoặc đơn vị"),
    # Loanwords in Vietnamese dictionaries
    **dict.fromkeys(["video", "podcast", "blog", "logo"], "từ mượn đã vào tiếng Việt"),
    # Brand mark
    **dict.fromkeys(["ai·radar"], "tên trang"),
}

# Unaccented Vietnamese syllable: initial consonant, vowel nucleus, final. English words that happen to fit
# the shape (the, hot, top) are listed in FALSE_FRIENDS so they are still caught.
SYLLABLE = re.compile(r"^(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdđghklmnprstvx])?"
                      r"(?:oai|oay|uya|uyu|ai|ao|au|ay|eo|ia|iu|oa|oe|oi|ua|ui|uy|a|e|i|o|u|y)"
                      r"(?:ch|ng|nh|c|m|n|p|t)?$")
FALSE_FRIENDS = {"the", "hot", "top", "new", "of", "is", "it", "by", "at", "on", "see", "chip", "tab"}
VIET_MARKS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
WORD = re.compile(r"[A-Za-zÀ-ỹĐđ·]+")


def foreign_words(text):
    """Words in `text` that are neither Vietnamese nor listed exceptions."""
    found = []
    for raw in WORD.findall(text):
        word = raw.lower()
        if word in EXCEPTIONS:
            continue
        parts = [p for p in word.split("·") if p]
        if len(parts) > 1 and all(p in EXCEPTIONS or VIET_MARKS.search(p) for p in parts):
            continue
        if len(word) <= 1 or VIET_MARKS.search(word):
            continue
        if SYLLABLE.match(word) and word not in FALSE_FRIENDS:
            continue
        found.append(raw)
    return found


class _Visible(HTMLParser):
    """Visible text and labels of an HTML fragment; <code>, <kbd>, <script>, <style>, <svg> are skipped."""

    SKIP = {"code", "kbd", "script", "style", "svg"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.texts = [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("aria-label", "title", "alt", "placeholder"):
            if attrs.get(key):
                self.texts.append(attrs[key])
        if tag == "meta" and (attrs.get("name") in {"description", "twitter:title", "twitter:description"}
                              or str(attrs.get("property", "")).startswith("og:") and attrs.get("property") not in {"og:url", "og:image", "og:type", "og:locale", "og:image:type", "og:image:width", "og:image:height"}):
            self.texts.append(attrs.get("content") or "")
        if tag not in self.VOID:
            self.depth.append(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.depth) - 1, -1, -1):
            if self.depth[index] == tag:
                del self.depth[index:]
                break

    def handle_data(self, data):
        if data.strip() and not self.SKIP.intersection(self.depth):
            self.texts.append(data)


def visible_html(fragment):
    parser = _Visible()
    parser.feed(fragment)
    return parser.texts


def js_literals(source):
    """(literal, text before it) for every string and template literal, comments and regex literals skipped.
    Template interpolations become a space; literals inside them are returned too."""
    out, i, n = [], 0, len(source)
    last = ""  # last significant character, to tell a regex literal from a division

    def read_template(start):
        j, parts, buf = start + 1, [], []
        while j < n:
            c = source[j]
            if c == "\\":
                buf.append(source[j:j + 2]); j += 2; continue
            if c == "`":
                parts.append("".join(buf)); return " ".join(parts), j + 1
            if c == "$" and source[j + 1:j + 2] == "{":
                parts.append("".join(buf)); buf = []
                depth, k = 1, j + 2
                inner_start = k
                while k < n and depth:
                    if source[k] in "'\"`":
                        _, k = read_literal(k)
                        continue
                    depth += source[k] == "{"
                    depth -= source[k] == "}"
                    k += 1
                out.extend(js_literals(source[inner_start:k - 1]))
                j = k
                continue
            buf.append(c); j += 1
        raise ValueError("unterminated template literal")

    def read_literal(start):
        q = source[start]
        if q == "`":
            return read_template(start)
        j = start + 1
        while j < n and source[j] != q:
            j += 2 if source[j] == "\\" else 1
        return source[start + 1:j], j + 1

    while i < n:
        c = source[i]
        if source.startswith("//", i):
            i = source.find("\n", i); i = n if i < 0 else i; continue
        if source.startswith("/*", i):
            i = source.find("*/", i + 2) + 2; continue
        if c in "'\"`":
            text, end = read_literal(i)
            out.append((text, source[max(0, i - 60):i]))
            i, last = end, "a"
            continue
        if c == "/" and (last == "" or last in "(,=:[!&|?{};+-*%<>~^"):
            j, in_class = i + 1, False
            while j < n and (source[j] != "/" or in_class):
                if source[j] == "\\":
                    j += 1
                elif source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                j += 1
            i, last = j + 1, "a"
            continue
        if not c.isspace():
            last = c
            if c.isalnum() or c in "_$)]":
                last = "a"
                # keywords after which a slash starts a regex
                m = re.match(r"(?:return|typeof|case|in|of)\b", source[i:])
                if m and (i == 0 or not (source[i - 1].isalnum() or source[i - 1] == "_")):
                    last = "("
                    i += len(m.group(0)) - 1
        i += 1
    return out


UI_KEYS = re.compile(r"\b(?:label|title|note|unit|gained|phrase|msg)\s*:\s*$")
UI_SINKS = re.compile(r"(?:toast|showError|pageError|Error|state)\s*\(\s*$")
WORD_MAPS = ("KIND", "METRIC", "SIGNALS", "VALUE")


def page_texts():
    texts = []
    # design/tokens.html is the internal showcase (moved out of the published site/ on 03/10); it stays checked.
    for path in (ROOT / "site" / "index.html", ROOT / "design" / "tokens.html"):
        texts += [(path.name, t) for t in visible_html(path.read_text(encoding="utf-8"))]
    for path in sorted((ROOT / "site").glob("*.js")) + sorted((ROOT / "design").glob("*.js")):
        source = path.read_text(encoding="utf-8")
        map_spans = []
        for name in WORD_MAPS:
            m = re.search(r"\bconst " + name + r"\s*=\s*[\[{]", source)
            if m:
                depth, k = 0, m.end() - 1
                while k < len(source):
                    depth += source[k] in "[{"
                    depth -= source[k] in "]}"
                    k += 1
                    if not depth:
                        break
                map_spans.append((m.end(), k))
        position = 0
        for literal, before in js_literals(source):
            position = source.find(literal, position) if literal else position
            if "<" in literal and ">" in literal:
                texts += [(path.name, t) for t in visible_html(literal)]
            elif VIET_MARKS.search(literal) or UI_KEYS.search(before) or UI_SINKS.search(before):
                texts.append((path.name, literal))
            elif any(a <= position < b for a, b in map_spans) and re.search(r":\s*$", before):
                texts.append((path.name, literal))  # a value in a word map; keys are machine ids
    return texts


def pipeline_texts():
    from radar import catalog, feeds, github, huggingface, events, youtube
    from radar.common import vi_error
    from radar.curation import (CATEGORIES, LABEL_NAMES, FLAG_COPYLEFT, FLAG_CUSTOM, FLAG_FSL, FLAG_NC,
                                FLAG_UNMEASURED, WINDOW_NAMES, score_github_repo, score_hf_model)
    from radar.ranking import LABELS
    from datetime import datetime, timezone

    now = datetime(2026, 10, 3, tzinfo=timezone.utc)
    sources = feeds.SOURCES + catalog.sources(now) + huggingface.SOURCES + [github.SOURCE, huggingface.TRENDING_SOURCE, events.SOURCE]
    texts = [("source name", s["name"]) for s in sources]
    texts += [("source name", c[2] + " YouTube") for c in youtube.CHANNELS + (catalog.NVIDIA_CHANNEL,)]
    texts += [("pause reason", s.get("disabled_reason", "")) for s in sources]
    texts += [("curation", v) for v in list(CATEGORIES.values()) + list(LABEL_NAMES.values()) + list(WINDOW_NAMES.values())]
    texts += [("license flag", v) for v in (FLAG_COPYLEFT, FLAG_CUSTOM, FLAG_FSL, FLAG_NC, FLAG_UNMEASURED)]
    texts += [("hot reason", v) for v in LABELS.values()]
    for error in ("Disabled: lý do", "Build deadline exceeded", "TimeoutError: Source exceeded fetch deadline",
                  "HTTPError: HTTP Error 403: Forbidden", "ValueError: Source response exceeds 8 MiB limit",
                  "URLError: <urlopen error [Errno 11001] getaddrinfo failed>", "ParseError: not well-formed",
                  "RuntimeError: something new"):
        texts.append(("error", vi_error(error)))
    release = {"tag_name": "v1.0.0", "published_at": "2026-10-01T00:00:00Z", "assets": [{"name": "x"}]}
    readme = "### Quickstart\n```bash\npip install demo-tool\n```\nhttps://huggingface.co/spaces/a/b\n### Examples\narxiv.org\nnon-commercial"
    for license_name in ("MIT", "NOASSERTION", "GPL-3.0", None):
        why = score_github_repo({"repo": "a/demo-tool", "homepage": "https://x.dev"}, readme_text=readme, license_name=license_name,
                                release_info=release, contents=["examples", "pyproject.toml", "Dockerfile"], now=now)["why"]
        texts.append(("repo why", re.sub(r"`[^`]*`|\bbản \S+|MIT|GPL-3\.0", " ", why)))
    details = {"gated": "auto", "library_name": "transformers", "cardData": {"license": "other"}, "spaces": ["s"] * 100,
               "childrenModelCount": {"quantized": 3, "finetune": 2}, "inferenceProviderMapping": {"x": {}}}
    texts.append(("model why", score_hf_model({"id": "a/m-GGUF", "likes": 1200}, model_details=details)["why"].replace("transformers", " ")))
    return [(where, t) for where, t in texts if t]


def report(texts):
    leftovers = {}
    for where, text in texts:
        words = foreign_words(text)
        if words:
            leftovers.setdefault(where, []).append((text.strip()[:120], words))
    return leftovers


class VietnameseInterfaceTests(unittest.TestCase):
    def test_word_rule_catches_english_and_passes_vietnamese(self):
        self.assertEqual(foreign_words("Repo lấy về dùng được"), ["Repo"])
        self.assertEqual(foreign_words("+1.234 stars this week"), ["stars", "this", "week"])
        self.assertEqual(foreign_words("hot new model"), ["hot", "new", "model"])
        self.assertEqual(foreign_words("Kho mã AI đang lên trên GitHub, xem tin trong ngày"), [])
        self.assertEqual(foreign_words("ai·radar · Tin AI hôm nay"), [])
        self.assertEqual(foreign_words("Hãy bật JavaScript trong trình duyệt rồi tải lại trang"), [])

    def test_extractor_reads_html_fragments_ui_keys_and_skips_code(self):
        sample = ("const A = {label:'Upvote', id:'video'}; el.querySelector('.repo-hero'); /* 'comment words' */\n"
                  "const re = /'quoted'/g; toast('Saved');\n"
                  "x = `<b title=\"Copy\">${n} stars</b><code>pip install</code>`;")
        literals = js_literals(sample)
        found = [t for t, before in literals if UI_KEYS.search(before) or UI_SINKS.search(before)]
        self.assertIn("Upvote", found)
        self.assertIn("Saved", found)
        self.assertNotIn("comment words", [t for t, _ in literals])
        self.assertNotIn("quoted", [t for t, _ in literals])
        html = next(t for t, _ in literals if "<b" in t)
        self.assertEqual(visible_html(html), ["Copy", "  stars"])

    def test_page_has_no_english_words(self):
        leftovers = report(page_texts())
        self.assertEqual(leftovers, {}, "Chuỗi tiếng Anh còn sót trên giao diện:\n" + json.dumps(leftovers, ensure_ascii=False, indent=1))

    def test_pipeline_reader_text_has_no_english_words(self):
        leftovers = report(pipeline_texts())
        self.assertEqual(leftovers, {}, "Chuỗi tiếng Anh còn sót do pipeline sinh:\n" + json.dumps(leftovers, ensure_ascii=False, indent=1))

    def test_every_exception_has_a_reason(self):
        self.assertTrue(all(isinstance(reason, str) and reason for reason in EXCEPTIONS.values()))


if __name__ == "__main__":
    if len(sys.argv) in (3, 4) and sys.argv[1] == "--rendered":
        data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        # Original content (titles, summaries, repository names and descriptions, event and stream titles) is
        # allowed to stay as published; with the snapshot given, those strings are removed before the word rule.
        # Their machine translations (title_vi, description_vi) are content too: names inside them stay as written.
        content = set()
        if len(sys.argv) == 4:
            snap = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
            for st in snap.get("stories", []):
                content.update([st.get("title") or "", st.get("summary") or "", st.get("title_vi") or ""])
                content.update(c.get(k) or "" for c in st.get("coverage", []) for k in ("title", "title_vi"))
            for r in snap.get("repos", []):
                content.update([r.get("full_name") or "", r.get("description") or "", r.get("description_vi") or ""]
                               + str(r.get("full_name") or "").split("/"))
                content.update(re.findall(r"`[^`]*`|\bbản \S+", r.get("why") or ""))
                content.update(str(v) for v in (r.get("license"), (r.get("signals") or {}).get("release_tag"),
                                                (r.get("signals") or {}).get("library_name")) if v)
            for e in snap.get("events", []):
                content.update([e.get("title") or "", e.get("location") or ""])
            for v in snap.get("live", []):
                content.update([v.get("title") or "", v.get("channel") or "", v.get("title_vi") or ""])
        content = sorted((c.strip() for c in content if len(c.strip()) >= 2), key=len, reverse=True)

        def strip_content(text):
            for c in content:
                if c in text:
                    text = text.replace(c, " ")
            return text

        groups = {f"page-{w}": r["texts"] for w, r in data["widths"].items()}
        groups["tokens"] = data.get("tokensTexts", [])
        for name, texts in groups.items():
            hits = {}
            for t in texts:
                for w in foreign_words(strip_content(t)):
                    hits.setdefault(w, t[:80])
            print(f"{name}: {len(texts)} chuỗi; từ không phải tiếng Việt: " + ("; ".join(f"{w} <- {t!r}" for w, t in sorted(hits.items())) or "(không có)"))
    else:
        unittest.main()
