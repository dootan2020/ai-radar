"""Schedule checks that need no Blender: python -m unittest wallpaper/test_daily.py"""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily  # noqa: E402

SPAN = [daily.EPOCH + dt.timedelta(days=k) for k in range(60)]


class ScheduleTest(unittest.TestCase):
    def test_seven_families(self):
        self.assertEqual(len(daily.FAMILIES), 7)

    def test_no_family_twice_in_any_window(self):
        window = len(daily.FAMILIES)
        families = [daily.schedule(day)[0] for day in SPAN]
        for k in range(len(families) - window + 1):
            chunk = families[k:k + window]
            self.assertEqual(len(set(chunk)), window, f'repeat near {SPAN[k]}: {chunk}')

    def test_every_family_appears_in_the_span(self):
        self.assertEqual({daily.schedule(day)[0] for day in SPAN}, set(daily.FAMILIES))

    def test_dates_before_the_epoch_are_refused(self):
        with self.assertRaises(ValueError):
            daily.schedule(daily.EPOCH - dt.timedelta(days=1))

    def test_same_date_gives_same_parameters(self):
        for day in SPAN[:7]:
            self.assertEqual(daily.params_for(day), daily.params_for(day))

    def test_a_returning_family_changes_composition(self):
        appearances = {}
        for day in SPAN:
            p = daily.params_for(day)
            appearances.setdefault(p['family'], []).append(p)
        for family, runs in appearances.items():
            self.assertGreaterEqual(len(runs), 8, family)
            for before, after in zip(runs, runs[1:]):
                self.assertNotEqual(before['side'], after['side'], family)
                self.assertNotEqual(before['palette']['name'], after['palette']['name'], family)
                self.assertNotEqual(before['seed'], after['seed'], family)

    def test_silicon_die_layout_changes_on_return(self):
        runs = [daily.params_for(day) for day in SPAN if daily.schedule(day)[0] == 'silicon-die']
        for before, after in zip(runs, runs[1:]):
            layout = ('layout_angle', 'cross', 'macro_scale')
            self.assertNotEqual([before[k] for k in layout], [after[k] for k in layout])

    def test_polytope_shape_changes_on_return(self):
        runs = [daily.params_for(day) for day in SPAN if daily.schedule(day)[0] == 'projected-polytope']
        for before, after in zip(runs, runs[1:]):
            self.assertNotEqual(before['polytope'], after['polytope'])


if __name__ == '__main__':
    unittest.main()
