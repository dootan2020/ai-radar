"""Give every story without a usable picture a cover drawn from its own facts.

Run after the summary step, when stories carry their Vietnamese headline and key points:

    python -m radar.covers --input site/data/radar.json

A cover is the owner's chosen "Con số" drawing (covers/templates/con-so.html): the story's key figure, else its
subject's name, else its outlet, rendered locally by headless Chrome (covers/render-site.mjs). It only fills a gap:
a published photo or an AI illustration always wins, and a story that gains one in a later run loses its cover.
Its image entry says what it is (via "cover", kind "cover"), so no page calls it a photo or an AI illustration.
Files live in site/assets/cover and are reused while the story's facts are unchanged (the hash in the file name).
Without Node or Chrome the step changes nothing and the feed keeps its text cards.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from radar.pipeline import write_atomic
from radar.site_payload import complete_published_snapshot, write_site_snapshot

ROOT = Path(__file__).resolve().parent.parent
RENDERER = ROOT / "covers" / "render-site.mjs"
COVER_SRC = re.compile(r"assets/cover/([\w-]+)-[0-9a-f]{10}(?:-t)?\.png")
RENDER_TIMEOUT = 600


def is_cover(image) -> bool:
    return isinstance(image, dict) and image.get("via") == "cover"


def needs_cover(story) -> bool:
    """A story needs a cover when it has no picture, or only a cover (which may be stale)."""
    image = story.get("image")
    return not (isinstance(image, dict) and image.get("src")) or is_cover(image)


def cover_image(entry) -> dict:
    return {"src": entry["src"], "tall": entry["tall"], "via": "cover", "kind": "cover"}


def attach_covers(stories, covers, site_root) -> dict:
    """Put each rendered cover on its story; never touch a story whose picture is a photo or an AI illustration."""
    counts = {"attached": 0, "dropped": 0}
    for story in stories:
        if not isinstance(story, dict) or not needs_cover(story):
            continue
        entry = covers.get(story.get("id"))
        if entry and all((Path(site_root) / entry[k]).is_file() for k in ("src", "tall")):
            story["image"] = cover_image(entry)
            counts["attached"] += 1
        elif is_cover(story.get("image")):
            # A cover that could not be drawn again this run is not left pointing at a file that may be gone.
            story.pop("image", None)
            counts["dropped"] += 1
    return counts


def prune_covers(cover_dir, keep_ids) -> int:
    """Remove superseded covers: every file of a story no longer kept, and older versions of a kept story's cover."""
    cover_dir = Path(cover_dir)
    if not cover_dir.is_dir():
        return 0
    removed = 0
    for path in cover_dir.glob("*.png"):
        match = COVER_SRC.fullmatch(f"assets/cover/{path.name}")
        if match and path.name not in keep_ids.get(match.group(1), set()):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def render(stories, sources, cover_dir, node=None, timeout=RENDER_TIMEOUT):
    """Ask the renderer for the cover of each story; returns its result, or None when it cannot run."""
    node = node or shutil.which("node")
    if not node or not RENDERER.is_file():
        print("Covers: skipped (Node not found)")
        return None
    with tempfile.TemporaryDirectory(prefix="radar-covers-") as tmp:
        request, result = Path(tmp) / "request.json", Path(tmp) / "result.json"
        request.write_text(json.dumps({"stories": stories, "sources": sources, "out_dir": str(cover_dir)},
                                      ensure_ascii=False), encoding="utf-8")
        try:
            proc = subprocess.run([node, str(RENDERER), str(request), str(result)], cwd=ROOT, timeout=timeout,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"Covers: renderer did not finish ({error.__class__.__name__})")
            return None
        if proc.returncode != 0 or not result.is_file():
            print(f"Covers: renderer failed (exit {proc.returncode}): {proc.stderr.strip()[-400:]}")
            return None
        print(proc.stdout.strip())
        return json.loads(result.read_text(encoding="utf-8"))


def apply_covers(payload, site_root, node=None, history=()) -> dict:
    """history: stories of the published snapshot, whose permanent pages may still show their cover."""
    stories = [s for s in payload.get("stories", []) if isinstance(s, dict)]
    wanted = [s for s in stories if needs_cover(s)]
    cover_dir = Path(site_root) / "assets" / "cover"
    result = render(wanted, payload.get("sources", []), cover_dir, node=node) if wanted else {"covers": {}}
    covers = (result or {}).get("covers", {})
    counts = attach_covers(stories, covers, site_root)
    if result is not None and stories:   # an empty snapshot is a broken input, never a reason to delete covers
        keep = {}
        for story in [*stories, *(s for s in history if isinstance(s, dict))]:
            if is_cover(story.get("image")) and story.get("id"):
                keep.setdefault(story["id"], set()).update(Path(story["image"][k]).name for k in ("src", "tall"))
        counts["pruned"] = prune_covers(cover_dir, keep)
        counts["failed"] = len((result or {}).get("failed", {}))
    counts["wanted"] = len(wanted)
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="site/data/radar.json")
    parser.add_argument("--site-root", default=str(ROOT / "site"))
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"Covers: cannot read {args.input}: {error}", file=sys.stderr)
        return 1
    published = os.environ.get("RADAR_PUBLISHED_SNAPSHOT")
    try:
        history = json.loads(Path(published).read_text(encoding="utf-8")).get("stories", []) if published else []
    except (OSError, ValueError, AttributeError):
        history = []
    counts = apply_covers(payload, args.site_root, history=history)
    print("Covers: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    write_site_snapshot(payload, args.input)
    if published and Path(published).is_file():
        try:
            write_atomic(complete_published_snapshot(payload, Path(published)), published)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
