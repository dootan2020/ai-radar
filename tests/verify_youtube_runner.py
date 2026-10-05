"""Live hosted-runner probe for YouTube Data API v3; exit nonzero when channels fail."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar import youtube
from radar.transport import Fetcher, read_url


def verify(items, sources):
    """Require configured channels to succeed without errors."""
    expected = {channel[0] for channel in youtube.CHANNELS}
    if {source["id"] for source in sources} != expected or any(not source["ok"] for source in sources):
        raise ValueError("Not all configured channels were readable via YouTube Data API v3")
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    items, sources = youtube.collect(Fetcher(time.monotonic() + 100, read_url), now)
    report = {"checked_at": now.isoformat(), "sources": sources, "streams": items}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    try:
        verify(items, sources)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(sources)} verified channels; {len(items)} videos/streams")
    return 0


if __name__ == "__main__":
    sys.exit(main())
