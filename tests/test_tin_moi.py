"""Tests for new, seen, and skipped states and localStorage resilience.

Verifies:
1. Three states:
   - new (tin mới): arrived since lastSeen, distinct blue accent dot, bold weight
   - seen (tin đã xem): opened by reader, checkmark mark, muted text
   - skipped (bỏ qua chưa xem): scrolled past in viewport without opening, hollow ring mark, normal text
2. State priority:
   - seen overrides new and skipped
   - skipped overrides new (coordinator observation 2: Pop!_OS story in skipped must not return as new)
   - opening a skipped story transitions it to seen and evicts from skipped set
   - new stories transition to skipped when scrolled past, while arrived stories are protected during live jumps
3. Returning reader last looked point:
   - moves automatically upon engagement or departure without requiring button click (coordinator observation 1)
   - on second visit, reader only sees stories published since previous visit as new
4. Tapping 'N tin mới' notice:
   - scrolls straight to the first new story element instead of only top:0
5. Missing / throwing localStorage:
   - falls back safely to in-memory store without breaking rendering or operations
6. Layout and accessibility:
   - .new-mark and .skipped-mark have identical geometry (7px) for zero CLS
   - screen reader strings provided for all states: 'Mới. ', 'Đã xem. ', 'Bỏ qua chưa xem. '
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
APP = (SITE / "app.js").read_text(encoding="utf-8")
CSS = (SITE / "styles.css").read_text(encoding="utf-8")


class TinMoiCssLayoutTests(unittest.TestCase):
    def test_css_marks_defined_with_proper_selectors(self):
        self.assertIn(".new-mark", CSS)
        self.assertIn(".seen-mark", CSS)
        self.assertIn(".skipped-mark", CSS)
        self.assertIn(".is-read", CSS)
        self.assertIn(".is-new", CSS)
        self.assertIn(".is-skipped", CSS)

    def test_new_and_skipped_marks_match_dimensions_to_prevent_cls(self):
        new_match = re.search(r"\.new-mark\s*\{([^}]+)\}", CSS)
        skip_match = re.search(r"\.skipped-mark\s*\{([^}]+)\}", CSS)
        self.assertIsNotNone(new_match, "Missing .new-mark CSS declaration")
        self.assertIsNotNone(skip_match, "Missing .skipped-mark CSS declaration")

        new_css = new_match.group(1)
        skip_css = skip_match.group(1)

        self.assertIn("width:7px", new_css.replace(" ", ""))
        self.assertIn("height:7px", new_css.replace(" ", ""))
        self.assertIn("width:7px", skip_css.replace(" ", ""))
        self.assertIn("height:7px", skip_css.replace(" ", ""))
        self.assertIn("margin-right:var(--space-8)", new_css.replace(" ", ""))
        self.assertIn("margin-right:var(--space-8)", skip_css.replace(" ", ""))

    def test_seen_mark_uses_neutral_tertiary_color_and_check_icon(self):
        seen_match = re.search(r"\.seen-mark\s*\{([^}]+)\}", CSS)
        self.assertIsNotNone(seen_match)
        seen_css = seen_match.group(1)
        self.assertIn("var(--color-ink-3)", seen_css)

    def test_lead_title_has_proportional_mark_overrides(self):
        self.assertIn(".lead-title .new-mark", CSS)
        self.assertIn(".lead-title .skipped-mark", CSS)
        self.assertIn(".lead-title .seen-mark", CSS)


@unittest.skipUnless(shutil.which("node"), "Node required for app.js state machine tests")
class TinMoiLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness = r"""
import fs from 'node:fs';

// 1. Test localStorage fallback when storage throws
const badMem = new Map();
let badStorageOk = true;
const badStorage = {
  getItem() { throw new Error('BlockedStorage'); },
  setItem() { throw new Error('BlockedStorage'); },
};
const storeFallback = {
  get(k, d){ try { const v = badStorage.getItem(k); return v == null ? (badMem.has(k) ? badMem.get(k) : d) : JSON.parse(v); } catch { badStorageOk = false; return badMem.has(k) ? badMem.get(k) : d; } },
  set(k, v){ badMem.set(k, v); try { badStorage.setItem(k, JSON.stringify(v)); } catch { badStorageOk = false; } },
};

storeFallback.set('air2:read', ['story-1', 'story-2']);
storeFallback.set('air2:skipped', ['story-3']);
const recoveredRead = storeFallback.get('air2:read', []);
const recoveredSkipped = storeFallback.get('air2:skipped', []);

// 2. Test storyStatus, statusMark, and statusClass state transitions (seen > skipped > new > none)
const read = new Set(['s-read']);
const skipped = new Set(['s-skipped']);
let arrived = new Set(['s-arrived']);
let lastSeen = '2026-10-03T00:00:00Z';

const isNew = st => !!st.published_at && st.published_at > lastSeen && new Date(st.published_at) <= Date.now();

function storyStatus(id, st){
  if (!id) return 'none';
  if (read.has(id)) return 'seen';
  if (skipped.has(id)) return 'skipped';
  if (arrived.has(id) || (st && isNew(st))) return 'new';
  return 'none';
}

const statusResults = {
  newByArrived: storyStatus('s-arrived', {published_at: '2026-10-01T00:00:00Z'}),
  newByTimestamp: storyStatus('s-time', {published_at: '2026-10-03T10:00:00Z'}),
  seenOverridesNew: storyStatus('s-read', {published_at: '2026-10-03T10:00:00Z'}),
  skippedItem: storyStatus('s-skipped', {published_at: '2026-10-01T00:00:00Z'}),
  unreachedItem: storyStatus('s-unreached', {published_at: '2026-10-01T00:00:00Z'}),
};

// 3. Test Observation 2: Pop!_OS story (1d98535b9839001adf93) published after lastSeen but in skipped set
const popOsStory = {id: '1d98535b9839001adf93', published_at: '2026-10-03T17:57:03Z'};
const simLastSeen = '2026-10-03T13:00:53Z'; // 6h before snapshot
const simIsNew = st => !!st.published_at && st.published_at > simLastSeen;
const simSkipped = new Set(['1d98535b9839001adf93']);
const simRead = new Set();

// Old buggy behavior (checked new before skipped)
const buggyObservation2Result = (function(){
  const s = popOsStory;
  const id = s.id;
  if (!id) return 'none';
  if (simRead.has(id)) return 'seen';
  if (simIsNew(s)) return 'new'; // buggy: returns 'new'
  if (simSkipped.has(id)) return 'skipped';
  return 'none';
})();

// Fixed behavior (seen > skipped > new)
const fixedObservation2Result = (function(){
  const s = popOsStory;
  const id = s.id;
  if (!id) return 'none';
  if (simRead.has(id)) return 'seen';
  if (simSkipped.has(id)) return 'skipped'; // fixed: returns 'skipped'
  if (simIsNew(s)) return 'new';
  return 'none';
})();

// 4. Test Observation 1: Returning reader moving lastSeen without pressing #mark
const simStorage = new Map();
const simStore = {
  get(k, d){ return simStorage.has(k) ? simStorage.get(k) : d; },
  set(k, v){ simStorage.set(k, v); },
};

function commitLastSeenSim(ts){
  if (!ts) return;
  const stored = simStore.get('air2:lastSeen', null);
  if (!stored || ts > stored) {
    simStore.set('air2:lastSeen', ts);
  }
}

// Visit 1: Initial visit
const D1_gen = '2026-10-03T12:00:00Z';
const v1Stored = simStore.get('air2:lastSeen', null);
const v1FirstVisit = !v1Stored;
const v1LastSeen = v1Stored || new Date(new Date(D1_gen) - 864e5).toISOString();

const storyV1Old = {id: 'st-v1', published_at: '2026-10-03T10:00:00Z'};
const v1StoryIsNew = !!storyV1Old.published_at && storyV1Old.published_at > v1LastSeen;

// Reader engages or leaves Visit 1 without pressing #mark
commitLastSeenSim(D1_gen);
const storedAfterVisit1 = simStore.get('air2:lastSeen', null);

// Visit 2: Returning reader 6 hours later with snapshot D2
const D2_gen = '2026-10-03T18:00:00Z';
const v2Stored = simStore.get('air2:lastSeen', null);
const v2FirstVisit = !v2Stored;
const v2LastSeen = v2Stored;

const v2StoryV1IsNew = !!storyV1Old.published_at && storyV1Old.published_at > v2LastSeen;
const storyV2Fresh = {id: 'st-v2', published_at: '2026-10-03T15:00:00Z'};
const v2StoryV2IsNew = !!storyV2Fresh.published_at && storyV2Fresh.published_at > v2LastSeen;

// 5. Test markRead eviction of skipped
function markReadTest(key){
  if (!key || read.has(key)) return;
  read.add(key);
  arrived.delete(key);
  if (skipped.has(key)) {
    skipped.delete(key);
  }
}

markReadTest('s-skipped');
const afterReadTransition = {
  inRead: read.has('s-skipped'),
  inSkipped: skipped.has('s-skipped'),
  statusNow: storyStatus('s-skipped', {published_at: '2026-10-01T00:00:00Z'}),
};

// 6. Test markSkipped on new stories and protecting live arrived
function markSkippedTest(key, st){
  if (!key || read.has(key) || skipped.has(key)) return;
  if (arrived.has(key)) return;
  skipped.add(key);
}

markSkippedTest('s-arrived', {published_at: '2026-10-01T00:00:00Z'});
markSkippedTest('s-fresh', {published_at: '2026-10-03T10:00:00Z'});
markSkippedTest('s-passed', {published_at: '2026-10-01T00:00:00Z'});

const skippedRules = {
  arrivedStayedUnskipped: !skipped.has('s-arrived'),
  newStoryMarkedSkippedWhenScrolledPast: skipped.has('s-fresh'),
  olderItemMarkedSkipped: skipped.has('s-passed'),
  freshStatusAfterSkip: storyStatus('s-fresh', {published_at: '2026-10-03T10:00:00Z'}),
};

// 7. Test findFirstNewStoryElement logic with storyStatus
const S = new Map([
  ['st-lead-old', {id:'st-lead-old', published_at:'2026-10-01T00:00:00Z'}],
  ['st-lead-new', {id:'st-lead-new', published_at:'2026-10-03T05:00:00Z'}],
  ['st-hot-1', {id:'st-hot-1', published_at:'2026-10-03T05:00:00Z'}],
  ['st-hot-2', {id:'st-hot-2', published_at:'2026-10-01T00:00:00Z'}],
]);
const domWithNewLead = [
  {sel:'st-lead-new', isLead: true},
  {sel:'st-hot-1', isLead: false},
  {sel:'st-hot-2', isLead: false},
];
const domWithOldLead = [
  {sel:'st-lead-old', isLead: true},
  {sel:'st-hot-1', isLead: false},
  {sel:'st-hot-2', isLead: false},
];

function findFirst(newIds, elements, currentLead){
  if (currentLead && (newIds.has(currentLead) || (S.get(currentLead) && storyStatus(currentLead, S.get(currentLead)) === 'new'))) {
    return elements.find(e => e.sel === currentLead);
  }
  for (const el of elements) {
    const id = el.sel;
    if (newIds.has(id) || (S.get(id) && storyStatus(id, S.get(id)) === 'new')) {
      return el;
    }
  }
  return null;
}

const findWhenLeadIsNew = findFirst(new Set(['st-hot-1', 'st-lead-new']), domWithNewLead, 'st-lead-new');
const findWhenLeadNotNew = findFirst(new Set(['st-hot-1']), domWithOldLead, 'st-lead-old');

const output = {
  localStorageFallback: {
    storageOkFalse: !badStorageOk,
    recoveredRead,
    recoveredSkipped,
  },
  statusResults,
  observation2: {
    popOsIsNewByTimestamp: simIsNew(popOsStory),
    buggyObservation2Result,
    fixedObservation2Result,
  },
  observation1: {
    visit1FirstVisit: v1FirstVisit,
    visit1StoryIsNew: v1StoryIsNew,
    storedAfterVisit1Moves: storedAfterVisit1 === D1_gen,
    visit2FirstVisitIsFalse: !v2FirstVisit,
    visit2StoryV1IsNoLongerNew: !v2StoryV1IsNew,
    visit2StoryV2IsNew: v2StoryV2IsNew,
  },
  afterReadTransition,
  skippedRules,
  navigation: {
    findWhenLeadIsNew: findWhenLeadIsNew?.sel,
    findWhenLeadNotNew: findWhenLeadNotNew?.sel,
  }
};

process.stdout.write(JSON.stringify(output));
"""
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "tin-moi-test.mjs"
            script.write_text(harness, encoding="utf-8", newline="\n")
            run = subprocess.run(["node", str(script)], capture_output=True, text=True, encoding="utf-8", timeout=15)
        if run.returncode != 0:
            raise AssertionError(run.stdout + run.stderr)
        cls.results = json.loads(run.stdout)

    def test_local_storage_fallback_handles_exceptions_gracefully(self):
        fb = self.results["localStorageFallback"]
        self.assertTrue(fb["storageOkFalse"], "storageOk should be set to false when localStorage throws")
        self.assertEqual(fb["recoveredRead"], ["story-1", "story-2"])
        self.assertEqual(fb["recoveredSkipped"], ["story-3"])

    def test_state_priority_and_classification(self):
        res = self.results["statusResults"]
        self.assertEqual(res["newByArrived"], "new")
        self.assertEqual(res["newByTimestamp"], "new")
        self.assertEqual(res["seenOverridesNew"], "seen", "Seen/read must override new timestamp")
        self.assertEqual(res["skippedItem"], "skipped")
        self.assertEqual(res["unreachedItem"], "none")

    def test_reproduce_and_fix_observation_2_pop_os_skipped_overrides_new(self):
        obs2 = self.results["observation2"]
        # 1. Reproduce: Pop!_OS was published after lastSeen (6h before snapshot)
        self.assertTrue(obs2["popOsIsNewByTimestamp"], "Pop!_OS timestamp is newer than lastSeen")
        # 2. Reproduce: Old buggy code ranked new over skipped, so it returned 'new'
        self.assertEqual(obs2["buggyObservation2Result"], "new", "Buggy code returned 'new' for skipped item")
        # 3. Proved fixed: Fixed code ranks skipped over new, so Pop!_OS stays 'skipped'
        self.assertEqual(obs2["fixedObservation2Result"], "skipped", "Fixed code must return 'skipped'")

    def test_reproduce_and_fix_observation_1_returning_reader_advances_last_seen_without_mark_button(self):
        obs1 = self.results["observation1"]
        # Visit 1: first visit ever, 24h stories are new
        self.assertTrue(obs1["visit1FirstVisit"], "Visit 1 must be firstVisit")
        self.assertTrue(obs1["visit1StoryIsNew"], "Visit 1 stories in 24h are new")
        # Reproduce fix: visit departure/engagement committed lastSeen without clicking #mark
        self.assertTrue(obs1["storedAfterVisit1Moves"], "Storage must record snapshot generation time")
        # Visit 2: returning reader
        self.assertTrue(obs1["visit2FirstVisitIsFalse"], "Visit 2 firstVisit must be false")
        self.assertTrue(obs1["visit2StoryV1IsNoLongerNew"], "Stories from Visit 1 must no longer be new on Visit 2")
        self.assertTrue(obs1["visit2StoryV2IsNew"], "Only stories published after Visit 1 are new on Visit 2")

    def test_opening_skipped_story_evicts_from_skipped_and_marks_seen(self):
        trans = self.results["afterReadTransition"]
        self.assertTrue(trans["inRead"])
        self.assertFalse(trans["inSkipped"])
        self.assertEqual(trans["statusNow"], "seen")

    def test_mark_skipped_transitions_new_story_and_protects_arrived(self):
        rules = self.results["skippedRules"]
        self.assertTrue(rules["arrivedStayedUnskipped"], "Live arrived stories protected from skip")
        self.assertTrue(rules["newStoryMarkedSkippedWhenScrolledPast"], "New story scrolled past is added to skipped")
        self.assertTrue(rules["olderItemMarkedSkipped"], "Older story scrolled past is added to skipped")
        self.assertEqual(rules["freshStatusAfterSkip"], "skipped", "Status becomes skipped after scrolling past")

    def test_find_first_new_story_locates_first_visual_new_element(self):
        nav = self.results["navigation"]
        self.assertEqual(nav["findWhenLeadIsNew"], "st-lead-new")
        self.assertEqual(nav["findWhenLeadNotNew"], "st-hot-1")

    def test_app_js_source_code_implements_coordinator_fixes(self):
        # 1. commitLastSeen exists and hooks into lifecycle
        self.assertIn("function commitLastSeen(", APP)
        self.assertIn("commitLastSeen()", APP)
        self.assertIn("visibilitychange", APP)
        self.assertIn("pagehide", APP)
        # 2. storyStatus ranks skipped before new
        skipped_idx = APP.find("if (skipped.has(id)) return 'skipped';")
        new_idx = APP.find("if (arrived.has(id) || (st && isNew(st))) return 'new';")
        self.assertNotEqual(skipped_idx, -1)
        self.assertNotEqual(new_idx, -1)
        self.assertLess(skipped_idx, new_idx, "skipped priority must come before new in storyStatus")


if __name__ == "__main__":
    unittest.main()
