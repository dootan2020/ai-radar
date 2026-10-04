"""Live hosted-runner probe; exit nonzero when requested evidence is absent."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from threading import Lock
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar import youtube
from radar.transport import Fetcher, read_url


def verify(items, sources, require_fallback=False):
    """Require verified channels and, optionally, a returned degraded-watch item."""
    expected = {channel[0] for channel in youtube.CHANNELS}
    if {source["id"] for source in sources} != expected or any(not source["ok"] for source in sources):
        raise ValueError("Not all configured channel Live tabs were readable and identity-verified")
    fallbacks = [item for item in items if item.get("status_source") == "channel_streams"]
    diagnostics = [line for source in sources for line in source.get("diagnostics", [])]
    observed = [item for item in fallbacks
                if any(line.startswith(f"watch {item['video_id']}: ") for line in diagnostics)]
    if require_fallback and not observed:
        raise ValueError("No returned stream used fallback after an actual watch failure; fallback is unproven on this runner")
    return fallbacks, observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-fallback", action="store_true",
                        help="Require a returned stream whose watch request actually failed")
    parser.add_argument("--capture-blocked", type=Path,
                        help="Save an actual metadata-free LOGIN_REQUIRED bot-check status/reason")
    args = parser.parse_args()
    captured, lock = [], Lock()

    def transport(url, source_id=None, **kwargs):
        body = read_url(url, source_id=source_id)
        if args.capture_blocked and "/watch?" in url:
            try:
                player = youtube._embedded(body, "ytInitialPlayerResponse")
                status = player.get("playabilityStatus", {})
                if (status.get("status") == "LOGIN_REQUIRED"
                        and "bot" in str(status.get("reason", "")).lower()
                        and not any(key in player for key in ("videoDetails", "microformat"))):
                    minimal = {"playabilityStatus": {key: status[key] for key in ("status", "reason") if key in status}}
                    with lock:
                        if not captured:
                            captured.append((url, minimal, datetime.now(timezone.utc).isoformat()))
            except ValueError:
                pass
        return body

    now = datetime.now(timezone.utc)
    items, sources = youtube.collect(Fetcher(time.monotonic() + 100, transport), now)
    report = {"checked_at": now.isoformat(), "sources": sources, "streams": items}
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if args.capture_blocked:
        if captured:
            args.capture_blocked.parent.mkdir(parents=True, exist_ok=True)
            player_json = json.dumps(captured[0][1], sort_keys=True)
            provenance = {"source_url": captured[0][0], "captured_at": captured[0][2],
                          "extraction": "Observed bot-check response had no videoDetails or microformat; retained playabilityStatus status/reason only",
                          "extracted_player_sha256": hashlib.sha256(player_json.encode("utf-8")).hexdigest()}
            body = "<!-- " + json.dumps(provenance) + " -->\n"
            body += "<script>var ytInitialPlayerResponse = " + player_json + ";</script>\n"
            args.capture_blocked.write_bytes(body.encode("utf-8"))
            if args.capture_blocked.read_text(encoding="utf-8") != body:
                raise OSError("Blocked fixture read-back differs")
            print(f"Captured actual LOGIN_REQUIRED from {captured[0][0]} at {captured[0][2]} to {args.capture_blocked}")
        else:
            print("No actual metadata-free LOGIN_REQUIRED bot check observed; no blocked fixture written")
    try:
        fallbacks, observed = verify(items, sources, args.require_fallback)
    except ValueError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(sources)} verified channels; {len(items)} streams; "
          f"{len(fallbacks)} channel fallbacks, {len(observed)} after actual watch failure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
