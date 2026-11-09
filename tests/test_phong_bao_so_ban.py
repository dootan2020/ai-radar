"""Read-only ledger replay against trimmed real newsroom cycles."""

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from phong_bao.so_ban import _checker_label, collect, report, run


FIXTURE = Path(__file__).parent / "fixtures" / "so-ban"
# A fixed clock in the 00:00-02:00 gap, where the window once collapsed to the month's first slot.
NOW = datetime.fromisoformat("2026-11-10T00:17:00+07:00")


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
        checker = [row for row in ledger if row["type"] == "story" and row["desk"] == "checker"]
        self.assertEqual(Counter(row["check_status"] for row in checker), {"not_checked": 4, "checked": 2})
        old = [row for row in checker if row["cycle"] == "20261108T230008Z"]
        self.assertEqual({row["skip_reason"] for row in old}, {"editor_hold", "paywall"})
        self.assertTrue(all(row["reason"] == "checker_not_checked" and row["invalid_response"] is False
                            for row in old))

    def test_cli_artifacts_are_deterministic_and_month_scoped(self):
        with TemporaryDirectory() as temporary:
            out = Path(temporary)
            path = run(FIXTURE, out, month="2026-11", now=NOW)
            first = (out / "so-ban.jsonl").read_bytes(), path.read_bytes()
            text = path.read_text(encoding="utf-8")
            self.assertIn("20261109T030010Z", text)
            self.assertIn("từ 2026-11-01T02:00:00+07:00 đến 2026-11-09T22:00:00+07:00.", text)
            self.assertIn("Kỳ vọng: 54; có cycle: 3; đúng khung: 3", text)
            self.assertIn("Publish: 0/2", text)
            self.assertIn("Chưa gửi kiểm: 2", text)
            self.assertIn("lỗi kiểm chứng: 0", text)
            self.assertTrue((out / "so-ban-domains.csv").is_file())
            self.assertEqual(first, ((out / "so-ban.jsonl").read_bytes(), run(FIXTURE, out, month="2026-11", now=NOW).read_bytes()))
            self.assertEqual(len((out / "so-ban.jsonl").read_text(encoding="utf-8").splitlines()), 46)

    def test_window_tracks_the_clock_on_any_day_of_the_month(self):
        _, cycles, problems = collect(FIXTURE)
        cases = {
            # Before the day's first slot the window ends at the previous day's 22:00.
            "2026-11-10T00:17:00+07:00": ("2026-11-09T22:00:00+07:00", 54),
            "2026-11-10T02:00:00+07:00": ("2026-11-09T22:00:00+07:00", 54),
            "2026-11-10T02:00:01+07:00": ("2026-11-10T02:00:00+07:00", 55),
            "2026-11-10T10:30:00+07:00": ("2026-11-10T10:00:00+07:00", 57),
            "2026-11-30T01:00:00+07:00": ("2026-11-29T22:00:00+07:00", 174),
            "2026-11-30T23:59:00+07:00": ("2026-11-30T22:00:00+07:00", 180),
            # A finished month is capped at its last slot.
            "2026-12-05T09:00:00+07:00": ("2026-11-30T22:00:00+07:00", 180),
        }
        for stamp, (last, expected) in cases.items():
            with self.subTest(now=stamp):
                text = report("2026-11", cycles, Counter(problems), now=datetime.fromisoformat(stamp))
                self.assertIn(f"từ 2026-11-01T02:00:00+07:00 đến {last}.", text)
                self.assertIn(f"Kỳ vọng: {expected}; có cycle: 3; đúng khung: 3;", text)
                missing = next(line for line in text.splitlines() if line.startswith("Khung vắng: "))
                self.assertEqual(missing.count("+07:00"), expected - 3)
                for slot in ("2026-11-01T06:00:00", "2026-11-09T06:00:00", "2026-11-09T10:00:00"):
                    self.assertNotIn(slot, missing)

    def test_old_sent_cycle_reply_failures_keep_distinct_labels(self):
        job = FIXTURE / "20261109T030010Z" / "job"
        editor = json.loads((job / "editor.json").read_text(encoding="utf-8"))
        reporter = json.loads((job / "reporter.json").read_text(encoding="utf-8"))
        sid = "af3b84067d2d1e42cef4"
        failed = {"id": sid, "reason": "checker_invalid", "invalid_response": True}
        self.assertEqual(_checker_label(failed, editor[sid], reporter[sid], set(), {}),
                         ("checker_failure", "no_reply"))
        self.assertEqual(_checker_label(failed, editor[sid], reporter[sid], {sid}, {}),
                         ("checker_failure", "invalid_reply"))

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
            text = run(FIXTURE, out, month="2026-11", labels=labels, now=NOW).read_text(encoding="utf-8")
            self.assertIn('"targets_met": true', text)
            self.assertFalse((out / "quyet-dinh-evaluate.json").exists())

    def test_invalid_json_is_reported(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary) / "cycles" / "20261109T030010Z"
            folder.mkdir(parents=True)
            (folder / "status.json").write_bytes(b"{")
            text = run(folder.parent, Path(temporary) / "out", now=NOW).read_text(encoding="utf-8")
            self.assertIn("không đọc được JSON", text)
            self.assertIn("thiếu desks", text)


if __name__ == "__main__":
    unittest.main()
