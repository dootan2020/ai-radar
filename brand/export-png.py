"""Export Halcyon extension and Store PNGs from the SVGs in brand/assets/.

Run from anywhere, after brand/build-assets.py:  python brand/export-png.py
Use --site for the Halcyon website kit, ICO and screenshot pipeline.
Each SVG is rendered by headless Chrome with a fresh profile under
plans/nhap/, then every PNG's pixel size is read back from its IHDR header and checked
against the platform size below; a mismatch stops the run. The extension path
falls back to ImageMagick when Chrome cannot render. The default command
copies the extension icons and leaves the website untouched.

Chrome path: CHROME env var, else the default Windows install path.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import publish_kit

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "brand" / "assets"
SITE = ROOT / "site"
SCRATCH = ROOT / "plans" / "nhap"
CHROME = os.environ.get("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# (svg, png, css width, css height, device scale, transparent background)
# Sizes: Facebook cover 1640x624 (2x of the 820x312 desktop display), YouTube banner 2560x1440,
# avatar 800x800 (YouTube's recommended upload; Facebook needs 320+), share image 1200x630,
# stories / Shorts / Reels 1080x1920, Apple touch icon 180x180, Chrome Web Store
# icon 128x128, promo tile 440x280, and new-tab screenshots 1280x800.
JOBS = [
    ("cover-facebook.svg", "cover-facebook.png", 1640, 624, 1, False),
    ("cover-youtube.svg", "cover-youtube.png", 2560, 1440, 1, False),
    ("avatar.svg", "avatar.png", 400, 400, 2, False),
    ("og-default.svg", "og-default.png", 1200, 630, 1, False),
    ("khung-9x16.svg", "khung-9x16.png", 1080, 1920, 1, False),
    ("apple-touch-icon-180.svg", "apple-touch-icon.png", 180, 180, 1, False),
    ("favicon-16.svg", "favicon-16.png", 16, 16, 1, True),
    ("favicon-32.svg", "favicon-32.png", 32, 32, 1, True),
    ("extension-icon-16.svg", "store/extension-icon-16.png", 16, 16, 1, True),
    ("extension-icon-32.svg", "store/extension-icon-32.png", 32, 32, 1, True),
    ("extension-icon-48.svg", "store/extension-icon-48.png", 48, 48, 1, True),
    ("extension-icon-128.svg", "store/extension-icon-128.png", 128, 128, 1, True),
    ("store-promo-small.svg", "store/promo-small.png", 440, 280, 1, False),
]
EXTENSION_ICONS = (16, 32, 48, 128)
STORE_SHOTS = ("new-tab-light.png", "new-tab-dark.png")
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
    (ASSETS / png).parent.mkdir(parents=True, exist_ok=True)
    (ASSETS / png).unlink(missing_ok=True)
    profile = tempfile.mkdtemp(prefix="chrome-", dir=SCRATCH)
    args = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            f"--user-data-dir={profile}", f"--force-device-scale-factor={scale}",
            f"--window-size={w},{h}", f"--screenshot={ASSETS / png}", (ASSETS / svg).as_uri()]
    if transparent:
        args.insert(1, "--default-background-color=00000000")
    try:
        done = (subprocess.run(args, capture_output=True, text=True, timeout=60)
                if Path(CHROME).exists() else subprocess.CompletedProcess(args, 1, "", "Chrome not found"))
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if done.returncode != 0 or not (ASSETS / png).exists():
        magick = shutil.which("magick")
        if not magick:
            raise RuntimeError(f"chrome failed on {svg}: {done.stderr.strip()[-400:]}")
        fallback = subprocess.run([magick, "-background", "none", str(ASSETS / svg),
                                   "-resize", f"{w * scale}x{h * scale}!", str(ASSETS / png)],
                                  capture_output=True, text=True, timeout=60)
        if fallback.returncode != 0 or not (ASSETS / png).exists():
            raise RuntimeError(f"Chrome and ImageMagick failed on {svg}: {fallback.stderr.strip()[-400:]}")
        print(f"{png}: rendered with ImageMagick after Chrome failed")
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
    if not Path(CHROME).exists() and not shutil.which("magick"):
        sys.exit(f"Chrome not found at {CHROME}; set CHROME")
    if "--site" not in sys.argv:
        for job in JOBS:
            if job[0].startswith("extension-icon-") or job[0] == "store-promo-small.svg":
                render(*job)
        icons = ROOT / "extension" / "icons"
        icons.mkdir(parents=True, exist_ok=True)
        for size in EXTENSION_ICONS:
            shutil.copyfile(ASSETS / "store" / f"extension-icon-{size}.png", icons / f"{size}.png")
            print(f"extension/icons/{size}.png <- brand/assets/store/extension-icon-{size}.png")
        return
    for job in JOBS:
        render(*job)
    write_ico(ICO_PARTS, "favicon.ico")
    for part in ICO_PARTS:                     # only the .ico is a deliverable
        (ASSETS / part).unlink()
    for src, dst in TO_SITE.items():
        shutil.copyfile(ASSETS / src, SITE / dst)
        print(f"site/{dst} <- brand/assets/{src}")
    icons = ROOT / "extension" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for size in EXTENSION_ICONS:
        shutil.copyfile(ASSETS / "store" / f"extension-icon-{size}.png", icons / f"{size}.png")
        print(f"extension/icons/{size}.png <- brand/assets/store/extension-icon-{size}.png")
    subprocess.run(["node", str(ROOT / "brand" / "store-shots.js")], cwd=ROOT, check=True)
    for name in STORE_SHOTS:
        got = png_size(ASSETS / "store" / name)
        if got != (1280, 800):
            raise RuntimeError(f"{name}: {got[0]}x{got[1]}, expected 1280x800")
        print(f"store/{name}: {got[0]}x{got[1]}")
    publish_kit.publish()


if __name__ == "__main__":
    main()
