"""Read-only by default; --report reconciles the workflow's health issue."""

import argparse
import json
import os
import sys
from time import sleep

from radar.failure_alert import AlertError, GitHub
from radar.health_alert import reconcile_report
from radar.health_probe import probe

CONFIRM_DELAY = 30


def collect_report():
    first = probe()
    initial = {row["id"] for row in first["checks"] if not row["ok"]}
    latest = first
    if initial:
        sleep(CONFIRM_DELAY)
        latest = probe()
    failures = [row for row in latest["checks"] if not row["ok"]]
    confirmed = [row for row in failures if row["id"] in initial]
    status = "healthy" if not failures else "failed" if confirmed else "inconclusive"
    return {**latest, "status": status, "confirmed_failures": confirmed}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="Reconcile GitHub health issue using built-in workflow token")
    options = parser.parse_args(argv)
    try:
        report = collect_report()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if options.report and report["status"] != "inconclusive":
            repository = os.environ["GITHUB_REPOSITORY"]
            api = GitHub(repository, os.environ.get("GITHUB_TOKEN", ""))
            result = reconcile_report(report, api, repository, os.environ["GITHUB_RUN_ID"],
                                      os.environ["GITHUB_RUN_ATTEMPT"], os.environ["GITHUB_REPOSITORY_OWNER"])
            print(f"Health incident {result}.")
        return 0 if report["status"] == "healthy" else 1
    except AlertError as error:
        print(f"Health monitor failed: {error}", file=sys.stderr)
    except (KeyError, TypeError, ValueError, OSError):
        print("Health monitor failed: invalid report or missing workflow environment.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
