"""The front page's first-screen CSS, inlined in site/index.html so no stylesheet holds the first paint (Lighthouse,
11/11: five blocking files, about 55 KB gzip, set a 2.8 s floor under the first paint on a phone).

The block is derived, never hand-written: every rule of the front page's stylesheets whose selector can match the HTML
as it arrives (the page's own markup plus what radar/front_lead.py bakes into it) is kept, in source order, with its
@media/@supports wrapper. A selector is kept when every class and id it names (outside :not()) appears in that markup;
element and attribute selectors always stay. menu-cong-cu.css is kept whole: menu-cong-cu.js is a classic script that
draws the top-right launcher before the module that applies the complete files can run. The complete files still load,
without blocking (index.html preloads them, site/nap-kieu.js applies them), and whatever a script draws waits for them.

    python -m radar.critical_css          # rewrite the block in site/index.html
    python -m radar.critical_css --check  # exit 1 when the block differs from its source (tests run this too)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
INDEX = SITE / "index.html"
FRONT_LEAD = Path(__file__).resolve().parent / "front_lead.py"
# The front page's stylesheets, in the order index.html applied them as blocking links before 11/11.
SHEETS = ("tokens.css", "feed.css", "trang-nhat.css", "trang-msn.css", "menu-cong-cu.css")
WHOLE = {"menu-cong-cu.css"}
START = "<!-- critical css: written by radar/critical_css.py from the stylesheets preloaded below; do not edit by hand -->\n"
END = "<!-- /critical css -->\n"
BLOCK_RE = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CLASS_ATTR = re.compile(r'class="([^"]*)"')
_ID_ATTR = re.compile(r'\bid="([^"]+)"')
_NAME_TOKEN = re.compile(r"[.#](-?[_a-zA-Z][\w-]*)")


def markup_names(index_html: str, lead_source: str) -> set[str]:
    """Every class (".x") and id ("#x") in the page's markup and in the lead block front_lead.py writes.
    A build's baked lead is left out (its classes come from front_lead.py's source), so the block depends only on
    the template and the stylesheets, never on the day's story."""
    html = BLOCK_RE.sub("", index_html)
    html = re.sub(r"<!-- lead picture: .*?<!-- /lead picture -->|<!-- lead slide: .*?<!-- /lead slide -->", "", html, flags=re.S)
    names = set()
    for text in (html, lead_source):
        for m in _CLASS_ATTR.finditer(text):
            names.update("." + c for c in m.group(1).split() if re.fullmatch(r"-?[_a-zA-Z][\w-]*", c))
        for m in _ID_ATTR.finditer(text):
            if re.fullmatch(r"-?[_a-zA-Z][\w-]*", m.group(1)):
                names.add("#" + m.group(1))
    return names


def _split_top(text: str, sep: str) -> list[str]:
    """Split on sep outside parentheses and brackets."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _strip_not(selector: str) -> str:
    """Drop :not(...) arguments: a class named only there need not exist."""
    out, i = [], 0
    while i < len(selector):
        if selector.startswith(":not(", i):
            depth, j = 0, i + 4
            while j < len(selector):
                depth += selector[j] == "("
                depth -= selector[j] == ")"
                j += 1
                if depth == 0:
                    break
            i = j
        else:
            out.append(selector[i]); i += 1
    return "".join(out)


def selector_matches(selector: str, names: set[str]) -> bool:
    sel = re.sub(r"\[[^\]]*\]", "", _strip_not(selector))   # attribute values may hold dots
    return all(("." if m.group(0)[0] == "." else "#") + m.group(1) in names for m in _NAME_TOKEN.finditer(sel))


def _blocks(css: str):
    """Yield (prelude, body) for each top-level rule; body is None for a statement such as @import."""
    i, n = 0, len(css)
    while i < n:
        while i < n and css[i].isspace():
            i += 1
        if i >= n:
            return
        j, depth = i, 0
        while j < n and css[j] not in "{;":
            j += 1
        if j >= n:
            return
        if css[j] == ";":
            yield css[i:j].strip(), None
            i = j + 1
            continue
        prelude, k, depth = css[i:j].strip(), j, 0
        while k < n:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            elif css[k] in "\"'":
                q = css[k]; k += 1
                while k < n and css[k] != q:
                    k += 2 if css[k] == "\\" else 1
            k += 1
        yield prelude, css[j + 1:k]
        i = k + 1


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def filter_css(css: str, names: set[str]) -> str:
    """The rules of css whose selectors can match names, in source order."""
    out = []
    for prelude, body in _blocks(_COMMENT.sub("", css)):
        if body is None:
            continue   # @import and @charset have no place in an inline block
        at = prelude.split(None, 1)[0].lower() if prelude.startswith("@") else ""
        if at in ("@media", "@supports", "@layer", "@container"):
            inner = filter_css(body, names)
            if inner:
                out.append(f"{_squeeze(prelude)}{{{inner}}}")
        elif at in ("@font-face", "@property", "@keyframes", "@-webkit-keyframes", "@counter-style"):
            out.append(f"{_squeeze(prelude)}{{{_squeeze(body)}}}")
        elif at:
            continue
        else:
            kept = [s.strip() for s in _split_top(prelude, ",") if selector_matches(s.strip(), names)]
            if kept:
                out.append(f"{','.join(_squeeze(s) for s in kept)}{{{_squeeze(body)}}}")
    return "".join(out)


def critical_css(index_html: str, site: Path = SITE, lead_source: str | None = None) -> str:
    names = markup_names(index_html, FRONT_LEAD.read_text(encoding="utf-8") if lead_source is None else lead_source)
    parts = []
    for name in SHEETS:
        css = (site / name).read_text(encoding="utf-8")
        parts.append(_squeeze(_COMMENT.sub("", css)) if name in WHOLE else filter_css(css, names))
    return "\n".join(parts)


def render_block(index_html: str, site: Path = SITE) -> str:
    return f"{START}<style>\n{critical_css(index_html, site)}\n</style>\n{END}"


def update(index_path: Path = INDEX, check: bool = False) -> bool:
    """Rewrite the block; with check, only report whether it is current. Returns True when it is (or now is) current."""
    html = index_path.read_text(encoding="utf-8")
    if not BLOCK_RE.search(html):
        raise ValueError(f"{index_path}: the critical css markers are missing")
    fresh = BLOCK_RE.sub(lambda _m: render_block(html, index_path.parent), html, count=1)
    if fresh == html:
        return True
    if check:
        return False
    index_path.write_bytes(fresh.encode("utf-8"))
    return True


if __name__ == "__main__":
    check = "--check" in sys.argv[1:]
    ok = update(check=check)
    if check and not ok:
        print("site/index.html: the inline critical css differs from its stylesheets; run python -m radar.critical_css")
        sys.exit(1)
    print("critical css current" if check else "critical css written")
