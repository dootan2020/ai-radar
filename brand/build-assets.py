"""Build every SVG in brand/assets/ from one geometry and the live tokens.

Run from the repository root:  python brand/build-assets.py
Needs fontTools (pip install fonttools). Text is converted to outlines with the
Be Vietnam Pro files in brand/fonts/, so each SVG opens correctly anywhere,
without the font installed. Colours are read from site/tokens.css (oklch) and
converted to sRGB hex, so the kit cannot drift from the running site.

The mark, "Vòng tín hiệu": one ring (everything ai-radar listens to), one gap
(the filter), one blue dot sitting in the gap (the one thing worth your time).
"""
import json
import math
import re
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

import publish_kit

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "brand" / "assets"
FONTS = ROOT / "brand" / "fonts"


# ---------- colour: tokens.css (oklch) -> sRGB hex ----------
def oklch_to_hex(L, C, H):
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    rgb = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )

    def enc(x):
        x = max(0.0, min(1.0, x))
        return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055

    return "#%02X%02X%02X" % tuple(round(enc(v) * 255) for v in rgb)


def load_tokens():
    css = (ROOT / "site" / "tokens.css").read_text(encoding="utf-8")
    hue = float(re.search(r"--hue:\s*([\d.]+)", css).group(1))
    out = {}
    for name, L, C, H in re.findall(r"--([a-z]+-\d+):\s*oklch\(([\d.]+)\s+([\d.]+)\s+([^)\s]+)\)", css):
        out[name] = oklch_to_hex(float(L), float(C), hue if "hue" in H else float(H))
    return out


T = load_tokens()
LIGHT = dict(canvas=T["gray-96"], surface=T["gray-99"], fill=T["gray-93"], ink=T["gray-21"],
             ink2=T["gray-44"], ink3=T["gray-51"], accent=T["blue-53"], live=T["red-55"])
DARK = dict(canvas=T["gray-13"], surface=T["gray-17"], fill=T["gray-25"], ink=T["gray-96"],
            ink2=T["gray-80"], ink3=T["gray-70"], accent=T["blue-74"], live=T["red-70"])


# ---------- type: text -> outlines, with GPOS pair kerning ----------
class Face:
    def __init__(self, file):
        self.f = TTFont(FONTS / file)
        self.upm = self.f["head"].unitsPerEm
        self.cmap = self.f.getBestCmap()
        self.gs = self.f.getGlyphSet()
        self.hmtx = self.f["hmtx"]
        self.pairs, self.classes = {}, []
        for lk in self.f["GPOS"].table.LookupList.Lookup:
            for st in lk.SubTable:
                if lk.LookupType == 9:
                    if st.ExtensionLookupType != 2:
                        continue
                    st = st.ExtSubTable
                elif lk.LookupType != 2:
                    continue
                if st.Format == 1:
                    for i, first in enumerate(st.Coverage.glyphs):
                        for r in st.PairSet[i].PairValueRecord:
                            v = getattr(r.Value1, "XAdvance", 0) if r.Value1 else 0
                            if v:
                                self.pairs.setdefault((first, r.SecondGlyph), v)
                elif st.Format == 2:
                    self.classes.append((set(st.Coverage.glyphs), st.ClassDef1.classDefs,
                                         st.ClassDef2.classDefs, st.Class1Record))

    def kern(self, a, b):
        if (a, b) in self.pairs:
            return self.pairs[(a, b)]
        for cov, c1, c2, rec in self.classes:
            if a in cov:
                r = rec[c1.get(a, 0)].Class2Record[c2.get(b, 0)]
                v = getattr(r.Value1, "XAdvance", 0) if r.Value1 else 0
                return v or 0
        return 0

    def gname(self, ch):
        return self.cmap[ord(ch)]

    def width(self, text, size, track=0.0):
        s = size / self.upm
        names = [self.gname(c) for c in text]
        w = sum(self.hmtx[n][0] for n in names)
        w += sum(self.kern(a, b) for a, b in zip(names, names[1:]))
        return w * s + track * size * max(0, len(text) - 1)

    def path(self, text, size, x, y, track=0.0, anchor="start"):
        s = size / self.upm
        if anchor != "start":
            w = self.width(text, size, track)
            x -= w if anchor == "end" else w / 2
        names = [self.gname(c) for c in text]
        parts, cx = [], x
        for i, n in enumerate(names):
            pen = SVGPathPen(self.gs, ntos=lambda v: ("%.2f" % v).rstrip("0").rstrip("."))
            self.gs[n].draw(TransformPen(pen, (s, 0, 0, -s, cx, y)))
            parts.append(pen.getCommands())
            cx += self.hmtx[n][0] * s + track * size
            if i + 1 < len(names):
                cx += self.kern(n, names[i + 1]) * s
        return " ".join(p for p in parts if p)


REG, MED, SEMI, BOLD = (Face(f"BeVietnamPro-{w}.ttf") for w in ("Regular", "Medium", "SemiBold", "Bold"))
TRACK_DISPLAY, TRACK_NUMBER = -0.025, -0.04          # --tracking-display, --tracking-number


def text(face, s, size, x, y, fill, track=0.0, anchor="start"):
    return f'<path fill="{fill}" d="{face.path(s, size, x, y, track, anchor)}"/>'


# ---------- the mark ----------
# Master grid 48 x 48: ring centre (24,24), radius 15, stroke 6; dot radius 5 sits ON the
# ring path at -45 deg (up-right). The gap leaves 3 units of air on each side of the dot.
R, STROKE, DOT, AIR, DOT_ANGLE = 15.0, 6.0, 5.0, 3.0, -45.0


def mark(cx, cy, size, ring, dot, r=R, stroke=STROKE, dot_r=DOT, air=AIR):
    """Mark whose ring outer diameter (r*2 + stroke) maps to `size` px."""
    k = size / (2 * r + stroke)
    r, stroke, dot_r, air = r * k, stroke * k, dot_r * k, air * k
    half = math.degrees(2 * math.asin((dot_r + air + stroke / 2) / (2 * r)))
    a1, a2 = math.radians(DOT_ANGLE + half), math.radians(DOT_ANGLE - half + 360)
    p = lambda a: (cx + r * math.cos(a), cy + r * math.sin(a))
    (x1, y1), (x2, y2) = p(a1), p(a2)
    dx, dy = p(math.radians(DOT_ANGLE))
    f = lambda v: ("%.3f" % v).rstrip("0").rstrip(".")
    return (f'<path d="M{f(x1)} {f(y1)}A{f(r)} {f(r)} 0 1 1 {f(x2)} {f(y2)}" fill="none" '
            f'stroke="{ring}" stroke-width="{f(stroke)}" stroke-linecap="round"/>'
            f'<circle cx="{f(dx)}" cy="{f(dy)}" r="{f(dot_r)}" fill="{dot}"/>')


# ---------- the wordmark: "ai·radar", the middot redrawn as the same blue dot ----------
WM_DOT = 0.175           # dot diameter, in em
WM_SIDE = 0.085          # air either side of the dot, in em


def wordmark(x, baseline, size, ink, dot):
    """Returns (svg, width). x-height of Be Vietnam Pro = 0.53 em; the dot is centred on it."""
    left, right = "ai", "radar"
    wl = BOLD.width(left, size, TRACK_DISPLAY)
    slot = (WM_DOT + 2 * WM_SIDE) * size
    xr = x + wl + slot
    d = text(BOLD, left, size, x, baseline, ink, TRACK_DISPLAY) + text(BOLD, right, size, xr, baseline, ink, TRACK_DISPLAY)
    cx, cy = x + wl + slot / 2, baseline - 0.265 * size
    d += f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{WM_DOT * size / 2:.2f}" fill="{dot}"/>'
    return d, xr + BOLD.width(right, size, TRACK_DISPLAY) - x


def lockup(x, baseline, size, ink, dot, ring=None):
    """Mark + wordmark. Mark diameter = 0.96 em, centred on the x-height middle; gap 0.34 em."""
    m = 0.96 * size
    cy = baseline - 0.265 * size
    svg = mark(x + m / 2, cy, m, ring or ink, dot)
    wm, ww = wordmark(x + m + 0.34 * size, baseline, size, ink, dot)
    return svg + wm, m + 0.34 * size + ww


def doc(w, h, body, title, bg=None):
    rect = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{title}"><title>{title}</title>{rect}{body}</svg>\n')


def write(name, svg):
    (OUT / name).write_text(svg, encoding="utf-8", newline="\n")
    print("wrote", name, len(svg), "bytes")


def nf(n):
    """Vietnamese number format: 50.562"""
    return f"{n:,}".replace(",", ".")


# ---------- real data ----------
def real_data():
    d = json.loads((ROOT / "site" / "data" / "radar.json").read_text(encoding="utf-8"))
    gh = max(d["trending"]["github"], key=lambda r: r["stars_today"])
    hf = max(d["hf_releases"], key=lambda r: r["downloads"] if r["created_at"] >= "2026" else 0)
    date = d["generated_at"][:10].split("-")
    return gh, hf, f"{date[2]}/{date[1]}/{date[0]}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    L, D = LIGHT, DARK
    TAG = "Tín hiệu trước, nhiễu sau."
    URL = "dootan2020.github.io/ai-radar"

    # logo: full lockup (size 64 -> about 330 x 64 canvas incl. clear space x = 0.53em)
    size, pad = 64, 64 * 0.53
    probe, w = lockup(0, 0, size, "#000", "#000")
    W, H = math.ceil(w + 2 * pad), math.ceil(0.96 * size + 2 * pad)
    base = pad + 0.48 * size + 0.265 * size
    for name, ink, dot, bg in (("logo-full.svg", L["ink"], L["accent"], None),
                               ("logo-full-dark.svg", D["ink"], D["accent"], None),
                               ("logo-full-mono-ink.svg", L["ink"], L["ink"], None),
                               ("logo-full-mono-white.svg", "#FFFFFF", "#FFFFFF", None)):
        write(name, doc(W, H, lockup(pad, base, size, ink, dot)[0], "ai·radar", bg))

    # wordmark alone
    wm, ww = wordmark(0, 0, size, "#000", "#000")
    WW = math.ceil(ww + 2 * pad)
    WH = math.ceil(size * 0.74 + 2 * pad)
    for name, ink, dot in (("wordmark.svg", L["ink"], L["accent"]), ("wordmark-dark.svg", D["ink"], D["accent"])):
        write(name, doc(WW, WH, wordmark(pad, pad + 0.74 * size, size, ink, dot)[0], "ai·radar"))

    # mark alone, 48 grid, clear space = 1/4 of the mark built into the 72 canvas
    for name, ring, dot in (("mark.svg", L["ink"], L["accent"]), ("mark-dark.svg", D["ink"], D["accent"]),
                            ("mark-mono-ink.svg", L["ink"], L["ink"]), ("mark-mono-white.svg", "#FFFFFF", "#FFFFFF")):
        write(name, doc(72, 72, mark(36, 36, 48, ring, dot), "ai·radar"))

    # favicons: a dark tile so the mark reads on light and dark browser tabs
    # 16 px is hand-tuned: stroke exactly 2 px, ring radius 4.25, dot radius 1.9, 2.75 px of tile around it.
    fav16 = (f'<rect width="16" height="16" rx="3.5" fill="{L["ink"]}"/>'
             + mark(8, 8.25, 10.5, D["ink"], D["accent"], r=4.25, stroke=2, dot_r=1.9, air=0.85))
    write("favicon-16.svg", doc(16, 16, fav16, "ai·radar"))
    fav32 = f'<rect width="32" height="32" rx="7" fill="{L["ink"]}"/>' + mark(16, 16.5, 22, D["ink"], D["accent"])
    write("favicon-32.svg", doc(32, 32, fav32, "ai·radar"))
    # apple-touch: full bleed, iOS rounds the corners itself
    write("apple-touch-icon-180.svg", doc(180, 180, mark(90, 92, 112, D["ink"], D["accent"]), "ai·radar", L["ink"]))

    # social avatars, 400 x 400; mark stays inside the circle crop (diameter 400)
    write("avatar.svg", doc(400, 400, mark(200, 204, 200, D["ink"], D["accent"]), "ai·radar", L["ink"]))
    write("avatar-light.svg", doc(400, 400, mark(200, 204, 200, L["ink"], L["accent"]), "ai·radar", L["canvas"]))

    gh, hf, day = real_data()

    # share image 1200 x 630, a real story: the repo with the most stars gained in one day
    owner, repo = gh["repo"].split("/")
    body = f'<rect x="40" y="40" width="1120" height="550" rx="24" fill="{L["surface"]}"/>'
    body += lockup(96, 120, 34, L["ink"], L["accent"])[0]
    body += text(MED, f"GitHub Trending · {day}", 22, 1104, 118, L["ink3"], anchor="end")
    chip = "Nóng nhất hôm nay"
    cw = SEMI.width(chip, 26) + 64
    body += f'<rect x="96" y="164" width="{cw:.1f}" height="52" rx="26" fill="{L["live"]}" fill-opacity="0.1"/>'
    body += f'<circle cx="122" cy="190" r="7" fill="{L["live"]}"/>'
    body += text(SEMI, chip, 26, 140, 199, L["live"])
    big = nf(gh["stars_today"])
    body += text(BOLD, big, 216, 86, 412, L["ink"], TRACK_NUMBER)
    bw = BOLD.width(big, 216, TRACK_NUMBER)
    body += text(MED, "sao mới", 38, 86 + bw + 24, 364, L["ink2"])
    body += text(MED, "trong một ngày", 38, 86 + bw + 24, 410, L["ink2"])
    ow = REG.width(owner + "/", 46)
    body += text(REG, owner + "/", 46, 96, 492, L["ink2"]) + text(BOLD, repo, 46, 96 + ow, 492, L["ink"], TRACK_DISPLAY)
    body += text(MED, f'Tổng {nf(gh["stars"])} sao · {gh["language"]}', 26, 96, 540, L["ink3"])
    body += text(MED, URL, 24, 1104, 540, L["accent"], anchor="end")
    write("og-story.svg", doc(1200, 630, body, f'{gh["repo"]}: {big} sao mới trong một ngày', L["canvas"]))

    # share image 1200 x 630, default for the home page (no dated number, so it never goes stale)
    body = f'<rect x="40" y="40" width="1120" height="550" rx="24" fill="{L["surface"]}"/>'
    body += mark(900, 315, 380, L["fill"], L["accent"])
    body += lockup(96, 196, 72, L["ink"], L["accent"])[0]
    body += text(BOLD, "Tín hiệu trước,", 60, 96, 350, L["ink"], TRACK_DISPLAY)
    body += text(BOLD, "nhiễu sau.", 60, 96, 424, L["ink"], TRACK_DISPLAY)
    body += text(MED, "Tin AI mỗi sáng, lọc bằng số đo thật.", 26, 96, 500, L["ink2"])
    body += text(MED, URL, 22, 96, 546, L["accent"])
    write("og-default.svg", doc(1200, 630, body, "ai·radar, tín hiệu trước, nhiễu sau", L["canvas"]))

    # Facebook cover 1640 x 624. Mobile shows only the centre ~1110 px; desktop covers the
    # bottom-left with the page avatar. Everything that matters sits in the centre.
    lw = lockup(0, 0, 96, "#000", "#000")[1]
    body = lockup(820 - lw / 2, 300, 96, L["ink"], L["accent"])[0]
    body += text(MED, TAG, 40, 820, 400, L["ink2"], anchor="middle")
    body += text(MED, "Lab · Paper · Repo · Podcast · Diễn đàn", 26, 820, 460, L["ink3"], anchor="middle")
    write("cover-facebook.svg", doc(1640, 624, body, "ai·radar, bìa trang Facebook", L["canvas"]))

    # YouTube banner 2560 x 1440. Safe area on every device: centre 1546 x 423 (y 508-931).
    lw = lockup(0, 0, 150, "#000", "#000")[1]
    body = mark(1280, 720, 1300, D["surface"], D["surface"])          # tone on tone; whole only on TV
    body += lockup(1280 - lw / 2, 720, 150, D["ink"], D["accent"])[0]
    body += text(MED, TAG, 52, 1280, 864, D["ink2"], anchor="middle")
    write("cover-youtube.svg", doc(2560, 1440, body, "ai·radar, ảnh bìa kênh YouTube", D["canvas"]))

    # short-video thumbnail 1080 x 1920 (9:16). Bottom 420 px and right 160 px stay free for the
    # platform's caption and buttons.
    downloads = hf["downloads"]
    millions = f"{downloads / 1e6:.1f}".replace(".", ",")
    org, model = hf["id"].split("/")
    body = lockup(80, 200, 52, L["ink"], L["accent"])[0]
    body += f'<rect x="56" y="300" width="968" height="1180" rx="48" fill="{L["surface"]}"/>'
    chip = "Model mở · Hugging Face"
    cw = SEMI.width(chip, 32) + 56
    body += f'<rect x="112" y="368" width="{cw:.1f}" height="64" rx="32" fill="{L["accent"]}" fill-opacity="0.1"/>'
    body += text(SEMI, chip, 32, 140, 411, L["accent"])
    body += text(BOLD, millions, 340, 96, 800, L["ink"], TRACK_NUMBER)
    body += text(MED, "triệu lượt tải", 64, 112, 900, L["ink2"])
    body += text(REG, org + "/", 56, 112, 1080, L["ink2"])
    body += text(BOLD, model, 64, 112, 1160, L["ink"], TRACK_DISPLAY)
    body += text(MED, f"{nf(downloads)} lượt tải · {hf['pipeline_tag']}", 34, 112, 1250, L["ink3"])
    body += text(MED, f"Số đo ngày {day}", 34, 112, 1400, L["ink3"])
    write("short-9x16.svg", doc(1080, 1920, body, f"{hf['id']}: {millions} triệu lượt tải", L["canvas"]))

    # 9:16 brand frame 1080 x 1920 for stories and video covers. No dated number, so it never
    # goes stale. Same free zones as the thumbnail: bottom 420 px and right 160 px.
    body = mark(540, 760, 900, L["fill"], L["accent"])               # tone on tone behind the words
    body += lockup(96, 240, 64, L["ink"], L["accent"])[0]
    body += text(BOLD, "Tín hiệu trước,", 104, 96, 1120, L["ink"], TRACK_DISPLAY)
    body += text(BOLD, "nhiễu sau.", 104, 96, 1244, L["ink"], TRACK_DISPLAY)
    body += text(MED, "Tin AI mỗi sáng,", 44, 96, 1340, L["ink2"])
    body += text(MED, "lọc bằng số đo thật.", 44, 96, 1400, L["ink2"])
    body += text(MED, URL, 36, 96, 1480, L["accent"])
    write("khung-9x16.svg", doc(1080, 1920, body, "ai·radar, khung 9:16", L["canvas"]))

    # the brand page must stand alone when brand/ is published by itself: ship its own tokens
    (ROOT / "brand" / "tokens.css").write_bytes((ROOT / "site" / "tokens.css").read_bytes())
    print("wrote tokens.css (copy of site/tokens.css)")
    publish_kit.publish()          # site/brand/ is what GitHub Pages serves


if __name__ == "__main__":
    main()
