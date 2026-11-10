"""Schedule checks that need no Blender: python -m unittest wallpaper/test_daily.py"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily  # noqa: E402


class ScheduleTest(unittest.TestCase):
    days = [daily.EPOCH + dt.timedelta(days=k) for k in range(0, 1200)]

    def test_no_family_repeats_inside_its_window(self):
        window = len(daily.FAMILIES) // 2 + 1
        families = [daily.schedule(day)[0] for day in self.days]
        for k in range(len(families) - window + 1):
            chunk = families[k:k + window]
            self.assertEqual(len(set(chunk)), window, f'repeat near {self.days[k]}: {chunk}')

    def test_each_family_once_per_cycle(self):
        n = len(daily.FAMILIES)
        families = [daily.schedule(day)[0] for day in self.days]
        for start in range(0, len(families) - n + 1, n):
            self.assertEqual(sorted(families[start:start + n]), sorted(daily.FAMILIES))

    def test_dates_before_the_epoch_are_refused(self):
        with self.assertRaises(ValueError):
            daily.schedule(daily.EPOCH - dt.timedelta(days=1))

    def test_same_date_gives_same_parameters(self):
        day = dt.date(2026, 11, 20)
        self.assertEqual(daily.params_for(day), daily.params_for(day))

    def test_a_returning_family_changes_composition(self):
        appearances = {}
        for day in self.days[30:60]:
            p = daily.params_for(day)
            appearances.setdefault(p['family'], []).append(p)
        for family, runs in appearances.items():
            for before, after in zip(runs, runs[1:]):
                self.assertNotEqual(before['side'], after['side'], family)
                self.assertNotEqual(before['palette']['name'], after['palette']['name'], family)
                self.assertNotEqual(before['seed'], after['seed'], family)

    def test_every_family_is_used(self):
        used = {daily.schedule(day)[0] for day in self.days[30:60]}
        self.assertEqual(used, set(daily.FAMILIES))


if __name__ == '__main__':
    unittest.main()
