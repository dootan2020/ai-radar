"""Tests for 7-day story search page (site/tra-cuu.html, site/tra-cuu.js, site/tra-cuu.css)."""

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from radar.search_index import normalize_vietnamese
from tests.test_vietnamese_ui import foreign_words, visible_html, js_literals, UI_KEYS, UI_SINKS, VIET_MARKS


class TraCuuPageTests(unittest.TestCase):
    def setUp(self):
        self.html_path = ROOT / "site" / "tra-cuu.html"
        self.js_path = ROOT / "site" / "tra-cuu.js"
        self.css_path = ROOT / "site" / "tra-cuu.css"
        self.fixture_path = ROOT / "tests" / "fixtures" / "radar-search.json"

    def test_required_files_exist(self):
        self.assertTrue(self.html_path.exists(), "site/tra-cuu.html must exist")
        self.assertTrue(self.js_path.exists(), "site/tra-cuu.js must exist")
        self.assertTrue(self.css_path.exists(), "site/tra-cuu.css must exist")
        self.assertTrue(self.fixture_path.exists(), "tests/fixtures/radar-search.json must exist")

    def test_tra_cuu_html_has_no_english_words(self):
        html = self.html_path.read_text(encoding="utf-8")
        texts = visible_html(html)
        leftovers = {}
        for t in texts:
            words = foreign_words(t)
            if words:
                leftovers[t] = words
        self.assertEqual(leftovers, {}, f"Foreign words found in tra-cuu.html: {leftovers}")

    def test_tra_cuu_js_has_no_english_words(self):
        source = self.js_path.read_text(encoding="utf-8")
        literals = js_literals(source)
        leftovers = {}
        for literal, before in literals:
            if "<" in literal and ">" in literal:
                for t in visible_html(literal):
                    words = foreign_words(t)
                    if words:
                        leftovers[t] = words
            elif VIET_MARKS.search(literal) or UI_KEYS.search(before) or UI_SINKS.search(before):
                words = foreign_words(literal)
                if words:
                    leftovers[literal] = words
        self.assertEqual(leftovers, {}, f"Foreign words found in tra-cuu.js: {leftovers}")

    def test_no_em_dash_in_visible_ui(self):
        html = self.html_path.read_text(encoding="utf-8")
        self.assertNotIn("—", html, "tra-cuu.html should not contain em-dash (—)")
        js = self.js_path.read_text(encoding="utf-8")
        # Ensure template literals with HTML do not have visible em-dash
        literals = js_literals(js)
        for literal, _ in literals:
            if "<" in literal and ">" in literal:
                for t in visible_html(literal):
                    self.assertNotIn("—", t, f"Visible string in tra-cuu.js should not contain em-dash: {t}")

    def test_search_fixture_integrity(self):
        with open(self.fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        stories = data.get("stories", [])
        self.assertGreaterEqual(len(stories), 300, "Fixture should contain at least 300 real stories")
        sources = data.get("sources", [])
        self.assertGreaterEqual(len(sources), 60, "Fixture should retain sources block")

        # Verify key queries return results
        queries = ["DeepSeek", "GPT-6.1", "Trí tuệ nhân tạo", "OpenAI", "Anthropic", "Apple", "Nvidia"]
        for q in queries:
            norm_q = normalize_vietnamese(q)
            q_words = norm_q.split()
            matched = [s for s in stories if all(w in s.get("search_text", "") for w in q_words)]
            self.assertGreater(len(matched), 0, f"Query '{q}' should find matches in fixture")

    def test_css_contains_bento_keynote_tokens(self):
        css = self.css_path.read_text(encoding="utf-8")
        self.assertIn("var(--tile-radius)", css)
        self.assertIn("var(--family)", css)
        self.assertIn("tabular-nums", css)
        self.assertIn("@media (max-width: 767px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def _run_harness(self, queries):
        js_code = """
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const searchJson = JSON.parse(fs.readFileSync('tests/fixtures/radar-search.json', 'utf8'));
const traCuuUrl = pathToFileURL(path.resolve('site/tra-cuu.js')).href;
const { normalizeVietnamese, groupStories } = await import(traCuuUrl);

const generatedAt = searchJson.generated_at;
const genMs = new Date(generatedAt).getTime();
const limit7dMs = genMs - 7 * 864e5;

function runQuery(query) {
  const normQ = normalizeVietnamese(query);
  const qWords = normQ.split(/\\s+/).filter(Boolean);
  const matched = searchJson.stories.filter(s => {
    const st = s.search_text || '';
    return qWords.every(w => st.includes(w));
  });

  const clusters = groupStories(matched, qWords, generatedAt);
  if (clusters.length === 0) {
    return { query, matchedCount: matched.length, topStory: null, clusters: [], timeline: [] };
  }

  const top = clusters[0];
  const timeline = clusters.slice(1);
  timeline.sort((a, b) => {
    if (!a.latestDate && b.latestDate) return 1;
    if (a.latestDate && !b.latestDate) return -1;
    return (b.latestDate || '').localeCompare(a.latestDate || '');
  });

  const within7d = timeline.filter(s => s.isWithin7Days);
  const older = timeline.filter(s => s.latestDate && !s.isWithin7Days);
  const undated = timeline.filter(s => !s.latestDate);

  const serializeCluster = c => ({
    title: c.primary.title,
    title_vi: c.primary.title_vi,
    kind: c.primary.kind,
    url: c.primary.url,
    sourceCount: c.sourceCount,
    daySpan: c.daySpan,
    latestDate: c.latestDate,
    isNews: c.isNews,
    isWithin7Days: c.isWithin7Days,
    publishers: Array.from(c.publishers)
  });

  return {
    query,
    matchedCount: matched.length,
    topStory: serializeCluster(top),
    clusters: clusters.map(serializeCluster),
    within7dCount: within7d.length,
    olderCount: older.length,
    undatedCount: undated.length,
    within7dDates: within7d.map(s => s.latestDate),
    olderDates: older.map(s => s.latestDate),
    undatedTitles: undated.map(s => s.primary.title)
  };
}

const inputQueries = %s;
const results = {};
for (const q of inputQueries) {
  results[q] = runQuery(q);
}
results.__meta = { generatedAt, limit7dMs };

process.stdout.write(JSON.stringify(results));
""" % json.dumps(queries)

        proc = subprocess.run(
            ["node", "--input-type=module", "-e", js_code],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        raw = proc.stdout.strip()
        json_start = raw.find("{")
        self.assertGreaterEqual(json_start, 0, "No JSON found in node output")
        return json.loads(raw[json_start:])

    def test_round2_point1_wrong_main_tile_fixed(self):
        """Point 1: Main tile must be a newsworthy story within 7 days, not a model listing."""
        res = self._run_harness(["deepseek", "tri tue nhan tao", "nvidia", "khongcoketqua"])
        
        # ?q=deepseek
        ds = res["deepseek"]["topStory"]
        self.assertIsNotNone(ds)
        self.assertTrue(ds["isNews"], "Main tile for deepseek must be news, not model/repo")
        self.assertNotEqual(ds["kind"], "model", "Main tile for deepseek must not be a model listing")
        self.assertIn("semafor", ds["url"])
        self.assertIn("Huawei", ds["title"])

        # ?q=tri tue nhan tao
        ttnt = res["tri tue nhan tao"]["topStory"]
        self.assertIsNotNone(ttnt)
        self.assertTrue(ttnt["isNews"])
        self.assertTrue(ttnt["isWithin7Days"])
        self.assertIn("Stargate", ttnt["title"])

        # ?q=nvidia
        nv = res["nvidia"]["topStory"]
        self.assertIsNotNone(nv)
        self.assertTrue(nv["isNews"])
        self.assertGreaterEqual(nv["sourceCount"], 2)

        # ?q=khongcoketqua
        no_res = res["khongcoketqua"]["topStory"]
        self.assertIsNone(no_res)

    def test_round2_point2_timeline_out_of_order_fixed(self):
        """Point 2: Timeline must be strictly sorted newest first."""
        res = self._run_harness(["deepseek", "tri tue nhan tao", "nvidia"])

        for q in ["deepseek", "tri tue nhan tao", "nvidia"]:
            data = res[q]
            w7d = data["within7dDates"]
            for i in range(len(w7d) - 1):
                self.assertGreaterEqual(w7d[i], w7d[i + 1], f"7-day timeline for '{q}' not newest first at index {i}")

            older = data["olderDates"]
            for i in range(len(older) - 1):
                self.assertGreaterEqual(older[i], older[i + 1], f"Older timeline for '{q}' not newest first at index {i}")

        # DeepSeek specifically: June 28 (2026-06-28) must sit at the bottom of older, well after Oct 1 and Sep 23
        ds_older = res["deepseek"]["olderDates"]
        self.assertTrue(any("2026-06-28" in d for d in ds_older[-2:]), "June 28 must be at the very bottom")
        self.assertTrue(ds_older[0].startswith("2026-09-23"), "Sep 23 must be at the top of older")

    def test_round2_point3_seven_days_integrity(self):
        """Point 3: Nothing older than seven days sits under the seven-day heading."""
        res = self._run_harness(["deepseek", "tri tue nhan tao", "nvidia"])
        limit7d_ms = res["__meta"]["limit7dMs"]

        for q in ["deepseek", "tri tue nhan tao", "nvidia"]:
            data = res[q]
            # Every item in within7d must have date >= limit7d
            for d in data["within7dDates"]:
                import datetime
                dt = datetime.datetime.fromisoformat(d.replace("Z", "+00:00"))
                ms = dt.timestamp() * 1000
                self.assertGreaterEqual(ms, limit7d_ms, f"Date {d} in 7-day timeline is older than cutoff")

            # Every item in older must have date < limit7d
            for d in data["olderDates"]:
                import datetime
                dt = datetime.datetime.fromisoformat(d.replace("Z", "+00:00"))
                ms = dt.timestamp() * 1000
                self.assertLess(ms, limit7d_ms, f"Date {d} in older timeline is within 7 days")

        # For tri tue nhan tao: exactly 1 in 7 days (28/9), 3 older (23/9, 21/9, 21/9)
        self.assertEqual(res["tri tue nhan tao"]["within7dCount"], 1)
        self.assertEqual(res["tri tue nhan tao"]["olderCount"], 3)
        self.assertEqual(res["tri tue nhan tao"]["undatedCount"], 0)

        # For nvidia: 1 undated row
        self.assertEqual(res["nvidia"]["undatedCount"], 1)
        self.assertIn("Nvidia dựng 'hàng rào' ngăn tác nhân AI 'nổi loạn'", res["nvidia"]["undatedTitles"])

    def test_round2_point4_headings_and_no_duplicate_days(self):
        """Point 4: Day headings must use h3 and not be duplicated in the DOM."""
        js = self.js_path.read_text(encoding="utf-8")
        # Check semantic hierarchy
        self.assertIn('<h2 class="tc-section-title"', js)
        self.assertIn('<h3 class="tc-day-title">', js)
        self.assertIn('<h4 class="tc-card-title">', js)

        # Verify in tra-cuu.js that dayGroups deduplicates by dayKey
        self.assertIn("const dayGroups = new Map()", js)
        self.assertIn("dayGroups.has(k)", js)

    def test_round2_point5_monogram_fallbacks_for_blank_squares(self):
        """Point 5: Sources without verified logos get monograms, no blank grey squares."""
        js = self.js_path.read_text(encoding="utf-8")
        css = self.css_path.read_text(encoding="utf-8")

        self.assertIn("monogram", js)
        self.assertIn("watchImageErrors", js)
        self.assertIn("safeFaceOfStory", js)
        self.assertIn("safeFaceOfSource", js)

        # Check CSS fallback styling
        self.assertIn(".av:not(:has(img))::before", css)
        self.assertIn(".av.is-fallback::before", css)
        self.assertIn("--av-mono-ink", css)
        self.assertIn("--av-mono-bg", css)

    def test_round2_point6_search_placeholder_fits_mobile(self):
        """Point 6: Search placeholder shortened to avoid cutoff at 375px."""
        html = self.html_path.read_text(encoding="utf-8")
        css = self.css_path.read_text(encoding="utf-8")

        self.assertIn('placeholder="Nhập một cái tên..."', html)
        placeholder_match = re.search(r'placeholder="([^"]+)"', html)
        self.assertIsNotNone(placeholder_match)
        ph_text = placeholder_match.group(1)
        self.assertLessEqual(len(ph_text), 25, f"Placeholder is too long: {ph_text}")

        # Check mobile CSS padding
        self.assertIn(".tc-search-form", css)
        self.assertIn(".tc-search-input", css)

    def test_round3_most_covered_story_wins_main_tile(self):
        """Round 3: Main tile must be the story the most sources covered.
        Proves three requirements:
        1. For 'GPT-6.1', the main tile is 'Introducing GPT-6.1 Sol' (4 publishers, kind: model, within 7 days).
        2. For 'deepseek', it is still the Semafor story (Huawei partnership).
        3. For every query in tests, no story with fewer sources outranks one with more inside the 7-day window.
        """
        test_queries = ["GPT-6.1", "deepseek", "tri tue nhan tao", "nvidia", "OpenAI", "Anthropic", "Apple"]
        res = self._run_harness(test_queries)

        # 1. For GPT-6.1: Main tile is "Introducing GPT-6.1 Sol"
        gpt6 = res["GPT-6.1"]["topStory"]
        self.assertIsNotNone(gpt6, "GPT-6.1 must have a top story")
        self.assertEqual(gpt6["title"], "Introducing GPT-6.1 Sol")
        self.assertEqual(gpt6["sourceCount"], 4)
        self.assertTrue(gpt6["isWithin7Days"], "GPT-6.1 Sol must be inside seven-day window")
        self.assertEqual(
            sorted(gpt6["publishers"]),
            ["amazon", "genk", "openai", "simon-willison"],
            "GPT-6.1 Sol must have 4 publishers: amazon, genk, openai, simon-willison"
        )

        # 2. For deepseek: It is still the Semafor story
        ds = res["deepseek"]["topStory"]
        self.assertIsNotNone(ds, "deepseek must have a top story")
        self.assertEqual(ds["title"], "Deepseek and Huawei partner to develop AI software")
        self.assertIn("semafor", ds["url"])
        self.assertTrue(ds["isWithin7Days"])

        # 3. For every query in tests: No story with fewer sources outranks one with more inside the 7-day window
        for q in test_queries:
            clusters = res[q]["clusters"]
            w7d_clusters = [c for c in clusters if c["isWithin7Days"]]
            for i in range(len(w7d_clusters) - 1):
                c1 = w7d_clusters[i]
                c2 = w7d_clusters[i + 1]
                self.assertGreaterEqual(
                    c1["sourceCount"],
                    c2["sourceCount"],
                    f"Query '{q}': inside 7-day window, story '{c1['title']}' ({c1['sourceCount']} sources) "
                    f"is outranked by story '{c2['title']}' ({c2['sourceCount']} sources)"
                )

            # Within-7-day window always comes before older stories
            seen_older = False
            for c in clusters:
                if not c["isWithin7Days"]:
                    seen_older = True
                elif seen_older:
                    self.fail(f"Query '{q}': story '{c['title']}' within 7 days was ranked after older story")

    def test_round2_vietnamese_ui_strings(self):
        """Ensure all custom Vietnamese UI strings comply with language and formatting rules."""
        strings = [
            "Dòng thời gian 7 ngày qua",
            "Không có câu chuyện nào khác về tên này trong 7 ngày qua.",
            "Trước 7 ngày qua",
            "chuyện cũ hơn",
            "Chưa rõ ngày xuất bản",
            "chuyện",
            "Các mục dưới đây không có ngày xuất bản trong dữ liệu nguồn.",
            "Nhập một cái tên..."
        ]
        for s in strings:
            fw = foreign_words(s)
            self.assertEqual(fw, [], f"Foreign words found in '{s}': {fw}")
            self.assertNotIn("—", s, f"Em-dash found in '{s}'")

    def test_round6_home_entry_to_tra_cuu(self):
        """Requirement 2: Readers must reach site/tra-cuu.html from site/index.html.
        Verifies header search control beside ed-link, proper icon, and no search index loading on home.
        """
        index_html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        styles_css = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")

        # Home header must contain .tc-link pointing to tra-cuu.html
        self.assertRegex(index_html, r'<a\s+class="tc-link"\s+href="tra-cuu\.html"')
        self.assertIn('aria-label="Tra cứu câu chuyện AI"', index_html)
        self.assertIn('<use href="#i-search"/>', index_html)
        self.assertIn('<span class="tc-label">Tra cứu</span>', index_html)
        self.assertIn('<symbol id="i-search"', index_html)

        # Home CSS must style .tc-link in header and adapt on mobile
        self.assertIn(".tc-link{", styles_css)
        self.assertIn(".tc-link:hover{", styles_css)
        self.assertIn(".tc-link .tc-label{display:none}", styles_css)

        # Home must NEVER preload or load radar-search.json
        self.assertNotIn("radar-search.json", index_html)
        app_js = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("radar-search.json", app_js)

    def test_round6_tra_cuu_navigation_resolves_to_home(self):
        """Requirement 3: Desktop section links, phone tab bar, and wordmark on site/tra-cuu.html
        must take the reader to matching home sections and home.
        """
        html = self.html_path.read_text(encoding="utf-8")
        index_html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        app_js = (ROOT / "site" / "app.js").read_text(encoding="utf-8")

        # 1. Wordmark takes reader to home
        self.assertRegex(html, r'<a class="brand" href="index\.html"[^>]*>ai<b>·</b>radar</a>')

        # 2. Desktop section links (.nav a)
        nav_match = re.search(r'<nav class="nav" id="nav"[^>]*>([\s\S]*?)</nav>', html)
        self.assertIsNotNone(nav_match, "tra-cuu.html must have desktop nav")
        nav_links = re.findall(r'href="([^"]+)"', nav_match.group(1))
        self.assertGreaterEqual(len(nav_links), 9, "tra-cuu.html nav must have at least 9 section links")

        for href in nav_links:
            self.assertTrue(href.startswith("index.html#"), f"Nav link {href} must point to index.html section")
            sec_id = href.split("#", 1)[1]
            # Check that sec_id is defined in CHAPTERS in app.js or in index.html
            found = f"id:'{sec_id}'" in app_js or f'id="{sec_id}"' in index_html
            self.assertTrue(found, f"Nav link target #{sec_id} must exist in index.html or app.js chapters")

        # 3. Phone tab bar (#tabs a)
        tabs_match = re.search(r'<nav class="tabs" id="tabs"[^>]*>([\s\S]*?)</nav>', html)
        self.assertIsNotNone(tabs_match, "tra-cuu.html must have phone tab bar")
        tab_links = re.findall(r'<a\s+href="([^"]+)"', tabs_match.group(1))
        self.assertEqual(len(tab_links), 5, "Phone tab bar must have 5 tabs")

        for href in tab_links:
            self.assertTrue(href.startswith("index.html#"), f"Tab link {href} must point to index.html section")
            sec_id = href.split("#", 1)[1]
            found = f'id="{sec_id}"' in index_html or f'id="{sec_id}"' in app_js or f"id:'{sec_id}'" in app_js
            self.assertTrue(found, f"Tab link target #{sec_id} must exist in home page")


if __name__ == "__main__":
    unittest.main()

