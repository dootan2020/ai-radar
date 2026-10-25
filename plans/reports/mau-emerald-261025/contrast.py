"""Measure the LogosTab colour pairs used by the emerald pass (WCAG 2.x)."""

import math
import re
from pathlib import Path


CSS = (Path(__file__).resolve().parents[3] / "site" / "tokens.css").read_text(encoding="utf-8")


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def oklch_rgb(lightness, chroma, hue):
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )
    return tuple(max(0, min(1, 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055)) for x in linear)


def token(name):
    match = re.search(rf"--{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}}|oklch\([^;]+\))", CSS)
    if not match:
        raise ValueError(f"Missing colour token: {name}")
    value = match.group(1)
    if value.startswith("#"):
        return hex_rgb(value)
    parts = value[7:-1].split()
    hue = float(re.search(r"--hue:\s*([\d.]+)", CSS).group(1)) if "var(--hue)" in value else float(parts[2])
    return oklch_rgb(float(parts[0]), float(parts[1]), hue)


def luminance(rgb):
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return sum(x * weight for x, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def show(label, before, after, background, minimum=4.5):
    old = contrast(before, background)
    new = contrast(after, background)
    print(f"{label:34} {old:5.2f}:1 -> {new:5.2f}:1  (min {minimum:g}:1)")
    assert new >= minimum, label


if __name__ == "__main__":
    light = token("emerald-ink")
    dark = token("emerald-bright")
    old_light = oklch_rgb(0.50, 0.20, 256)
    old_dark = oklch_rgb(0.74, 0.14, 252)
    show("light accent / surface", old_light, light, token("gray-99"))
    show("light accent / canvas", old_light, light, token("gray-96"))
    show("light on-accent / action", token("gray-99"), token("gray-99"), light)
    show("dark accent / surface", old_dark, dark, token("gray-17"))
    show("dark accent / canvas", old_dark, dark, token("gray-13"))
    show("dark on-accent / action", token("gray-13"), token("gray-13"), dark)
    show("light ok / fill", oklch_rgb(0.45, 0.12, 155), token("gray-44"), token("gray-93"))
    show("dark ok / fill", oklch_rgb(0.80, 0.13, 155), token("gray-80"), token("gray-25"))
    show("light quiet label / surface", old_light, token("gray-44"), token("gray-99"))
    show("dark quiet label / surface", old_dark, token("gray-80"), token("gray-17"))
    show("OG caption / paper", hex_rgb("#005CD1"), light, hex_rgb("#F1F2F5"))
    show("Google badge light", token("gt-blue-700"), token("gt-blue-700"), token("gt-blue-50"))
    show("Google badge dark", token("gt-blue-300"), token("gt-blue-300"), token("gt-blue-night"))
