"""Rebuild original synthetic image fixtures; no downloaded or third-party pixels.

Run from any directory with Pillow 12.1.0. These exercise layout invariants,
not photographic accuracy. The generated files belong to this repository.
"""

import math
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent


def main():
    # A shaded subject occupies a minority of a near-white canvas.
    subject = Image.new("RGB", (640, 360), (248, 248, 248))
    for y in range(25, 355):
        for x in range(220, 450):
            radius = ((x - 335) / 112) ** 2 + ((y - 190) / 165) ** 2
            if radius < 1:
                light = math.sqrt(1 - radius)
                ripple = 18 * math.sin(x / 13) * math.cos(y / 17)
                subject.putpixel((x, y), (int(45 + 125 * light + ripple),
                                         int(30 + 95 * light + ripple),
                                         int(25 + 65 * light + ripple)))
    subject.save(ROOT / "tonal-subject.png")
    tagged = subject.copy()
    draw = ImageDraw.Draw(tagged)
    draw.rounded_rectangle((12, 15, 154, 40), radius=5, fill="#444444")
    draw.text((20, 19), "AI GENERATED", font=ImageFont.load_default(size=16), fill="white")
    tagged.save(ROOT / "tagged-subject.png")

    # Repeated high-contrast details on an irregular surface resemble foliage
    # or racks of equipment. Alignment is not sufficient evidence of text.
    rng = random.Random(41)
    texture = Image.new("RGB", (400, 240))
    texture.putdata([(rng.randrange(20, 120), rng.randrange(35, 175), rng.randrange(15, 110))
                     for _ in range(400 * 240)])
    draw = ImageDraw.Draw(texture)
    for y in range(10, 230, 20):
        for x in range(10, 390, 15):
            draw.ellipse((x, y, x + 5, y + 9), fill="#eedc75")
    texture.save(ROOT / "aligned-texture.png")

    banner = Image.new("RGB", (800, 450))
    banner.putdata([(int(60 + 150 * x / 800), int(80 + 120 * y / 450), 180)
                    for y in range(450) for x in range(800)])
    draw = ImageDraw.Draw(banner)
    font = ImageFont.load_default(size=32)
    for y, text in [(70, "RESEARCH NEWS"), (150, "How software teams build agents"),
                    (205, "with better tools and clear results"), (350, "Read the full article")]:
        draw.text((35, y), text, font=font, fill="black")
    banner.save(ROOT / "gradient-text-card.png")

    headline = Image.new("RGB", (800, 450), "#222222")
    draw = ImageDraw.Draw(headline)
    headline.putdata([(v, v, v) for y in range(450) for x in range(800)
                      for v in [int(20 + 65 * x / 800 + 30 * y / 450)]])
    font = ImageFont.load_default(size=64)
    for y, text in [(75, "DAYS"), (175, "LEFT")]:
        draw.text((280, y), text, font=font, fill="white", stroke_width=1)
    draw.polygon([(0, 0), (200, 0), (0, 80)], fill="#20bb66")
    headline.save(ROOT / "stacked-headline.png")


if __name__ == "__main__":
    main()
