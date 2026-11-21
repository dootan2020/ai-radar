"""Halcyon scene3d producer (halcyon_canh.py, video/halcyon/scene3d/): the timeline the three.js page draws, the sources it is proved against,
and every gate that refuses a clip. Standard library only: nothing here needs Chrome, a GPU, ffmpeg or the network."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAL = ROOT / "video" / "halcyon"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


entry = load_module("halcyon_canh_t", HAL / "halcyon_canh.py")
canh = entry.canh
SRC = canh.load_sources()

FENCE = '''```python
# server.py
from ag_ui.encoder import EventEncoder

@app.post("/")
async def run_agent(input_data: RunAgentInput, request: Request):
    encoder = EventEncoder(accept=request.headers.get("accept"))

    async def events():
        yield encoder.encode(RunStartedEvent(
            thread_id=input_data.thread_id,
        ))
        message_id = str(uuid.uuid4())
        yield encoder.encode(TextMessageStartEvent(message_id=message_id, role="assistant"))
        for chunk in ["Hello ", "from ", "AG-UI!"]:
            yield encoder.encode(TextMessageContentEvent(message_id=message_id, delta=chunk))
        yield encoder.encode(TextMessageEndEvent(message_id=message_id))
        yield encoder.encode(RunFinishedEvent(thread_id=input_data.thread_id, run_id=input_data.run_id))

    return StreamingResponse(events(), media_type=encoder.get_content_type())
```
'''
DEMO = {"TOOL_CALL_START": 1, "TOOL_CALL_ARGS": 12, "TOOL_CALL_END": 1, "TOOL_CALL_RESULT": 1, "STATE_SNAPSHOT": 35, "TEXT_MESSAGE_CONTENT": 29,
        "RAW": 123, "RUN_STARTED": 1, "RUN_FINISHED": 1}


def chay(source=None, sha=None, printed="Hello from AG-UI!"):
    return {"files": [{"name": "server.py", "source": source or SRC["readme"]["url"], "sha256": sha or SRC["fence"]["sha256"]}],
            "states": [{"step": 5, "output": ["run started (AG-UI 1.0)", printed, "run finished"]}], "captured": "2026-11-21T00:52:15+07:00"}


def good_render(**over):
    rj = {"renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 Direct3D11 vs_5_0 ps_5_0, D3D11)", "aborted": 0, "fonts": [["600 32px BVP", True]],
          "frames": 660, "determinism": {"pixels": [{"f": 132, "max_diff": 2, "over_tol": 0}]}, "labels": {"min_size": 28, "violations": [], "frames": 660}}
    rj.update(over)
    return rj


class Sources(unittest.TestCase):
    def test_wire_names_are_the_sdk_classes_in_screaming_snake_case(self):
        self.assertEqual(canh.wire_name("RunStartedEvent"), "RUN_STARTED")
        self.assertEqual(canh.wire_name("TextMessageContentEvent"), "TEXT_MESSAGE_CONTENT")
        self.assertEqual(canh.wire_name("ToolCallArgs"), "TOOL_CALL_ARGS")

    def test_the_server_fence_gives_seven_events_with_the_loop_expanded(self):
        ev, de = canh.events_from_fence(canh.fence(FENCE, "# server.py"))
        self.assertEqual(ev, SRC["events"])
        self.assertEqual(de, ["Hello ", "from ", "AG-UI!"])
        self.assertEqual(len(ev), 7)

    def test_a_readme_other_than_the_pinned_one_is_refused(self):
        with self.assertRaises(canh.Refusal) as cm:
            canh.check_readme(SRC, FENCE)
        self.assertIn("is not the pinned", str(cm.exception))

    def test_a_readme_whose_fence_says_something_else_is_refused(self):
        changed = FENCE.replace('["Hello ", "from ", "AG-UI!"]', '["Hi"]')
        src = dict(SRC, readme=dict(SRC["readme"], sha256=hashlib.sha256(changed.encode()).hexdigest()))
        with self.assertRaises(canh.Refusal) as cm:
            canh.check_readme(src, changed)
        self.assertIn("the scene draws", str(cm.exception))
        same = dict(SRC, readme=dict(SRC["readme"], sha256=hashlib.sha256(FENCE.encode()).hexdigest()))
        self.assertEqual(canh.check_readme(same, FENCE)["events"], SRC["events"])

    def test_no_fence_is_a_refusal(self):
        with self.assertRaises(canh.Refusal):
            canh.fence("no code here", "# server.py")

    def test_the_run_record_must_have_run_the_pinned_fence_and_printed_its_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "chay.json"
            p.write_text(json.dumps(chay()), encoding="utf-8")
            self.assertEqual(canh.check_run(SRC, p)["printed"], "Hello from AG-UI!")
            for bad, said in ((chay(sha="0" * 64), "the scene is pinned"), (chay(source="https://example.com/README.md"), "the scene is pinned"),
                              (chay(printed="nothing"), "never printed")):
                p.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(canh.Refusal) as cm:
                    canh.check_run(SRC, p)
                self.assertIn(said, str(cm.exception))
            with self.assertRaises(canh.Refusal):
                canh.check_run(SRC, Path(d) / "missing.json")

    def test_demo_counts_are_read_and_bad_ones_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "demo.json"
            p.write_text(json.dumps({"events": DEMO, "source": "dojo", "date": "21/11/2026"}), encoding="utf-8")
            self.assertEqual(canh.counts_from_demo(p)["counts"]["STATE_SNAPSHOT"], 35)
            p.write_text(json.dumps({"events": {"total": 209, "by_type": DEMO, "order": ["RUN_STARTED", "STATE_SNAPSHOT"], "streams": 1}}), encoding="utf-8")
            c = canh.counts_from_demo(p)                                   # the shape halcyon_demo.py writes
            self.assertEqual((c["counts"]["TOOL_CALL_ARGS"], c["order"]), (12, ["RUN_STARTED", "STATE_SNAPSHOT"]))
            p.write_text(json.dumps({"event_counts": DEMO}), encoding="utf-8")
            self.assertEqual(canh.counts_from_demo(p)["counts"]["TEXT_MESSAGE_CONTENT"], 29)
            for bad in ({}, {"events": {}}, {"events": {"X": -1}}, {"events": {"X": True}}, {"events": ["RUN_STARTED"]}):
                p.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(canh.Refusal):
                    canh.counts_from_demo(p)
        self.assertIsNone(canh.counts_from_demo(None))


class Timeline(unittest.TestCase):
    def counts(self):
        return {"counts": DEMO, "source": "dojo", "date": "21/11/2026"}

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the production page timeline tests')
    def test_the_page_samples_the_producer_timeline_without_a_browser(self):
        counts = dict(self.counts(), counts=dict(DEMO, TOOL_CALL_ARGS=15, TEXT_MESSAGE_CONTENT=22),
                      order=['RUN_STARTED', 'STATE_SNAPSHOT', 'TOOL_CALL_START', 'TEXT_MESSAGE_CONTENT', 'RUN_FINISHED'])
        cases = dict(counted=canh.timeline(SRC, counts, 26), names=canh.timeline(SRC),
                     narrated=canh.timeline(SRC, counts, 25),
                     voiced=canh.timeline(SRC, counts, 25.25),
                     short_counted=canh.timeline(SRC, counts, 22), long_counted=canh.timeline(SRC, counts, 30),
                     shortest=canh.timeline(SRC, counts, 18), longest=canh.timeline(SRC, counts, 34))
        result = subprocess.run(['node', str(HAL / 'scene3d' / 'timeline.test.mjs')], input=json.dumps(cases),
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_act_three_is_the_pinned_run_in_order_and_each_text_bead_carries_its_delta(self):
        d = canh.timeline(SRC, self.counts())
        self.assertEqual([e["name"] for e in d["run1"]], SRC["events"])
        self.assertEqual("".join(e["delta"] for e in d["run1"] if e["delta"]), "Hello from AG-UI!")
        self.assertTrue(all(a["t1"] <= b["t1"] for a, b in zip(d["run1"], d["run1"][1:])))
        self.assertTrue(canh.check_timeline(d, SRC, self.counts()))

    def test_act_four_draws_exactly_the_demo_counts(self):
        d = canh.timeline(SRC, self.counts())
        tal = {t["label"]: t["total"] for t in d["run2"]["tallies"]}
        self.assertEqual(tal, {"TOOL_CALL_*": 15, "STATE_SNAPSHOT": 35, "TEXT_MESSAGE_CONTENT": 29})
        kinds = [b["kind"] for b in d["run2"]["beads"]]
        self.assertEqual((kinds.count("tool"), kinds.count("state"), kinds.count("text")), (15, 35, 29))
        self.assertEqual(kinds[0], "life")
        self.assertEqual(kinds[-1], "life")

    def test_act_four_sends_the_kinds_in_the_order_the_demo_stream_first_had_them(self):
        order = ["RUN_STARTED", "STEP_STARTED", "STATE_SNAPSHOT", "RAW", "TOOL_CALL_START", "TOOL_CALL_ARGS", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "RUN_FINISHED"]
        c = dict(self.counts(), order=order)
        d = canh.timeline(SRC, c)
        self.assertEqual(d["run2"]["kind_order"], ["state", "tool", "text"])
        self.assertEqual([t["label"] for t in d["run2"]["tallies"]], ["STATE_SNAPSHOT", "TOOL_CALL_*", "TEXT_MESSAGE_CONTENT"])
        kinds = [b["kind"] for b in d["run2"]["beads"]]
        self.assertEqual(kinds, ["life"] + ["state"] * 35 + ["tool"] * 15 + ["text"] * 29 + ["life"])   # each kind one group, in first-appearance order
        self.assertTrue(canh.check_timeline(d, SRC, c))
        d = canh.timeline(SRC, self.counts())                            # no order: the table's order
        self.assertEqual(d["run2"]["kind_order"], ["tool", "state", "text"])
        self.assertIn("not given", d["run2"]["kind_order_from"])
        with self.assertRaises(canh.Refusal):
            canh.timeline(SRC, dict(self.counts(), order=["RUN_STARTED", "TEXT_MESSAGE_CONTENT", "RUN_FINISHED"]))

    def test_without_a_demo_the_scene_names_the_types_only(self):
        d = canh.timeline(SRC, None)
        self.assertTrue(all(t["total"] is None for t in d["run2"]["tallies"]))
        self.assertEqual(len([b for b in d["run2"]["beads"] if b["kind"] != "life"]), 3)
        self.assertTrue(canh.check_timeline(d, SRC, None))

    def test_the_timeline_is_pure_and_fits_the_clip(self):
        a, b = canh.timeline(SRC, self.counts()), canh.timeline(SRC, self.counts())
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual((a["w"], a["h"], a["fps"], a["frames"], a["duration"]), (886, 976, 30, 660, 22.0))     # default: the 22 s narration
        self.assertAlmostEqual(a["scale"] * a["base"], a["duration"])
        b = canh.timeline(SRC, self.counts(), 26)
        self.assertEqual((b["frames"], b["scale"]), (780, 1.0))
        self.assertEqual(b["run1"], a["run1"])                                    # the base timeline is the same; only the playback scale changes
        for bad in (10, 41, "22", True, None.__class__):
            with self.assertRaises(canh.Refusal):
                canh.timeline(SRC, self.counts(), bad)
        self.assertLessEqual(a["duration"], 40)
        self.assertEqual([x["name"] for x in a["swap"]], SRC["frameworks"])

    def test_a_planted_change_turns_the_proof_of_diagram_red(self):
        d = canh.timeline(SRC, self.counts())
        d["run1"][2]["name"] = "TOOL_CALL_START"
        with self.assertRaises(canh.Refusal):
            canh.check_timeline(d, SRC, self.counts())
        d = canh.timeline(SRC, self.counts())
        d["run2"]["beads"].pop(5)
        with self.assertRaises(canh.Refusal):
            canh.check_timeline(d, SRC, self.counts())


class ProducerPaths(unittest.TestCase):
    def test_relative_job_and_output_survive_the_renderer_working_directory(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='scene paths ') as d:
            root = Path(d)
            job = root / 'job.json'
            job.write_text(json.dumps({'scene': {'name': 'giao-thuc'}}), encoding='utf-8')
            out = root / 'render output'
            dependencies = root / 'dependencies'
            dependencies.mkdir()

            def renderer(cmd, *, cwd, **kwargs):
                self.assertEqual(cwd, dependencies)
                paths = {flag: Path(cmd[cmd.index(flag) + 1]) for flag in ('--data', '--out')}
                self.assertTrue(all(p.is_absolute() for p in paths.values()), paths)
                self.assertEqual(paths['--out'], out)
                self.assertEqual(json.loads(paths['--data'].read_text(encoding='utf-8'))['frames'], 660)
                (paths['--out'] / 'render.err').write_bytes(b'')
                (paths['--out'] / 'render.json').write_text(json.dumps(good_render()), encoding='utf-8')
                return subprocess.CompletedProcess(cmd, 0, '', '')

            with mock.patch.object(canh, 'node_dir', return_value=dependencies), \
                 mock.patch.object(canh, 'three_build', return_value=dependencies / 'three'), \
                 mock.patch.object(canh.subprocess, 'run', side_effect=renderer), \
                 mock.patch.object(canh, 'determinism'), mock.patch.object(canh, 'check_encoded', return_value={}):
                args = ['run', '--job', str(job.relative_to(ROOT)), '--out', str(out.relative_to(ROOT))]
                self.assertEqual(canh.main(args, say=lambda _: None), 0)
            self.assertTrue((out / 'render.err').exists())
            self.assertEqual(json.loads((out / 'clip.json').read_text(encoding='utf-8'))['frames'], 660)


class Gates(unittest.TestCase):
    def test_a_clock_in_a_page_helper_is_refused_before_rendering(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in canh.PAGE_MODULES:
                shutil.copy2(HAL / 'scene3d' / name, root / name)
            (root / 'timeline.mjs').write_bytes(b'const now = Date.now();\n')
            with mock.patch.object(canh, 'HERE', root), mock.patch.object(canh, 'render') as render:
                with self.assertRaises(canh.Refusal) as cm:
                    canh.run({'scene': {'name': 'giao-thuc'}}, root / 'out')
                self.assertIn('timeline.mjs uses Date', str(cm.exception))
                render.assert_not_called()

    def test_the_scene_source_reads_no_clock_and_no_randomness(self):
        for name in canh.PAGE_MODULES:
            self.assertTrue(canh.check_scene_source((HAL / "scene3d" / name).read_text(encoding="utf-8"), name))
            self.assertIn(name, canh.SCENE_FILES)
        for bad in ("const t = Date.now();", "x = Math.random();", "requestAnimationFrame(f);", "performance.now()", "setTimeout(f, 1)"):
            with self.assertRaises(canh.Refusal):
                canh.check_scene_source(bad)
        self.assertTrue(canh.check_scene_source("// no Date, no Math.random here\nconst a = 1;"))

    def test_render_gates(self):
        d = canh.timeline(SRC, None)
        self.assertTrue(canh.check_render(good_render(), d))   # 22 s default: 660 frames
        for over, said in ((dict(renderer="ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)"), "software"),
                           (dict(renderer=""), "software"),
                           (dict(aborted=2, aborted_urls=["https://cdn.example/three.js"]), "off the local origin"),
                           (dict(fonts=[["800 46px BarlowXB", False]]), "fonts did not load"),
                           (dict(frames=659), "rendered 659 frames"),
                           (dict(determinism={"pixels": [{"f": 1, "max_diff": 40, "over_tol": 900}]}), "differ by more than"),
                           (dict(determinism={}), "differ by more than"),
                           (dict(labels={"min_size": 28, "violations": ['f3 "A" overlaps "B"'], "frames": 780}), "labels outside"),
                           (dict(labels={"min_size": 27, "violations": [], "frames": 780}), "the floor is 28")):
            with self.assertRaises(canh.Refusal, msg=said) as cm:
                canh.check_render(good_render(**over), d)
            self.assertIn(said, str(cm.exception))

    def test_repeatability_keeps_the_four_level_boundary_for_the_voiced_clip(self):
        d = canh.timeline(SRC, None, 25.25)
        for difference in (2, 4, 5, 6):
            render = good_render(frames=d['frames'],
                                 determinism={'pixels': [{'f': 416, 'max_diff': difference, 'over_tol': int(difference > 4)}]})
            if difference <= 4:
                self.assertTrue(canh.check_render(render, d))
            else:
                with self.assertRaisesRegex(canh.Refusal, 'differ by more than 4 levels'):
                    canh.check_render(render, d)

    def test_three_is_pinned_and_the_entry_point_says_it_is_built(self):
        self.assertEqual(canh.THREE_VERSION, "0.187.0")
        self.assertEqual(set(canh.THREE_PIN), {"three.module.js", "three.core.js"})
        self.assertRegex((HAL / "halcyon_canh.py").read_text(encoding="utf-8"), r"(?m)^CLIP_PRODUCER = 1$")
        lines = []
        self.assertEqual(canh.main([], say=lines.append), 2)
        self.assertIn("run --job", lines[0])

    def test_a_job_naming_another_scene_is_refused_before_anything_runs(self):
        with tempfile.TemporaryDirectory() as d:
            job = Path(d) / "job.json"
            job.write_text(json.dumps({"ref": "x", "scene": {"name": "khac"}}), encoding="utf-8")
            lines = []
            self.assertEqual(canh.main(["run", "--job", str(job), "--out", str(Path(d) / "o")], say=lines.append), 1)
            self.assertIn('scene "khac" is not built', "\n".join(lines))

    def test_the_clip_fits_the_builder_window(self):
        sys.path.insert(0, str(HAL))
        try:
            ve = load_module("ve_halcyon_canh_t", HAL / "ve_halcyon.py")
        except ImportError as e:
            self.skipTest(f"ve_halcyon needs {e}")
        finally:
            sys.path.remove(str(HAL))
        ve.set_layout("thu-gon-r3-l2")
        top, bottom = ve.WIN["FOOT"]
        self.assertLessEqual(canh.H, bottom - top)
        self.assertLessEqual(canh.W, ve.REC_W)
        y_at, x_at = (top + bottom) // 2 - canh.H // 2, (ve.W - canh.W) // 2          # where the builder seats the clip (halcyon_spec.plan_clip)
        self.assertLessEqual(canh.SAFE_BOTTOM, ve.SLOT[1] - y_at)                       # no label reaches the subtitle's slot
        self.assertLessEqual(canh.COLUMN["from_y"], ve.COL_Y - y_at)                    # the right-hand limit starts no lower than the button column
        self.assertLessEqual(x_at + canh.COLUMN["max_x"], 907)                          # TikTok's button column starts at frame x 907


if __name__ == "__main__":
    unittest.main()
