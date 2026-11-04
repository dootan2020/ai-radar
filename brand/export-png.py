"""Export Halcyon extension and Store PNGs: the kit's own icon PNGs, plus renders of composed SVGs.

Run from anywhere, after brand/build-assets.py:  python brand/export-png.py
Use --site for the Halcyon website kit, favicon and screenshot pipeline.
Icons, the favicon ICO and the Apple touch icon are the Lime Anchor kit's own pixel files
(brand/logo/lime-anchor/), copied unchanged; each PNG's pixel size is read back from its IHDR header.
Composed SVGs (covers, share images, avatar, Store promo) are rendered by headless Chrome with a
fresh profile under plans/nhap/ and checked the same way; a mismatch stops the run. Rendering
falls back to ImageMagick when Chrome cannot render. The default command copies the extension
icons, renders the Store promo and leaves the website untouched.

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
KIT = ROOT / "brand" / "logo" / "lime-anchor"
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
    ("store-promo-small.svg", "store/promo-small.png", 440, 280, 1, False),
]
EXTENSION_ICONS = (16, 32, 48, 128)
STORE_SHOTS = ("new-tab-light.png", "new-tab-dark.png")
# (kit file, brand/assets file, pixel size or None for the ICO)
KIT_COPIES = [(f"icons/halcyon-icon-primary-{n}.png", f"store/extension-icon-{n}.png", (n, n)) for n in EXTENSION_ICONS] + [
    ("favicons/apple-touch-icon.png", "apple-touch-icon.png", (180, 180)),
    ("favicons/favicon.ico", "favicon.ico", None),
]
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


def copy_kit(names):
    """Copy the kit's own pixel files unchanged and check each PNG's size."""
    for src, dst, size in KIT_COPIES:
        if dst not in names:
            continue
        (ASSETS / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(KIT / src, ASSETS / dst)
        if size and png_size(ASSETS / dst) != size:
            raise RuntimeError(f"{dst}: {png_size(ASSETS / dst)}, expected {size}")
        print(f"{dst} <- brand/logo/lime-anchor/{src}")


def copy_extension_icons():
    copy_kit({f"store/extension-icon-{size}.png" for size in EXTENSION_ICONS})
    icons = ROOT / "extension" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for size in EXTENSION_ICONS:
        shutil.copyfile(ASSETS / "store" / f"extension-icon-{size}.png", icons / f"{size}.png")
        print(f"extension/icons/{size}.png <- brand/assets/store/extension-icon-{size}.png")


def main():
    if not Path(CHROME).exists() and not shutil.which("magick"):
        sys.exit(f"Chrome not found at {CHROME}; set CHROME")
    if "--site" not in sys.argv:
        render(*next(job for job in JOBS if job[0] == "store-promo-small.svg"))
        copy_extension_icons()
        return
    for job in JOBS:
        render(*job)
    copy_kit({"apple-touch-icon.png", "favicon.ico"})
    for src, dst in TO_SITE.items():
        shutil.copyfile(ASSETS / src, SITE / dst)
        print(f"site/{dst} <- brand/assets/{src}")
    copy_extension_icons()
    subprocess.run(["node", str(ROOT / "brand" / "store-shots.js")], cwd=ROOT, check=True)
    for name in STORE_SHOTS:
        got = png_size(ASSETS / "store" / name)
        if got != (1280, 800):
            raise RuntimeError(f"{name}: {got[0]}x{got[1]}, expected 1280x800")
        print(f"store/{name}: {got[0]}x{got[1]}")
    publish_kit.publish()


if __name__ == "__main__":
    main()
