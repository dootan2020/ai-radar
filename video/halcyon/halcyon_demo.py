"""Halcyon demo beat (`demo:<ref>` in the one command): record, by script, a public agent demo page as a 390x844 phone video and prove what it showed.

    python halcyon_demo.py run --job job.json --out <folder>
    python halcyon_demo.py check --job job.json            (the job only, no network)

The job: {"ref": ..., "demo": {"entry": <public page the viewer can reach>, "page": <the page recorded>, "say": <the sentence typed>, "expect": {"events": [...], "effect": "notes"}}}.
It writes `<folder>/demo.webm` (390x844, 25 fps, what Playwright's headless Chrome showed) and `<folder>/demo.json` (the manifest: file, duration, captured, source, date, the
moments of the footage in seconds, the AG-UI event counts of that very run, the notes the agent wrote, rectangles worth focusing on). The page is driven by demo/quay-demo.mjs.

Every refusal is `demo: <kind>: <why>` then `to fix: ...` on stderr, exit 1, nothing written to demo.json. The gates are the point (demo/README.md): public https pages only,
two named hosts, a sentence that holds nothing personal, a wall (sign-in, key field, cookie wall, CAPTCHA) refuses, the stream must be text/event-stream and hold the events the
script expects, the page must show the effect (the agent's notes appeared), the video must be the size the builder plays. An attempt has a deadline and one retry; two refusals
mean the demo is dropped and reported, never replaced by something else. Standard library only; ffprobe measures the video."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

CLIP_PRODUCER = 1                      # the chain looks for this line (MOT-LENH.md); until it exists the demo beat stops with "producer not built yet"

HERE = Path(__file__).resolve().parent
RECORDER = HERE / 'demo' / 'quay-demo.mjs'
TZ = timezone(timedelta(hours=7))
W, H, FPS = 390, 844, 25               # what the builder plays (SPEC.md: recordings must be 390x844 at 25 fps)
ATTEMPT_DEADLINE = 100                 # seconds per attempt; the chain gives the whole step 300 s (halcyon_mot_lenh.DEADLINES), so two attempts fit
ATTEMPTS = 2                           # one retry
MAX_SAY = 90
ALWAYS_EVENTS = ('RUN_STARTED', 'RUN_FINISHED')
EXPECT_KEYS = ('events', 'effect', 'min_notes')
RETRY_KINDS = ('timeout', 'chat', 'answer', 'stream', 'typing', 'browser', 'status')


class Refusal(Exception):
    def __init__(self, kind, why, fix=''):
        super().__init__(why)
        self.kind, self.why, self.fix = kind, why, fix

    def __str__(self):
        return f'demo: {self.kind}: {self.why}' + (f'\nto fix: {self.fix}' if self.fix else '')


def now_iso():
    return datetime.now(TZ).isoformat(timespec='seconds')


def today():
    return datetime.now(TZ).strftime('%d/%m/%Y')


def tool_sha():
    h = hashlib.sha256()
    for f in (Path(__file__), RECORDER):
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


# ------------------------------------------------------------------ the job (no network)
def public_https(u, where):
    p = urlparse(u) if isinstance(u, str) else None
    host = (p.hostname or '') if p else ''
    if not p or p.scheme != 'https' or not host:
        raise Refusal('address', f'{where} is {u!r}, not a public https address', 'the recorder opens public https pages only')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.test')) or re.fullmatch(r'[\d.]+|[\da-fA-F:]+', host) or '.' not in host:
        raise Refusal('address', f'{where} is on {host}, which is not a public host', 'name the page by its public domain; localhost and addresses are never recorded')
    return p.netloc.lower()


def check_say(say):
    if not isinstance(say, str) or not say.strip():
        raise Refusal('say', 'demo.say is empty', 'write the one sentence the script types')
    if len(say) > MAX_SAY or '\n' in say:
        raise Refusal('say', f'demo.say is {len(say)} characters or has a line break (one line, up to {MAX_SAY})', 'shorten it')
    if re.search(r'@|https?:|www\.|\d{6,}', say):
        raise Refusal('say', 'demo.say holds an address, a link or a long number; it is typed into a third party\'s server', 'type a harmless sentence, never anything personal')
    return say.strip()


def check_expect(exp):
    if not isinstance(exp, dict) or not exp:
        raise Refusal('expect', 'demo.expect is missing', 'write {"events": ["TOOL_CALL_START", ...], "effect": "the agent writes a note"}')
    extra = [k for k in exp if k not in EXPECT_KEYS]
    if extra:
        raise Refusal('expect', f'demo.expect has unknown key(s) {", ".join(extra)}', f'allowed keys: {", ".join(EXPECT_KEYS)}')
    ev = exp.get('events', [])
    if not (isinstance(ev, list) and all(isinstance(x, str) and re.fullmatch(r'[A-Z_]+', x) for x in ev)):
        raise Refusal('expect', 'demo.expect.events must be a list of AG-UI event types such as "TOOL_CALL_START"', 'fix the list')
    eff = exp.get('effect', 'the agent writes notes')     # a sentence for the pack: what the viewer sees happen; the gate is always the one in judge()
    if not (isinstance(eff, str) and eff.strip()):
        raise Refusal('expect', 'demo.expect.effect must be a sentence saying what the page shows after the run', 'for example "the agent writes a note"')
    mn = exp.get('min_notes', 1)
    if not (isinstance(mn, int) and not isinstance(mn, bool) and mn >= 1):
        raise Refusal('expect', 'demo.expect.min_notes must be a whole number of at least 1', 'fix it')
    return dict(events=list(dict.fromkeys([*ALWAYS_EVENTS, *ev])), effect=eff.strip(), min_notes=mn)


def check_job(job):
    """Returns dict(ref, entry, page, say, hosts, expect) or raises Refusal. No network."""
    if not isinstance(job, dict) or not isinstance(job.get('demo'), dict):
        raise Refusal('job', 'the job has no "demo" block', 'the chain writes it from the script\'s demo source')
    d = job['demo']
    entry_host = public_https(d.get('entry'), 'demo.entry')
    page_host = public_https(d.get('page'), 'demo.page')
    return dict(ref=job.get('ref') or 'demo', entry=d['entry'], page=d['page'], say=check_say(d.get('say')), hosts=sorted({entry_host, page_host}),
                expect=check_expect(d.get('expect')))


# ------------------------------------------------------------------ what the recorder reported (pure: tested offline)
def judge(rec, want, probe):
    """The gates over one recording (`rec` is quay-demo.mjs's rec.json, `probe` the ffprobe measurements of its video). Returns the facts for the manifest or raises Refusal."""
    if rec.get('blocked'):
        raise Refusal('navigation', f'the page tried to leave the two hosts for {rec["blocked"][0]} (blocked)', 'nothing was recorded from there; run again, or tell the coordinator the demo page changed')
    streams = rec.get('events') or []
    run = next((s for s in streams if 'RUN_STARTED' in s['by_type']), None)
    if not rec.get('streams') or run is None:
        raise Refusal('events', 'no text/event-stream answer with a RUN_STARTED event was seen after the sentence was sent', 'the page may have changed; look at it by hand before trusting the demo')
    missing = [e for e in want['events'] if e not in run['by_type']]
    if missing:
        raise Refusal('events', f'the stream of this run lacks {", ".join(missing)}; it held {json.dumps(run["by_type"], sort_keys=True)}', 'the agent did not do what the script expects; run again, or change "expect.events" if the page changed')
    # the effect this page can show, whatever sentence the script words it with: the scratch pad was empty, and the agent's tool filled it
    n = len(rec.get('notes') or [])
    if not rec.get('notes_empty_before') or rec.get('notes_before'):
        raise Refusal('effect', f'the scratch pad was not empty before the sentence ({rec.get("notes_before")} notes); the notes would not be the agent\'s', 'run again on a fresh page')
    if n < want['min_notes'] or rec.get('notes_empty_after'):
        raise Refusal('effect', f'the scratch pad holds {n} note(s) after the run, {want["min_notes"]} needed ({want["effect"]})', 'the agent did not write its notes; run again')
    if not (rec.get('answer') or '').strip():
        raise Refusal('effect', 'the agent\'s answer is empty', 'run again')
    m = rec.get('moments') or {}
    order = ['page_ready', 'typed_start', 'typed_end', 'sent', 'answer_start', 'answer_end', 'chat_closed', 'notes_in_view', 'end']
    if any(k not in m for k in order) or any(m[a] > m[b] for a, b in zip(order, order[1:])):
        raise Refusal('timeline', f'the moments of the recording are missing or out of order: {m}', 'tell the coordinator; this is a bug in the recorder')
    if (probe['w'], probe['h']) != (W, H):
        raise Refusal('video', f'the video is {probe["w"]}x{probe["h"]}, the builder plays {W}x{H}', 'tell the coordinator')
    if probe['fps'] != FPS or abs(probe['frames'] / FPS - probe['duration']) > 1 / FPS + 1e-3:
        raise Refusal('video', f'the video is {probe["frames"]} frames at {probe["fps"]} fps lasting {probe["duration"]} s; the builder plays {FPS} fps and counts whole frames', 'tell the coordinator')
    # the video starts when the page is created, so the moments are seconds of it; it ends at its last frame, which can come before the page closes (nothing moves on a still page)
    if not m['notes_in_view'] <= probe['duration'] <= m['end'] + 4:
        raise Refusal('timeline', f'the video lasts {probe["duration"]} s but the scratch pad came into view at {m["notes_in_view"]} s and the page was driven for {m["end"]} s; the moments cannot be trusted against the video', 'run again')
    if probe['duration'] < 8:
        raise Refusal('video', f'the video lasts {probe["duration"]} s, too short for a demo', 'run again')
    return dict(events=dict(total=sum(run['by_type'].values()), by_type=dict(sorted(run['by_type'].items())), order=run['order'], streams=len(streams)),
                notes=list(rec['notes']), answer=rec['answer'])


def typing_rect(box):
    """Focus for the typing part: the input box with 272 px of the screen above it. The builder cuts a recording on a row that holds only background, and the fade of its FOOT window
    would otherwise fall on the grey line of text under the box; this height puts the cut in the blank rows between them (measured with a 390x844 recording and SPEC.md's rule)."""
    if not box:
        return None
    return [28, max(0, box[3] - 272), 362, box[3]]


def ffprobe(webm):
    """Size, frames, fps and duration of the recording, read from the file itself."""
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,nb_read_frames,avg_frame_rate:format=duration',
                        '-of', 'json', str(webm)], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise Refusal('video', f'ffprobe could not read {webm.name}: {r.stderr.strip()[:200]}', 'run again')
    j = json.loads(r.stdout)
    st = j['streams'][0]
    num, den = (st.get('avg_frame_rate') or '0/1').split('/')
    frames = int(st['nb_read_frames'])
    dur = float(j['format']['duration'])
    return dict(w=int(st['width']), h=int(st['height']), frames=frames, fps=round(int(num) / int(den)) if int(den) else 0, duration=round(frames / FPS, 3) if abs(frames / FPS - dur) < 0.5 else round(dur, 3), container_s=round(dur, 3))


# ------------------------------------------------------------------ the recording
def record_once(job, out, node='node', deadline=ATTEMPT_DEADLINE):
    """One attempt: returns (rec, refusal-dict). The recorder writes demo.webm and rec.json, or refusal.json."""
    for f in ('demo.webm', 'rec.json', 'refusal.json'):
        (out / f).unlink(missing_ok=True)
    jf = out / 'recorder-job.json'
    jf.write_text(json.dumps(dict(page=job['page'], say=job['say'], hosts=job['hosts'], deadline=deadline), ensure_ascii=False), encoding='utf-8', newline='\n')
    try:
        p = subprocess.run([node, str(RECORDER), '--job', str(jf), '--out', str(out)], capture_output=True, text=True, encoding='utf-8', timeout=deadline + 30)
        code, err = p.returncode, p.stderr
    except subprocess.TimeoutExpired:
        code, err = 1, 'demo: timeout: the recorder did not return in time'
    except FileNotFoundError:
        raise Refusal('node', 'node is not installed', 'install Node 22 or newer')
    jf.unlink(missing_ok=True)
    if code == 0 and (out / 'rec.json').exists() and (out / 'demo.webm').exists():
        return json.loads((out / 'rec.json').read_text(encoding='utf-8')), None
    rf = out / 'refusal.json'
    if rf.exists():
        return None, json.loads(rf.read_text(encoding='utf-8'))
    return None, dict(kind='browser', why=(err.strip().splitlines() or [f'the recorder exited {code} without a message'])[-1][:300], retry=True)


def run(job, out, node='node', attempts=ATTEMPTS, say=print):
    j = check_job(job)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'demo.json').unlink(missing_ok=True)
    last = None
    for n in range(1, attempts + 1):
        rec, ref = record_once(j, out, node)
        if rec is not None:
            try:
                probe = ffprobe(out / 'demo.webm')
                facts = judge(rec, j['expect'], probe)
                break
            except Refusal as e:
                last = dict(kind=e.kind, why=e.why, retry=e.kind in ('timeline', 'video', 'events', 'effect'), fix=e.fix)
        else:
            last = ref
        say(f'demo: attempt {n} of {attempts} refused: {last["kind"]}: {last["why"]}')
        if not last.get('retry') or n == attempts:
            raise Refusal(last['kind'], last['why'] + (f' (after {n} attempt(s))' if n > 1 else ''), last.get('fix') or 'a wall or a changed page is not the script\'s fault: skip the demo (the video ships with the diagram alone) or run again later')
        (out / 'demo.webm').unlink(missing_ok=True)
    m = rec['moments']
    moments = dict(m)
    man = dict(
        file='demo.webm', w=probe['w'], h=probe['h'], fps=probe['fps'], frames=probe['frames'], duration=probe['duration'],
        captured=now_iso(), source=urlparse(j['entry']).hostname, date=today(), entry=j['entry'], page=j['page'], say=j['say'],
        tool_sha=tool_sha(), moments=moments, events=facts['events'], notes=facts['notes'], answer=facts['answer'],
        counts=facts['events']['by_type'],
        suggest=dict(typing=dict(**{'from': round(max(0, m['typed_start'] - 0.4), 2), 'to': round(m['sent'] + 0.8, 2)}, rect=typing_rect(rec['rects'].get('input'))),
                     chat=dict(**{'from': round(m['answer_start'] - 0.2, 2), 'to': round(min(m['answer_end'] + 2.0, m['chat_closed'] - 0.3), 2)}, rect=rec['rects'].get('chat')),
                     notes=dict(**{'from': round(m['notes_in_view'], 2), 'to': round(probe['duration'] - 0.1, 2)}, rect=rec['rects'].get('notes'))),
        stills=[dict(t=round(m[k], 2), label=lab) for k, lab in (('typed_end', 'the sentence typed'), ('answer_end', 'the answer'), ('notes_in_view', 'the scratch pad'))],
        proof=dict(content_type='text/event-stream', streams=facts['events']['streams'], events_needed=j['expect']['events'], effect=j['expect']['effect'],
                   notes_before=rec.get('notes_before'), notes_after=len(facts['notes']), blocked_navigations=len(rec.get('blocked') or []), attempts=n,
                   throwaway_profile_deleted=True, hosts=j['hosts'], cosmetic=rec.get('cosmetic')))
    (out / 'demo.json').write_text(json.dumps(man, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    for f in ('rec.json', 'refusal.json'):
        (out / f).unlink(missing_ok=True)
    return man


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('run', 'check'):
        p = sub.add_parser(name)
        p.add_argument('--job', required=True)
        if name == 'run':
            p.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    try:
        job = json.loads(Path(a.job).read_text(encoding='utf-8'))
        if a.cmd == 'check':
            j = check_job(job)
            print(f'demo: {j["ref"]}: job ok ({", ".join(j["hosts"])}); nothing recorded')
            return 0
        man = run(job, a.out)
    except Refusal as e:
        print(e, file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f'demo: job: {e}', file=sys.stderr)
        return 2
    print(f'demo: {job.get("ref")}: recorded {man["duration"]} s ({man["frames"]} frames) of {man["source"]}; {man["events"]["total"]} AG-UI events in {man["events"]["streams"]} stream(s), '
          f'{len(man["notes"])} note(s) written by the agent; throwaway profile deleted')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
