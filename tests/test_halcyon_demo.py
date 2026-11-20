"""Halcyon demo recorder (video/halcyon/halcyon_demo.py and demo/quay-demo.mjs).
The job checks and every gate over a recording (`judge`) are pure and run offline, each with a planted violation that must be refused. The recorder tests drive the real
quay-demo.mjs against a fake agent page served from 127.0.0.1 (same test ids as the AG-UI Dojo page, a real text/event-stream), so they need Node, `npm install` in video/ and
Chrome and skip without them. The test against the live Dojo runs only when HALCYON_LIVE=1 (it types a sentence into a third party's public demo)."""
import copy
import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HALCYON = ROOT / "video" / "halcyon"
PW = ROOT / "video" / ("node" + "_modules") / "playwright-core"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hd = load("halcyon_demo", "video/halcyon/halcyon_demo.py")
mot = load("halcyon_mot_lenh", "video/halcyon/halcyon_mot_lenh.py")
kb = load("halcyon_kich_ban", "video/halcyon/halcyon_kich_ban.py")


def chrome_ok():
    if os.environ.get("CHROME_PATH"):
        return Path(os.environ["CHROME_PATH"]).exists()
    return any(Path(p).exists() for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                                          "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/opt/google/chrome/chrome"))


CAN_RECORD = bool(shutil.which("node") and shutil.which("ffprobe") and PW.exists() and chrome_ok())

JOB = {"ref": "ag-ui", "demo": {"entry": "https://dojo.ag-ui.com/langgraph-fastapi/feature/shared_state",
                                "page": "https://showcase-langgraph-fastapi-production.up.railway.app/demos/shared-state-read-write",
                                "say": "Mình thích phở và đạp xe", "expect": {"events": ["TOOL_CALL_START", "STATE_SNAPSHOT"], "effect": "notes"}}}
REC = {"page": "x", "say": "x", "blocked": [], "streams": [{"url": "u", "status": 200}], "notes_before": 0, "notes_empty_before": True, "notes_empty_after": False,
       "notes": ["Thích phở", "Thích đạp xe"], "answer": "Đã nhớ.",
       "events": [{"total": 9, "by_type": {"RUN_STARTED": 1, "TOOL_CALL_START": 1, "STATE_SNAPSHOT": 3, "TEXT_MESSAGE_CONTENT": 3, "RUN_FINISHED": 1}, "order": []}],
       "moments": {"page_ready": 1.4, "typed_start": 3.0, "typed_end": 5.0, "sent": 5.5, "answer_start": 10.0, "answer_end": 11.0, "chat_closed": 13.0, "notes_in_view": 15.0, "end": 18.0}}
PROBE = {"w": 390, "h": 844, "frames": 450, "fps": 25, "duration": 18.0}
WANT = hd.check_expect(JOB["demo"]["expect"])


def refused(kind, fn, *a):
    try:
        fn(*a)
    except hd.Refusal as e:
        assert e.kind == kind, f"refused as {e.kind} ({e.why}), wanted {kind}"
        return e
    raise AssertionError(f"not refused (wanted {kind})")


class JobTests(unittest.TestCase):
    def test_good_job(self):
        j = hd.check_job(JOB)
        self.assertEqual(j["hosts"], ["dojo.ag-ui.com", "showcase-langgraph-fastapi-production.up.railway.app"])
        self.assertEqual(j["expect"]["events"][:2], ["RUN_STARTED", "RUN_FINISHED"])

    def test_addresses_must_be_public_https(self):
        for bad in ("http://dojo.ag-ui.com/x", "https://localhost:8080/", "https://127.0.0.1/", "https://192.168.1.5/x", "https://intranet/x", "file:///c:/x", "dojo.ag-ui.com"):
            job = copy.deepcopy(JOB)
            job["demo"]["page"] = bad
            refused("address", hd.check_job, job)

    def test_sentence_holds_nothing_personal(self):
        for bad in ("", "a" * 91, "viết\nhai dòng", "mail me at a@b.co", "xem https://x.y", "số 0912345678"):
            refused("say", hd.check_say, bad)

    def test_expect(self):
        refused("expect", hd.check_expect, {})
        refused("expect", hd.check_expect, {"events": ["tool call"]})
        refused("expect", hd.check_expect, {"effect": ""})
        refused("expect", hd.check_expect, {"effect": 3})
        self.assertEqual(hd.check_expect({"events": [], "effect": "one note"})["effect"], "one note")
        refused("expect", hd.check_expect, {"events": [], "min_notes": 0})
        refused("expect", hd.check_expect, {"foo": 1})

    def test_the_chain_sees_a_built_producer(self):
        self.assertTrue(mot.producer_ready("demo"))
        self.assertEqual(mot.PRODUCERS["demo"]["tool"], "halcyon_demo.py")

    def test_manifest_fields_the_chain_needs(self):
        facts = hd.judge(copy.deepcopy(REC), WANT, PROBE)
        self.assertEqual(facts["events"]["by_type"]["TOOL_CALL_START"], 1)
        src = (HALCYON / "halcyon_demo.py").read_text(encoding="utf-8")   # the manifest of run(): every field of DEMO_FIELDS
        for f in kb.DEMO_FIELDS:
            self.assertRegex(src, rf"\b{f}=", f"the manifest does not say {f}")


class GateTests(unittest.TestCase):
    def test_good_recording(self):
        facts = hd.judge(copy.deepcopy(REC), WANT, PROBE)
        self.assertEqual(facts["notes"], ["Thích phở", "Thích đạp xe"])

    def test_no_stream(self):
        rec = copy.deepcopy(REC); rec["streams"] = []; rec["events"] = []
        refused("events", hd.judge, rec, WANT, PROBE)

    def test_missing_event(self):
        rec = copy.deepcopy(REC); del rec["events"][0]["by_type"]["TOOL_CALL_START"]
        e = refused("events", hd.judge, rec, WANT, PROBE)
        self.assertIn("TOOL_CALL_START", e.why)

    def test_run_never_finished(self):
        rec = copy.deepcopy(REC); del rec["events"][0]["by_type"]["RUN_FINISHED"]
        refused("events", hd.judge, rec, WANT, PROBE)

    def test_no_effect(self):
        rec = copy.deepcopy(REC); rec["notes"] = []; rec["notes_empty_after"] = True
        refused("effect", hd.judge, rec, WANT, PROBE)

    def test_notes_were_there_before(self):
        rec = copy.deepcopy(REC); rec["notes_before"] = 2; rec["notes_empty_before"] = False
        refused("effect", hd.judge, rec, WANT, PROBE)

    def test_empty_answer(self):
        rec = copy.deepcopy(REC); rec["answer"] = "  "
        refused("effect", hd.judge, rec, WANT, PROBE)

    def test_left_the_hosts(self):
        rec = copy.deepcopy(REC); rec["blocked"] = ["https://ads.example.com/x"]
        refused("navigation", hd.judge, rec, WANT, PROBE)

    def test_moments_out_of_order(self):
        rec = copy.deepcopy(REC); rec["moments"]["sent"] = 99
        refused("timeline", hd.judge, rec, WANT, PROBE)

    def test_video_size_and_rate(self):
        refused("video", hd.judge, copy.deepcopy(REC), WANT, dict(PROBE, w=800))
        refused("video", hd.judge, copy.deepcopy(REC), WANT, dict(PROBE, fps=30))

    def test_video_not_the_driven_time(self):
        refused("timeline", hd.judge, copy.deepcopy(REC), WANT, dict(PROBE, frames=300, duration=12.0))


# ---------------------------------------------------------------- the recorder against a fake agent page (a real SSE stream, the Dojo's test ids)
PAGE = """<!doctype html><meta charset=utf-8><title>fake</title><body style="font:16px sans-serif">
<h1>Shared state</h1><p>%s</p>
<div data-testid=notes-card><h2>Agent Scratch pad</h2><div data-testid=notes-empty>No notes yet</div><ol data-testid=notes-list></ol></div>
<div data-testid=copilot-sidebar style="position:fixed;inset:0;background:#fff"><button data-testid=copilot-close-button aria-label=Close onclick="this.parentNode.style.display='none'">x</button>
<div data-testid=copilot-message-list></div><textarea data-testid=copilot-chat-textarea></textarea><button data-testid=copilot-send-button id=s>send</button></div>
<script>
s.onclick=async()=>{const ta=document.querySelector('textarea'),list=document.querySelector('[data-testid=copilot-message-list]');
 list.insertAdjacentHTML('beforeend','<div data-testid=copilot-user-message>'+ta.value+'</div>');
 const r=await fetch('/api/run',{method:'POST',body:'{}'});const t=await r.text();
 const ol=document.querySelector('[data-testid=notes-list]');document.querySelector('[data-testid=notes-empty]').remove();
 for(const n of ['Thich pho','Thich dap xe'])ol.insertAdjacentHTML('beforeend','<li data-testid=note-item>'+n+'</li>');
 list.insertAdjacentHTML('beforeend','<div data-testid=copilot-assistant-message>Da nho.</div>');};
</script>"""
EVENTS = ["RUN_STARTED", "TOOL_CALL_START", "STATE_SNAPSHOT", "TEXT_MESSAGE_CONTENT", "RUN_FINISHED"]


def serve(page_html):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b = page_html.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_POST(self):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for t in EVENTS:
                self.wfile.write(f'data: {json.dumps({"type": t})}\n\n'.encode()); self.wfile.flush()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@unittest.skipUnless(CAN_RECORD, "needs node, ffprobe, `npm install` in video/ and Chrome")
class RecorderTests(unittest.TestCase):
    def record(self, html, say="Mình thích phở"):
        srv = serve(html)
        self.addCleanup(srv.shutdown)
        out = Path(tempfile.mkdtemp(prefix="demo-test-"))
        self.addCleanup(shutil.rmtree, out, True)
        host = f"127.0.0.1:{srv.server_address[1]}"
        # the recorder itself takes plain http for this fake host; the https rule is the Python job check's, tested above
        rj = out / "rj.json"
        rj.write_text(json.dumps({"page": f"http://{host}/", "say": say, "hosts": [host], "deadline": 60}), encoding="utf-8")
        p = subprocess.run(["node", str(HALCYON / "demo" / "quay-demo.mjs"), "--job", str(rj), "--out", str(out)], capture_output=True, text=True, encoding="utf-8", timeout=120)
        return out, p

    def test_records_the_run_and_reads_its_stream(self):
        out, p = self.record(PAGE % ("x " * 300))
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = json.loads((out / "rec.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["events"][0]["by_type"]["TOOL_CALL_START"], 1)
        self.assertEqual(rec["notes"], ["Thich pho", "Thich dap xe"])
        self.assertEqual(rec["typed"], "Mình thích phở")
        probe = hd.ffprobe(out / "demo.webm")
        self.assertEqual((probe["w"], probe["h"], probe["fps"]), (390, 844, 25))
        facts = hd.judge(rec, hd.check_expect({"events": ["TOOL_CALL_START"]}), probe)
        self.assertEqual(facts["events"]["order"], EVENTS)

    def test_a_wall_refuses(self):
        out, p = self.record((PAGE % ("x " * 300)).replace("<h1>", "<div style='position:fixed;inset:0;z-index:9;background:#fff'>Sign in to continue to the demo</div><h1>"))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads((out / "refusal.json").read_text(encoding="utf-8"))["kind"], "wall")
        self.assertFalse((out / "demo.webm").exists())

    def test_a_key_field_refuses(self):
        out, p = self.record((PAGE % ("x " * 300)).replace("<h1>", "<input type=password><h1>"))
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads((out / "refusal.json").read_text(encoding="utf-8"))["kind"], "wall")

    def test_leftover_profile_is_deleted(self):
        before = {p.name for p in Path(tempfile.gettempdir()).glob("demo-profile-*")}
        self.record(PAGE % ("x " * 300))
        after = {p.name for p in Path(tempfile.gettempdir()).glob("demo-profile-*")}
        self.assertEqual(after - before, set())


@unittest.skipUnless(CAN_RECORD and os.environ.get("HALCYON_LIVE") == "1" and not os.environ.get("CI"), "live: set HALCYON_LIVE=1 (types a sentence into the public AG-UI Dojo)")
class LiveTests(unittest.TestCase):
    def test_the_real_dojo(self):
        out = Path(tempfile.mkdtemp(prefix="demo-live-"))
        self.addCleanup(shutil.rmtree, out, True)
        man = hd.run(JOB, out)
        self.assertGreaterEqual(len(man["notes"]), 1)
        self.assertIn("TOOL_CALL_START", man["events"]["by_type"])
        self.assertEqual((man["w"], man["h"], man["fps"]), (390, 844, 25))


if __name__ == "__main__":
    unittest.main()
