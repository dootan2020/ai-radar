"""Manual newsroom command line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .discovery import discover_raw, report
from .evaluation import evaluate
from .newsroom import (DEFAULT_CALL_TIMEOUT_SECONDS, DEFAULT_DESK_BUDGET_SECONDS, DEFAULT_RUN_BUDGET_SECONDS,
                       DEFAULT_WRITER_BUDGET_SECONDS, DESKS, FixtureArticles, run)
from .registry import load_registry
from .runner import CLIRunner, FixtureRunner
from .cycle import cycle
from .bu_cham import bu_cham
from .so_ban import run as run_so_ban


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local newsroom")
    sub = parser.add_subparsers(dest="command", required=True)
    discovery = sub.add_parser("discover")
    discovery.add_argument("--fixture")
    discovery.add_argument("--output")
    newsroom = sub.add_parser("run")
    newsroom.add_argument("--input", required=True)
    newsroom.add_argument("--corpus")
    newsroom.add_argument("--job", required=True)
    newsroom.add_argument("--through", choices=DESKS, default="chief")
    newsroom.add_argument("--desk-budget-seconds", type=float, default=DEFAULT_DESK_BUDGET_SECONDS)
    newsroom.add_argument("--writer-budget-seconds", type=float, default=DEFAULT_WRITER_BUDGET_SECONDS)
    newsroom.add_argument("--run-budget-seconds", type=float, default=DEFAULT_RUN_BUDGET_SECONDS)
    newsroom.add_argument("--call-timeout-seconds", type=float, default=DEFAULT_CALL_TIMEOUT_SECONDS)
    newsroom.add_argument("--from", dest="rerun_from", choices=DESKS)
    newsroom.add_argument("--discovery-fixture")
    newsroom.add_argument("--runner-fixture")
    newsroom.add_argument("--articles-fixture")
    scoring = sub.add_parser("evaluate")
    ledger = sub.add_parser("so-ban")
    ledger.add_argument("--cycles", required=True)
    ledger.add_argument("--out", required=True)
    ledger.add_argument("--month")
    ledger.add_argument("--labels")
    cycle_parser = sub.add_parser("cycle")
    cycle_parser.add_argument("--snapshot-url")
    cycle_parser.add_argument("--since-hours", type=float, default=36)
    backfill = sub.add_parser("bu-cham")
    backfill.add_argument("--decisions", required=True)
    backfill.add_argument("--cycles", required=True)
    backfill.add_argument("--since")
    backfill.add_argument("--modes", default="score,write")
    backfill.add_argument("--limit", type=int)
    backfill.add_argument("--run", action="store_true")
    scoring.add_argument("--decisions", required=True)
    scoring.add_argument("--labels", required=True)
    args = parser.parse_args(argv)
    if args.command == "bu-cham":
        modes = tuple(part.strip() for part in args.modes.split(","))
        if not modes or len(set(modes)) != len(modes) or set(modes) - {"score", "write"}:
            parser.error("--modes must be score,write or one of those modes")
        try:
            result = bu_cham(args.decisions, args.cycles, since=args.since, modes=modes,
                             limit=args.limit, execute=args.run)
        except ValueError as error:
            parser.error(str(error))
        print("Mode             Count")
        for mode in ("score", "write"):
            print(f"{mode:<16} {result['candidates'].get(mode, 0)}")
        print(f"Selected         {result['selected']}")
        print(f"Newest           {result['newest'] or '-'}")
        print(f"Oldest           {result['oldest'] or '-'}")
        print("Excluded")
        for reason, count in result["excluded"].items():
            print(f"  {reason:<30} {count}")
        if args.run:
            print(json.dumps(result["results"], ensure_ascii=False, indent=2))
        return 0
    if args.command == "so-ban":
        print(run_so_ban(args.cycles, args.out, month=args.month, labels=args.labels))
        return 0
    if args.command == "cycle":
        options = {"since_hours": args.since_hours}
        if args.snapshot_url:
            options["snapshot_url"] = args.snapshot_url
        print(json.dumps(cycle(**options), ensure_ascii=False, indent=2))
        return 0
    if args.command == "evaluate":
        value = evaluate(args.decisions, args.labels)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value["targets_met"] else 1
    tools = load_registry()
    raw = discover_raw(fixture=_json(args.fixture) if args.command == "discover" and args.fixture else
                       _json(args.discovery_fixture) if args.command == "run" and args.discovery_fixture else None)
    found = report(raw, tools)
    if args.command == "discover":
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes((json.dumps(found, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        print(json.dumps(found, ensure_ascii=False, indent=2))
        return 0
    runner = FixtureRunner(_json(args.runner_fixture)) if args.runner_fixture else CLIRunner()
    articles = FixtureArticles(_json(args.articles_fixture)) if args.articles_fixture else None
    status = run(args.input, args.job, tools, raw, runner, through=args.through, articles=articles,
                 corpus_path=args.corpus, rerun_from=args.rerun_from,
                 desk_budget_seconds=args.desk_budget_seconds, writer_budget_seconds=args.writer_budget_seconds,
                 run_budget_seconds=args.run_budget_seconds, call_timeout_seconds=args.call_timeout_seconds)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
