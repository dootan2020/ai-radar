"""Offline regressions from the 26 October audited snapshot."""

import json
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from radar import translate as nllb
from radar.translation_gemini import Config
from radar.translation_pipeline import invalidate_wrong_cache, translate_payload, validated
from radar.translation_semantics import changes_meaning
from radar.search_index import search_story_row


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "audited-headlines-live.json").read_text(encoding="utf-8"))
BAD_FIELDS = {
    107: ("title",), 238: ("summary",), 251: ("summary",), 142: ("title",),
    127: ("title",), 220: ("title",), 103: ("title", "summary"), 104: ("title",),
    125: ("summary",), 368: ("title",), 451: ("summary",), 840: ("title",),
    842: ("title",), 762: ("title",), 791: ("title",), 808: ("title",),
    109: ("title",),
}


class AuditedTranslationTests(unittest.TestCase):
    def test_all_seventeen_wrong_senses_are_rejected_before_glossary(self):
        self.assertEqual(set(BAD_FIELDS), {row["index"] for row in FIXTURE["stories"]})
        for row in FIXTURE["stories"]:
            for field in BAD_FIELDS[row["index"]]:
                with self.subTest(index=row["index"], field=field):
                    source, bad = row[field], row[field + "_vi"]
                    self.assertTrue(changes_meaning(source, bad))
                    self.assertIsNone(validated(source, bad, set()))
                    self.assertFalse(changes_meaning(source, source))

    def test_only_wrong_cache_entries_are_invalidated(self):
        groups = {}
        gemini_cache = {"A good unrelated title": "Một tiêu đề đúng"}
        nllb_cache = {"A good unrelated title": "Một tiêu đề đúng"}
        for row in FIXTURE["stories"]:
            for field in BAD_FIELDS[row["index"]]:
                source, bad = nllb.normalize(row[field]), row[field + "_vi"]
                groups[source] = {}
                gemini_cache[source] = bad
                segments = nllb.split_source(source)[1]
                if len(segments) == 1:
                    nllb_cache[segments[0]] = bad
        invalidate_wrong_cache(groups, nllb_cache, gemini_cache)
        self.assertEqual(gemini_cache, {"A good unrelated title": "Một tiêu đề đúng"})
        self.assertEqual(nllb_cache, {"A good unrelated title": "Một tiêu đề đúng"})

    def test_a_faithful_retranslation_can_enter_the_cache(self):
        source = "Mercury 3: Diffusion at scale"
        faithful = "Mercury 3: Khuếch tán ở quy mô lớn"
        self.assertFalse(changes_meaning(source, faithful))
        self.assertEqual(validated(source, faithful, set()), faithful)

    def test_glossary_repairs_audited_technical_senses(self):
        for row in FIXTURE["stories"]:
            if row["index"] in (104, 840):
                continue  # These context-dependent titles safely fall back to English.
            for field in BAD_FIELDS[row["index"]]:
                with self.subTest(index=row["index"], field=field):
                    source, bad = row[field], row[field + "_vi"]
                    repaired = nllb.apply_glossary(source, bad)
                    self.assertFalse(changes_meaning(source, repaired), repaired)

    def test_search_projection_carries_only_verified_editorial_headline(self):
        s107 = FIXTURE["stories"][0]
        projected = search_story_row(s107)
        self.assertEqual(projected["editorial_headline_vi"], s107["editorial_headline_vi"])
        self.assertTrue(projected["editorial_headline_verified"])
        self.assertIn("cat ket noi internet", projected["search_text"])
        unverified = search_story_row({**s107, "key_points": []})
        self.assertNotIn("editorial_headline_vi", unverified)

    def test_offline_pipeline_drops_bad_cache_and_published_translations(self):
        payload = deepcopy(FIXTURE)
        gemini_cache, nllb_cache = {}, {}
        for row in FIXTURE["stories"]:
            for field in BAD_FIELDS[row["index"]]:
                source, bad = nllb.normalize(row[field]), row[field + "_vi"]
                gemini_cache[source] = bad
                segments = nllb.split_source(source)[1]
                if len(segments) == 1:
                    nllb_cache[segments[0]] = bad
        with tempfile.TemporaryDirectory() as tmp:
            translate_payload(payload, nllb_cache, gemini_cache, config=Config(), budget=0,
                              previous=FIXTURE, ledger_path=Path(tmp) / "ledger.json")
        for row in payload["stories"]:
            for field in BAD_FIELDS[row["index"]]:
                with self.subTest(index=row["index"], field=field):
                    self.assertNotIn(field + "_vi", row)
        self.assertEqual(gemini_cache, {})


@unittest.skipUnless(shutil.which("node"), "Node required for offline JavaScript tests")
class AuditedHeadlineDisplayTests(unittest.TestCase):
    def test_verified_editorial_headline_is_shared_by_list_and_detail(self):
        program = """
import fs from 'node:fs';
import {headlineShown} from './site/editorial-headline.js';
import {storyTitle, renderStoryHTML} from './site/story.js';
const rows = JSON.parse(fs.readFileSync(process.argv[1], 'utf8')).stories;
const main = rows.find(row => row.index === 107);
const html = renderStoryHTML(main, new Map(), {isPage:true});
console.log(JSON.stringify({list:headlineShown(main), detail:storyTitle(main), html,
  unverified:headlineShown({...main, key_points:[]}),
  other:rows.filter(row => row.index !== 107).map(row => headlineShown(row))}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", program,
             str(ROOT / "tests" / "fixtures" / "audited-headlines-live.json")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        shown = json.loads(result.stdout)
        headline = FIXTURE["stories"][0]["editorial_headline_vi"]
        self.assertEqual(shown["list"], headline)
        self.assertEqual(shown["detail"], headline)
        self.assertIn(headline, shown["html"])
        self.assertNotIn("mô hình AI hàng rào", shown["html"])
        self.assertNotEqual(shown["unverified"], headline)


if __name__ == "__main__":
    unittest.main()
