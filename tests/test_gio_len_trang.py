"""A story that just reached Halcyon reads as new, wherever its source time falls (captain, 14/11 15:45: "Sửa luôn").

On 14/11 at 14:27 a build put "Ra mắt ChatGPT Wallet" on hco.news. Its published_at is the OpenAI post time, 13/11
15:00Z, so "Vừa đăng" left it out and it never carried "Mới". The build now records `appeared_at`, the time of the
first published build that showed the story to readers, and carries it forward (across cluster ID changes through
`aliases`). The feed orders "Vừa đăng" and measures NEW_MARK_HOURS from it. A story whose appearance is unknown falls
back to its source time; nothing is ever stamped with the current time for want of a record.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from radar.appearance import stamp_appearance, visible_story_ids
from radar.site_payload import write_site_snapshot

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = (ROOT / "site", ROOT / "extension")

NOW = datetime(2026, 11, 14, 7, 27, tzinfo=timezone.utc)   # 14:27 VN, the build that published Wallet


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def story(story_id, published, **extra):
    return dict(id=story_id, published_at=published, **extra)


def snapshot(generated, stories, tracked=True):
    payload = {"schema_version": 2, "generated_at": iso(generated), "stories": stories}
    if tracked:
        payload["appeared_at_since"] = "2026-11-10T00:00:00Z"
    return payload


ARCHIVE = {"additions": {}, "archived": set()}   # the story archive was read and holds none of these stories


class ReturningStory(unittest.TestCase):
    """A story Halcyon has shown before keeps its first appearance however it left and came back."""

    def test_a_story_shown_hidden_and_shown_again_keeps_its_first_appearance(self):
        # Build 1 shows it; build 2 hides it (the newsroom gate), so the field is dropped from its record;
        # build 3 shows it again. The story archive (radar-story-pages) still holds the commit that first added it.
        shown = NOW - timedelta(hours=30)
        first = snapshot(shown, [story("a", "2026-11-12T01:00:00Z")])
        stamp_appearance(first, snapshot(shown - timedelta(minutes=20), []), {"a"}, archive=ARCHIVE)
        self.assertEqual(first["stories"][0]["appeared_at"], iso(shown))
        hidden = snapshot(NOW - timedelta(minutes=20), [story("a", "2026-11-12T01:00:00Z")])
        stamp_appearance(hidden, first, set(), archive=ARCHIVE)
        hidden["stories"][0].pop("appeared_at")  # what the build's rebuild of a carried story does to it
        archive = {"additions": {"a": shown + timedelta(minutes=3)}, "archived": {"a"}}
        back = snapshot(NOW, [story("a", "2026-11-12T01:00:00Z")], tracked=False)
        stamp_appearance(back, hidden, {"a"}, archive=archive)
        self.assertEqual(back["stories"][0]["appeared_at"], iso(shown + timedelta(minutes=3)),
                         "the archive commit that first added it, minutes after that build")

    def test_a_story_that_left_the_record_and_came_back_is_never_new(self):
        # Gone from the carried collection (pool cap, rebuilt cluster) and back under a new ID; one of its names
        # is in the archive, but from before the fetched history began: shown before, time unknown.
        archive = {"additions": {}, "archived": {"old-name"}}
        prior = snapshot(NOW - timedelta(minutes=20), [])
        payload = snapshot(NOW, [story("new-name", "2026-11-12T01:00:00Z", aliases=["old-name"])], tracked=False)
        stamp_appearance(payload, prior, {"new-name"}, archive=archive)
        self.assertEqual(payload["stories"][0]["appeared_at"], "2026-11-12T01:00:00Z", "source time, never now")

    def test_a_piece_split_off_under_a_new_id_keeps_the_appearance_of_its_coverage(self):
        prior = snapshot(NOW - timedelta(minutes=20), [
            story("joined", "2026-11-12T01:00:00Z", appeared_at="2026-11-12T02:00:00Z", url="https://a.example/1",
                  coverage=[{"url": "https://a.example/1"}, {"url": "https://b.example/2"}])])
        payload = snapshot(NOW, [story("piece", "2026-11-12T00:30:00Z", url="https://b.example/2",
                                       coverage=[{"url": "https://b.example/2"}])], tracked=False)
        stamp_appearance(payload, prior, {"piece"}, archive=ARCHIVE)
        self.assertEqual(payload["stories"][0]["appeared_at"], "2026-11-12T02:00:00Z")

    def test_the_archive_repairs_an_appearance_stamped_too_late(self):
        # The four stories of 14/11 carry a late appeared_at in every record; the archive's first addition wins.
        prior = snapshot(NOW - timedelta(minutes=20), [
            story("d0923a9b", "2026-11-12T03:13:00Z", appeared_at="2026-11-14T11:22:57Z")])
        payload = snapshot(NOW, [story("d0923a9b", "2026-11-12T03:13:00Z", appeared_at="2026-11-14T11:22:57Z")],
                           tracked=False)
        archive = {"additions": {"d0923a9b": datetime(2026, 11, 12, 7, 19, 35, tzinfo=timezone.utc)},
                   "archived": {"d0923a9b"}}
        stamp_appearance(payload, prior, {"d0923a9b"}, archive=archive)
        self.assertEqual(payload["stories"][0]["appeared_at"], "2026-11-12T07:19:35Z")

    def test_without_the_archive_nothing_is_stamped_now(self):
        # The carried collection alone is not a complete record (7-day prune, 2,000-story pool, rebuilt clusters).
        prior = snapshot(NOW - timedelta(minutes=20), [])
        payload = snapshot(NOW, [story("wallet", "2026-11-13T15:00:00Z")], tracked=False)
        stamp_appearance(payload, prior, {"wallet"}, archive=None)
        self.assertEqual(payload["stories"][0]["appeared_at"], "2026-11-13T15:00:00Z")


class StampAppearance(unittest.TestCase):
    def test_a_story_first_shown_by_this_build_gets_this_build_time(self):
        payload = snapshot(NOW, [story("wallet", "2026-11-13T15:00:00Z")], tracked=False)
        prior = snapshot(NOW - timedelta(minutes=20), [], tracked=True)
        stamp_appearance(payload, prior, {"wallet"}, archive=ARCHIVE)
        self.assertEqual(payload["stories"][0]["appeared_at"], iso(NOW))
        self.assertEqual(payload["stories"][0]["published_at"], "2026-11-13T15:00:00Z", "source time is kept")

    def test_a_story_collected_earlier_but_shown_only_now_is_new_now(self):
        # Wallet sat in the collection (ungated) since the night before; the newsroom passed it at 14:27.
        prior = snapshot(NOW - timedelta(minutes=20), [story("wallet", "2026-11-13T15:00:00Z")])
        payload = snapshot(NOW, [story("wallet", "2026-11-13T15:00:00Z")], tracked=False)
        stamp_appearance(payload, prior, {"wallet"}, archive=ARCHIVE)
        self.assertEqual(payload["stories"][0]["appeared_at"], iso(NOW))

    def test_the_appearance_is_carried_forward(self):
        prior = snapshot(NOW - timedelta(minutes=20), [story("a", "2026-11-12T01:00:00Z",
                                                             appeared_at="2026-11-12T02:00:00Z")])
        payload = snapshot(NOW, [story("a", "2026-11-12T01:00:00Z")], tracked=False)
        stamp_appearance(payload, prior, {"a"})
        self.assertEqual(payload["stories"][0]["appeared_at"], "2026-11-12T02:00:00Z")
        self.assertEqual(payload["appeared_at_since"], "2026-11-10T00:00:00Z", "tracking start is carried too")

    def test_the_appearance_survives_a_cluster_id_change(self):
        prior = snapshot(NOW - timedelta(minutes=20), [
            story("old", "2026-11-12T01:00:00Z", appeared_at="2026-11-12T02:00:00Z"),
            story("older", "2026-11-11T01:00:00Z", appeared_at="2026-11-11T03:00:00Z", aliases=["oldest"])])
        payload = snapshot(NOW, [story("renamed", "2026-11-12T01:00:00Z", aliases=["old", "oldest"])], tracked=False)
        stamp_appearance(payload, prior, {"renamed"})
        self.assertEqual(payload["stories"][0]["appeared_at"], "2026-11-11T03:00:00Z", "earliest of its names")

    def test_a_story_readers_never_saw_gets_no_appearance(self):
        payload = snapshot(NOW, [story("held", "2026-11-14T06:00:00Z")], tracked=False)
        stamp_appearance(payload, snapshot(NOW - timedelta(minutes=20), []), set())
        self.assertNotIn("appeared_at", payload["stories"][0])

    def test_first_deploy_backfills_source_times_never_now(self):
        # The prior snapshot predates the field: every visible story takes its own source time.
        prior = snapshot(NOW - timedelta(minutes=20), [story("a", "2026-11-10T01:00:00Z")], tracked=False)
        payload = snapshot(NOW, [story("a", "2026-11-10T01:00:00Z"), story("wallet", "2026-11-13T15:00:00Z"),
                                 story("undated", None)], tracked=False)
        stamp_appearance(payload, prior, {"a", "wallet", "undated"})
        by_id = {row["id"]: row for row in payload["stories"]}
        self.assertEqual(by_id["a"]["appeared_at"], "2026-11-10T01:00:00Z")
        self.assertEqual(by_id["wallet"]["appeared_at"], "2026-11-13T15:00:00Z")
        self.assertNotIn("appeared_at", by_id["undated"], "no source time: left unknown, not stamped now")
        self.assertNotIn(iso(NOW), [row.get("appeared_at") for row in payload["stories"]])
        self.assertEqual(payload["appeared_at_since"], iso(NOW))

    def test_no_prior_snapshot_backfills_source_times(self):
        payload = snapshot(NOW, [story("a", "2026-11-10T01:00:00Z")], tracked=False)
        stamp_appearance(payload, None, {"a"})
        self.assertEqual(payload["stories"][0]["appeared_at"], "2026-11-10T01:00:00Z")

    def test_a_prior_snapshot_older_than_two_days_does_not_count_as_a_record(self):
        prior = snapshot(NOW - timedelta(hours=49), [])
        payload = snapshot(NOW, [story("a", "2026-11-10T01:00:00Z")], tracked=False)
        stamp_appearance(payload, prior, {"a"})
        self.assertEqual(payload["stories"][0]["appeared_at"], "2026-11-10T01:00:00Z")

    def test_an_unreadable_carried_value_is_ignored(self):
        prior = snapshot(NOW - timedelta(minutes=20), [story("a", "2026-11-10T01:00:00Z", appeared_at="soon")])
        payload = snapshot(NOW, [story("a", "2026-11-10T01:00:00Z", appeared_at="later")], tracked=False)
        stamp_appearance(payload, prior, {"a"}, archive=ARCHIVE)
        self.assertEqual(payload["stories"][0]["appeared_at"], iso(NOW))

    def test_the_build_carries_the_appearance_through_retention_and_an_id_change(self):
        # The real assembly: a carried story is re-clustered under a new ID (its old ID becomes an alias).
        from unittest import mock
        from radar import assembly
        from radar.clustering import cluster_items
        try:
            from .test_v2_support import NOW as BUILD, coverage
        except ImportError:
            from test_v2_support import NOW as BUILD, coverage
        fresh = coverage("wire", "https://wire.example/videos/chips", publisher="wire",
                         title="Lattice in Early Financing Talks for OpenAI Chips")
        old = coverage("wire", "https://wire.example/articles/chips", publisher="wire",
                       title="Lattice Holds Early Talks About Financing for OpenAI Chips",
                       published_at="2026-10-01T22:00:00Z")
        arrival = coverage("lab", "https://lab.example/post", publisher="lab",
                           title="A lab posts its model card a day late", published_at="2026-10-01T20:00:00Z")
        carried = cluster_items([old], BUILD)
        carried[0]["appeared_at"] = "2026-10-01T23:00:00Z"
        published = dict(schema_version=2, generated_at=iso(BUILD - timedelta(minutes=20)),
                         appeared_at_since="2026-09-30T00:00:00Z", stories=carried)
        with mock.patch("radar.appearance.visible_story_ids", lambda data, _rows: {s["id"] for s in data["stories"]}):
            result = assembly.finish(dict(sources=[], trending={}), [fresh, arrival], [], BUILD, None,
                                     published=published, resolve_images=False, appearance_archive=ARCHIVE)
        by_url = {story["url"]: story for story in result["stories"]}
        renamed = next(s for s in result["stories"] if carried[0]["id"] in s.get("aliases", []))
        self.assertEqual(renamed["appeared_at"], "2026-10-01T23:00:00Z")
        self.assertEqual(by_url[arrival["url"]]["appeared_at"], iso(BUILD), "first shown by this build")
        self.assertEqual(by_url[arrival["url"]]["published_at"], "2026-10-01T20:00:00Z")
        self.assertEqual(result["appeared_at_since"], "2026-09-30T00:00:00Z")

    def test_the_build_reads_the_record_before_rebuilding_the_carried_stories(self):
        # Measured 14/11 10:25Z: finish() rebuilds a carried story whose coverage no longer forms one cluster
        # (radar.press_relevance.filter_published_stories). The rebuilt pieces are new dicts without `appeared_at`,
        # and a split-off piece does not keep the old ID. 46 names lost their record in that one build; a story
        # first shown 10/11 (78c954e9) came back stamped 14/11 10:25:56Z and led "Vừa đăng" with "Mới".
        from unittest import mock
        from radar import assembly
        from radar.clustering import cluster_items
        try:
            from .test_v2_support import NOW as BUILD, coverage
        except ImportError:
            from test_v2_support import NOW as BUILD, coverage
        first = coverage("wire", "https://wire.example/chips", publisher="wire",
                         title="Lattice Holds Early Talks About Financing for OpenAI Chips",
                         published_at="2026-10-01T22:00:00Z")
        second = coverage("lab", "https://lab.example/model-card", publisher="lab",
                          title="A lab posts its model card a day late", published_at="2026-10-01T20:00:00Z")
        # One story was published holding both items; the current rules no longer group them.
        joined = dict(cluster_items([first], BUILD)[0], appeared_at="2026-10-01T23:00:00Z")
        joined["coverage"] = joined["coverage"] + cluster_items([second], BUILD)[0]["coverage"]
        published = dict(schema_version=2, generated_at=iso(BUILD - timedelta(minutes=20)),
                         appeared_at_since="2026-09-30T00:00:00Z", stories=[joined])
        with mock.patch("radar.appearance.visible_story_ids", lambda data, _rows: {s["id"] for s in data["stories"]}):
            result = assembly.finish(dict(sources=[], trending={}), [], [], BUILD, None, published=published,
                                     resolve_images=False, appearance_archive={"additions": {}, "archived": set()})
        stamped = {story["url"]: story.get("appeared_at") for story in result["stories"]}
        self.assertEqual(set(stamped), {first["url"], second["url"]}, "the old story is split in two")
        self.assertEqual(stamped, {first["url"]: "2026-10-01T23:00:00Z", second["url"]: "2026-10-01T23:00:00Z"},
                         "both pieces were on Halcyon since 01/10 23:00")

    def test_visible_ids_follow_the_newsroom_gate(self):
        payload = snapshot(NOW, [story("a", "2026-11-10T01:00:00Z")])
        self.assertEqual(visible_story_ids(payload, None), set(), "no decisions: nothing is shown")

    def test_the_reader_projection_carries_the_field(self):
        payload = snapshot(NOW, [story("a", "2026-11-10T01:00:00Z", appeared_at=iso(NOW), title="A",
                                       url="https://a.example/1", coverage=[])])
        decisions = {"decisions": [{"id": "a", "decision": "publish"}]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data" / "radar.json"
            out.parent.mkdir()
            from unittest import mock
            with mock.patch("radar.site_payload.apply_decisions", lambda data, _rows: deepcopy(data)):
                write_site_snapshot(payload, out)
            ui = json.loads((out.parent / "radar-ui.json").read_text(encoding="utf-8"))
        self.assertEqual(ui["stories"][0]["appeared_at"], iso(NOW))
        self.assertNotIn("appeared_at_since", ui, "the tracking marker stays out of the reader file")


FEED_HARNESS = r"""
import { readFileSync } from 'node:fs';
const src = readFileSync(%(feed)s, 'utf8');
const grab = re => { const m = src.match(re); if (!m) throw new Error('missing ' + re); return m[0]; };
const code = [
  grab(/^const NEW_MARK_HOURS = [^\n]*;/m),
  grab(/^const isNew = [\s\S]*?;$/m),
  grab(/^function storyStatus\([^\n]*\) \{[\s\S]*?^\}/m),
  grab(/const rankTime = [^\n]*/),
  grab(/const pubTime = [^\n]*/),
  grab(/const NEWEST = [^\n]*/),
  grab(/const FRESH_TILE_ROWS = [^\n]*/),
  grab(/const byPub = [^\n]*/),
  grab(/function newestStories\(\) \{[\s\S]*?\r?\n\}\r?\n/),
  grab(/function freshItem\(st\) \{[\s\S]*?\r?\n\}\r?\n/),
].join('\n');
const NOW = Date.parse('2026-11-14T08:45:00Z');   // 15:45 VN, when the captain looked
Date.now = () => NOW;
const ago = h => new Date(NOW - h * 36e5).toISOString();
const env = {
  ms: iso => new Date(iso).getTime() || 0, GEN: NOW, FRONT_IDS: new Set(), read: new Set(), skipped: new Set(),
  arrived: new Set(), seenAll: null, freshIds: [], titleOf: st => ({ text: st.id }), esc: s => String(s),
  hhmm: d => d.toISOString().slice(11, 16), exact: s => 'exact:' + s, langAttr: () => '', markHTML: () => '',
  statusClass: () => '',
};
const run = (body, extra = {}) => {
  const scope = { ...env, ...extra };
  return new Function(...Object.keys(scope), code + ';\n' + body)(...Object.values(scope));
};
// Wallet: OpenAI posted it 13/11 15:00Z, it reached Halcyon 14/11 07:27Z (1.3 hours before NOW).
const wallet = { id: 'wallet', published_at: '2026-11-13T15:00:00Z', appeared_at: '2026-11-14T07:27:00Z' };
const others = [
  { id: 'n1137', published_at: '2026-11-14T04:37:00Z', appeared_at: '2026-11-14T04:40:00Z' },
  { id: 'n0900', published_at: '2026-11-14T02:00:00Z', appeared_at: '2026-11-14T02:05:00Z' },
  { id: 'n0859', published_at: '2026-11-14T01:59:00Z', appeared_at: '2026-11-14T02:05:00Z' },
  { id: 'n0624', published_at: '2026-11-13T23:24:00Z', appeared_at: '2026-11-13T23:30:00Z' },
  { id: 'legacy', published_at: ago(2) },   // no appearance recorded: its source time stands in
];
const all = [wallet, ...others];
const late = { id: 'late', published_at: ago(30), appeared_at: ago(7) };
const out = {};
out.order = run("return newestStories().list.map(s => s.id);", { allStories: all, STORY_ANY: new Map(all.map(s => [s.id, s])) });
out.walletRow = run("return freshItem(st);", { st: wallet });
out.walletNew = run("return storyStatus('wallet', st);", { st: wallet });
out.lateNew = run("return storyStatus('late', st);", { st: late });
out.legacyNew = run("return storyStatus('legacy', st);", { st: others[4] });
out.walletAfterOlderMark = run("return storyStatus('wallet', st);", { st: wallet, seenAll: '2026-11-14T05:00:00Z' });
out.walletAfterMark = run("return storyStatus('wallet', st);", { st: wallet, seenAll: '2026-11-14T08:00:00Z' });
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required")
class FeedReadsArrival(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = {}
        for folder in FOLDERS:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "gio-len-trang.mjs"
                path.write_text(FEED_HARNESS % {"feed": json.dumps(str(folder / "feed.js"))},
                                encoding="utf-8", newline="\n")
                result = subprocess.run(["node", str(path)], capture_output=True, text=True, encoding="utf-8",
                                        timeout=60)
            if result.returncode:
                raise AssertionError(f"{folder.name}: {result.stderr}")
            cls.out[folder.name] = json.loads(result.stdout)

    def test_a_just_arrived_story_with_an_old_source_time_leads_vua_dang(self):
        for name, out in self.out.items():
            self.assertEqual(out["order"][0], "wallet", name)
            self.assertEqual(out["order"][1:], ["legacy", "n1137", "n0900", "n0859", "n0624"], name)

    def test_it_carries_moi_and_a_story_that_arrived_seven_hours_ago_does_not(self):
        for name, out in self.out.items():
            self.assertEqual(out["walletNew"], "new", name)
            self.assertEqual(out["lateNew"], "none", name)
            self.assertEqual(out["legacyNew"], "new", f"{name}: no appearance falls back to the source time")

    def test_mark_seen_compares_the_arrival(self):
        for name, out in self.out.items():
            self.assertEqual(out["walletAfterOlderMark"], "new", f"{name}: arrived after the reader's mark")
            self.assertEqual(out["walletAfterMark"], "none", name)

    def test_the_row_prints_the_arrival_and_keeps_the_source_time_in_reach(self):
        for name, out in self.out.items():
            row = out["walletRow"]
            self.assertRegex(row, r'<time class="num" datetime="2026-11-14T07:27:00Z"[^>]*>07:27</time>', name)
            self.assertIn("2026-11-13T15:00:00Z", row, f"{name}: the source time stays in the row's title")

    def test_the_window_is_still_six_hours(self):
        for folder in FOLDERS:
            feed = (folder / "feed.js").read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r"^const NEW_MARK_HOURS = 6;", feed, re.M)), 1, folder.name)


if __name__ == "__main__":
    unittest.main()
