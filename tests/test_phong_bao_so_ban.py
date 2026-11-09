"""Read-only ledger replay against trimmed real newsroom cycles."""

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phong_bao.so_ban import collect, report, run


FIXTURE = Path(__file__).parent / "fixtures" / "so-ban"


class DeskLedgerTests(unittest.TestCase):
    def test_trimmed_history_counts_and_interruption(self):
        ledger, cycles, problems = collect(FIXTURE)
        self.assertEqual(len(cycles), 4)
        self.assertEqual(Counter(c["state"] for c in cycles), {"decided": 2, "running": 1, "no_new_stories": 1})
        self.assertEqual(len(ledger), 46)
        self.assertEqual(Counter((r["desk"], r["verdict"]) for r in ledger if r["type"] == "story"), {
            ("intake", "pass"): 6, ("reporter", "pass"): 3, ("reporter", "fail"): 3,
            ("editor", "pass"): 4, ("editor", "fail"): 2,
            ("checker", "pass"): 1, ("checker", "fail"): 5,
            ("writer", "fail"): 2, ("chief", "publish"): 1, ("chief", "hold"): 3,
        })
        self.assertEqual(sum(problems.values()), 5)

    def test_cli_artifacts_are_deterministic_and_month_scoped(self):
        with TemporaryDirectory() as temporary:
            out = Path(temporary)
            path = run(FIXTURE, out, month="2026-11")
            first = (out / "so-ban.jsonl").read_bytes(), path.read_bytes()
            text = path.read_text(encoding="utf-8")
            self.assertIn("20261109T030010Z", text)
            self.assertIn("từ 2026-11-01T02:00:00+07:00", text)
            self.assertIn("có cycle: 3; đúng khung: 3", text)
            self.assertIn("Publish: 0/2", text)
            self.assertTrue((out / "so-ban-domains.csv").is_file())
            self.assertEqual(first, ((out / "so-ban.jsonl").read_bytes(), run(FIXTURE, out, month="2026-11").read_bytes()))
            self.assertEqual(len((out / "so-ban.jsonl").read_text(encoding="utf-8").splitlines()), 46)

    def test_report_limits_domain_table_and_sums_remainder(self):
        start = datetime.fromisoformat("2026-11-01T02:00:00+07:00")
        stories = [{"desk": "chief", "verdict": "hold", "source_url": f"https://domain-{n}.example/news", "tier_capped": False,
                    "reason": "held", "degradation_reasons": None} for n in range(18)]
        cycle = {"start": start, "stories": stories, "desks": {}, "decisions": [], "writer_retry": None,
                 "id": "20261031T190000Z", "state": "decided"}
        text = report("2026-11", [cycle], Counter(), now=datetime.fromisoformat("2026-11-01T03:00:00+07:00"))
        table = text.split("| Domain | Publish | Hold |", 1)[1].split("## Writer", 1)[0]
        rows = [line for line in table.splitlines() if line.startswith("|") and "---" not in line]
        self.assertEqual(len(rows), 16)
        self.assertIn("Các domain còn lại (3) | 0 | 3", rows[-1])

    def test_labels_use_existing_evaluation(self):
        with TemporaryDirectory() as temporary:
            out = Path(temporary)
            decision = next(row for cycle in collect(FIXTURE)[1] for row in cycle["decisions"]
                            if row.get("decision") == "publish")
            labels = out / "labels.json"
            labels.write_bytes(json.dumps({"stories": [{"id": decision["id"], "labels": {"junk": False}}]}).encode("utf-8"))
            text = run(FIXTURE, out, month="2026-11", labels=labels).read_text(encoding="utf-8")
            self.assertIn('"targets_met": true', text)
            self.assertFalse((out / "quyet-dinh-evaluate.json").exists())

    def test_invalid_json_is_reported(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary) / "cycles" / "20261109T030010Z"
            folder.mkdir(parents=True)
            (folder / "status.json").write_bytes(b"{")
            text = run(folder.parent, Path(temporary) / "out").read_text(encoding="utf-8")
            self.assertIn("không đọc được JSON", text)
            self.assertIn("thiếu desks", text)


if __name__ == "__main__":
    unittest.main()
