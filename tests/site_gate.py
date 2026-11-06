"""Open the newsroom's scoring gate for tests of what the site build does with the stories it is given.

The gate hides every story without a passing scoring-desk verdict, and every story when there is no decisions file:
radar.newsroom_decisions.apply_decisions in the site snapshot (radar.site_payload.write_site_snapshot) and
radar.story_pages.gated_stories for the per-story pages. tests/test_newsroom_decisions.py covers both. Modules that
test translation, summaries, publication, search or page rendering on their own fixture stories import these as
setUpModule and tearDownModule, so the build keeps their stories.
"""

from unittest.mock import patch

_OPEN = (patch("radar.site_payload.apply_decisions", side_effect=lambda payload, decisions: payload),
         patch("radar.story_pages.gated_stories", side_effect=lambda stories, decisions: stories))


def open_gate():
    for patcher in _OPEN:
        patcher.start()


def close_gate():
    for patcher in _OPEN:
        patcher.stop()
