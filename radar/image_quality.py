"""Local, conservative editorial-image screening without a model or service.

Pillow is optional. Without a decoder, uninspected source images are withheld.
This is a layout heuristic, not semantic image understanding or OCR.
"""

from collections import Counter
from io import BytesIO
import re
from urllib.parse import unquote, urlsplit

QUALITY_VERSION = 2
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Bound decoder memory, independently of the much smaller analysis raster.
MAX_IMAGE_PIXELS = 80_000_000


def decision(keep, reason, **metrics):
    return dict(version=QUALITY_VERSION, keep=keep, reason=reason, **metrics)


def metadata_rejection(src, via=None):
    """Reject explicit preview-card/logo assets before spending a download."""
    parts = urlsplit(src or "")
    host = (parts.hostname or "").lower()
    path = unquote(parts.path).lower()
    if via == "github-social" or host == "opengraph.githubassets.com":
        return decision(False, "repository-preview-card")
    if host == "cdn-thumbnails.huggingface.co" and "/social-thumbnails/" in path:
        return decision(False, "repository-preview-card")
    if host == "news.ycombinator.com" or host == "ycombinator.com":
        return decision(False, "publisher-logo")
    if re.search(r"(?:^|[/_. -])(?:logos?|favicons?|og-card|social-card|banners?|screenshots?)(?:[/_. -]|$)", path):
        return decision(False, "named-logo-banner-screenshot")
    if re.search(r"(?:^|/)(?:opengraph-image|og-image|og\.png)(?:[/.]|$)", path):
        return decision(False, "named-preview-card")
    return None


def classify_pixels(raw):
    """Withhold clear graphic layouts; prefer retaining ambiguous photographs."""
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return decision(False, "empty-or-oversize-image")
    try:
        from PIL import Image
    except ImportError:
        return decision(False, "decoder-unavailable")
    try:
        with Image.open(BytesIO(raw)) as source:
            width, height = source.size
            if width * height > MAX_IMAGE_PIXELS:
                return decision(False, "pixel-safety-limit")
            if min(width, height) < 64:
                return decision(False, "tiny-dimensions")
            # JPEG draft decoding avoids allocating the full camera-sized raster.
            # Other formats still have the pixel safety ceiling above.
            source.draft("RGB", (400, 300))
            source.thumbnail((400, 300))
            # Composite transparent logos onto white, rather than treating alpha as a photo.
            rgba = source.convert("RGBA")
            image = Image.new("RGBA", rgba.size, "white")
            image.alpha_composite(rgba)
            image = image.convert("RGB")
    except Exception:
        return decision(False, "undecodable-image")
    width, height = image.size
    if min(width, height) < 3:
        # Very wide/tall source photos can shrink to a one-pixel strip. There
        # is no meaningful neighborhood to measure; aspect ratio is not a veto.
        return decision(True, "insufficient-layout-resolution")
    rgb = image.tobytes()
    colors = Counter(tuple(channel // 16 for channel in rgb[i:i + 3]) for i in range(0, len(rgb), 3))
    flat_fraction = sum(count for _, count in colors.most_common(4)) / (width * height)

    # Quantized color dominance alone confuses a portrait on white or a render
    # on a solid background with a logo. Require much stronger color dominance,
    # and gate the glyph test with smoothness to avoid mistaking scene texture
    # for lettering. Smooth shading alone is not evidence of a logo.
    smooth = 0
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = (y * width + x) * 3
            if all(abs(rgb[i + c] - rgb[i + 3 + c]) <= 4
                   and abs(rgb[i + c] - rgb[i + width * 3 + c]) <= 4 for c in range(3)):
                smooth += 1
    smooth_fraction = smooth / ((width - 2) * (height - 2))
    metrics = dict(flat_fraction=round(flat_fraction, 3), smooth_fraction=round(smooth_fraction, 3))
    if flat_fraction >= .85:
        return decision(False, "flat-logo-or-text-layout", **metrics)

    # High-contrast connected components approximate glyphs on both light and dark
    # backgrounds. Aligned rows distinguish text blocks from scattered photo edges.
    gray = image.convert("L").tobytes()
    edges = set()
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = y * width + x
            if max(abs(gray[i] - gray[i + 1]), abs(gray[i] - gray[i + width])) >= 55:
                edges.add(i)
    glyphs = []
    while edges:
        first = edges.pop()
        pending = [first]
        xs, ys = [], []
        while pending:
            i = pending.pop()
            y, x = divmod(i, width)
            xs.append(x)
            ys.append(y)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    j = i + dy * width + dx
                    if j in edges:
                        edges.remove(j)
                        pending.append(j)
        w, h = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        if 2 <= w <= 45 and 5 <= h <= 55 and 0.08 <= w / h <= 3:
            glyphs.append((min(xs), min(ys), w, h))
    text_glyphs = set()
    large_glyphs = set()
    for _, y, _, h in glyphs:
        row = [(j, g) for j, g in enumerate(glyphs)
               if abs(g[1] - y) <= max(2, h * .25) and .6 <= g[3] / h <= 1.6]
        if len(row) >= 6 and max(g[0] + g[2] for _, g in row) - min(g[0] for _, g in row) >= width * .25:
            text_glyphs.update(j for j, _ in row)
        # Short stacked headlines have fewer letters per line than body text.
        if h >= height * .10 and len(row) >= 3:
            large_glyphs.update(j for j, _ in row)
    text_area = sum(glyphs[j][2] * glyphs[j][3] for j in text_glyphs) / (width * height)
    large_area = sum(glyphs[j][2] * glyphs[j][3] for j in large_glyphs) / (width * height)
    metrics.update(glyphs=len(text_glyphs), text_area=round(text_area, 3),
                   large_glyphs=len(large_glyphs), large_text_area=round(large_area, 3))
    dominant_text = ((len(text_glyphs) >= 24 and text_area >= .025)
                     or (len(text_glyphs) >= 12 and text_area >= .045)
                     or (flat_fraction >= .65 and len(large_glyphs) >= 7 and large_area >= .04))
    if smooth_fraction >= .45 and dominant_text:
        return decision(False, "aligned-text-layout", **metrics)
    return decision(True, "no-dominant-text-or-logo-detected", **metrics)
