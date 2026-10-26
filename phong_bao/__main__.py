"""Manual newsroom command line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .discovery import discover_raw, report
from .evaluation import evaluate
from .newsroom import DEFAULT_DESK_BUDGET_SECONDS, DESKS, FixtureArticles, run
from .registry import load_registry
from .runner import CLIRunner, FixtureRunner
from .cycle import cycle


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
    newsroom.add_argument("--from", dest="rerun_from", choices=DESKS)
    newsroom.add_argument("--discovery-fixture")
    newsroom.add_argument("--runner-fixture")
    newsroom.add_argument("--articles-fixture")
    scoring = sub.add_parser("evaluate")
    cycle_parser = sub.add_parser("cycle")
    cycle_parser.add_argument("--snapshot-url")
    scoring.add_argument("--decisions", required=True)
    scoring.add_argument("--labels", required=True)
    args = parser.parse_args(argv)
    if args.command == "cycle":
        options = {"snapshot_url": args.snapshot_url} if args.snapshot_url else {}
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
                 desk_budget_seconds=args.desk_budget_seconds)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
