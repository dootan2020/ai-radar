"""Manual newsroom command line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .discovery import discover_raw, report
from .evaluation import evaluate
from .newsroom import DESKS, FixtureArticles, run
from .registry import load_registry
from .runner import CLIRunner, FixtureRunner


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local newsroom phase 0")
    sub = parser.add_subparsers(dest="command", required=True)
    discovery = sub.add_parser("discover")
    discovery.add_argument("--fixture")
    discovery.add_argument("--output")
    newsroom = sub.add_parser("run")
    newsroom.add_argument("--input", required=True)
    newsroom.add_argument("--corpus")
    newsroom.add_argument("--job", required=True)
    newsroom.add_argument("--through", choices=DESKS, default="chief")
    newsroom.add_argument("--discovery-fixture")
    newsroom.add_argument("--runner-fixture")
    newsroom.add_argument("--articles-fixture")
    scoring = sub.add_parser("evaluate")
    scoring.add_argument("--decisions", required=True)
    scoring.add_argument("--labels", required=True)
    args = parser.parse_args(argv)
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
                 corpus_path=args.corpus)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
