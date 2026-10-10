"""Editorially retired sources: still listed as disabled, never shown to readers.

Deleting a catalog row while 7-day retention still holds its observations makes
publication reject every snapshot ("invalid observation source"). Retirement
therefore disables the row and withdraws its coverage from reader output.
"""

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from radar import catalog, feeds, huggingface, pipeline, youtube
from radar.clustering import cluster_items
from radar.publication import prepare_publication
from radar.site_payload import write_site_snapshot
from radar.story_pages import reader_story, render_site

if __package__:
    from .test_v2_support import NOW, coverage
else:
    from test_v2_support import NOW, coverage

RETIRED_IDS = ("vnexpress-tech", "genk-ai", "tuoitre-so", "thanhnien-cong-nghe")
GOOD_IDS = ("good-a", "good-b", "good-c", "good-d")
FEED = ('<rss><channel><item><title>AI synthetic architecture released today</title>'
        '<link>https://lab.example/release</link>'
        '<pubDate>Fri, 02 Oct 2026 11:00:00 GMT</pubDate></item></channel></rss>')
LATER = NOW + timedelta(minutes=20)


def good_source(id_):
    return {"id": id_, "name": id_, "url": "https://fixture.invalid/" + id_, "kind": "rss", "parser": "feed",
            "group": "press", "lab": "", "publisher": id_, "first_wave": True}


def retired_item(source_id, url, **changes):
    publisher = next(row for row in catalog.sources(NOW) if row["id"] == source_id)["publisher"]
    return coverage(source=source_id, publisher=publisher, url=url,
                    title="Vietnamese copy of an AI model launch", **changes)


def mentions_retired(text):
    return any(id_ in text for id_ in RETIRED_IDS) or "retired.example" in text


class RetiredSourceTests(unittest.TestCase):
    def setUp(self):
        real = {row["id"]: row for row in catalog.sources(NOW)}
        # The real catalog rows, so the real disable mechanism is under test.
        self.retired_rows = [real[id_] for id_ in RETIRED_IDS]
        roster = patch.object(catalog, "sources",
                              side_effect=lambda now: [good_source(id_) for id_ in GOOD_IDS] + self.retired_rows)
        for stub in (roster, patch.object(youtube, "collect", return_value=([], [])),
                     patch.object(feeds, "SOURCES", []), patch.object(huggingface, "SOURCES", [])):
            stub.start()
            self.addCleanup(stub.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.events = Path(self.temp.name) / "events.json"
        self.events.write_bytes(b"[]")
        self.fetched = []

    def fetch(self, url, **kwargs):
        self.fetched.append(url)
        if url.startswith("https://fixture.invalid/good-"):
            return FEED
        raise OSError("synthetic unavailable source")

    def published_snapshot(self):
        pure = [cluster_items([retired_item(id_, f"https://retired.example/{id_}")], NOW)[0]
                for id_ in RETIRED_IDS]
        mixed = cluster_items([coverage(source="good-a", url="https://lab.example/other",
                                        title="Lab publishes a separate AI reasoning benchmark")], NOW)[0]
        mixed["coverage"].append(retired_item("vnexpress-tech", "https://retired.example/mixed"))
        mixed["source_count"] = 2
        return {"schema_version": 2, "generated_at": NOW.isoformat(), "stories": pure + [mixed]}

    def test_retired_rows_stay_in_inventory_as_disabled(self):
        for row in self.retired_rows:
            with self.subTest(source=row["id"]):
                self.assertTrue(row["disabled"])
                self.assertIn("quyết định biên tập", row["disabled_reason"])
                self.assertTrue(catalog.is_retired({"source": row["id"]}))
        self.assertFalse(catalog.is_retired({"source": "good-a"}))

    def test_snapshot_holding_retired_items_publishes_without_showing_them(self):
        published = self.published_snapshot()
        before = deepcopy(published)
        result = pipeline.build_v2(fetch=self.fetch, now=LATER, events_path=self.events,
                                   published=published, resolve_images=False)
        self.assertEqual(published, before)
        self.assertFalse(any("retired.example" in url or "tuoitre" in url for url in self.fetched))

        # (a) Publication accepts the snapshot; the retired rows remain as disabled source records.
        candidate, status = prepare_publication(result, published, LATER)
        self.assertTrue(status["published"], status["reason"])
        records = {row["id"]: row for row in candidate["sources"]}
        for id_ in RETIRED_IDS:
            self.assertTrue(records[id_]["disabled"])
            self.assertFalse(records[id_]["ok"])

        # (b) No reader-facing output carries a retired observation.
        stories = candidate["stories"]
        self.assertIn("https://lab.example/other", {story["url"] for story in stories})
        self.assertFalse(any(catalog.is_retired(item) for story in stories for item in story["coverage"]))
        mixed = next(story for story in stories if story["url"] == "https://lab.example/other")
        self.assertEqual(mixed["source_count"], 1)
        output = Path(self.temp.name) / "site/data/radar.json"
        write_site_snapshot(candidate, output)
        written = sorted(output.parent.iterdir())
        self.assertGreaterEqual(len(written), 4)
        for path in written:
            document = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(document, dict):
                document.pop("sources", None)  # the source list names them only as disabled
            with self.subTest(output=path.name):
                self.assertFalse(mentions_retired(json.dumps(document, ensure_ascii=False)))

    def test_archived_story_pages_withhold_retired_coverage(self):
        published = self.published_snapshot()
        archive = {story["id"]: story for story in published["stories"]}
        mixed = published["stories"][-1]
        site = Path(self.temp.name) / "site"
        count = render_site(archive, site)
        self.assertEqual(count, 1)
        pages = list((site / "tin").glob("*/index.html"))
        self.assertEqual([page.parent.name for page in pages], [mixed["id"]])
        self.assertFalse(mentions_retired(pages[0].read_text(encoding="utf-8")))
        sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn(f"/tin/{mixed['id']}/", sitemap)
        self.assertFalse(any(f"/tin/{story['id']}/" in sitemap for story in published["stories"][:-1]))
        # History stays append-only: the archived record itself is not rewritten.
        self.assertEqual(len(archive[mixed["id"]]["coverage"]), 2)

    def test_reader_story_withholds_a_story_led_by_a_retired_observation(self):
        lead = retired_item("genk-ai", "https://retired.example/lead")
        story = cluster_items([lead], NOW)[0]
        story["coverage"].append(coverage(source="good-b", url="https://lab.example/echo"))
        self.assertIsNone(reader_story(story))
        unaffected = cluster_items([coverage(source="good-b", url="https://lab.example/plain")], NOW)[0]
        self.assertIs(reader_story(unaffected), unaffected)


if __name__ == "__main__":
    unittest.main()
