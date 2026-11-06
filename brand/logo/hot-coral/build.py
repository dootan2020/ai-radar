"""Recolour the Halcyon mark and wordmark into the Hot Coral palette and render contact sheets.

Run from anywhere:  python brand/logo/hot-coral/build.py
The shapes are the approved Lime Anchor vectors (brand/logo/lime-anchor/), read at run time and never
redrawn: only the fill of each shape changes. Each treatment gets its own folder of SVGs and PNGs,
one contact sheet PNG, and the Lime Anchor kit gets the same sheet for comparison.
Renders use headless Chrome (CHROME env var, else the default Windows install path); the atlas crop
and the sheet size check use Pillow.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
LIME = ROOT / "brand" / "logo" / "lime-anchor"
SCRATCH = ROOT / "plans" / "nhap" / "hot-coral"
CHROME = os.environ.get("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")

PALETTE = {
    "coral": "#F0446E", "plum": "#5B1738", "cyan": "#20C7D9", "surface": "#F7F9FC",
    "surface-dark": "#111827", "ink": "#101828", "muted": "#667085", "border": "#E4E7EC", "white": "#FFFFFF",
}
LIME_PALETTE = {"signature": "#2F6B00", "secondary": "#174A34", "lime": "#D7FF2F", "surface": "#F8FBF3", "ink": "#142018"}

# Each treatment: the mark (tile, bird, beak) and the wordmark on a light and on a dark ground
# (letters, beak). Grounds are the palette's Surface and Surface dark.
TREATMENTS = {
    "coral-tile": dict(
        title="Coral Tile", tile="coral", bird="surface", beak="plum",
        word_light=("coral", "plum"), word_dark=("coral", "surface")),
    "plum-tile": dict(
        title="Plum Tile", tile="plum", bird="surface", beak="coral",
        word_light=("plum", "coral"), word_dark=("surface", "coral")),
    "ink-tile": dict(
        title="Ink Tile", tile="ink", bird="coral", beak="cyan",
        word_light=("ink", "coral"), word_dark=("coral", "cyan")),
}
ICON_SIZES = (16, 32, 48, 128, 512)
WORD_WIDTH = 640


# ---------- colour ----------
def luminance(hex_colour):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


# ---------- svg recolour ----------
def recolour(source, fills):
    """Replace the fill of each shape in document order; the shape count must match."""
    text = source.read_text(encoding="utf-8")
    found = re.findall(r'fill="#[0-9A-Fa-f]{6}"', text)
    if len(found) != len(fills):
        raise ValueError(f"{source.name}: {len(found)} fills, {len(fills)} colours given")
    it = iter(fills)
    return re.sub(r'fill="#[0-9A-Fa-f]{6}"', lambda m: f'fill="{next(it)}"', text)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_svgs(key, t):
    """The treatment's vectors, in the Lime Anchor kit's file names."""
    P = PALETTE
    out = HERE / key
    tile, bird, beak = P[t["tile"]], P[t["bird"]], P[t["beak"]]
    wl, bl = (P[c] for c in t["word_light"])
    wd, bd = (P[c] for c in t["word_dark"])
    write(out / "icons" / "halcyon-icon-primary.svg", recolour(LIME / "icons/halcyon-icon-primary.svg", [tile, bird, beak]))
    write(out / "favicons" / "favicon.svg", recolour(LIME / "favicons/favicon.svg", [tile, bird, beak]))
    write(out / "logos" / "halcyon-primary.svg", recolour(LIME / "logos/halcyon-primary.svg", [wl, bl]))
    write(out / "logos" / "halcyon-dark.svg", recolour(LIME / "logos/halcyon-dark.svg", [wd, bd]))
    write(out / "logos" / "halcyon-on-surface.svg", recolour(LIME / "logos/halcyon-on-surface.svg", [P["surface"], wl, bl]))
    write(out / "logos" / "halcyon-on-dark.svg", recolour(LIME / "logos/halcyon-on-ink.svg", [P["surface-dark"], wd, bd]))
    write(out / "logos" / "halcyon-mono-ink.svg", recolour(LIME / "logos/halcyon-mono-ink.svg", [P["ink"]] * 2))
    write(out / "logos" / "halcyon-mono-white.svg", recolour(LIME / "logos/halcyon-mono-white.svg", [P["white"]] * 2))
    return out


# ---------- chrome ----------
def screenshot(html, png, w, h, transparent=False):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="chrome-", dir=SCRATCH)
    Path(png).unlink(missing_ok=True)
    args = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            f"--user-data-dir={profile}", "--force-device-scale-factor=1",
            f"--window-size={w},{h}", f"--screenshot={png}", Path(html).as_uri()]
    if transparent:
        args.insert(1, "--default-background-color=00000000")
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=90)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if done.returncode != 0 or not Path(png).exists():
        raise RuntimeError(f"chrome failed on {html}: {done.stderr.strip()[-400:]}")
    got = Image.open(png).size
    if got != (w, h):
        raise RuntimeError(f"{png}: {got}, expected {(w, h)}")


def render_atlas(kit, icon_svg, word_light_svg, word_dark_svg):
    """One transparent page holding every raster we need; crop it into the kit's PNG files."""
    boxes, y, body = {}, 0, []
    for n in ICON_SIZES:
        boxes[f"icons/halcyon-icon-primary-{n}.png"] = (0, y, n, n)
        body.append(f'<img src="{icon_svg.as_uri()}" style="position:absolute;left:0;top:{y}px" width="{n}" height="{n}">')
        y += n + 8
    word_h = round(WORD_WIDTH * 417 / 1510)
    for name, svg in (("logos/halcyon-primary-640.png", word_light_svg), ("logos/halcyon-dark-640.png", word_dark_svg)):
        boxes[name] = (0, y, WORD_WIDTH, word_h)
        body.append(f'<img src="{svg.as_uri()}" style="position:absolute;left:0;top:{y}px" width="{WORD_WIDTH}" height="{word_h}">')
        y += word_h + 8
    html = SCRATCH / f"atlas-{kit.name}.html"
    write(html, '<!doctype html><html><body style="margin:0;background:transparent">' + "".join(body) + "</body></html>")
    atlas = SCRATCH / f"atlas-{kit.name}.png"
    screenshot(html, atlas, WORD_WIDTH, y, transparent=True)
    sheet = Image.open(atlas).convert("RGBA")
    for name, (x, top, w, h) in boxes.items():
        target = kit / name
        target.parent.mkdir(parents=True, exist_ok=True)
        sheet.crop((x, top, x + w, top + h)).save(target)
    return kit


# ---------- contact sheet ----------
def toolbar(icon16, dark):
    """A Chrome toolbar strip at 1x: omnibox, the extension's 16 px icon, two grey neighbours, a menu."""
    bar, box, ink, dot = ("#35363A", "#202124", "#E8EAED", "#9AA0A6") if dark else ("#FFFFFF", "#F1F3F4", "#202124", "#5F6368")
    return (f'<div style="display:flex;align-items:center;gap:14px;height:40px;padding:0 12px;background:{bar};'
            f'border-radius:8px;width:560px;box-sizing:border-box">'
            f'<div style="flex:1;height:28px;border-radius:14px;background:{box};color:{dot};font:13px system-ui;'
            f'line-height:28px;padding-left:12px">radar-ai-vn.pages.dev</div>'
            f'<img src="{icon16.as_uri()}" width="16" height="16">'
            f'<span style="width:16px;height:16px;border-radius:3px;background:{dot};opacity:.55"></span>'
            f'<span style="width:16px;height:16px;border-radius:50%;background:{dot};opacity:.55"></span>'
            f'<span style="color:{ink};font:700 16px system-ui;letter-spacing:1px">⋮</span></div>')


def panel(kit, dark, ground, ink, muted, border):
    """Half of a contact sheet: the mark at 512, 48, 16 (and the 16 enlarged 8x), the lockup, the toolbar."""
    i = lambda n: kit / f"icons/halcyon-icon-primary-{n}.png"
    word = kit / ("logos/halcyon-dark-640.png" if dark else "logos/halcyon-primary-640.png")
    cap = f'font:500 12px system-ui;color:{muted};margin-top:8px'
    return f'''
<section style="background:{ground};color:{ink};padding:32px;border-radius:16px;border:1px solid {border};flex:1">
  <div style="font:600 13px system-ui;letter-spacing:.08em;text-transform:uppercase;color:{muted}">
    {"Surface dark " + PALETTE["surface-dark"] if dark else "Surface " + PALETTE["surface"]}</div>
  <div style="display:flex;gap:32px;align-items:flex-start;margin-top:20px">
    <div><img src="{i(512).as_uri()}" width="512" height="512"><div style="{cap}">mark 512 px</div></div>
    <div style="display:flex;flex-direction:column;gap:24px">
      <div><img src="{i(48).as_uri()}" width="48" height="48"><div style="{cap}">48 px</div></div>
      <div><img src="{i(16).as_uri()}" width="16" height="16"><div style="{cap}">16 px</div></div>
      <div><img src="{i(16).as_uri()}" width="128" height="128" style="image-rendering:pixelated"><div style="{cap}">16 px, 8x</div></div>
      <div><img src="{i(128).as_uri()}" width="128" height="128"><div style="{cap}">store icon 128 px</div></div>
    </div>
  </div>
  <div style="margin-top:32px"><img src="{word.as_uri()}" width="480" height="{round(480 * 417 / 1510)}"><div style="{cap}">full logo 480 px</div></div>
  <div style="margin-top:28px">{toolbar(i(16), dark)}<div style="{cap}">Chrome toolbar, extension icon 16 px</div></div>
</section>'''


def contact_sheet(kit, title, note):
    P = PALETTE
    body = f'''<!doctype html><html><body style="margin:0;background:{P["white"]};font-family:system-ui,sans-serif">
<div style="padding:32px 36px 0"><span style="font:700 26px system-ui;color:{P["ink"]}">{title}</span>
  <span style="font:400 15px system-ui;color:{P["muted"]};margin-left:16px">{note}</span></div>
<div style="display:flex;gap:24px;padding:20px 36px 36px">
  {panel(kit, False, P["surface"], P["ink"], P["muted"], P["border"])}
  {panel(kit, True, P["surface-dark"], P["surface"], "#98A2B3", "#1F2937")}
</div></body></html>'''
    html = SCRATCH / f"sheet-{kit.name}.html"
    write(html, body)
    png = HERE / f"contact-sheet-{kit.name}.png"
    screenshot(html, png, 1600, 1100)
    return png


def lime_anchor_kit():
    """The current kit, renamed into the same file layout so the same sheet code reads it."""
    kit = SCRATCH / "lime-anchor"
    kit.mkdir(parents=True, exist_ok=True)
    return render_atlas(kit, LIME / "icons/halcyon-icon-primary.svg", LIME / "logos/halcyon-primary.svg",
                        LIME / "logos/halcyon-dark.svg")


def contrast_checks():
    P, out = PALETTE, {}
    for a, b in (("ink", "surface"), ("coral", "surface"), ("plum", "surface"), ("cyan", "surface"),
                 ("muted", "surface"), ("surface", "surface-dark"), ("coral", "surface-dark"),
                 ("cyan", "surface-dark"), ("plum", "surface-dark"), ("white", "coral"), ("ink", "coral"),
                 ("plum", "coral"), ("cyan", "coral"), ("surface", "plum"), ("coral", "plum"), ("cyan", "plum"),
                 ("coral", "ink"), ("cyan", "ink"), ("surface", "ink"), ("ink", "cyan"), ("white", "plum")):
        out[f"{a.title()} / {b.title()}"] = contrast(P[a], P[b])
    for key, t in TREATMENTS.items():
        name = t["title"]
        out[f"{name}: bird / tile"] = contrast(P[t["bird"]], P[t["tile"]])
        out[f"{name}: beak / tile"] = contrast(P[t["beak"]], P[t["tile"]])
        out[f"{name}: tile / surface"] = contrast(P[t["tile"]], P["surface"])
        out[f"{name}: tile / surface dark"] = contrast(P[t["tile"]], P["surface-dark"])
        out[f"{name}: wordmark / surface"] = contrast(P[t["word_light"][0]], P["surface"])
        out[f"{name}: wordmark beak / surface"] = contrast(P[t["word_light"][1]], P["surface"])
        out[f"{name}: wordmark / surface dark"] = contrast(P[t["word_dark"][0]], P["surface-dark"])
        out[f"{name}: wordmark beak / surface dark"] = contrast(P[t["word_dark"][1]], P["surface-dark"])
    L = LIME_PALETTE
    out["Lime Anchor: bird / tile"] = contrast(L["surface"], L["secondary"])
    out["Lime Anchor: beak / tile"] = contrast(L["lime"], L["secondary"])
    out["Lime Anchor: wordmark / surface"] = contrast(L["signature"], L["surface"])
    out["Lime Anchor: wordmark beak / surface"] = contrast(L["lime"], L["surface"])
    write(HERE / "contrast-checks.json", json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return out


def main():
    if not Path(CHROME).exists():
        raise SystemExit(f"Chrome not found at {CHROME}; set CHROME")
    for key, t in TREATMENTS.items():
        kit = build_svgs(key, t)
        render_atlas(kit, kit / "icons/halcyon-icon-primary.svg", kit / "logos/halcyon-primary.svg",
                     kit / "logos/halcyon-dark.svg")
        note = (f'tile {PALETTE[t["tile"]]} · bird {PALETTE[t["bird"]]} · beak {PALETTE[t["beak"]]} · '
                f'wordmark {PALETTE[t["word_light"][0]]} / {PALETTE[t["word_dark"][0]]}')
        print(contact_sheet(kit, f"Halcyon · {t['title']}", note))
    lime = lime_anchor_kit()
    print(contact_sheet(lime, "Halcyon · Lime Anchor (current)",
                        f'tile {LIME_PALETTE["secondary"]} · bird {LIME_PALETTE["surface"]} · beak {LIME_PALETTE["lime"]} · '
                        f'wordmark {LIME_PALETTE["signature"]} / {LIME_PALETTE["surface"]}'))
    for pair, ratio in contrast_checks().items():
        print(f"{ratio:6.2f}  {pair}")


if __name__ == "__main__":
    main()
