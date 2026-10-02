"""Offline checks for the Bento page behaviours an independent review questioned.

Pure page modules (site/calendar.js, site/faces.js, site/time-text.js, site/snapshot.js) run under Node
without a DOM. Behaviour that needs a rendered page (focus after S, lists kept open after a re-render) is
measured by tests/measure_bento_render.mjs on a real Chrome; here only its wiring in site/app.js is checked.
"""

from pathlib import Path
import json
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

HARNESS = """
import {{ canCalendar, buildIcs, gcalURL, verifiedNote }} from {calendar};
import {{ faceOfStory, faceOfSource }} from {faces};
import {{ ago, dayKey, daysLeftHTML }} from {time_text};
import {{ isSnapshotV2 }} from {snapshot};

const exact = (s, e) => ({{uid: 'x', title: 'Talk', startAt: s, endAt: e}});
const S = '2026-10-16T09:00:00Z';
const out = {{}};

out.canCal = {{
  endBefore: canCalendar(exact(S, '2026-10-16T08:00:00Z')),
  endEqual: canCalendar(exact(S, S)),
  endAfter: canCalendar(exact(S, '2026-10-16T11:00:00Z')),
}};
out.icsEqual = buildIcs(exact(S, S));
out.icsAfter = buildIcs(exact(S, '2026-10-16T11:00:00Z'));
out.gcalBefore = gcalURL(exact(S, '2026-10-16T08:00:00Z'));
const g = gcalURL(exact(S, '2026-10-16T11:00:00Z'));
out.gcalRaw = g;
out.gcalDates = new URL(g).searchParams.get('dates');
out.notes = [
  verifiedNote('2026-09-30', 'https://neurips.cc/'),
  verifiedNote(undefined, 'https://neurips.cc/'),
  verifiedNote('2026-09-30', undefined),
  verifiedNote(undefined, undefined),
];

const SRC = new Map([
  ['hn-front', {{id: 'hn-front', name: 'Hacker News', lab: '', publisher: 'hacker-news'}}],
  ['latent', {{id: 'latent', name: 'Latent Space', lab: '', publisher: ''}}],
  ['hf-models', {{id: 'hf-models', name: 'Hugging Face', lab: '', publisher: ''}}],
]);
out.faces = {{
  forumLinkingRepo: faceOfStory({{kind: 'forum', url: 'https://github.com/dtonon/outis', coverage: [{{source: 'hn-front', url: 'https://github.com/dtonon/outis'}}]}}, SRC),
  articleCitingRepo: faceOfStory({{kind: 'other', url: 'https://example.com/post', coverage: [{{source: 'latent', url: 'https://example.com/post'}}, {{source: 'hn-front', url: 'https://github.com/acme/tool'}}]}}, SRC),
  repository: faceOfStory({{kind: 'repository', url: 'https://github.com/acme/tool', coverage: [{{source: 'hn-front', url: 'https://github.com/acme/tool'}}]}}, SRC),
  model: faceOfStory({{kind: 'model', url: 'https://huggingface.co/Qwen/Qwen3-8B', coverage: [{{source: 'hf-models', url: 'https://huggingface.co/Qwen/Qwen3-8B'}}]}}, SRC),
  channelNoLab: faceOfSource({{source: '', name: 'Dwarkesh Patel', lab: ''}}, SRC),
  channelWithLab: faceOfSource({{source: '', name: 'OpenAI', lab: 'openai'}}, SRC),
  noCoverage: faceOfStory({{kind: 'other', url: 'https://example.com/', coverage: []}}, SRC),
}};

// ago(): a fixed clock, 10:00 on 3 October 2026 in Vietnam.
const NOW = Date.parse('2026-10-03T03:00:00Z');
out.ago = [
  ago('2026-10-03T02:30:00Z', NOW), ago('2026-10-02T04:00:00Z', NOW), ago('2026-10-02T02:00:00Z', NOW),
  ago('2026-10-01T16:30:00Z', NOW), ago('2026-10-03T03:05:00Z', NOW), ago(null, NOW), ago('not a time', NOW),
];
// Every age from 24 to 72 hours, in 5-minute steps, at clocks around the day: "Hôm qua" must only ever
// name the previous calendar day in Vietnam, and an age of 24 hours or more is never the same calendar day.
let checked = 0, wrongYesterday = 0, sameDay = 0;
for (let clock = 0; clock < 24 * 60; clock += 37) {{
  const now = Date.parse('2026-10-03T00:00:00+07:00') + clock * 6e4;
  const yesterday = dayKey(new Date(Date.parse(dayKey(new Date(now)) + 'T12:00:00+07:00') - 864e5));
  for (let m = 24 * 60; m < 72 * 60; m += 5) {{
    const d = new Date(now - m * 6e4), text = ago(d.toISOString(), now);
    checked++;
    if (text.startsWith('Hôm qua') && dayKey(d) !== yesterday) wrongYesterday++;
    if (dayKey(d) === dayKey(new Date(now))) sameDay++;
  }}
}}
out.agoSweep = {{checked, wrongYesterday, sameDay}};

out.daysLeft = [daysLeftHTML(3), daysLeftHTML(1), daysLeftHTML(0), daysLeftHTML(-1), daysLeftHTML(NaN)];

const good = {{schema_version: 2, generated_at: '2026-10-03T00:00:00Z', stories: [], sections: {{hot: []}}, sources: []}};
out.snapshot = [
  isSnapshotV2(good),
  isSnapshotV2({{...good, sections: undefined}}),
  isSnapshotV2({{...good, sections: []}}),
  isSnapshotV2({{...good, schema_version: 3}}),
  isSnapshotV2({{...good, stories: {{}}}}),
  isSnapshotV2({{...good, generated_at: ''}}),
  isSnapshotV2({{...good, sources: undefined}}),
  isSnapshotV2(null),
];
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class BentoReviewFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        uri = lambda name: json.dumps((SITE / name).as_uri())
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "harness.mjs"
            harness.write_text(HARNESS.format(
                calendar=uri("calendar.js"), faces=uri("faces.js"),
                time_text=uri("time-text.js"), snapshot=uri("snapshot.js"),
            ), encoding="utf-8", newline="\n")
            result = subprocess.run(["node", str(harness)], cwd=ROOT, capture_output=True,
                                    text=True, encoding="utf-8", timeout=60)
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        cls.out = json.loads(result.stdout)
        cls.app = (SITE / "app.js").read_text(encoding="utf-8")

    # Calendar: an exact end before its start is refused (RFC 5545 3.8.2.2).
    def test_exact_end_before_start_is_refused(self):
        self.assertEqual(self.out["canCal"], {"endBefore": False, "endEqual": True, "endAfter": True})
        self.assertIsNone(self.out["gcalBefore"])

    def test_end_equal_to_start_gets_no_dtend(self):
        self.assertIn("DTSTART:20261016T090000Z", self.out["icsEqual"])
        self.assertNotIn("DTEND", self.out["icsEqual"])
        self.assertIn("DTEND:20261016T110000Z", self.out["icsAfter"])

    def test_google_dates_decode_to_start_slash_end(self):
        # A query string carries "/" as %2F; any standard query parser (and Google's) decodes it back.
        self.assertEqual(self.out["gcalDates"], "20261016T090000Z/20261016T110000Z")
        self.assertIn("dates=20261016T090000Z%2F20261016T110000Z", self.out["gcalRaw"])

    def test_event_note_never_prints_undefined(self):
        self.assertEqual(self.out["notes"], [
            "Ngày đã xác minh 2026-09-30 từ https://neurips.cc/",
            "Ngày đã xác minh từ https://neurips.cc/",
            "Ngày đã xác minh 2026-09-30",
            "",
        ])
        self.assertIn("verifiedNote(e.verified_at, e.source_url)", self.app)
        self.assertNotIn("Ngày đã xác minh ${", self.app)
        self.assertNotIn("Livestream của ${v.channel}`}", self.app)

    # Logos: a story's logo is its source's, unless the story IS a repository or model.
    def test_discussion_linking_a_repo_keeps_its_source_logo(self):
        f = self.out["faces"]
        self.assertEqual(f["forumLinkingRepo"], {"kind": "gh", "id": "HackerNews", "label": "Hacker News"})
        self.assertEqual(f["articleCitingRepo"], {"kind": "mono", "id": "LS", "label": "Latent Space"})
        self.assertEqual(f["repository"], {"kind": "gh", "id": "acme", "label": "acme"})
        self.assertEqual(f["model"], {"kind": "hf", "id": "Qwen", "label": "Qwen"})
        self.assertEqual(f["noCoverage"]["kind"], "mono")

    def test_stream_channel_without_lab_gets_its_own_monogram(self):
        f = self.out["faces"]
        self.assertEqual(f["channelNoLab"], {"kind": "mono", "id": "DP", "label": "Dwarkesh Patel"})
        self.assertEqual(f["channelWithLab"], {"kind": "gh", "id": "openai", "label": "OpenAI"})
        self.assertIn("faceOfSource({source:'', name:v.channel, lab:v.lab}, SRC)", self.app)

    # Time wording.
    def test_ago_wording(self):
        self.assertEqual(self.out["ago"], [
            "30 phút trước", "23 giờ trước", "Hôm qua, 09:00", "2 ngày trước", "sắp tới",
            "không rõ thời gian", "không rõ thời gian",
        ])

    def test_yesterday_only_names_the_previous_calendar_day(self):
        sweep = self.out["agoSweep"]
        self.assertGreater(sweep["checked"], 20000)
        self.assertEqual(sweep["wrongYesterday"], 0)
        self.assertEqual(sweep["sameDay"], 0)

    def test_event_row_never_reads_zero_or_negative_days(self):
        self.assertEqual(self.out["daysLeft"], [
            'còn <span class="num">3</span> ngày', 'còn <span class="num">1</span> ngày', "hôm nay", "đang diễn ra", "",
        ])
        self.assertIn("${daysLeftHTML(n)} · ", self.app)
        self.assertNotIn('còn <span class="num">${n}</span> ngày', self.app)

    def test_page_uses_the_tested_time_helpers(self):
        self.assertIn("ago, daysLeftHTML } from './time-text.js';", self.app)
        self.assertNotIn("function ago", self.app)

    # Snapshot contract: one check for the first load and for every poll.
    def test_snapshot_contract(self):
        self.assertEqual(self.out["snapshot"], [True, False, False, False, False, False, False, False])
        self.assertEqual(self.app.count("isSnapshotV2(j)"), 2)
        self.assertIn("if (!isSnapshotV2(j) || j.generated_at <= D.generated_at) return;", self.app)

    # Wiring of the two rendered-page fixes (measured by tests/measure_bento_render.mjs).
    def test_save_keeps_focus_and_open_lists(self):
        self.assertRegex(self.app, r"function toggleSave\(key\)\{[\s\S]*?keepFocus\(\(\) => \{[\s\S]*?renderChapters\(\)[\s\S]*?renderBoard\(\);")
        self.assertIn("expanded.has(owner)", self.app)
        self.assertIn("if (owner) expanded.add(owner);", self.app)


class BentoStaticTests(unittest.TestCase):
    def test_tokens_page_sets_theme_before_first_paint(self):
        html = (SITE / "tokens.html").read_text(encoding="utf-8")
        script = html.find("localStorage.getItem('air2:theme')")
        self.assertGreater(script, 0)
        self.assertLess(script, html.find('<link rel="stylesheet"'))

    def test_tokens_page_tolerates_empty_coverage(self):
        js = (SITE / "tokens.js").read_text(encoding="utf-8")
        self.assertNotIn("coverage[0]", js)

    def test_component_literals_live_in_tokens(self):
        css = (SITE / "styles.css").read_text(encoding="utf-8")
        tokens = (SITE / "tokens.css").read_text(encoding="utf-8")
        for literal in ("oklch(0.", "#000", "monospace", "font-size:0.", "font-size:1."):
            self.assertNotIn(literal, css, literal)
        for name in ("--family-mono", "--av-mono-bg", "--av-mono-ink", "--av-text-xs", "--av-text-sm", "--av-text-md",
                     "--av-text-lg", "--av-text-xl", "--datebadge-text", "--tab-badge-text", "--nav-fade"):
            self.assertIn(f"var({name})", css, name)
            self.assertRegex(tokens, rf"{re.escape(name)}:", name)
        # Light and dark both define the monogram tint, as every other themed value does.
        self.assertEqual(tokens.count("--av-mono-bg:"), 3)

    def test_repo_names_break_only_after_the_slash(self):
        # Chrome gives no break opportunity after "/", so overflow-wrap:anywhere alone split "impecca|ble";
        # every place that prints owner/name must offer <wbr> right after the slash.
        app = (SITE / "app.js").read_text(encoding="utf-8")
        self.assertEqual(app.count('${esc(own)}/</span><wbr>'), 3)
        self.assertIn("esc(r.full_name).replace('/', '/<wbr>')", app)


if __name__ == "__main__":
    unittest.main()
