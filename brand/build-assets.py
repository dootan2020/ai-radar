"""Build AIBit News extension and Store SVGs from the approved kingfisher.

Run from the repository root:  python brand/build-assets.py
Use --site for the AIBit News website kit pipeline.
Needs fontTools (pip install fonttools). Text is converted to outlines with the
Be Vietnam Pro files in brand/fonts/, so each SVG opens correctly anywhere,
without the font installed. The website kit retains its existing tokens.
"""
import json
import math
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

import publish_kit
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar.site_config import SITE_URL

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
    for name, value in re.findall(r"--(emerald-[a-z]+):\s*(#[0-9a-fA-F]{6})", css):
        out[name] = value.upper()
    return out


T = load_tokens()
LIGHT = dict(canvas=T["gray-96"], surface=T["gray-99"], fill=T["gray-93"], ink=T["gray-21"],
             ink2=T["gray-44"], ink3=T["gray-51"], accent=T["emerald-ink"], live=T["red-55"])
DARK = dict(canvas=T["gray-13"], surface=T["gray-17"], fill=T["gray-25"], ink=T["gray-96"],
            ink2=T["gray-80"], ink3=T["gray-70"], accent=T["emerald-bright"], live=T["red-70"])


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


def doc(w, h, body, title, bg=None):
    rect = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{title}"><title>{title}</title>{rect}{body}</svg>\n')


def write(name, svg):
    (OUT / name).write_text(svg, encoding="utf-8", newline="\n")
    print("wrote", name, len(svg), "bytes")


def approved_logo(name, x, y, width, height):
    """Embed the approved vector without changing its silhouette or palette."""
    source = (ROOT / "brand" / "logo" / "a-kingfisher-emerald" / name).read_text(encoding="utf-8")
    body = source.split(">", 1)[1].rsplit("</svg>", 1)[0]
    view_box = ElementTree.fromstring(source).attrib["viewBox"]
    return (f'<svg x="{x}" y="{y}" width="{width}" height="{height}" '
            f'viewBox="{view_box}">{body}</svg>')


def lockup_ratio():
    source = ROOT / "brand" / "logo" / "a-kingfisher-emerald" / "lockup-light.svg"
    _, _, width, height = map(float, ElementTree.parse(source).getroot().attrib["viewBox"].split())
    return width / height


def small_kingfisher(size):
    """Head, beak and chest from the approved pose, enlarged for toolbar pixels."""
    body = f'<rect width="{size}" height="{size}" rx="{size * .225:g}" fill="#00B377"/>'
    body += (f'<g transform="scale({size / 1024:g})" fill="#FFFFFF">'
             '<path d="M 392 393 C 480 390 604 454 640 570 C 646 660 554 758 398 790 '
             'C 308 780 282 692 314 584 C 324 516 350 438 392 393 Z"/>'
             '<circle cx="444" cy="385" r="153"/>'
             '<path d="M 415 245 L 182 288 L 330 357 L 162 402 L 335 441 Z"/>'
             '<path d="M 505 315 L 899 408 L 505 446 Z"/>'
             '</g>')
    return doc(size, size, body, "AIBit News kingfisher toolbar icon")


def extension_assets():
    OUT.mkdir(parents=True, exist_ok=True)
    for pixels in (16, 32):
        write(f"extension-icon-{pixels}.svg", small_kingfisher(pixels))
    write("extension-icon-48.svg", doc(48, 48, approved_logo("mark-light.svg", 0, 0, 48, 48), "AIBit News kingfisher extension icon"))
    write("extension-icon-128.svg", doc(128, 128, approved_logo("mark-light.svg", 0, 0, 128, 128), "AIBit News Chrome Web Store icon"))
    promo = f'<rect width="440" height="280" fill="{DARK["canvas"]}"/>'
    promo += approved_logo("lockup-dark.svg", 36, 52, 368, 368 / lockup_ratio())
    promo += text(MED, "Những mẩu tin AI ngắn gọn", 22, 38, 218, DARK["ink2"])
    write("store-promo-small.svg", doc(440, 280, promo, "AIBit News Chrome Web Store promo"))


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
    TAG = "Những mẩu tin AI ngắn gọn"
    URL = SITE_URL.removeprefix("https://").rstrip("/")

    # The approved vectors are the single source for the public identity.
    logo_dir = ROOT / "brand" / "logo" / "a-kingfisher-emerald"
    logo_files = {
        "logo-full.svg": "lockup-light.svg", "logo-full-dark.svg": "lockup-dark.svg",
        "logo-full-mono-ink.svg": "lockup-light.svg", "logo-full-mono-white.svg": "lockup-dark.svg",
        "wordmark.svg": "lockup-light.svg", "wordmark-dark.svg": "lockup-dark.svg",
        "mark.svg": "mark-light.svg", "mark-dark.svg": "mark-dark.svg",
        "mark-mono-ink.svg": "mark-light.svg", "mark-mono-white.svg": "mark-dark.svg",
        "favicon-16.svg": "mark-light.svg", "favicon-32.svg": "mark-light.svg",
        "apple-touch-icon-180.svg": "mark-light.svg", "avatar.svg": "mark-light.svg",
        "avatar-light.svg": "mark-light.svg",
    }
    for target, source in logo_files.items():
        if target in {"avatar.svg", "avatar-light.svg"}:
            size = 800
            write(target, doc(size, size, approved_logo(source, 0, 0, size, size), "AIBit News"))
        elif target == "apple-touch-icon-180.svg":
            size = 180
            tile = f'<rect width="{size}" height="{size}" fill="#00B377"/>'
            write(target, doc(size, size, tile + approved_logo(source, 0, 0, size, size), "AIBit News"))
        elif target in {"favicon-16.svg", "favicon-32.svg"}:
            size = int(target.split("-")[1].split(".")[0])
            write(target, doc(size, size, approved_logo(source, 0, 0, size, size), "AIBit News"))
        else:
            write(target, (logo_dir / source).read_text(encoding="utf-8"))
    (ROOT / "site" / "logo.svg").write_bytes((logo_dir / "mark-light.svg").read_bytes())
    extension_assets()

    # Keep each approved vector inside its own canvas; choose the light or dark palette.
    def mark(cx, cy, size, theme="light"):
        return approved_logo(f"mark-{theme}.svg", cx - size / 2, cy - size / 2, size, size)

    def lockup(x, baseline, size, theme="light"):
        width = size * lockup_ratio()
        return approved_logo(f"lockup-{theme}.svg", x, baseline - size, width, size), width

    gh, hf, day = real_data()

    # share image 1200 x 630, a real story: the repo with the most stars gained in one day
    owner, repo = gh["repo"].split("/")
    body = f'<rect x="40" y="40" width="1120" height="550" rx="24" fill="{L["surface"]}"/>'
    body += lockup(96, 120, 34)[0]
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
    body += mark(914, 326, 300)
    body += lockup(96, 196, 72)[0]
    body += text(BOLD, "Những mẩu tin AI", 60, 96, 350, L["ink"], TRACK_DISPLAY)
    body += text(BOLD, "ngắn gọn", 60, 96, 424, L["ink"], TRACK_DISPLAY)
    body += text(MED, "Tin AI mỗi sáng, lọc bằng số đo thật.", 26, 96, 500, L["ink2"])
    body += text(MED, URL, 22, 96, 546, L["accent"])
    write("og-default.svg", doc(1200, 630, body, "AIBit News, Những mẩu tin AI ngắn gọn", L["canvas"]))

    # Facebook cover 1640 x 624. Mobile shows only the centre ~1110 px; desktop covers the
    # bottom-left with the page avatar. Everything that matters sits in the centre.
    lw = lockup(0, 0, 96)[1]
    body = lockup(820 - lw / 2, 300, 96)[0]
    body += text(MED, TAG, 40, 820, 400, L["ink2"], anchor="middle")
    body += text(MED, "Lab · Paper · Repo · Podcast · Diễn đàn", 26, 820, 460, L["ink3"], anchor="middle")
    write("cover-facebook.svg", doc(1640, 624, body, "AIBit News, bìa trang Facebook", L["canvas"]))

    # YouTube banner 2560 x 1440. Safe area on every device: centre 1546 x 423 (y 508-931).
    lw = lockup(0, 0, 150, "dark")[1]
    body = lockup(1280 - lw / 2, 720, 150, "dark")[0]
    body += text(MED, TAG, 52, 1280, 864, D["ink2"], anchor="middle")
    write("cover-youtube.svg", doc(2560, 1440, body, "AIBit News, ảnh bìa kênh YouTube", D["canvas"]))

    # short-video thumbnail 1080 x 1920 (9:16). Bottom 420 px and right 160 px stay free for the
    # platform's caption and buttons.
    downloads = hf["downloads"]
    millions = f"{downloads / 1e6:.1f}".replace(".", ",")
    org, model = hf["id"].split("/")
    body = lockup(80, 200, 52)[0]
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
    body = mark(540, 690, 520)
    body += lockup(96, 240, 64)[0]
    body += text(BOLD, "Những mẩu tin AI", 88, 96, 1120, L["ink"], TRACK_DISPLAY)
    body += text(BOLD, "ngắn gọn", 104, 96, 1244, L["ink"], TRACK_DISPLAY)
    body += text(MED, "Tin AI mỗi sáng,", 44, 96, 1340, L["ink2"])
    body += text(MED, "lọc bằng số đo thật.", 44, 96, 1400, L["ink2"])
    body += text(MED, URL, 36, 96, 1480, L["accent"])
    write("khung-9x16.svg", doc(1080, 1920, body, "AIBit News, khung 9:16", L["canvas"]))

    # the brand page must stand alone when brand/ is published by itself: ship its own tokens
    (ROOT / "brand" / "tokens.css").write_bytes((ROOT / "site" / "tokens.css").read_bytes())
    print("wrote tokens.css (copy of site/tokens.css)")
    publish_kit.publish()          # site/brand/ is what GitHub Pages serves


if __name__ == "__main__":
    main() if "--site" in sys.argv else extension_assets()
