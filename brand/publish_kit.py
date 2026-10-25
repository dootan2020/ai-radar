"""Mirror the publishable brand kit into site/brand/, which GitHub Pages serves.

Imported by build-assets.py and export-png.py (each calls publish() as its last step), or run
directly:  python brand/publish_kit.py
site/brand/ is generated; never edit it by hand. tests/test_brand_meta.py fails when it differs
from the publishable brand kit. Store PNG screenshots stay out of the website copy.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "brand"
DEST = ROOT / "site" / "brand"
PUBLISHED = ("index.html", "tokens.css", "assets", "fonts", "logo")
IMAGE_SUFFIXES = {".svg", ".png", ".ico", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}


def is_extension_art(relative):
    return relative == "assets/store" or relative.startswith("assets/store/")


def is_publishable(relative):
    return not is_extension_art(relative) and (
        not relative.startswith("logo/") or Path(relative).suffix.lower() in IMAGE_SUFFIXES
    )


def ignore_unpublished(directory, names):
    relative = Path(directory).relative_to(BRAND)
    return {name for name in names if is_extension_art((relative / name).as_posix())
            or (relative.parts and relative.parts[0] == "logo" and name == "__pycache__")
            or (not (Path(directory) / name).is_dir()
                and not is_publishable((relative / name).as_posix()))}


def files(base):
    """Relative posix paths of every published file under `base`."""
    out = []
    for name in PUBLISHED:
        p = base / name
        if p.is_file():
            out.append(name)
        elif p.is_dir():
            out += [f.relative_to(base).as_posix() for f in sorted(p.rglob("*"))
                    if f.is_file() and is_publishable(f.relative_to(base).as_posix())]
    return out


def publish():
    source_book = (BRAND / "aibit-news" / "index.html").read_text(encoding="utf-8")
    source_book = source_book.replace('../assets/', 'assets/').replace('../fonts/', 'fonts/').replace('../logo/', 'logo/')
    downloads = "".join(
        f'<a href="assets/{name}" download>{name}</a>'
        for name in ("cover-facebook.png", "cover-youtube.png", "avatar.png", "og-default.png",
                     "khung-9x16.png", "apple-touch-icon.png", "favicon.ico")
    )
    source_book = source_book.replace('</div></section>\n  </main>', downloads + '</div></section>\n  </main>')
    (BRAND / "index.html").write_text(source_book, encoding="utf-8", newline="\n")
    for name in PUBLISHED:
        src, dst = BRAND / name, DEST / name
        if not src.exists():
            raise FileNotFoundError(src)
        if dst.is_dir():
            shutil.rmtree(dst)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=ignore_unpublished)
        else:
            DEST.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    print(f"published {len(files(DEST))} files to site/brand/")


if __name__ == "__main__":
    publish()
