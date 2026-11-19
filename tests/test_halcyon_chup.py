"""Halcyon capture step (video/halcyon/chup.mjs): a source address + a verbatim sentence -> a phone-width screenshot and the capture-manifest
entry the assembler reads. Runs the real command against local HTML fixtures (tests/fixtures/halcyon/chup/) served from 127.0.0.1, so it needs
Node, `npm install` in video/ and Google Chrome, and no network. Every picture is also checked with the builder's own ink code (ve_halcyon)."""
import functools
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "halcyon" / "chup"
CHUP = ROOT / "video" / "halcyon" / "chup.mjs"
PW = ROOT / "video" / ("node" + "_modules") / "playwright-core"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kb = load("halcyon_kich_ban", "video/halcyon/halcyon_kich_ban.py")


def chrome_ok():
    if os.environ.get("CHROME_PATH"):
        return Path(os.environ["CHROME_PATH"]).exists()
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              "/opt/google/chrome/chrome", "/usr/bin/google-chrome"):
        if Path(p).exists():
            return True
    return False


CURLY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})
QUOTE ='The company said it\'s fine to read "this" sentence exactly as written'   # the page has curly quotes and tags inside
BOARD_CAP = "The board will meet on Monday morning to decide"
BOARD ="the board will meet on Monday morning to decide"


@unittest.skipUnless(shutil.which("node") and PW.exists() and chrome_ok(), "needs node, playwright-core (npm install in video/) and Chrome")
class ChupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIX))
        handler.log_message = lambda *a, **k: None
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}/"
        cls.tmp = Path(tempfile.mkdtemp(prefix="chup-test-"))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_chup(self, name, urls, quote, *extra):
        out = self.tmp / name
        cmd = ["node", str(CHUP), "--quote", quote, "--ref", "cap", "--out", str(out), "--timeout", "40"]
        for u in urls:
            cmd += ["--url", u if u.startswith("http") else self.base + u]
        p = subprocess.run(cmd + list(extra), capture_output=True, text=True, encoding="utf-8", timeout=300, env=dict(os.environ, TEMP=str(self.tmp), TMP=str(self.tmp)))
        return p, out

    def check_picture(self, out, quote=QUOTE):
        """The entry is valid for the assembler, and the picture is what the builder will accept: rows are ink-band edges, u_rows lie in blank gaps."""
        from PIL import Image
        ve = load("ve_halcyon", "video/halcyon/ve_halcyon.py")
        man = json.loads((out / "captures.json").read_text(encoding="utf-8"))
        c = kb.check_manifest(man)["cap"]
        for f in ("file", "focus", "u_rows", "source", "date", "captured", "bands"):
            self.assertIn(f, c)
        img = Image.open(out / c["file"]).convert("RGB")
        self.assertEqual(img.width, 1170)
        a, b = c["focus"]["rows"]
        ua, ub = c["u_rows"]
        bands = ve.ink_bands(img, 0, img.height)
        self.assertIn(a, [x[0] for x in bands]); self.assertIn(b, [x[1] for x in bands])
        self.assertTrue(0 <= ua < a and b < ub <= img.height)
        ink = ve.ink_mask(img, 0, None, 60, 1110)
        self.assertFalse(ink[ua:ua + 2].any()); self.assertFalse(ink[ub - 2:ub].any())      # check_shown: nothing beside the cut rows
        for b0, b1 in bands:
            self.assertFalse(b0 < ua < b1); self.assertFalse(b0 < ub < b1)                  # no text line straddles a cut
        for bd in c["bands"]:
            x, y, w, h = bd["rect"]
            self.assertTrue(0 <= x and x + w <= img.width and 0 <= y and y + h <= img.height)
            self.assertTrue(ink[y:y + h, max(x, 60):x + w].any())                           # there is ink inside the rectangle
            self.assertIn(bd["text"].translate(CURLY), quote)
        return c, img

    def test_found_across_tags_and_quotes(self):
        p, out = self.run_chup("ok", ["article.html"], QUOTE, "--band", "fine to read", "--band", "exactly as written")
        self.assertEqual(p.returncode, 0, p.stderr)
        c, img = self.check_picture(out)
        self.assertEqual([b["text"] for b in c["bands"]], ["fine to read", "exactly as written"])
        self.assertEqual(c["source"], "Fixture Daily")
        self.assertRegex(c["captured"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+07:00$")
        # the line holding "exactly as written" is a different line from "fine to read": two rects at different heights
        self.assertGreater(c["bands"][1]["rect"][1], c["bands"][0]["rect"][1])

    def test_phrase_wrapping_gives_one_rect_per_line(self):
        p, out = self.run_chup("wrap", ["article.html"], QUOTE, "--band", '"this" sentence exactly')
        self.assertEqual(p.returncode, 0, p.stderr)
        c, _ = self.check_picture(out)
        self.assertEqual(len(c["bands"]), 2)            # "this" is at the end of one line, "sentence exactly" starts the next
        self.assertEqual([b["text"] for b in c["bands"]], ["\u201cthis\u201d", "sentence exactly"])

    def test_twice_is_refused_without_occurrence_and_found_with_it(self):
        p, out = self.run_chup("twice", ["twice.html"], BOARD)
        self.assertEqual(p.returncode, 1)
        self.assertIn("appears 2 times", p.stderr)
        self.assertFalse(out.exists())
        p1, o1 = self.run_chup("twice1", ["twice.html"], BOARD, "--occurrence", "1")
        p2, o2 = self.run_chup("twice2", ["twice.html"], BOARD, "--occurrence", "2")
        self.assertEqual((p1.returncode, p2.returncode), (0, 0), p1.stderr + p2.stderr)
        c1 = json.loads(p1.stdout)["context"]; c2 = json.loads(p2.stdout)["context"]
        self.assertIn("First time", c1); self.assertIn("another paragraph", c2)

    def test_missing_sentence_is_refused_and_nothing_written(self):
        p, out = self.run_chup("missing", ["article.html"], "The company said nothing of the kind")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not in the visible text", p.stderr)
        self.assertIn("nothing written", p.stderr)
        self.assertFalse(out.exists())

    def test_walls_are_refused(self):
        for page, word in (("consent-wall.html", "wall"), ("signin-wall.html", "wall")):
            p, out = self.run_chup(page, [page], BOARD_CAP)
            self.assertEqual(p.returncode, 1, page)
            self.assertIn(word, p.stderr)
            self.assertFalse(out.exists(), page)

    def test_sentence_only_in_a_pinned_bar_is_refused(self):
        p, out = self.run_chup("bar", ["bar-only.html"], BOARD)
        self.assertEqual(p.returncode, 1)
        self.assertIn("pop-up, banner or pinned bar", p.stderr)

    def test_cookie_banner_is_declined_and_page_captured(self):
        p, out = self.run_chup("cookie", ["cookie-banner.html"], BOARD_CAP)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.check_picture(out, BOARD_CAP)

    def test_fallback_order_and_hco_last(self):
        p, out = self.run_chup("fallback", ["no-such-page.html", "signin-wall.html"], QUOTE, "--hco", self.base + "article.html")
        self.assertEqual(p.returncode, 0, p.stderr)
        info = json.loads(p.stdout)
        self.assertEqual([(t["url"].rsplit("/", 1)[1], t["ok"], t.get("kind")) for t in info["trail"]],
                         [("no-such-page.html", False, "status"), ("signin-wall.html", False, "wall"), ("article.html", True, None)])
        self.assertTrue(info["url"].endswith("article.html"))
        self.check_picture(out)

    def test_all_addresses_fail_gives_a_loud_message(self):
        p, out = self.run_chup("allfail", ["no-such-page.html", "signin-wall.html"], QUOTE)
        self.assertEqual(p.returncode, 1)
        self.assertIn("could not be shown from any of 2 address(es)", p.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
