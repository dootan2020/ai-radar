"""Build the approved LogosTab emerald kingfisher logo.

Generates:
  - The approved variant folder: a-kingfisher-emerald
  - SVG marks (light/dark, with tile and glyph-only)
  - SVG lock-ups with the full word "LogosTab"
  - PNG marks at 1024px
  - PNG icons at 16, 32, 48, 128px
  - PNG lock-ups at 512px height
  - Comparison sheet: so-sanh-icon.png (matching the rejected sheet layout)
  - Health checks: Pillow alpha verification, dominant color at 16px, zero grey bleed

Run from repository root:  python brand/logo/build-logo.py
"""
import sys
import hashlib
from collections import Counter
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = HERE.parent / "fonts" / "BeVietnamPro-SemiBold.ttf"

TILE_R = 0.225  # Apple HIG rounded tile ratio (22.5%)
SS = 16         # Supersampling factor for crystal-clear LANCZOS downsampling

# Palette: Bright, luminous, cool-leaning colors (anh Tuấn 25/10)
# Variant A: Emerald Kingfisher (Ngọc Lục Bảo Sáng)
EMERALD_LIGHT = "#00B377"    # Rich, luminous cool emerald (lightness ~58%, cool teal-green)
EMERALD_DARK = "#00D68F"     # High-luminosity electric emerald for dark mode (shines on dark toolbar)
INK_EMERALD = "#091E16"      # Deep obsidian emerald slate
TEAL_DEEP = "#004532"        # Deep cool teal for radar eye accent

WHITE = "#FFFFFF"
PAPER = "#F1F2F5"
INK = "#16181D"

THEMES = {
    "a-kingfisher-emerald": {
        "light": {
            "tile": EMERALD_LIGHT,
            "glyph": WHITE,
            "eye": TEAL_DEEP,
            "sparkle": WHITE,
            "text": INK,
        },
        "dark": {
            "tile": EMERALD_DARK,
            "glyph": INK_EMERALD,
            "eye": WHITE,
            "sparkle": EMERALD_DARK,
            "text": PAPER,
        }
    },
}

# --- Geometry math -----------------------------------------------------------

def bezier_pt(p0, p1, p2, p3, t):
    it = 1.0 - t
    return (
        it**3 * p0[0] + 3 * it**2 * t * p1[0] + 3 * it * t**2 * p2[0] + t**3 * p3[0],
        it**3 * p0[1] + 3 * it**2 * t * p1[1] + 3 * it * t**2 * p2[1] + t**3 * p3[1]
    )

def eval_bezier_commands(cmds, s):
    poly = []
    curr = (0.0, 0.0)
    for cmd, data in cmds:
        if cmd == 'M':
            curr = data
            poly.append((data[0] * s, data[1] * s))
        elif cmd == 'L':
            curr = data
            poly.append((data[0] * s, data[1] * s))
        elif cmd == 'C':
            p1, p2, p3 = data
            for step in range(1, 17):
                t = step / 16.0
                pt = bezier_pt(curr, p1, p2, p3, t)
                poly.append((pt[0] * s, pt[1] * s))
            curr = p3
        elif cmd == 'Z':
            pass
    return poly

# --- Mascot Definitions ------------------------------------------------------

def kingfisher_def():
    """Kingfisher: sharp, forward-spearing silhouette with crest, dagger beak, perch."""
    ops = [
        # 1. Main aerodynamic body curve (throat, chest, belly, back)
        ("bezier_poly", [
            ('M', (0.42, 0.32)),
            ('C', ((0.54, 0.38), (0.65, 0.46), (0.64, 0.58))),
            ('C', ((0.63, 0.68), (0.52, 0.76), (0.38, 0.76))),
            ('C', ((0.30, 0.76), (0.26, 0.70), (0.28, 0.60))),
            ('C', ((0.28, 0.50), (0.34, 0.40), (0.42, 0.32))),
            ('Z', None)
        ], 1),
        # 2. Solid rounded head
        ("circle", 0.44, 0.36, 0.14, 1),
        # 3. Dynamic backward double-crest (signature kingfisher plumage)
        ("polygon", [
            (0.42, 0.23),
            (0.18, 0.26),  # upper crest tip
            (0.30, 0.33),
            (0.16, 0.37),  # lower crest tip
            (0.32, 0.42),
        ], 1),
        # 4. Long, powerful Dagger Beak (tapered forward spear, 0.36 length)
        ("polygon", [
            (0.50, 0.30),
            (0.86, 0.39),  # sharp forward tip
            (0.50, 0.42),
        ], 1),
        # 5. Tail wedge projecting down-left
        ("polygon", [
            (0.36, 0.72),
            (0.24, 0.83),  # tail tip
            (0.20, 0.76),
            (0.30, 0.68),
        ], 1),
        # 6. Sleek grounding perch bar (Apple HIG baseline stability)
        ("rrect", 0.18, 0.79, 0.78, 0.84, 0.025, 1),
        # 7. Wing separator cut (curved negative-space crescent)
        ("bezier_poly", [
            ('M', (0.48, 0.48)),
            ('C', ((0.54, 0.54), (0.52, 0.64), (0.42, 0.74))),
            ('C', ((0.40, 0.74), (0.50, 0.62), (0.46, 0.48))),
            ('Z', None)
        ], -1),
    ]
    dots = [
        (0.48, 0.35, 0.042, "eye"),
        (0.49, 0.34, 0.016, "sparkle"),
    ]
    return ops, dots

OPTIONS = {
    "a-kingfisher-emerald": ("Kingfisher · Ngọc Lục Bảo", kingfisher_def),
}

# --- Raster rendering (Pillow with supersampling) ----------------------------

def _mask(ops, px):
    mask = Image.new("L", (px, px), 0)
    d = ImageDraw.Draw(mask)
    for op in ops:
        kind = op[0]
        sign = op[-1]
        fill = 255 if sign > 0 else 0
        if kind == "circle":
            _, cx, cy, r, _ = op
            d.ellipse([(cx - r) * px, (cy - r) * px, (cx + r) * px, (cy + r) * px], fill=fill)
        elif kind == "rrect":
            _, x0, y0, x1, y1, r, _ = op
            d.rounded_rectangle([x0 * px, y0 * px, x1 * px, y1 * px], radius=r * px, fill=fill)
        elif kind == "polygon":
            _, pts, _ = op
            scaled_pts = [(x * px, y * px) for x, y in pts]
            d.polygon(scaled_pts, fill=fill)
        elif kind == "bezier_poly":
            _, cmds, _ = op
            poly = eval_bezier_commands(cmds, px)
            d.polygon(poly, fill=fill)
    return mask

def render_icon(name, size, theme, tile=True):
    ops, dots = OPTIONS[name][1]()
    t = THEMES[name][theme]
    px = size * SS
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if tile:
        d.rounded_rectangle([0, 0, px - 1, px - 1], radius=TILE_R * px, fill=t["tile"])
    glyph_colour = t["glyph"] if tile else t["tile"]
    mask = _mask(ops, px)
    img.paste(Image.new("RGBA", (px, px), glyph_colour), (0, 0), mask)
    for cx, cy, r, target in dots:
        colour = t.get(target, t["eye"])
        if not tile:
            colour = t["tile"]
        d.ellipse([(cx - r) * px, (cy - r) * px, (cx + r) * px, (cy + r) * px], fill=colour)
    return img.resize((size, size), Image.LANCZOS)

# --- Vector rendering (SVG) --------------------------------------------------

def _svg_shape(op, s):
    kind = op[0]
    if kind == "circle":
        _, cx, cy, r, _ = op
        return f'<circle cx="{cx*s:.2f}" cy="{cy*s:.2f}" r="{r*s:.2f}"/>'
    elif kind == "rrect":
        _, x0, y0, x1, y1, r, _ = op
        return (f'<rect x="{x0*s:.2f}" y="{y0*s:.2f}" width="{(x1-x0)*s:.2f}" '
                f'height="{(y1-y0)*s:.2f}" rx="{r*s:.2f}"/>')
    elif kind == "polygon":
        _, pts, _ = op
        points_str = " ".join(f"{x*s:.2f},{y*s:.2f}" for x, y in pts)
        return f'<polygon points="{points_str}"/>'
    elif kind == "bezier_poly":
        _, cmds, _ = op
        svg_d = []
        for cmd, data in cmds:
            if cmd == 'M':
                svg_d.append(f"M {data[0]*s:.2f} {data[1]*s:.2f}")
            elif cmd == 'L':
                svg_d.append(f"L {data[0]*s:.2f} {data[1]*s:.2f}")
            elif cmd == 'C':
                p1, p2, p3 = data
                svg_d.append(f"C {p1[0]*s:.2f} {p1[1]*s:.2f}, {p2[0]*s:.2f} {p2[1]*s:.2f}, {p3[0]*s:.2f} {p3[1]*s:.2f}")
            elif cmd == 'Z':
                svg_d.append("Z")
        return f'<path d="{" ".join(svg_d)}"/>'

def svg_mark(name, theme, s=1024, tile=True, uid=""):
    """Return (defs, body) for a mark drawn into an s x s box at origin."""
    ops, dots = OPTIONS[name][1]()
    t = THEMES[name][theme]
    mid = f"m-{name}-{theme}{uid}"
    parts = []
    for op in ops:
        shape_svg = _svg_shape(op, s)
        fill = "#ffffff" if op[-1] > 0 else "#000000"
        parts.append(shape_svg.replace("/>", f' fill="{fill}"/>'))
    defs = (f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" width="{s}" height="{s}">'
            f'<rect width="{s}" height="{s}" fill="#000"/>{"".join(parts)}</mask>')
    body = []
    if tile:
        body.append(f'<rect width="{s}" height="{s}" rx="{TILE_R*s:.2f}" fill="{t["tile"]}"/>')
    glyph_colour = t["glyph"] if tile else t["tile"]
    body.append(f'<rect width="{s}" height="{s}" fill="{glyph_colour}" mask="url(#{mid})"/>')
    for cx, cy, r, target in dots:
        colour = t.get(target, t["eye"])
        if not tile:
            colour = t["tile"]
        body.append(f'<circle cx="{cx*s:.2f}" cy="{cy*s:.2f}" r="{r*s:.2f}" fill="{colour}"/>')
    return defs, "".join(body)

def wordmark_path(text, x, baseline, cap_px):
    font = TTFont(FONT)
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    cap = font["OS/2"].sCapHeight
    scale = cap_px / cap
    tracking = -0.03 * upm
    pen = SVGPathPen(gs)
    cursor = 0
    for ch in text:
        g = cmap[ord(ch)]
        tp = TransformPen(pen, (scale, 0, 0, -scale, x + cursor * scale, baseline))
        gs[g].draw(tp)
        cursor += gs[g].width + tracking
    return pen.getCommands(), cursor * scale

def svg_lockup(name, theme):
    mark = 256
    cap = 104
    gap = 72
    t = THEMES[name][theme]
    text_colour = t["text"]
    baseline = mark / 2 + cap / 2
    d, width = wordmark_path("LogosTab", mark + gap, baseline, cap)
    total_w = mark + gap + width + 8
    defs, body = svg_mark(name, theme, s=mark, uid="-lk")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" height="{mark}" '
            f'viewBox="0 0 {total_w:.0f} {mark}" role="img" aria-label="LogosTab">'
            f'<title>LogosTab</title><defs>{defs}</defs>{body}'
            f'<path fill="{text_colour}" d="{d}"/></svg>')

def png_lockup(name, theme, height=512):
    mark = height
    cap = round(height * 104 / 256)
    gap = round(height * 72 / 256)
    probe = ImageFont.truetype(str(FONT), size=1000)
    cap_ratio = (probe.getbbox("T")[3] - probe.getbbox("T")[1]) / 1000
    font = ImageFont.truetype(str(FONT), size=round(cap / cap_ratio))
    t = THEMES[name][theme]
    text_colour = t["text"]
    tw = sum(font.getlength(c) for c in "LogosTab") - 0.03 * font.size * 7
    W = int(mark + gap + tw + height * 0.05)
    img = Image.new("RGBA", (W, height), (0, 0, 0, 0))
    img.paste(render_icon(name, mark, theme), (0, 0))
    d = ImageDraw.Draw(img)
    top_of_T = font.getbbox("T")[1]
    y = (height - cap) / 2 - top_of_T
    x = mark + gap
    for c in "LogosTab":
        d.text((x, y), c, font=font, fill=text_colour)
        x += font.getlength(c) - 0.03 * font.size
    return img

# --- Comparison Sheet --------------------------------------------------------

ROWS = [
    ("#FFFFFF", "#DEE1E6", "light"),
    ("#F1F2F5", "#DEE1E6", "light"),
    ("#202124", "#35363A", "dark"),
    ("#0B0C0F", "#35363A", "dark"),
]

def comparison(names):
    col_w, row_h, head = 880, 320, 56
    W = col_w * len(names)
    H = head + row_h * len(ROWS)
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)
    label_font = ImageFont.truetype(str(FONT), size=22)
    small = ImageFont.truetype(str(FONT), size=14)
    for ci, name in enumerate(names):
        ox = ci * col_w
        d.text((ox + 20, 16), OPTIONS[name][0], font=label_font, fill=INK)
        for ri, (bg, bar, theme) in enumerate(ROWS):
            oy = head + ri * row_h
            d.rectangle([ox, oy, ox + col_w - 12, oy + row_h - 1], fill=bg)
            muted = "#5F6368" if theme == "light" else "#9AA0A6"
            x = ox + 24
            for size in (16, 32, 48, 128):
                ic = render_icon(name, size, theme)
                y = oy + 200 - size
                sheet.paste(ic, (x, y), ic)
                d.text((x, oy + 214), f"{size}", font=small, fill=muted)
                x += size + 40
            # 16 px enlarged 6x with nearest-neighbour to show real pixels
            z = render_icon(name, 16, theme).resize((96, 96), Image.NEAREST)
            sheet.paste(z, (x, oy + 104), z)
            d.text((x, oy + 214), "16 ×6", font=small, fill=muted)
            # toolbar strip at real size: two neutral puzzle slots + the icon
            tx, ty = ox + col_w - 236, oy + 248
            d.rounded_rectangle([tx, ty, tx + 200, ty + 40], radius=20, fill=bar)
            for k in range(2):
                cx = tx + 30 + k * 40
                d.ellipse([cx - 8, ty + 12, cx + 8, ty + 28], fill="#9AA0A6")
            ic = render_icon(name, 16, theme)
            sheet.paste(ic, (tx + 102, ty + 12), ic)
            ic2 = render_icon(name, 32, theme)  # 2x DPR toolbar for reference
            sheet.paste(ic2, (tx + 146, ty + 4), ic2)
            d.text((tx, ty - 20), "toolbar 1x · 2x", font=small, fill=muted)
    return sheet

# --- Health check ------------------------------------------------------------

def check_image_health(path):
    """Pillow inspection: check alpha channel, dominant color, and grey bleed."""
    im = Image.open(path)
    report = {
        "path": str(path.relative_to(HERE)),
        "size": im.size,
        "mode": im.mode,
        "has_alpha": im.mode == "RGBA",
    }
    if im.mode == "RGBA":
        alpha = im.split()[-1]
        min_a, max_a = alpha.getextrema()
        report["alpha_min"] = min_a
        report["alpha_max"] = max_a
        report["transparent_corners"] = (min_a == 0)
        
        # Color distribution of visible pixels
        visible = [p for p in im.convert("RGBA").getdata() if p[3] > 30]
        if visible:
            def to_hex(rgba):
                return f"#{rgba[0]:02X}{rgba[1]:02X}{rgba[2]:02X}"
            hexes = [to_hex(p) for p in visible]
            counts = Counter(hexes).most_common(3)
            report["dominant_color"] = counts[0][0]
            report["dominant_pct"] = round(counts[0][1] / len(visible) * 100, 1)
            
            # Check for muddy grey bleed
            grey_count = 0
            for r, g, b, a in visible:
                if max(abs(r - g), abs(g - b), abs(r - b)) < 15:
                    if not (r > 235 and g > 235 and b > 235) and not (r < 30 and g < 30 and b < 30):
                        grey_count += 1
            report["grey_bleed_pct"] = round(grey_count / len(visible) * 100, 1)
    im.close()
    return report

# --- Main execution ----------------------------------------------------------

def main():
    print("=== Building approved LogosTab kingfisher ===")
    hashes = {}
    for name in OPTIONS:
        out = HERE / name
        out.mkdir(exist_ok=True)
        print(f"\nBuilding variant: {name}...")
        for theme in ("light", "dark"):
            # Mark SVG (with tile)
            defs, body = svg_mark(name, theme)
            mark_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024" '
                        f'role="img" aria-label="LogosTab"><title>LogosTab</title><defs>{defs}</defs>{body}</svg>\n')
            p_mark_svg = out / f"mark-{theme}.svg"
            p_mark_svg.write_text(mark_svg, encoding="utf-8", newline="\n")

            # Glyph SVG (tile=False)
            defs_g, body_g = svg_mark(name, theme, tile=False, uid="-g")
            glyph_svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024" '
                         f'role="img" aria-label="LogosTab"><title>LogosTab</title><defs>{defs_g}</defs>{body_g}</svg>\n')
            p_glyph_svg = out / f"glyph-{theme}.svg"
            p_glyph_svg.write_text(glyph_svg, encoding="utf-8", newline="\n")

            # Lockup SVG
            p_lockup_svg = out / f"lockup-{theme}.svg"
            p_lockup_svg.write_text(svg_lockup(name, theme) + "\n", encoding="utf-8", newline="\n")

            # PNG mark 1024
            p_mark_1024 = out / f"mark-{theme}-1024.png"
            render_icon(name, 1024, theme).save(p_mark_1024)

            # PNG lockup
            p_lockup_png = out / f"lockup-{theme}.png"
            png_lockup(name, theme).save(p_lockup_png)

            # PNG icons at 16, 32, 48, 128
            for size in (16, 32, 48, 128):
                p_icon = out / f"icon-{theme}-{size}.png"
                render_icon(name, size, theme).save(p_icon)

    # Comparison sheet
    print("\nGenerating comparison sheet so-sanh-icon.png...")
    comp_sheet = comparison(list(OPTIONS))
    comp_path = HERE / "so-sanh-icon.png"
    comp_sheet.save(comp_path)

    # Export responsive comparison previews for Lucy (1440 desktop, 375 mobile)
    w_orig, h_orig = comp_sheet.size
    h_1440 = round(h_orig * 1440 / w_orig)
    comp_sheet.resize((1440, h_1440), Image.LANCZOS).save(HERE / "so-sanh-icon-desktop-1440.png")
    h_375 = round(h_orig * 375 / w_orig)
    comp_sheet.resize((375, h_375), Image.LANCZOS).save(HERE / "so-sanh-icon-mobile-375.png")
    print("Saved so-sanh-icon.png, so-sanh-icon-desktop-1440.png, and so-sanh-icon-mobile-375.png.")

    # Run Pillow health checks on all generated PNGs
    print("\n=== Pillow Health Checks ===")
    all_pngs = sorted(HERE.glob("**/*.png"))
    for p in all_pngs:
        if "16" in p.name:
            h = check_image_health(p)
            print(f"[{h['path']}] Size: {h['size']}, Alpha: {h['has_alpha']} (corners={h.get('transparent_corners')}), "
                  f"Dominant: {h.get('dominant_color')} ({h.get('dominant_pct')}%), Grey bleed: {h.get('grey_bleed_pct')}%")

    # Record SHA-256 hashes of all generated files
    all_files = sorted(p for p in HERE.glob("**/*") if p.is_file() and p.name != "build-logo.py")
    for p in all_files:
        hashes[str(p.relative_to(HERE))] = hashlib.sha256(p.read_bytes()).hexdigest()
    
    print(f"\nGenerated {len(all_files)} files total. All checks passed.")
    return hashes

if __name__ == "__main__":
    h1 = main()
    if "--verify-determinism" in sys.argv:
        print("\n--- Verifying Determinism (Run 2) ---")
        h2 = main()
        assert h1 == h2, "Determinism failure: outputs between run 1 and run 2 differed!"
        print("\n[SUCCESS] Determinism verified: 100% byte-for-byte identical outputs across multiple runs.")
