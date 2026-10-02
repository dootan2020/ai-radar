"""Export the upload-ready PNG and ICO files from the SVGs in brand/assets/.

Run from anywhere, after brand/build-assets.py:  python brand/export-png.py
Python stdlib only. Each SVG is rendered by headless Chrome with a fresh profile under
plans/nhap/, then every PNG's pixel size is read back from its IHDR header and checked
against the platform size below; a mismatch stops the run. favicon.ico packs the 16 and 32
renders as PNG entries. The files the live site needs are copied into site/.

Chrome path: CHROME env var, else the default Windows install path.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "brand" / "assets"
SITE = ROOT / "site"
SCRATCH = ROOT / "plans" / "nhap"
CHROME = os.environ.get("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# (svg, png, css width, css height, device scale, transparent background)
# Sizes: Facebook cover 1640x624 (2x of the 820x312 desktop display), YouTube banner 2560x1440,
# avatar 800x800 (YouTube's recommended upload; Facebook needs 320+), share image 1200x630,
# stories / Shorts / Reels 1080x1920, Apple touch icon 180x180.
JOBS = [
    ("cover-facebook.svg", "cover-facebook.png", 1640, 624, 1, False),
    ("cover-youtube.svg", "cover-youtube.png", 2560, 1440, 1, False),
    ("avatar.svg", "avatar.png", 400, 400, 2, False),
    ("og-default.svg", "og-default.png", 1200, 630, 1, False),
    ("khung-9x16.svg", "khung-9x16.png", 1080, 1920, 1, False),
    ("apple-touch-icon-180.svg", "apple-touch-icon.png", 180, 180, 1, False),
    ("favicon-16.svg", "favicon-16.png", 16, 16, 1, True),
    ("favicon-32.svg", "favicon-32.png", 32, 32, 1, True),
]
ICO_PARTS = ("favicon-16.png", "favicon-32.png")
TO_SITE = {"og-default.png": "og-image.png", "apple-touch-icon.png": "apple-touch-icon.png",
           "favicon.ico": "favicon.ico"}


def png_size(path):
    """Pixel width and height from the PNG signature + IHDR chunk."""
    head = Path(path).read_bytes()[:24]
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"{path}: not a PNG")
    return struct.unpack(">II", head[16:24])


def render(svg, png, w, h, scale, transparent):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="chrome-", dir=SCRATCH)
    args = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            f"--user-data-dir={profile}", f"--force-device-scale-factor={scale}",
            f"--window-size={w},{h}", f"--screenshot={ASSETS / png}", (ASSETS / svg).as_uri()]
    if transparent:
        args.insert(1, "--default-background-color=00000000")
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=60)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if done.returncode != 0 or not (ASSETS / png).exists():
        raise RuntimeError(f"chrome failed on {svg}: {done.stderr.strip()[-400:]}")
    got, want = png_size(ASSETS / png), (w * scale, h * scale)
    if got != want:
        raise RuntimeError(f"{png}: {got[0]}x{got[1]}, expected {want[0]}x{want[1]}")
    print(f"{png}: {got[0]}x{got[1]}")


def write_ico(parts, out):
    """ICO with PNG-compressed entries (Windows Vista+, every current browser)."""
    blobs = [(ASSETS / p).read_bytes() for p in parts]
    offset = 6 + 16 * len(blobs)
    header = struct.pack("<HHH", 0, 1, len(blobs))
    entries = b""
    for p, blob in zip(parts, blobs):
        w, h = png_size(ASSETS / p)
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    (ASSETS / out).write_bytes(header + entries + b"".join(blobs))
    print(f"{out}: " + " + ".join("%dx%d" % png_size(ASSETS / p) for p in parts))


def main():
    if not Path(CHROME).exists():
        sys.exit(f"Chrome not found at {CHROME}; set CHROME")
    for job in JOBS:
        render(*job)
    write_ico(ICO_PARTS, "favicon.ico")
    for part in ICO_PARTS:                     # only the .ico is a deliverable
        (ASSETS / part).unlink()
    for src, dst in TO_SITE.items():
        shutil.copyfile(ASSETS / src, SITE / dst)
        print(f"site/{dst} <- brand/assets/{src}")


if __name__ == "__main__":
    main()
