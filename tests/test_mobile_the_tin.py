"""The front page's story cards on a phone (captain, 11/11 10:50, two Samsung News screens: "Trên Mobile làm sạch sẽ
kiểu như vậy. Nhớ tuân thủ design system"): below 768 px every story is its own card with the bento tile's corner,
the source over a headline of up to four lines, a square picture to the right and the time under both; a notable
story keeps a full-width picture above; "Chuyện lớn" becomes cards led by their rank. Tablet and desktop keep the
bento cards as they were. tests/capture-mobile-the-tin.mjs renders the fixture offline and measures it."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = (ROOT / "site", ROOT / "extension")
PHONES = ("320", "375", "375-toi", "414")


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def browser_ready():
    if not shutil.which("node"):
        return False
    chrome = [Path("C:/Program Files/Google/Chrome/Application/chrome.exe"), Path("/usr/bin/google-chrome"),
              Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    if not any(p.exists() for p in chrome):
        return False
    probe = subprocess.run(["node", "--input-type=module", "-e", "await import('puppeteer')"], cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
    return probe.returncode == 0


def rendered():
    if not hasattr(rendered, "out"):
        run = subprocess.run(["node", "tests/capture-mobile-the-tin.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=300)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        rendered.out = json.loads(run.stdout.strip().splitlines()[-1])
    return rendered.out


class Tokens(unittest.TestCase):
    def test_the_card_is_built_from_named_tokens_in_both_copies(self):
        for folder in FOLDERS:
            tokens, css = read(folder / "tokens.css"), read(folder / "trang-msn.css")
            for name, value in (("--story-card-r", "var(--msn-card-r)"), ("--story-card-pad", "var(--space-16)"),
                                ("--story-card-gap", "var(--space-12)"), ("--story-card-pic-r", "var(--radius-8)"),
                                ("--story-card-title", "var(--msn-title-wide)"), ("--story-card-title-big", "var(--msn-title-big)"),
                                ("--story-card-rank", "var(--num-md)")):
                self.assertIn(f"{name}: {value};", tokens, f"{folder.name}: {name}")
            self.assertIn("--story-card-pic: clamp(80px, 31cqi, 112px);", tokens)
            self.assertNotIn("--bento-thumb", tokens + css, f"{folder.name}: the old thumbnail tokens are gone")
            # The card's rules live only in the phone block of the front page's bands.
            phone = css[css.index("@media (max-width: 767px) {\n  :root { --bento-cols: 1;"):]
            phone = phone[:phone.index("\n}\n")]
            for rule in ('grid-template-areas: "mark who pic" "title title pic" "when when when";',
                         'grid-template-areas: "num mark who pic" "num title title pic" "num when when when";'):
                self.assertIn(rule, phone)
                self.assertEqual(css.count(rule), 1, rule)
            self.assertEqual(len(re.findall(r"var\(--story-card-", css)), len(re.findall(r"var\(--story-card-", phone)))

    def test_a_phone_card_picture_is_asked_for_at_its_size(self):
        for folder in FOLDERS:
            self.assertIn("card: '(max-width: 767px) 112px, (max-width: 1023px) 34vw, 25vw' };", read(folder / "feed.js"))


class SourceLogos(unittest.TestCase):
    """avatars.githubusercontent.com/<login> answers an organisation with GitHub's grey placeholder (11/11: NVIDIA,
    openai, google, anthropics showed the octocat on every card); github.com/<login>.png follows to the real picture."""

    @unittest.skipUnless(shutil.which("node"), "node is needed to run faces.js")
    def test_every_github_face_asks_for_the_account_picture(self):
        for folder in FOLDERS:
            script = ("const f = await import(process.argv[1]);"
                      "const out = Object.values(f.GH_IDENT).concat(['mattpocock'])"
                      ".map(id => /src=\"([^\"]+)\"/.exec(f.avatar({kind: 'gh', id, label: id}, 'xs'))[1]);"
                      "console.log(JSON.stringify(out));")
            run = subprocess.run(["node", "--input-type=module", "-e", script, (folder / "faces.js").as_uri()],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            urls = json.loads(run.stdout)
            self.assertTrue(urls)
            for url in urls:
                self.assertRegex(url, r"^https://github\.com/[\w.%-]+\.png\?size=40$", folder.name)

    def test_no_script_builds_the_placeholder_address(self):
        for folder in FOLDERS:
            for js in folder.glob("*.js"):
                self.assertNotRegex(read(js), r"avatars\.githubusercontent\.com/\$\{", js.name)

    def test_meta_is_the_meta_organisation(self):
        for folder in FOLDERS:
            self.assertIn("'meta':'meta'", read(folder / "faces.js"))
            self.assertNotIn("'facebook'", read(folder / "faces.js"))

    def test_the_morning_edition_admits_the_github_redirect(self):
        html = read(ROOT / "site" / "ban-tin.html")
        img = re.search(r"img-src ([^;]+);", html).group(1).split()
        self.assertIn("https://github.com", img)
        self.assertIn("https://avatars.githubusercontent.com", img)


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered cards")
class RenderedCards(unittest.TestCase):
    def test_no_errors_no_sideways_scroll_no_small_text_no_shift(self):
        out = rendered()
        self.assertEqual(out["errors"], [])
        for key, page in out["runs"].items():
            self.assertFalse(page["sideways"], key)
            self.assertEqual(page["smallCount"], 0, f"{key}: {page['small']}")
            self.assertLessEqual(page["shift"], 0.1, key)

    def test_every_phone_story_is_a_calm_card(self):
        for key in PHONES:
            page = rendered()["runs"][key]
            self.assertGreater(len(page["cards"]), 5, key)
            for c in page["cards"]:
                where = f"{key} {c['title']}"
                self.assertEqual((c["display"], c["radius"], c["border"], c["pad"]), ("grid", "12px", "0px none", "16px"), where)
                self.assertIsNone(c["sum"], f"{where}: no dek on a phone card")
                title, who, when = c["titleBox"], c["who"], c["when"]
                self.assertLess(who["y"], title["y"], where)
                bottom = max(title["y"] + title["h"], (c["pic"] or title)["y"] + (c["pic"] or title)["h"])
                self.assertGreaterEqual(when["y"], bottom, f"{where}: the time sits under the headline and picture")
                pic = c["pic"]
                if pic is None:
                    self.assertGreater(title["w"], c["w"] * 0.8, f"{where}: without a picture the headline takes the width")
                elif "nc-wide" in c["cls"] or "nc-big" in c["cls"]:
                    self.assertLess(pic["y"] + pic["h"], who["y"] + 1, f"{where}: a notable story's picture is on top")
                    self.assertGreater(pic["w"], c["w"] * 0.85, where)
                else:
                    self.assertEqual(pic["w"], pic["h"], f"{where}: square picture")
                    self.assertTrue(80 <= pic["w"] <= 112, f"{where}: {pic['w']}")
                    self.assertGreaterEqual(pic["x"], title["x"] + title["w"], f"{where}: the picture is right of the headline")
                    self.assertEqual(pic["radius"], "8px", where)

    def test_cards_below_the_first_screen_wait_for_their_pictures(self):
        for key in PHONES:
            page = rendered()["runs"][key]
            far = [c for c in page["cards"] if c["img"] and c["y"] > 2 * page["screen"]]
            self.assertTrue(far, key)
            for c in far:
                self.assertEqual(c["img"]["loading"], "lazy", key)
                self.assertTrue(c["img"]["waiting"] or not c["img"]["src"], f"{key} {c['title']}: fetched too early")

    def test_chuyen_lon_becomes_ranked_cards(self):
        for key in PHONES:
            top = rendered()["runs"][key]["top"]
            self.assertEqual(len(top), 4, key)
            for li in top:
                rank = "28px" if key == "320" else "32px"   # a narrow phone steps the rank down to text-feature
                self.assertEqual((li["display"], li["radius"], li["num"]["font"]), ("grid", "12px", rank), key)
                self.assertGreaterEqual(li["titleBox"]["w"], 120, f"{key}: room for the ranked headline")
                self.assertGreaterEqual(li["h"], 44, key)   # the headline's link covers the whole card
                self.assertLess(li["num"]["x"] + li["num"]["w"], li["titleBox"]["x"], key)
                self.assertLess(li["src"]["y"], li["titleBox"]["y"], key)
                self.assertGreaterEqual(li["time"]["y"], li["titleBox"]["y"] + li["titleBox"]["h"], key)
                if li["hasPhoto"]:
                    pic = li["pic"]
                    self.assertEqual(pic["w"], pic["h"], f"{key}: square picture")
                    self.assertTrue(80 <= pic["w"] <= 112, f"{key}: {pic['w']}")
                    self.assertGreaterEqual(pic["x"], li["titleBox"]["x"] + li["titleBox"]["w"], key)
                    self.assertGreaterEqual(li["time"]["y"], pic["y"] + pic["h"], key)
                else:
                    self.assertIsNone(li["pic"], key)
            self.assertTrue(any(li["hasPhoto"] for li in top), f"{key}: the fixture's top stories carry pictures")

    def test_the_panel_runs_edge_to_edge_on_a_phone_only(self):
        runs = rendered()["runs"]
        for key in PHONES:
            panel = runs[key]["panel"]
            self.assertEqual((panel["x"], panel["w"]), (0, runs[key]["width"]), key)
            self.assertEqual(panel["radius"], "16px 16px 0px 0px", key)
        for key in ("1440", "2000"):
            self.assertEqual(runs[key]["panel"]["radius"], "16px", key)

    def test_a_phone_card_wears_the_desktop_card_s_tokens(self):
        # Captain, 11/11 12:4x: "giao diện mobile và desktop nó không đồng bộ, rõ nhất là bo góc của thẻ tin".
        runs = rendered()["runs"]
        wide, phone = runs["1440"]["look"], runs["375"]["look"]
        for part, props in (("card", ("borderRadius", "boxShadow", "backgroundColor")),
                            ("src", ("fontSize", "fontWeight", "color")), ("time", ("fontSize", "fontWeight", "color")),
                            ("title", ("fontWeight", "color")), ("gap", ("rowGap",))):
            for prop in props:
                self.assertEqual(phone[part][prop], wide[part][prop], f"{part}.{prop}")
        self.assertEqual(phone["fav"], wide["fav"])

    def test_vua_dang_rows_keep_their_height_and_the_list_scrolls_on_a_phone(self):
        # Captain, 13/11: "trên mobile chỉ hiển thị 4 tin, không cuộn xem thêm được". A capped list must scroll to its
        # rows, never squeeze them until headlines run over each other.
        for key in PHONES:
            fresh = rendered()["runs"][key]["fresh"]
            self.assertIsNotNone(fresh, f"{key}: the fixture shows the Vừa đăng tile")
            for i, row in enumerate(fresh["rows"]):
                self.assertGreaterEqual(row["h"] + 1, row["need"], f"{key} row {i}: squeezed below its content")
            if sum(r["h"] for r in fresh["rows"]) > fresh["clientH"] + 1:
                self.assertGreater(fresh["scrollH"], fresh["clientH"] + 1, f"{key}: rows past the fold scroll")

    def test_the_order_sits_on_tin_moi_and_reorders_only_that_list(self):
        for key in ("375", "1440"):
            proof = rendered()["runs"][key]["sortProof"]
            before, after = proof["before"], proof["after"]
            self.assertEqual(before["place"], "band-head", key)
            self.assertEqual((before["pressed"], after["pressed"]), ("worth", "new"), key)
            self.assertEqual(after["stored"], '"new"', key)
            self.assertEqual((before["lead"], before["top"]), (after["lead"], after["top"]), f"{key}: the first screen stays")
            for b in before["buttons"]:
                self.assertGreaterEqual(b["h"], 44, key)
            self.assertLessEqual(proof["shiftAfterTap"], 0.1, key)
            self.assertEqual(len(after["news"]), len(before["news"]), key)
        self.assertIsNone(rendered()["runs"]["1440"]["top"][0]["pic"])

    def test_tablet_and_desktop_keep_their_bento_cards(self):
        for key in ("1440", "2000"):
            page = rendered()["runs"][key]
            self.assertTrue(page["cards"], key)
            for c in page["cards"]:
                self.assertEqual((c["display"], c["radius"]), ("flex", "12px"), f"{key} {c['title']}")
            for li in page["top"]:
                self.assertEqual((li["display"], li["radius"]), ("flex", "0px"), key)
                self.assertIsNone(li["pic"], f"{key}: the ranked list keeps its text-only rows")


if __name__ == "__main__":
    unittest.main()
