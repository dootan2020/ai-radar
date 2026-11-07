"""News pictures are drawn whole on every surface: the story page and modal, feed cards, thumbnails, the extension.

Charts, benchmark tables and screenshots carry a story's fact at their edges; the captain found one cut in half on
2026-11-07 ("ảnh ... bị cắt mất ảnh ... không bị cắt thông tin"). The CSS checks are wiring checks, not browser
geometry proof; the before/after captures in the pull request are the geometry proof.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
EXT = ROOT / "extension"
STYLESHEETS = [SITE / "feed.css", SITE / "story.css", EXT / "feed.css", EXT / "story.css"]

# The only pictures allowed to be cropped. Avatars are faces, not news; the backdrop is a blurred copy whose crop
# hides nothing because the whole picture sits on top of it; a stream's YouTube poster (4:3 hqdefault) carries its
# 16:9 frame between black bars baked into the file, and cover at 16:9 trims exactly those bars.
MAY_COVER = {".av-img", ".media-backdrop", ".tile-video img"}
NEWS_PICTURES = {".media-img", ".story-media-img", ".thumb img:not(.media-backdrop)", ".repo-img img", ".model-img img"}


def rules(css):
    """(selectors, declarations) for every innermost rule, inside or outside an at-rule."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for match in re.finditer(r"\{([^{}]*)\}", css):
        head = css[:match.start()]
        start = max(head.rfind("{"), head.rfind("}")) + 1
        selectors = [s.strip() for s in head[start:].split(",") if s.strip()]
        declarations = {}
        for part in match.group(1).split(";"):
            if ":" in part:
                name, value = part.split(":", 1)
                declarations[name.strip()] = value.strip()
        out.append((selectors, declarations))
    return out


class NewsPictureCssTests(unittest.TestCase):
    def test_only_non_news_pictures_are_cropped(self):
        for sheet in STYLESHEETS:
            for selectors, declarations in rules(sheet.read_text(encoding="utf-8")):
                if declarations.get("object-fit") == "cover":
                    with self.subTest(sheet=sheet.relative_to(ROOT).as_posix(), selectors=selectors):
                        self.assertLessEqual(set(selectors), MAY_COVER)

    def test_every_news_picture_is_drawn_whole(self):
        for sheet in (SITE / "feed.css", SITE / "story.css"):
            for selectors, declarations in rules(sheet.read_text(encoding="utf-8")):
                for selector in set(selectors) & NEWS_PICTURES:
                    if "object-fit" in declarations:
                        with self.subTest(sheet=sheet.name, selector=selector):
                            self.assertEqual(declarations["object-fit"], "contain")
        seen = {s for sheet in (SITE / "feed.css", SITE / "story.css")
                for selectors, d in rules(sheet.read_text(encoding="utf-8")) if d.get("object-fit") == "contain"
                for s in selectors}
        self.assertLessEqual(NEWS_PICTURES, seen)

    def test_frames_reserve_their_place_before_the_picture_arrives(self):
        found = {}
        for sheet in (SITE / "feed.css", SITE / "story.css"):
            for selectors, declarations in rules(sheet.read_text(encoding="utf-8")):
                for selector in selectors:
                    if selector in (".media", ".story-media-frame") and "aspect-ratio" in declarations:
                        found.setdefault(selector, declarations["aspect-ratio"])
                        self.assertIn("overflow", declarations, selector)
        self.assertEqual(found, {".media": "16 / 9", ".story-media-frame": "16 / 9"})

    def test_news_pictures_do_not_zoom_past_their_frame(self):
        css = (SITE / "feed.css").read_text(encoding="utf-8")
        for selectors, declarations in rules(css):
            if "transform" in declarations and "none" not in declarations["transform"]:
                for selector in selectors:
                    with self.subTest(selector=selector):
                        self.assertNotRegex(selector, r"\.media-img|\.thumb img|\.repo-img img|\.model-img img")

    def test_backdrop_keeps_its_blur_through_the_blur_up_and_reduced_motion(self):
        # Rules that sharpen or unfilter thumbnail pictures must leave the backdrop out.
        for selectors, declarations in rules((SITE / "feed.css").read_text(encoding="utf-8")):
            if "filter" in declarations and not declarations["filter"].startswith("blur(var(--media-backdrop-blur))"):
                for selector in selectors:
                    if re.search(r"\.thumb img", selector):
                        with self.subTest(selector=selector):
                            self.assertIn(":not(.media-backdrop", selector)

    def test_photo_card_type_never_covers_the_picture(self):
        # The lead and wide photo cards are two rows: the picture alone in the first, the type and its dark band in
        # the second. The old card stacked the type on the picture in one grid area.
        merged = {}
        for selectors, declarations in rules((SITE / "feed.css").read_text(encoding="utf-8")):
            for selector in selectors:
                if selector.startswith(".card-photo"):
                    merged.setdefault(selector, {}).update(declarations)
        rows = lambda area: area.split("/")[0].strip()
        self.assertIn(") auto /", merged[".card-photo"]["grid-template"])
        self.assertEqual(rows(merged[".card-photo > .photo-body"]["grid-area"]), "2")
        self.assertEqual(rows(merged[".card-photo > .media::after"]["grid-area"]), "2")
        # The picture is placed out of flow in the first row's grid area: it fills that row and never sizes it.
        picture = merged[".card-photo > .media .media-img"]
        self.assertIn("grid-area", picture)
        self.assertEqual(rows(picture["grid-area"]), "1")
        for selector, declarations in merged.items():
            if ".photo-body" in selector and "grid-area" in declarations:
                with self.subTest(selector=selector):
                    self.assertEqual(rows(declarations["grid-area"]), "2")
        # The picture row is at least a 16:9 frame of the card's width, reserved by CSS before the picture loads.
        floor = merged[".card-photo > .media::before"]
        self.assertEqual((rows(floor["grid-area"]), floor["aspect-ratio"]), ("1", "16 / 9"))

    def test_extension_carries_the_same_stylesheets(self):
        for name in ("feed.css", "story.css"):
            with self.subTest(name=name):
                self.assertEqual((EXT / name).read_text(encoding="utf-8").replace("\r\n", "\n"),
                                 (SITE / name).read_text(encoding="utf-8").replace("\r\n", "\n"))


class NewsPictureMarkupTests(unittest.TestCase):
    def test_feed_pictures_sit_on_their_backdrop(self):
        for path in (SITE / "feed.js", EXT / "feed.js"):
            source = path.read_text(encoding="utf-8")
            media = re.search(r"function mediaHTML\(img, size\) \{[\s\S]*?\n\}", source).group()
            self.assertIn("${mediaBackdrop(img.src, { loading })}<img class=\"media-img\"", media)
            # The hot list is the feed's one thumbnail list since 07/11 ("Vừa đăng" shows clock and headline only).
            thumbs = [line for line in source.splitlines() if 'class="thumb' in line and "<img" in line]
            self.assertEqual(len(thumbs), 1, path)
            for line in thumbs:
                with self.subTest(path=path.relative_to(ROOT).as_posix(), line=line.strip()[:60]):
                    self.assertIn("${mediaBackdrop(img.src)}<img", line)

    @unittest.skipUnless(shutil.which("node"), "Node required to render the story view")
    def test_story_view_frames_the_whole_picture(self):
        script = r"""
import { renderStoryHTML } from '%s';
const story = {id:'s1', title:'A chart', url:'https://example.com/a', kind:'post',
  image:{src:'https://example.com/chart.png?a=1&b=2', via:'og:image'}};
process.stdout.write(JSON.stringify(['modal','page'].map(k => renderStoryHTML(story, new Map(), k === 'page' ? {isPage:true} : {isModal:true}))));
"""
        for module in (SITE / "story.js", EXT / "story.js"):
            with self.subTest(module=module.relative_to(ROOT).as_posix()):
                run = subprocess.run(["node", "--input-type=module", "-e", script % module.as_uri()],
                                     capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
                for html in json.loads(run.stdout):
                    frame = re.search(r'<div class="story-media-frame">(.*?)</div>', html, re.S)
                    self.assertTrue(frame, html)
                    images = re.findall(r'<img class="([^"]+)" src="([^"]+)"', frame.group(1))
                    self.assertEqual([c for c, _ in images], ["media-backdrop", "story-media-img"])
                    self.assertEqual({s for _, s in images}, {"https://example.com/chart.png?a=1&amp;b=2"})
                    self.assertIn('alt=""', frame.group(1).split("<img", 2)[1])


if __name__ == "__main__":
    unittest.main()
