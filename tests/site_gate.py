"""Open the newsroom's scoring gate for tests of what the site build does with the stories it is given.

The gate (radar.newsroom_decisions.apply_decisions, applied by radar.site_payload.write_site_snapshot) hides every
story without a passing scoring-desk verdict, and every story when there is no decisions file;
tests/test_newsroom_decisions.py covers it. Modules that test translation, summaries, publication or search on their
own fixture stories import these as setUpModule and tearDownModule, so the build keeps their stories.
"""

from unittest.mock import patch

_OPEN = patch("radar.site_payload.apply_decisions", side_effect=lambda payload, decisions: payload)


def open_gate():
    _OPEN.start()


def close_gate():
    _OPEN.stop()
