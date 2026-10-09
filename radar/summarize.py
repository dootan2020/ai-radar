"""CLI entry point for story summarization into Vietnamese key points.

Run: python -m radar.summarize --input site/data/radar.json --cache data/summaries-gemini-vi.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

from radar.pipeline import write_atomic
from radar.site_payload import page_path, write_site_snapshot
from radar import summary_gemini as gemini
from radar import summary_pipeline


DEFAULT_BUDGET = 180.0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="site/data/radar.json")
    parser.add_argument("--output", help="defaults to --input")
    parser.add_argument("--cache", default="data/summaries-gemini-vi.json")
    parser.add_argument("--ledger", help="defaults to summary-gemini-ledger.json beside --cache")
    parser.add_argument("--article-failures", help="defaults to article-read-failures.json beside --cache")
    parser.add_argument("--script-path", default="site/data/video-script.json",
                        help="defaults to site/data/video-script.json")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET)
    args = parser.parse_args(argv)

    if args.budget <= 0:
        parser.error("--budget must be positive")

    ledger_path = args.ledger or str(Path(args.cache).with_name("summary-gemini-ledger.json"))
    article_failures_path = args.article_failures or str(Path(args.cache).with_name("article-read-failures.json"))
    companion = page_path(args.output or args.input).resolve()
    if companion in {Path(p).resolve() for p in (args.input, args.cache, ledger_path, article_failures_path)}:
        parser.error("page projection must differ from input, summary cache, ledger and article failure cache")

    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except Exception as error:
        print(f"Error reading input {args.input}: {error}", file=sys.stderr)
        return 1

    cache = gemini.load_cache(args.cache)
    before_cache = dict(cache)
    try:
        stored_failures = json.loads(Path(article_failures_path).read_text(encoding="utf-8"))
        if not isinstance(stored_failures, dict):
            stored_failures = {}
        article_failures = {
            key: {"reason": value["reason"], "time": value["time"]}
            for key, value in stored_failures.items()
            if isinstance(key, str)
            and re.fullmatch(r"[0-9a-f]{64}", key)
            and isinstance(value, dict)
            and set(value) == {"reason", "time"}
            and value.get("reason") in {"robots", "redirect", "non_html", "too_short", "paywall", "error"}
            and isinstance(value.get("time"), (int, float))
        }
    except (OSError, ValueError):
        article_failures = {}
    before_article_failures = dict(article_failures)
    try:
        ledger_before = Path(ledger_path).read_bytes()
    except OSError:
        ledger_before = None

    try:
        stats, alive = summary_pipeline.summarize_payload(
            payload,
            cache,
            article_failures=article_failures,
            ledger_path=ledger_path,
            script_path=args.script_path,
            budget=args.budget,
        )
    except Exception as error:
        stats = {
            "model": gemini.MODEL_ID,
            "status": "failed",
            "error": "summary_failed",
            "error_detail": type(error).__name__,
            "machine_written": True,
        }
        payload["summary"] = stats
        alive = False

    cache_written = cache != before_cache
    if cache_written:
        try:
            gemini.save_cache(args.cache, cache)
        except Exception:
            cache_written = False
            stats.setdefault("persistence_errors", []).append("summary_cache_write_failed")

    article_failures_written = article_failures != before_article_failures
    if article_failures_written:
        try:
            write_atomic(article_failures, article_failures_path)
        except Exception:
            article_failures_written = False
            stats.setdefault("persistence_errors", []).append("article_failure_cache_write_failed")

    try:
        ledger_written = Path(ledger_path).read_bytes() != ledger_before
    except OSError:
        ledger_written = False

    if os.environ.get("GITHUB_OUTPUT"):
        try:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"summary_cache_written={str(cache_written).lower()}\n"
                             f"summary_ledger_written={str(ledger_written).lower()}\n"
                             f"article_failures_written={str(article_failures_written).lower()}\n")
        except OSError:
            stats.setdefault("persistence_errors", []).append("workflow_output_write_failed")

    write_site_snapshot(payload, args.output or args.input)

    published_arg = os.environ.get("RADAR_PUBLISHED_SNAPSHOT")
    if published_arg:
        published_path = Path(published_arg)
        if published_path.is_file():
            try:
                write_atomic(payload, published_path)
            except Exception:
                pass

    print(f"Summary {stats['status']}: {stats.get('summarized', 0)}/{stats.get('stories', 0)} stories summarized, "
          f"{stats.get('requests', 0)} requests, "
          f"{stats.get('cache_hits', 0)} cache hits, {stats.get('pending', 0)} pending, "
          f"{stats.get('tokens', 0)} tokens"
          + (f" -- error: {stats['error']}" if stats.get("error") else ""))
    sys.stdout.flush()

    if alive:
        os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
