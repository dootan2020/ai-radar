"""List, or rewrite into a new file, published decisions that the paywall rule now holds.

The rule (phong_bao/paywall.py, captain 2026-11-05): a story whose own article sits behind a
subscription or login, and for which the reporter found no readable alternative, is held. In a
decisions file that is a "publish" row whose degradation_reasons include "no readable same-event
source" (its source_url is then the story's own URL) and whose source_url belongs to a publisher
measured as paywalled. The fetch result "paywall" is not stored in decisions files, so this script
only applies the measured publisher list.

Dry run (default) prints the rows; --apply OUT writes a copy with those rows held. It never writes
the input file.

usage: python scripts/hold-paywalled-decisions.py DECISIONS [--stories SNAPSHOT] [--apply OUT]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phong_bao.contracts import validate_chief_output  # noqa: E402
from phong_bao.paywall import HOLD_REASON, paywalled_publisher  # noqa: E402

NO_SOURCE = "no readable same-event source"


def affected(rows):
    return [row for row in rows if row.get("decision") == "publish"
            and NO_SOURCE in (row.get("degradation_reasons") or [])
            and paywalled_publisher(row.get("source_url")) is not None]


def held(row):
    changed = {key: value for key, value in row.items()
               if key not in {"written_by", "editorial_headline_vi", "summary_sources", "summary_limitations",
                              "key_points_prompt_version"}}
    changed.update(decision="hold", round="chief", reason=HOLD_REASON, summary="none",
                   degradation_reasons=[], key_points=[])
    validate_chief_output(changed)
    return changed


def title_of(row, titles):
    if row["id"] in titles:
        return titles[row["id"]]
    slug = urlsplit(row.get("source_url") or "").path.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").capitalize() + " (from URL)"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("decisions", type=Path)
    parser.add_argument("--stories", type=Path, help="snapshot with story titles (optional)")
    parser.add_argument("--apply", type=Path, metavar="OUT", help="write a copy with the rows held")
    args = parser.parse_args(argv)
    data = json.loads(args.decisions.read_text(encoding="utf-8"))
    titles = {}
    if args.stories:
        snapshot = json.loads(args.stories.read_text(encoding="utf-8"))
        titles = {story["id"]: story.get("title") or "" for story in snapshot.get("stories", [])}
    rows = affected(data["decisions"])
    for row in rows:
        host = (urlsplit(row["source_url"]).hostname or "").removeprefix("www.")
        print(f"{row['id']}\t{host}\t{title_of(row, titles)}")
    print(f"{len(rows)} of {sum(r.get('decision') == 'publish' for r in data['decisions'])} publish rows would be held")
    if args.apply:
        if args.apply.resolve() == args.decisions.resolve():
            parser.error("--apply must name a new file, never the input")
        ids = {row["id"] for row in rows}
        data = {**data, "decisions": [held(row) if row["id"] in ids else row for row in data["decisions"]]}
        args.apply.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.apply}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
