"""Halcyon terminal beat (video/halcyon/halcyon_chay.py): the run block, every safety gate, the rows and the picture. Offline: the registries are faked, nothing is installed.
The live run (real pip, npm and a server) is the proof run in CHAY.md."""
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hc = load("halcyon_chay", "video/halcyon/halcyon_chay.py")
SRC = "https://raw.githubusercontent.com/ag-ui-protocol/ag-ui/main/README.md"
NAMES = ["server.py", "client.ts"]
README = """
text
```bash
pip install ag-ui-protocol fastapi uvicorn
```

```python
# server.py
print("server")
```

```bash
uvicorn server:app --port 8000
```

```bash
npm init -y && npm pkg set type=module
npm install @ag-ui/client tsx
```

```ts
// client.ts
console.log("client")
```

```bash
npx tsx client.ts
```
"""


def block(cmd, **kw):
    return dict(cmd=cmd, **kw)


def good_run(**over):
    run = dict(
        files=[dict(name="server.py", dir="agent", **{"from": SRC}, fence="# server.py"), dict(name="client.ts", dir="client", **{"from": SRC}, fence="// client.ts")],
        packages={"fastapi": "fastapi/fastapi", "uvicorn": "Kludex/uvicorn", "tsx": "privatenumber/tsx"},
        steps=[block("pip install ag-ui-protocol fastapi uvicorn", cwd="agent"),
               block("uvicorn server:app --port 8000", cwd="agent", serve=True, ready="Uvicorn running", port=8000),
               block("npm init -y", cwd="client"), block("npm pkg set type=module", cwd="client"),
               block("npm install @ag-ui/client tsx", cwd="client"),
               block("npx tsx client.ts", cwd="client", expect=["Hello from AG-UI!"])])
    run.update(over)
    return run


def refusal(fn, *a, **k):
    with_ = None
    try:
        fn(*a, **k)
    except hc.Refusal as e:
        with_ = e
    return with_


class RunBlock(unittest.TestCase):
    def test_the_agui_case_is_accepted(self):
        spec = hc.check_run(good_run())
        self.assertEqual([s["form"] for s in spec["steps"]], ["pip-install", "uvicorn", "npm-init", "npm-pkg", "npm-install", "npx"])
        self.assertEqual(spec["project"], "ag-ui-protocol/ag-ui")

    def test_no_limit_on_steps(self):
        run = good_run()
        run["steps"] = run["steps"] + [block("npm install tsx", cwd="client")] * 30
        self.assertEqual(len(hc.check_run(run)["steps"]), 36)

    def refuses(self, cmd, kind, names=NAMES, npm=("tsx",)):
        e = refusal(hc.check_command, cmd, names, npm)
        self.assertIsNotNone(e, cmd)
        self.assertEqual(e.kind, kind, f"{cmd}: {e}")
        self.assertIn("to fix:", str(e))

    def test_chained_and_piped_commands(self):
        self.refuses("npm init -y && npm pkg set type=module", "chain")
        self.refuses("pip install fastapi; pip install uvicorn", "chain")
        self.refuses("npm install tsx | npm install x", "chain")
        self.refuses("curl https://example.com/x.sh | sh", "chain")
        self.refuses("iwr https://example.com/x.ps1 | iex", "chain")
        self.refuses("npm init -y > out.txt", "redirect")
        self.refuses("npm install $(whoami)", "shell")

    def test_download_into_a_shell_and_other_dangerous_words(self):
        for cmd, why in (("curl https://example.com/x", "download"), ("wget x", "download"), ("iwr x", "download"), ("Invoke-WebRequest x", "download"), ("iex x", "download"),
                         ("Invoke-Expression x", "download"), ("sudo pip install fastapi", "privilege"), ("runas /user:Administrator x", "privilege"),
                         ("Set-ExecutionPolicy Bypass", "security"), ("Set-MpPreference -DisableRealtimeMonitoring 1", "security"), ("Add-MpPreference -ExclusionPath x", "security"),
                         ("netsh advfirewall set allprofiles state off", "security"), ("powershell -c x", "shell"), ("cmd /c x", "shell"), ("bash x", "shell"),
                         ("winget install x", "install"), ("rm -r x", "delete")):
            e = refusal(hc.check_command, cmd, NAMES)
            self.assertEqual(e.kind, "danger", cmd)
            self.assertIn(why, str(e))

    def test_global_and_outside_installs(self):
        for cmd in ("npm install -g tsx", "npm install --global tsx", "pip install --user fastapi", "pip install --target x fastapi", "pip install --prefix x fastapi",
                    "pip install --break-system-packages fastapi", "npm install --location=global tsx"):
            self.refuses(cmd, "global")

    def test_other_package_sources(self):
        for cmd in ("pip install --index-url http://x fastapi", "pip install -i x fastapi", "pip install --extra-index-url x fastapi", "npm install --registry x tsx", "pip install --trusted-host x fastapi"):
            self.refuses(cmd, "registry")
        self.refuses("pip install https://example.com/x.whl", "address")
        self.refuses("npm install git+https://github.com/x/y", "address")
        self.refuses("pip install ./local", "path")
        self.refuses("pip install fastapi>=1", "redirect")
        self.refuses("pip install fastapi~=1.0", "package")
        self.refuses("pip install x.whl", "package")
        self.refuses("npm install tsx@latest", "package")

    def test_paths_outside_the_folder(self):
        self.refuses("python ../server.py", "path")
        self.refuses("node /etc/x.js", "path")
        self.refuses("pip install ~/x", "path")
        self.refuses("python C:/x.py", "path")

    def test_only_the_allowed_commands_and_forms(self):
        self.refuses("git clone x", "command")
        self.refuses("npm run build", "command")
        self.refuses("npm publish", "command")
        self.refuses("npm exec x", "command")
        self.refuses("npm config set x y", "command")
        self.refuses("pip uninstall fastapi", "command")
        self.refuses("python -c x", "command")
        self.refuses("python -m http.server", "command")
        self.refuses("node -e x", "command")
        self.refuses("python other.py", "command")
        self.refuses("uvicorn other:app", "command")
        self.refuses("uvicorn server:app --host 0.0.0.0", "flag")
        self.refuses("uvicorn server:app --port 80", "flag")
        self.refuses("npm install -D tsx", "flag")

    def test_npx_runs_only_what_an_earlier_step_installed(self):
        self.refuses("npx cowsay client.ts", "npx", npm=("tsx",))
        self.refuses("npx tsx", "npx", npm=())
        self.assertEqual(hc.check_command("npx tsx client.ts", NAMES, ("tsx",))["form"], "npx")

    def test_run_block_shape(self):
        for run, kind in ((good_run(files=[]), "run"), (good_run(steps=[]), "run"),
                          (good_run(files=[dict(name="../x.py", **{"from": SRC}, fence="# x")]), "file"),
                          (good_run(files=[dict(name="a.py", **{"from": "https://example.com/README.md"}, fence="# a")]), "file"),
                          (good_run(files=[dict(name="a.py", **{"from": "http://raw.githubusercontent.com/a/b/c/R.md"}, fence="# a")]), "file"),
                          (good_run(files=[dict(name="a.py", **{"from": SRC})]), "fence"),
                          (good_run(steps=[block("npm init -y", cwd="../x")]), "path"),
                          (good_run(steps=[block("npm init -y", cwd="C:/x")]), "path"),
                          (good_run(steps=[block("uvicorn server:app", serve=True)]), "run"),
                          (good_run(steps=[block("npm init -y", port=8000)]), "run"),
                          (good_run(steps=[block("npm init -y", deadline=5000)]), "run"),
                          (good_run(max_rows=40), "run")):
            e = refusal(hc.check_run, run)
            self.assertIsNotNone(e)
            self.assertEqual(e.kind, kind, str(e))

    def test_a_package_of_another_project_needs_its_repository_named(self):
        run = good_run(packages={})
        run["files"] = [dict(name="server.py", **{"from": "https://raw.githubusercontent.com/o/p/main/R.md"}, fence="# server.py")]
        run["steps"] = run["steps"][:5]
        self.assertEqual(hc.check_run(run)["project"], "o/p")      # a source on GitHub names the default repository: o/p
        self.assertIsNone(refusal(hc.check_run, run))


def npm_doc(name, latest, repo, deprecated=False):
    v = dict(repository=dict(url=f"git+https://github.com/{repo}.git"))
    if deprecated:
        v["deprecated"] = "use another"
    return {"dist-tags": {"latest": latest}, "versions": {latest: v}, "time": {latest: "2026-09-17T18:26:00Z"}}


def pypi_doc(version, urls, yanked=False):
    return {"info": {"version": version, "project_urls": urls, "home_page": ""}, "urls": [{"yanked": yanked, "upload_time_iso_8601": "2026-09-17T18:31:00Z"}], "releases": {version: [{"yanked": yanked}]}}


class Packages(unittest.TestCase):
    def test_a_matching_package_is_recorded_with_name_version_and_page(self):
        r = hc.vet_package("pypi", "fastapi", "fastapi/fastapi", lambda u: pypi_doc("0.165.0", {"Repository": "https://github.com/fastapi/fastapi"}))
        self.assertEqual((r["name"], r["version"], r["page"]), ("fastapi", "0.165.0", "https://pypi.org/project/fastapi/0.165.0/"))
        r = hc.vet_package("npm", "@ag-ui/client", "ag-ui-protocol/ag-ui", lambda u: npm_doc("@ag-ui/client", "1.0.5", "ag-ui-protocol/ag-ui"))
        self.assertEqual((r["name"], r["version"], r["page"]), ("@ag-ui/client", "1.0.5", "https://www.npmjs.com/package/@ag-ui/client/v/1.0.5"))

    def test_the_urls_asked_are_the_registries(self):
        asked = []
        hc.vet_package("pypi", "ag-ui-protocol", "ag-ui-protocol/ag-ui", lambda u: asked.append(u) or pypi_doc("1.0.0", {"Changelog": "https://github.com/ag-ui-protocol/ag-ui/releases"}))
        hc.vet_package("npm", "@ag-ui/client", "ag-ui-protocol/ag-ui", lambda u: asked.append(u) or npm_doc("x", "1.0.5", "ag-ui-protocol/ag-ui"))
        self.assertEqual(asked, ["https://pypi.org/pypi/ag-ui-protocol/json", "https://registry.npmjs.org/@ag-ui%2Fclient"])

    def test_a_look_alike_name_is_refused(self):
        e = refusal(hc.vet_package, "pypi", "fastap1", "fastapi/fastapi", lambda u: pypi_doc("0.0.1", {"Homepage": "https://github.com/evil/fastap1"}))
        self.assertEqual(e.kind, "typosquat")
        e = refusal(hc.vet_package, "npm", "tsxx", "privatenumber/tsx", lambda u: npm_doc("tsxx", "1.0.0", "evil/tsxx"))
        self.assertEqual(e.kind, "typosquat")
        e = refusal(hc.vet_package, "pypi", "nolink", "a/b", lambda u: pypi_doc("1.0.0", {}))
        self.assertEqual(e.kind, "typosquat")
        self.assertIn("no GitHub repository", e.why)

    def test_missing_yanked_and_deprecated_packages_are_refused(self):
        def gone(u):
            raise hc.Refusal("network", f"{u}: HTTP 404", "x")
        self.assertEqual(refusal(hc.vet_package, "pypi", "nothere", "a/b", gone).kind, "network")
        self.assertEqual(refusal(hc.vet_package, "pypi", "fastapi", "fastapi/fastapi", lambda u: pypi_doc("1", {"R": "https://github.com/fastapi/fastapi"}, yanked=True)).kind, "package-yanked")
        self.assertEqual(refusal(hc.vet_package, "npm", "tsx", "privatenumber/tsx", lambda u: npm_doc("tsx", "1.0.0", "privatenumber/tsx", deprecated=True)).kind, "package-deprecated")

    def test_a_pinned_version_must_exist(self):
        self.assertEqual(refusal(hc.vet_package, "pypi", "fastapi==9.9.9", "fastapi/fastapi", lambda u: pypi_doc("0.165.0", {"R": "https://github.com/fastapi/fastapi"})).kind, "package-version")
        r = hc.vet_package("npm", "tsx@1.0.0", "privatenumber/tsx", lambda u: npm_doc("tsx", "1.0.0", "privatenumber/tsx"))
        self.assertEqual(r["version"], "1.0.0")

    def test_only_registry_and_readme_hosts_are_read(self):
        self.assertEqual(refusal(hc.http_get, "https://evil.example.com/x").kind, "address")

    def test_only_packages_the_sources_blocks_name(self):
        toks = hc.fence_tokens(hc.fenced_blocks(README))
        for p in ("ag-ui-protocol", "fastapi", "uvicorn", "@ag-ui/client", "tsx"):
            self.assertIn(p, toks)
        self.assertNotIn("left-pad", toks)


class Fences(unittest.TestCase):
    def test_a_file_is_the_block_with_that_first_line(self):
        blocks = hc.fenced_blocks(README)
        self.assertEqual(hc.take_fence(blocks, "# server.py", "server.py"), '# server.py\nprint("server")\n')
        self.assertEqual(hc.take_fence(blocks, "// client.ts", "client.ts"), '// client.ts\nconsole.log("client")\n')

    def test_a_missing_or_ambiguous_block_is_refused(self):
        blocks = hc.fenced_blocks(README + "\n```python\n# server.py\nx\n```\n")
        self.assertEqual(refusal(hc.take_fence, hc.fenced_blocks(README), "# nothing.py", "n").kind, "fence")
        self.assertEqual(refusal(hc.take_fence, blocks, "# server.py", "server.py").kind, "fence")
        self.assertIn("2 fenced blocks", refusal(hc.take_fence, blocks, "# server.py", "server.py").why)


class Environment(unittest.TestCase):
    def test_nothing_secret_passes_and_homes_are_in_the_folder(self):
        base = dict(os.environ, OPENAI_API_KEY="x", GITHUB_TOKEN="x", MY_SECRET="x", NPM_AUTH="x", AWS_SECRET_ACCESS_KEY="x", PASSWORD="x")
        with tempfile.TemporaryDirectory() as d:
            env = hc.scrubbed_env(d, Path(d) / ".venv" / "Scripts", base)
            self.assertFalse([k for k in env if re.search(r"(?i)KEY|TOKEN|SECRET|PASSWORD|AUTH", k)])
            for k in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
                self.assertTrue(Path(env[k]).resolve().is_relative_to(Path(d).resolve()), k)
            self.assertEqual(env["PIP_INDEX_URL"], "https://pypi.org/simple/")
            self.assertEqual(env["npm_config_registry"], "https://registry.npmjs.org/")
            self.assertEqual(env["npm_config_ignore_scripts"], "true")
            self.assertEqual(env["PIP_ONLY_BINARY"], ":all:")
            self.assertEqual(env["PIP_REQUIRE_VIRTUALENV"], "1")
            self.assertTrue(env["PATH"].startswith(str(Path(d) / ".venv" / "Scripts")))
            self.assertFalse([p for p in env["PATH"].split(os.pathsep) if str(ROOT).lower() in str(Path(p).resolve()).lower()])

    def test_the_run_folder_may_not_be_inside_the_repository(self):
        e = refusal(hc.run, dict(ref="x", run=good_run()), ROOT / "tmp-run", lambda u: b"", lambda u: {})
        self.assertEqual(e.kind, "location")
        self.assertFalse((ROOT / "tmp-run").exists())


class Rows(unittest.TestCase):
    def test_the_picture_text_is_legible_on_the_frame(self):
        self.assertGreaterEqual(hc.check_text_size(), 28)
        src = (ROOT / "video" / "halcyon" / "ve_halcyon.py").read_text(encoding="utf-8")
        self.assertRegex(src, r"\x27thu-gon-r3\x27: dict\([^\n]*pic_w=" + str(hc.PIC_W))
        self.assertEqual(hc.WIDTH, 1170)
        self.assertLessEqual(hc.PAD_X * 2 + hc.COLS * hc.CHAR_W, hc.WIDTH)

    def test_a_command_wraps_once_and_no_row_is_wider_than_the_grid(self):
        rows, dropped = hc.build_rows("pip install ag-ui-protocol fastapi uvicorn", ["Successfully installed a b c"], 8)
        self.assertEqual(dropped, 0)
        self.assertTrue(all(len(r["text"]) <= hc.COLS for r in rows))
        self.assertEqual([r["kind"] for r in rows], ["cmd", "cmd", "out", "out"][:len(rows)])
        self.assertEqual(rows[0]["text"], "$ pip install ag-ui-protocol fastapi")

    def test_a_long_output_keeps_its_end_and_says_what_it_left_out(self):
        out = [f"line {i}" for i in range(30)]
        rows, dropped = hc.build_rows("npm install tsx", out, 8)
        self.assertLessEqual(len(rows), 8)
        self.assertEqual(rows[1]["kind"], "note")
        self.assertEqual(rows[1]["text"], f"[... {dropped} earlier lines]")
        self.assertEqual(rows[-1]["text"], "line 29")
        self.assertEqual(dropped, 30 - len([r for r in rows if r["kind"] == "out"]))

    def test_one_line_too_long_for_the_rows_is_cut_and_marked(self):
        rows, _ = hc.build_rows("x", ["word " * 100], 5)
        self.assertLessEqual(len(rows), 5)
        self.assertTrue(rows[-1]["text"].endswith("..."))

    def test_a_command_that_needs_more_than_half_the_rows_is_refused(self):
        self.assertEqual(refusal(hc.build_rows, "pip install " + "a" * 150, [], 8).kind, "too-tall")

    def test_bands_are_rects_on_the_grid_and_must_be_on_one_row(self):
        rows, _ = hc.build_rows("npx tsx client.ts", ["run started (AG-UI 1.0)", "Hello from AG-UI!", "run finished"], 8)
        geo = hc.layout(rows, ["Hello from AG-UI!"])
        x, y, w, h = geo["bands"][0]["rect"]
        self.assertEqual((x, w, h), (hc.PAD_X, 17 * hc.CHAR_W, hc.LINE_H))
        self.assertEqual(y, hc.PAD_Y + 2 * hc.LINE_H)
        self.assertEqual(geo["u_rows"], [geo["focus"][0] - 24, geo["focus"][1] + 12])
        self.assertEqual(refusal(hc.layout, rows, ["not shown"]).kind, "band")

    def test_output_is_cleaned_like_a_terminal(self):
        self.assertEqual(hc.clean_output("a\r\nprogress 10%\rprogress 100%\r\n\n\x1b[32mgreen\x1b[0m\t!\n  \n"), ["a", "progress 100%", "green   !"])

    def test_glyphs_the_font_lacks_are_refused(self):
        self.assertIsNone(refusal(hc.check_glyphs, [dict(kind="out", text="Hello from AG-UI! 100%")]))
        self.assertEqual(refusal(hc.check_glyphs, [dict(kind="out", text="Xin chào 漢")]).kind, "glyph")

    def test_the_manifest_the_assembler_reads_is_valid(self):
        kb = load("halcyon_kich_ban_t", "video/halcyon/halcyon_kich_ban.py")
        rows, _ = hc.build_rows("npx tsx client.ts", ["Hello from AG-UI!"], 8)
        geo = hc.layout(rows, ["Hello from AG-UI!"])
        entry = dict(file="s5.png", focus=dict(rows=geo["focus"]), u_rows=geo["u_rows"], source="x", date="20/11/2026", captured="2026-11-20T20:00:00+07:00", bands=geo["bands"], text="t")
        self.assertIn("a", kb.check_manifest({"captures": {"a": entry}}))


class Drawing(unittest.TestCase):
    def test_the_picture_has_flat_margins_and_text_ink_inside_the_shown_rows(self):
        try:
            from PIL import Image
            import numpy as np
        except ImportError:
            self.skipTest("Pillow and numpy are in the GPU interpreter, not in every Python")
        rows, _ = hc.build_rows("npx tsx client.ts", ["run started (AG-UI 1.0)", "Hello from AG-UI!", "run finished"], 8)
        geo = hc.layout(rows, ["Hello from AG-UI!"])
        with tempfile.TemporaryDirectory() as d:
            size = hc.draw(rows, geo, Path(d) / "s.png")
            img = np.asarray(Image.open(Path(d) / "s.png").convert("L")).astype(int)
        self.assertEqual(size, (1170, geo["height"]))
        bg = int(0.299 * 13 + 0.587 * 17 + 0.114 * 23)
        ink = (abs(img - bg) > 85)[:, 60:1110].any(axis=1)
        ys = np.nonzero(ink)[0]
        self.assertGreaterEqual(ys[0], geo["u_rows"][0] + 24)
        self.assertLessEqual(ys[-1], geo["u_rows"][1] - 12)
        with tempfile.TemporaryDirectory() as d2:
            hc.draw(rows, geo, Path(d2) / "s.png")
            rgb = np.asarray(Image.open(Path(d2) / "s.png").convert("RGB")).astype(int)
        x, y, w, h = geo["bands"][0]["rect"]
        amber = (np.abs(rgb[y:y + h, x:x + w] - np.array(hc.MARK)).sum(2) < 12).sum()
        other = (np.abs(rgb[y + h:y + 2 * h, x:x + w] - np.array(hc.MARK)).sum(2) < 12).sum()
        self.assertGreater(amber, 200)               # the phrase to highlight is drawn in the highlight colour, the other rows are not
        self.assertEqual(other, 0)
        self.assertFalse(ink[geo["u_rows"][0] - 2: geo["u_rows"][0] + 3].any())
        self.assertFalse(ink[geo["u_rows"][1] - 2: geo["u_rows"][1] + 3].any())


DOC = "https://raw.githubusercontent.com/o/p/main/README.md"
SERVER_PY = """# serve.py
import http.server, sys
print("listening on", sys.argv, flush=True)
http.server.HTTPServer(("127.0.0.1", PORT), http.server.SimpleHTTPRequestHandler).serve_forever()
"""
HELLO_PY = """# hello.py
import sys
print("Hello from the throwaway folder")
sys.exit(CODE)
"""


def doc(*blocks):
    return "\n".join(f"```python\n{b}```\n" if b.startswith("#") else f"```bash\n{b}\n```\n" for b in blocks).encode("utf-8")


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(importlib.util.find_spec("PIL"), "draws the pictures: needs Pillow (the GPU interpreter has it; the CI Python does not)")
class RunsForReal(unittest.TestCase):
    """`run` with the network replaced (the README and the registries are fakes) and real local processes: python in a venv inside the throwaway folder. Each gate that fires while
    the run is going is shown refusing here; the packages' own installs are the live proof run."""

    def go(self, readme, steps, packages=None, files=None, fetch_json=lambda u: {}, bands=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        out = Path(self.tmp.name) / "out"
        run = dict(files=files or [dict(name="hello.py", **{"from": DOC}, fence="# hello.py")], steps=steps)
        if packages:
            run["packages"] = packages
        return out, lambda: hc.run(dict(ref="t", run=run, bands=bands or {}), out, lambda u: readme, fetch_json, say=lambda s: None)

    def test_a_good_run_keeps_a_log_and_the_stills_and_deletes_the_throwaway_folder(self):
        out, go = self.go(doc(HELLO_PY.replace("CODE", "0")), [block("python hello.py", expect=["Hello from the throwaway folder"])], bands={"0": ["Hello from the throwaway folder"]})
        # one band row is 31 characters: fits the grid
        res = go()
        self.assertTrue(res["throwaway_folder_deleted"])
        self.assertFalse((out / "work").exists())
        self.assertTrue((out / "log" / "step-0.log").exists())
        self.assertTrue((out / "s0.png").exists())
        self.assertEqual(res["leftover_processes_after"], 0)
        self.assertEqual(res["states"][0]["exit"], 0)
        self.assertEqual(res["files"][0]["sha256"], hc.sha(HELLO_PY.replace("CODE", "0").encode()))
        self.assertTrue((out / "chay.json").exists())
        self.assertFalse([k for k in res["environment"]["passed"] if re.search(r"(?i)KEY|TOKEN|SECRET", k)])

    def test_a_step_that_exits_non_zero_is_refused(self):
        out, go = self.go(doc(HELLO_PY.replace("CODE", "3")), [block("python hello.py")])
        e = refusal(go)
        self.assertEqual(e.kind, "exit")
        self.assertIn("exited with 3", e.why)
        self.assertFalse((out / "work").exists())             # the throwaway folder goes even when the run is refused
        self.assertTrue((out / "log").exists())

    def test_text_the_real_output_does_not_hold_is_refused(self):
        _, go = self.go(doc(HELLO_PY.replace("CODE", "0")), [block("python hello.py", expect=["Hello from AG-UI!"])])
        e = refusal(go)
        self.assertEqual(e.kind, "expect")
        self.assertIn("Hello from the throwaway folder", e.why)

    def test_a_phrase_to_highlight_that_is_not_shown_is_refused(self):
        _, go = self.go(doc(HELLO_PY.replace("CODE", "0")), [block("python hello.py")], bands={"0": ["Hello from AG-UI!"]})
        self.assertEqual(refusal(go).kind, "band")

    def test_a_file_not_taken_from_a_fenced_block_is_refused(self):
        _, go = self.go(doc("pip install fastapi"), [block("python hello.py")])
        self.assertEqual(refusal(go).kind, "fence")
        _, go = self.go(b"# hello.py\nprint(1)\n", [block("python hello.py")])        # the text is in the README but not inside a fence
        self.assertEqual(refusal(go).kind, "fence")

    def test_a_package_the_source_does_not_name_is_refused_before_it_is_looked_up(self):
        asked = []
        _, go = self.go(doc(HELLO_PY.replace("CODE", "0"), "pip install fastapi"), [block("pip install left-pad")], packages={"left-pad": "o/left-pad"}, fetch_json=lambda u: asked.append(u))
        e = refusal(go)
        self.assertEqual(e.kind, "package-source")
        self.assertEqual(asked, [])

    def test_a_look_alike_package_stops_the_run_before_any_install(self):
        _, go = self.go(doc(HELLO_PY.replace("CODE", "0"), "pip install fastap1"), [block("pip install fastap1")], packages={"fastap1": "fastapi/fastapi"},
                        fetch_json=lambda u: pypi_doc("0.0.1", {"Homepage": "https://github.com/evil/fastap1"}))
        self.assertEqual(refusal(go).kind, "typosquat")

    def test_a_busy_port_is_refused_before_anything_starts(self):
        import socket
        port = free_port()
        s = socket.socket()
        s.bind(("127.0.0.1", port))
        s.listen(1)
        self.addCleanup(s.close)
        _, go = self.go(doc(SERVER_PY.replace("PORT", str(port))), [block("python serve.py", serve=True, ready="listening", port=port)],
                        files=[dict(name="serve.py", **{"from": DOC}, fence="# serve.py")])
        e = refusal(go)
        self.assertEqual(e.kind, "port")
        self.assertIn(str(port), e.why)

    def test_a_server_is_waited_for_and_stopped_and_nothing_is_left_running(self):
        port = free_port()
        out, go = self.go(doc(SERVER_PY.replace("PORT", str(port))), [block("python serve.py", serve=True, ready="listening", port=port)],
                          files=[dict(name="serve.py", **{"from": DOC}, fence="# serve.py")])
        res = go()
        self.assertEqual(res["leftover_processes_after"], 0)
        self.assertFalse(hc.port_busy(port))
        self.assertTrue(res["throwaway_folder_deleted"])

    def test_a_server_that_never_says_it_is_ready_is_refused_and_stopped(self):
        port = free_port()
        old, hc.READY_DEADLINE = hc.READY_DEADLINE, 4
        self.addCleanup(setattr, hc, "READY_DEADLINE", old)
        _, go = self.go(doc(SERVER_PY.replace("PORT", str(port))), [block("python serve.py", serve=True, ready="never printed", port=port)],
                        files=[dict(name="serve.py", **{"from": DOC}, fence="# serve.py")])
        e = refusal(go)
        self.assertEqual(e.kind, "serve")
        self.assertFalse(hc.port_busy(port))

    def test_a_step_over_its_deadline_is_killed(self):
        slow = "# slow.py\nimport time\ntime.sleep(60)\n"
        _, go = self.go(doc(slow), [block("python slow.py", deadline=10)], files=[dict(name="slow.py", **{"from": DOC}, fence="# slow.py")])
        e = refusal(go)
        self.assertEqual(e.kind, "deadline")


if __name__ == "__main__":
    unittest.main()
