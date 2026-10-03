"""Proper-name regressions using titles captured in plans/nhap/live-radar.json."""

import unittest

from radar import translate as tr
from radar.translation_names import names_in


# Source titles are verbatim from the captured snapshot; deliberately corrupted
# outputs exercise the guard, not the quality of an offline stand-in translator.
REAL_TITLES = [
    ("How Claude is uplifting biomolecular modeling", "Làm thế nào Claude đang nâng cao mô hình hóa học", "Claude"),
    ("Google announces Gemini 4 Argon AI model, but you can't use it yet",
     "Google công bố mô hình AI Gemini 4 Argon, nhưng bạn vẫn không thể sử dụng nó.", "Gemini"),
    ("Bringing Grok to Everyone", "Đưa Grok cho mọi người", "Grok"),
    ("Mistral CEO says U.S. AI safety debate masks competitors' 'negligence'",
     "Giám đốc điều hành Mistral nói cuộc tranh luận an toàn AI của Mỹ che giấu sự bất cẩn của đối thủ", "Mistral"),
]


class ProperNameTests(unittest.TestCase):
    def test_model_qualifiers_do_not_become_global_names(self):
        cases = (
            ("Mistral Small 3", "Small"),
            ("Mistral Medium 3", "Medium"),
            ("Grok 4 Fast", "Fast"),
            ("Gemini 2.5 Flash", "Flash"),
            ("Grok Code Fast 1", "Code"),
            ("Grok Voice Think Fast 1", "Voice"),
            ("Muse Image 2", "Image"),
            ("Gemini 2.5 Beta", "Beta"),
        )
        for model, qualifier in cases:
            with self.subTest(model=model):
                source = f"Building tools with {model} and {qualifier} examples"
                self.assertIn(model, names_in(source))
                self.assertNotIn(qualifier, names_in(source))
                good = f"Xây dựng công cụ với {model} và các ví dụ phù hợp"
                self.assertIsNone(tr.rejection(source, good))
                bad = good.replace(model, model.replace(qualifier, "").replace("  ", " ")) + f" ({qualifier})"
                self.assertTrue((tr.rejection(source, bad) or "").startswith("name lost:"))

    def test_model_spelling_repair_leaves_standalone_qualifier_alone(self):
        for model, qualifier in (("Mistral Small 3", "Small"), ("Mistral Medium 3", "Medium"),
                                 ("Grok 4 Fast", "Fast"), ("Gemini 2.5 Flash", "Flash")):
            with self.subTest(model=model):
                source = f"{model} offers {qualifier} examples"
                translated = f"{model.lower()} cung cấp ví dụ {qualifier.lower()}"
                self.assertEqual(tr.apply_glossary(source, translated),
                                 f"{model} cung cấp ví dụ {qualifier.lower()}")

    def test_standalone_generic_words_can_be_translated(self):
        for word, meaning in (("Small", "nhỏ"), ("Medium", "vừa"), ("Fast", "nhanh"),
                              ("Flash", "chớp nhoáng"), ("Code", "mã"), ("Image", "hình ảnh"),
                              ("Voice", "giọng nói"), ("Beta", "thử nghiệm")):
            with self.subTest(word=word):
                source = f"Learn about {word} examples today"
                translated = f"Tìm hiểu về các ví dụ {meaning} hôm nay"
                self.assertEqual(tr.compose(source, {source: translated}), (translated, None))

    def test_contextual_qualifiers_work_in_cached_and_fresh_translations(self):
        source = "Mistral Small 3 improves Small models today"
        good = "Mistral Small 3 cải thiện các mô hình nhỏ hôm nay"
        bad = "Mistral 3 cải thiện các mô hình Small hôm nay"
        for cached in (False, True):
            for translated, accepted in ((good, True), (bad, False)):
                with self.subTest(cached=cached, accepted=accepted):
                    story = dict(title=source, title_vi="stale", coverage=[dict(title=source)])
                    cache = {source: translated} if cached else {}

                    def factory():
                        self.assertFalse(cached, "cached strings must not load a model")
                        return lambda batch: [translated for _ in batch]

                    stats, alive = tr.translate_payload(dict(stories=[story]), cache, factory=factory)
                    self.assertFalse(alive)
                    self.assertEqual(stats["translated"], int(accepted))
                    self.assertEqual(stats["rejected"], int(not accepted))
                    for row in (story, story["coverage"][0]):
                        if accepted:
                            self.assertEqual(row["title_vi"], good)
                        else:
                            self.assertNotIn("title_vi", row)

    def test_real_titles_reject_translated_names(self):
        for source, translated, name in REAL_TITLES:
            with self.subTest(name=name):
                self.assertIsNone(tr.rejection(source, translated))
                reason = tr.rejection(source, translated.replace(name, "tên bị dịch"))
                self.assertTrue(reason.startswith("name lost:"))
                self.assertIn(name, reason)

    def test_missing_name_cannot_hide_inside_a_larger_word(self):
        self.assertEqual(tr.rejection("Bringing Grok to Everyone", "Đưa Grokking cho mọi người"), "name lost: Grok")

    def test_sora_family_is_protected_without_a_version(self):
        # Sora is not present in this captured snapshot; this is a separate family test.
        self.assertEqual(tr.rejection("Creating videos with Sora", "Tạo video với bầu trời mới"), "name lost: Sora")

    def test_cached_bad_translation_falls_back_without_model_loading(self):
        for title, translated, name in REAL_TITLES:
            with self.subTest(name=name):
                story = dict(title=title, title_vi=translated, coverage=[dict(title=title, title_vi=translated)])
                payload = dict(stories=[story])
                cache = {tr.normalize(title): translated.replace(name, "tên bị dịch")}
                def forbidden_model():
                    self.fail("a fully cached payload must not load a model")
                stats, alive = tr.translate_payload(payload, cache, factory=forbidden_model)
                self.assertFalse(alive)
                self.assertEqual(stats["rejected"], 1)
                self.assertNotIn("title_vi", story)
                self.assertNotIn("title_vi", story["coverage"][0])
                self.assertEqual(story["title"], title)

    def test_name_case_is_restored(self):
        self.assertEqual(tr.apply_glossary("Bringing Grok to Everyone", "Đưa GROK cho mọi người"), "Đưa Grok cho mọi người")

    def test_fresh_model_output_gets_the_same_guard(self):
        source, translated, name = REAL_TITLES[0]
        payload = dict(stories=[dict(title=source)])
        stats, _ = tr.translate_payload(payload, {}, factory=lambda: lambda batch: [translated.replace(name, "tên bị dịch")])
        self.assertEqual(stats["rejected"], 1)
        self.assertEqual(stats["new_segments"], 1)
        self.assertNotIn("title_vi", payload["stories"][0])

    def test_versioned_model_names_come_from_classifier(self):
        for name in ("Voxtral", "Qwen3.8", "WeatherNext 2"):
            with self.subTest(name=name):
                source = "Building tools with " + name
                good = "Xây dựng công cụ với " + name
                self.assertIsNone(tr.rejection(source, good))
                # Keep the number check satisfied while corrupting the name.
                bad = good.replace(name.split()[0].split("3")[0], "tên bị dịch")
                self.assertTrue(tr.rejection(source, bad).startswith("name lost:"))

    def test_catalog_source_and_snapshot_repo_identities(self):
        cases = [
            (dict(stories=[dict(title="Reading Simon Willison every morning")]),
             "Reading Simon Willison every morning", "Đọc một tác giả vào mỗi buổi sáng"),
            (dict(sources=[dict(name="Example Research", publisher="example")],
                  stories=[dict(title="Reading Example Research every morning")]),
             "Reading Example Research every morning", "Đọc nghiên cứu minh họa vào mỗi buổi sáng"),
            (dict(repos=[dict(id="author/Compass", description="Build your tools with Compass today")]),
             "Build your tools with Compass today", "Xây dựng công cụ của bạn với la bàn hôm nay"),
        ]
        for payload, source, translated in cases:
            with self.subTest(source=source):
                counts, rejected = tr.apply(payload, {source: translated})
                self.assertEqual(counts["rejected"], 1)
                self.assertTrue(rejected[0]["reason"].startswith("name lost:"))

    def test_repo_words_are_not_global_and_generic_title_case_is_translatable(self):
        source = "All Requests Are Welcome Today"
        payload = dict(repos=[dict(id="psf/requests")], stories=[dict(title=source)])
        counts, _ = tr.apply(payload, {source: "Mọi yêu cầu đều được chào đón hôm nay"})
        self.assertEqual(counts["translated"], 1)
        self.assertEqual(counts["rejected"], 0)


if __name__ == "__main__":
    unittest.main()
