"""Halcyon repo recording (video/halcyon/halcyon_quay.py and quay-repo.mjs): the stills of a GitHub repo are proved against GitHub's own listing.
The comparison and `cay` are pure and run offline on fixtures derived from a real capture of backnotprop/plannotator at 1280x800
(tests/fixtures/halcyon/quay/: the real file-list markup, the real code-line markup, the manifest and listing that capture produced).
The recorder tests run the real quay-repo.mjs against that markup served from 127.0.0.1, so they need Node, `npm install` in video/ and Chrome."""
import base64
import copy
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
FIX = ROOT / "tests" / "fixtures" / "halcyon" / "quay"
QUAY = ROOT / "video" / "halcyon" / "quay-repo.mjs"
PW = ROOT / "video" / ("node" + "_modules") / "playwright-core"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hq = load("halcyon_quay", "video/halcyon/halcyon_quay.py")
MANIFEST = json.loads((FIX / "quay.json").read_text(encoding="utf-8"))
CAY = json.loads((FIX / "cay.json").read_text(encoding="utf-8"))


def chrome_ok():
    if os.environ.get("CHROME_PATH"):
        return Path(os.environ["CHROME_PATH"]).exists()
    return any(Path(p).exists() for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                                          "/opt/google/chrome/chrome", "/usr/bin/google-chrome"))


def fixture_pair():
    return copy.deepcopy(MANIFEST), copy.deepcopy(CAY)


def page_of(m, path):
    return next(p for p in m["pages"] if p["path"] == path)


def refusal_of(m, c, pic_dir=None):
    try:
        hq.compare(m, c, pic_dir)
    except hq.Refusal as e:
        return e
    return None


class CompareTest(unittest.TestCase):
    def test_real_capture_passes(self):
        m, c = fixture_pair()
        self.assertIsNone(refusal_of(m, c))

    def test_the_real_collapsed_row_is_a_listing_child(self):
        m, c = fixture_pair()
        home = page_of(m, "")
        self.assertIn(".agents/skills", [r["path"] for r in home["rows"]])       # GitHub shows the chain as one row ...
        self.assertIn(".agents", [x["path"] for x in c["listings"][""]])          # ... and the API lists the first folder of it
        self.assertIsNone(refusal_of(m, c))

    def test_status(self):
        m, c = fixture_pair()
        page_of(m, "apps")["status"] = 404
        e = refusal_of(m, c)
        self.assertEqual((e.kind, e.step), ("status", "quay"))
        self.assertIn("apps", e.address)

    def test_renamed(self):
        m, c = fixture_pair()
        page_of(m, "")["final"] = "https://github.com/someone-else/plannotator-renamed"
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "renamed")
        self.assertIn("someone-else/plannotator-renamed", str(e))

    def test_theme(self):
        m, c = fixture_pair()
        page_of(m, "apps")["background"] = "rgb(13, 17, 23)"
        self.assertEqual(refusal_of(m, c).kind, "theme")

    def test_address_other_folder(self):
        m, c = fixture_pair()
        page_of(m, "apps")["final"] = "https://github.com/backnotprop/plannotator/tree/main/packages"
        self.assertEqual(refusal_of(m, c).kind, "address")

    def test_address_other_branch(self):
        m, c = fixture_pair()
        page_of(m, "apps")["final"] = "https://github.com/backnotprop/plannotator/tree/dev/apps"
        self.assertEqual(refusal_of(m, c).kind, "address")

    def test_address_title_names_neither(self):
        m, c = fixture_pair()
        page_of(m, "apps")["title"] = "Page not related"
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "address")
        self.assertIn("title", e.why)

    def test_address_wrong_commit_or_pages(self):
        m, c = fixture_pair()
        m["commit"] = "0" * 40
        self.assertEqual(refusal_of(m, c).kind, "address")
        m, c = fixture_pair()
        m["pages"].pop()
        self.assertEqual(refusal_of(m, c).kind, "address")

    def test_listing_one_row_removed(self):
        m, c = fixture_pair()
        home = page_of(m, "")
        gone = home["rows"].pop(5)
        home["entries"] = [x for x in home["entries"] if x["path"] != gone["path"]]
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "listing")
        self.assertIn(gone["path"].split("/")[0], e.why)
        self.assertIn("33", e.why)

    def test_listing_row_github_does_not_hold(self):
        m, c = fixture_pair()
        page_of(m, "apps")["rows"].append({"path": "apps/invented", "rect": [337, 400, 900, 40], "name_rect": [350, 410, 80, 19], "font_px": 14})
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "listing")
        self.assertIn("apps/invented", e.why)

    def test_listing_cut_list_is_allowed_only_when_recorded(self):
        m, c = fixture_pair()
        home = page_of(m, "")
        home["rows"] = home["rows"][:10]
        self.assertEqual(refusal_of(m, c).kind, "listing")
        home["truncated"], home["expanded"] = True, False
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "listing")        # the open rows `apps` and `package.json` are missing from the cut list: the row check or the cut itself refuses
        m2, c2 = fixture_pair()
        page_of(m2, "")["truncated"], page_of(m2, "")["expanded"] = True, True
        self.assertIsNone(refusal_of(m2, c2))

    def test_row_missing_for_the_next_page(self):
        m, c = fixture_pair()
        home = page_of(m, "")
        # drop both the row and the API child so only the missing-row rule can fire
        home["rows"] = [r for r in home["rows"] if r["path"] != "apps"]
        c["listings"][""] = [x for x in c["listings"][""] if x["path"] != "apps"]
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "row")
        self.assertIn("apps", e.why)

    def test_row_below_the_picture(self):
        m, c = fixture_pair()
        next(r for r in page_of(m, "")["rows"] if r["path"] == "package.json")["rect"][1] = 5200
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "row")
        self.assertIn("below", e.why)

    def test_row_collapsed_chain_names_the_deeper_row(self):
        m, c = fixture_pair()
        c["pages"].insert(1, {"path": ".agents", "kind": "tree"})
        c["listings"][".agents"] = []
        m["pages"].insert(1, copy.deepcopy(page_of(m, "apps")))
        m["pages"][1].update(path=".agents", requested="https://github.com/backnotprop/plannotator/tree/main/.agents", final="https://github.com/backnotprop/plannotator/tree/main/.agents",
                             rows=[], entries=[])
        c["listings"][".agents"] = [{"name": "skills", "path": ".agents/skills", "kind": "tree", "chain_to": ".agents/skills"}]
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "row")
        self.assertIn(".agents/skills", e.why)

    def test_file_first_line_differs(self):
        m, c = fixture_pair()
        page_of(m, "package.json")["file"]["code_lines"][0] = "<!DOCTYPE html>"
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "file")
        self.assertIn("{", e.why)

    def test_file_no_lines_drawn(self):
        m, c = fixture_pair()
        page_of(m, "package.json")["file"]["code_lines"] = []
        self.assertEqual(refusal_of(m, c).kind, "file")

    def test_file_rendered_markdown_is_checked_by_address_only(self):
        m, c = fixture_pair()
        page_of(m, "package.json")["file"] = {"kind": "markdown", "code_lines": [], "rendered_lines": 0}
        self.assertIsNone(refusal_of(m, c))

    def test_file_too_large_cannot_be_compared(self):
        m, c = fixture_pair()
        c["files"]["package.json"] = {"state": "too-large", "first_line": None, "index": None}
        self.assertEqual(refusal_of(m, c).kind, "file")

    def test_blank_ink(self):
        m, c = fixture_pair()
        page_of(m, "apps")["ink_ratio"] = 0.001
        e = refusal_of(m, c)
        self.assertEqual(e.kind, "blank")
        self.assertIn("ink", e.why)

    def test_blank_wrong_size(self):
        m, c = fixture_pair()
        page_of(m, "apps")["picture_px"] = [2560, 1000]
        self.assertEqual(refusal_of(m, c).kind, "blank")

    def test_blank_picture_file_checked_against_its_header(self):
        m, c = fixture_pair()
        with tempfile.TemporaryDirectory() as d:
            for i, p in enumerate(m["pages"]):
                w, h = p["picture_px"]
                (Path(d) / p["picture"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
            self.assertIsNone(refusal_of(m, c, d))
            (Path(d) / "1.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (1170).to_bytes(4, "big") + (3144).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
            self.assertEqual(refusal_of(m, c, d).kind, "blank")
            (Path(d) / "1.png").unlink()
            self.assertEqual(refusal_of(m, c, d).kind, "blank")

    def test_message_names_step_address_kind_and_a_fix_line(self):
        m, c = fixture_pair()
        page_of(m, "apps")["status"] = 500
        text = str(refusal_of(m, c))
        self.assertTrue(text.startswith("quay: https://github.com/backnotprop/plannotator/tree/main/apps: status: "))
        self.assertIn("\nto fix: ", text)

    def test_manifest_records_what_the_builder_aims_at(self):
        home = page_of(MANIFEST, "")
        self.assertEqual(MANIFEST["viewport"], {"width": 1280, "height": 800})
        self.assertEqual(MANIFEST["scale"], 2)
        row = home["rows"][0]
        self.assertEqual(len(row["rect"]), 4)
        self.assertEqual(len(row["name_rect"]), 4)
        self.assertGreaterEqual(row["font_px"], 12)
        self.assertTrue(home["boxes"]["file_list"] and home["boxes"]["readme"] and home["boxes"]["about"])
        self.assertTrue(page_of(MANIFEST, "package.json")["boxes"]["code"])
        self.assertTrue(home["capped"] and home["css_height"] == 5000)


# ---------------------------------------------------------------- cay on a fake GitHub API
TREE = [("a", "tree"), ("a/b", "tree"), ("a/b/c.txt", "blob"), ("README.md", "blob"), ("packages", "tree"), ("packages/ai", "tree"), ("packages/ai/x.py", "blob"),
        ("packages/server", "tree"), ("packages/server/s.py", "blob"), ("bin", "blob"), ("sub", "commit"), ("empty.txt", "blob"), ("big.bin", "blob")]
SHA = "abcdef0123456789abcdef0123456789abcdef01"


def fake_api(overrides=None, remaining="58"):
    overrides = overrides or {}
    contents = {"README.md": b"\n\n# Title\nmore\n", "empty.txt": b"", "big.bin": None}

    def fetch(url):
        for key, val in overrides.items():
            if key in url:
                return val
        h = {"x-ratelimit-remaining": remaining}
        if url.endswith("/repos/o/r"):
            return 200, h, json.dumps({"full_name": "o/r", "private": False, "default_branch": "main"}).encode()
        if "/commits/" in url:
            return (200, h, json.dumps({"sha": SHA}).encode()) if url.endswith("/main") else (404, h, b"{}")
        if "/git/trees/" in url:
            return 200, h, json.dumps({"truncated": False, "tree": [{"path": p, "type": t} for p, t in TREE]}).encode()
        if "/contents/" in url:
            name = url.split("/contents/")[1].split("?")[0]
            data = contents.get(name, b"x\n")
            if data is None:
                return 200, h, json.dumps({"size": 5000000, "encoding": "none", "content": ""}).encode()
            return 200, h, json.dumps({"size": len(data), "encoding": "base64", "content": base64.b64encode(data).decode()}).encode()
        return 404, h, b"{}"
    return fetch


def cay_refusal(*args, **kw):
    with unittest.TestCase().assertRaises(hq.Refusal) as cm:
        hq.cay(*args, **kw)
    return cm.exception


class CayTest(unittest.TestCase):
    def test_listing_chain_files_and_budget(self):
        doc = hq.cay("o/r", ["packages", "packages/ai", "README.md"], fetch=fake_api())
        self.assertEqual((doc["branch"], doc["commit"]), ("main", SHA))
        self.assertEqual([p["kind"] for p in doc["pages"]], ["home", "tree", "tree", "blob"])
        root = {c["name"]: c for c in doc["listings"][""]}
        self.assertEqual(root["a"]["chain_to"], "a/b")            # a folder holding one folder is shown by GitHub as `a/b`
        self.assertEqual(root["packages"]["chain_to"], "packages")
        self.assertEqual(root["sub"]["kind"], "commit")
        self.assertEqual(doc["files"]["README.md"], {"state": "text", "first_line": "# Title", "index": 2})
        self.assertEqual(doc["api_calls"], 4 + 0 + 0)               # repo, commit, tree, one file
        self.assertNotIn("token", json.dumps(doc).lower())

    def test_file_states(self):
        doc = hq.cay("o/r", ["empty.txt", "big.bin"], fetch=fake_api())
        self.assertEqual(doc["files"]["empty.txt"]["state"], "empty")
        self.assertEqual(doc["files"]["big.bin"]["state"], "too-large")

    def test_misspelt_folder_lists_the_real_children(self):
        e = cay_refusal("o/r", ["packages", "packages/servr"], fetch=fake_api())
        self.assertEqual((e.step, e.kind), ("cay", "path"))
        self.assertIn("packages/servr", e.why)
        self.assertIn("ai, server", e.why)
        self.assertIn(SHA[:7], e.why)
        self.assertIn("to fix: pick one of those", str(e))

    def test_misspelt_top_level_lists_root(self):
        e = cay_refusal("o/r", ["pakages"], fetch=fake_api())
        self.assertIn("holds:", e.why)
        self.assertIn("packages", e.why)

    def test_a_file_used_as_a_parent(self):
        e = cay_refusal("o/r", ["README.md/x"], fetch=fake_api())
        self.assertEqual(e.kind, "parent")
        self.assertIn("README.md", e.why)

    def test_parent_must_be_opened_first(self):
        e = cay_refusal("o/r", ["packages/ai"], fetch=fake_api())
        self.assertEqual(e.kind, "parent")

    def test_missing_repo(self):
        e = cay_refusal("o/r", [], fetch=fake_api({"/repos/o/r": (404, {}, b"{}")}))
        self.assertEqual(e.kind, "repo")
        self.assertIn("does not exist or is private", e.why)

    def test_renamed_repo(self):
        meta = json.dumps({"full_name": "new/name", "default_branch": "main"}).encode()
        e = cay_refusal("o/r", [], fetch=fake_api({"/repos/o/r": (200, {}, meta)}))
        self.assertEqual(e.kind, "renamed")
        self.assertIn("new/name", e.why)

    def test_api_limit_names_the_reset_time(self):
        e = cay_refusal("o/r", [], fetch=fake_api({"/commits/": (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1795000000"}, b"{}")}))
        self.assertEqual(e.kind, "limit")
        self.assertIn("resets at", e.why)
        self.assertIn("no token", e.fix)

    def test_limit_too_low_for_the_files(self):
        e = cay_refusal("o/r", ["README.md", "empty.txt"], fetch=fake_api(remaining="1"))
        self.assertEqual(e.kind, "limit")

    def test_missing_branch(self):
        e = cay_refusal("o/r", [], branch="nope", fetch=fake_api())
        self.assertEqual(e.kind, "branch")

    def test_truncated_tree_is_refused_not_guessed(self):
        e = cay_refusal("o/r", [], fetch=fake_api({"/git/trees/": (200, {}, json.dumps({"truncated": True, "tree": []}).encode())}))
        self.assertEqual(e.kind, "listing")

    def test_bad_arguments(self):
        for bad in (["/abs"], ["a\\b"], ["a/../b"], ["a/"], ["a", "a"]):
            self.assertEqual(cay_refusal("o/r", bad, fetch=fake_api()).kind, "path", bad)
        self.assertEqual(cay_refusal("o r", [], fetch=fake_api()).kind, "repo")
        self.assertEqual(cay_refusal("o/r", ["a", "a/b", "packages", "packages/ai", "bin", "README.md"], fetch=fake_api()).kind, "rate-limit")


# ---------------------------------------------------------------- the real recorder against real markup
def shell(title, body, bg="#fff", extra=""):
    return (f"<!doctype html><html data-color-mode=light><head><meta charset=utf-8><title>{title}</title><style>body{{margin:0;background:{bg};color:#1f2328;font:14px sans-serif}}"
            ".react-directory-row-name-cell-small-screen{display:none}table{border-collapse:collapse;width:900px}td{padding:10px}"
            f"article{{width:800px}}code,.react-file-line{{font:12px/20px monospace;white-space:pre}}</style></head><body><header><a href=/>GitHub</a> <a href=/login>Sign in</a></header>{body}"
            f"<footer><a href=#>Manage cookies</a></footer>{extra}</body></html>")


LOREM = "<p>" + ("The workspace to stay in the loop and on top of agents. " * 12) + "</p>"


def pages():
    table = (FIX / "home-table.html").read_text(encoding="utf-8")
    rl = (FIX / "readme-links.html").read_text(encoding="utf-8")
    code = (FIX / "code-lines.html").read_text(encoding="utf-8")
    home = shell("GitHub - backnotprop/plannotator: the workspace", f"<main><h1>plannotator</h1>{table}<aside><h2>About</h2>{LOREM}</aside>"
                 f"<article class=markdown-body><h2>Readme</h2>{LOREM}<table><tr><td>{rl}</td></tr></table></article></main>")
    blob = shell("plannotator/package.json at main · backnotprop/plannotator", f"<main><nav><a href=/backnotprop/plannotator/tree/main>plannotator</a></nav>{LOREM}<div>{code}</div></main>")
    return home, blob


class Handler(http.server.BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        r = self.routes.get(self.path.split("?")[0])
        if r is None:
            r = (404, {}, "<html><title>Page not found</title><body>Not Found</body></html>")
        status, headers, body = r
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        data = body.encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a, **k):
        pass


@unittest.skipUnless(shutil.which("node") and PW.exists() and chrome_ok(), "needs node, playwright-core (npm install in video/) and Chrome")
class RecorderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home, blob = pages()
        dark = shell("GitHub - acme/dark: x", f"<main><h1>dark</h1>{LOREM}{LOREM}</main>", bg="#0d1117")
        wall = shell("Just a moment...", f"<main>{LOREM}</main>")
        Handler.routes = {
            "/backnotprop/plannotator": (200, {}, home),
            "/backnotprop/plannotator/blob/main/package.json": (200, {}, blob),
            "/acme/gone": (404, {}, "x"),
            "/acme/moved": (302, {"Location": "/newowner/newname"}, ""),
            "/newowner/newname": (200, {}, home),
            "/acme/signin": (302, {"Location": "/login?return_to=/acme/signin"}, ""),
            "/login": (200, {}, shell("Sign in to GitHub", f"<main>{LOREM}</main>")),
            "/acme/wall": (200, {}, wall.replace("<main>", "<main><h1>Verify you are human</h1>")),
            "/acme/slow": (429, {"Retry-After": "1"}, "Too many requests"),
            "/acme/dark": (200, {}, dark),
        }
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.tmp = Path(tempfile.mkdtemp(prefix="quay-test-"))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_quay(self, name, repo, branch="main", pages_=None):
        pages_ = pages_ or [{"path": "", "kind": "home"}]
        cay = {"version": 1, "repo": repo, "branch": branch, "commit": "f" * 40, "open": [p["path"] for p in pages_ if p["path"]], "pages": pages_}
        f = self.tmp / f"{name}.cay.json"
        f.write_text(json.dumps(cay), encoding="utf-8")
        r = subprocess.run(["node", str(QUAY), "--cay", str(f), "--ref", name, "--out", str(self.tmp), "--base", self.base, "--gap", "0", "--timeout", "40"],
                           capture_output=True, text=True, encoding="utf-8")
        return r

    def test_real_markup_rows_are_found_by_address_and_position(self):
        r = self.run_quay("ok", "backnotprop/plannotator", pages_=[{"path": "", "kind": "home"}, {"path": "package.json", "kind": "blob"}])
        self.assertEqual(r.returncode, 0, r.stderr)
        m = json.loads((self.tmp / "ok" / "quay.json").read_text(encoding="utf-8"))
        home = m["pages"][0]
        paths = [x["path"] for x in home["rows"]]
        self.assertEqual(len(paths), 8)                           # the 8 real rows; the hidden duplicate anchors and the README's blob links are not rows
        self.assertEqual(len(set(paths)), 8)
        self.assertIn(".agents/skills", paths)
        self.assertEqual(home["listing_ignored"]["article"], 3)
        self.assertGreater(home["listing_ignored"]["hidden"], 0)
        self.assertTrue(all(len(x["rect"]) == 4 and len(x["name_rect"]) == 4 and x["rect"][2] > 0 for x in home["rows"]))
        self.assertTrue(home["boxes"]["file_list"] and home["boxes"]["readme"] and home["boxes"]["about"])
        code = m["pages"][1]["file"]
        self.assertEqual(code["kind"], "code")
        self.assertEqual(code["code_lines"][0], "{")
        self.assertEqual(code["code_lines"][1].strip(), '"name": "plannotator",')
        self.assertEqual(m["pages"][1]["picture_px"][0], 2560)
        self.assertEqual(hq.png_size(self.tmp / "ok" / "0.png"), (2560, m["pages"][0]["css_height"] * 2))

    def assert_refused(self, r, kind):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stderr.strip().splitlines()[-1], rf"^quay: \S+: {kind}: ")
        self.assertIn("nothing written", r.stderr)

    def test_status(self):
        self.assert_refused(self.run_quay("gone", "acme/gone"), "status")
        self.assertFalse((self.tmp / "gone").exists())

    def test_wall_bot_check(self):
        self.assert_refused(self.run_quay("wall", "acme/wall"), "wall")

    def test_wall_sign_in_redirect(self):
        self.assert_refused(self.run_quay("signin", "acme/signin"), "wall")

    def test_renamed(self):
        r = self.run_quay("moved", "acme/moved")
        self.assert_refused(r, "renamed")
        self.assertIn("newowner/newname", r.stderr)

    def test_theme(self):
        self.assert_refused(self.run_quay("dark", "acme/dark"), "theme")

    def test_rate_limit_after_one_retry(self):
        r = self.run_quay("slow", "acme/slow")
        self.assert_refused(r, "rate-limit")

    def test_too_many_pages_is_a_rate_limit_refusal_before_any_load(self):
        many = [{"path": "", "kind": "home"}] + [{"path": f"d{i}", "kind": "tree"} for i in range(6)]
        r = self.run_quay("many", "acme/gone", pages_=many)
        self.assert_refused(r, "rate-limit")


if __name__ == "__main__":
    unittest.main()
