"""The AG-UI scene producer (`scene3d` beats): timeline, sources, gates and clip.json. Entry point: ../halcyon_canh.py (`run --job <job.json> --out <dir>`).

The scene itself is three.js in headless Chrome (giao-thuc.js, driven by canh.mjs, encoded with h264_nvenc). This module is standard library only:
it computes the timeline the page draws (a pure function of the sources, tested offline), checks that the run record and the demo counts are the
real ones, starts the renderer, then checks what came back (GPU renderer, no network, determinism, label sizes and places, the encoded file) and
writes clip.json as video/halcyon/SPEC.md "Clip picture" asks. Usage and the refusals: README.md in this folder."""
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
HAL = HERE.parent
SOURCES = HERE / 'giao-thuc-nguon.json'
W, H, FPS = 886, 976, 30                 # final frame px: the FOOT window of thu-gon-r3-l2 is 976 high, the picture column 886 wide; the builder plays clips at 30 fps
BG = [16, 24, 40]                        # Halcyon ink #101828, the terminal panel's colour
MIN_TEXT = 28                            # SPEC.md: a clip's smallest text, frame px
SAFE_BOTTOM = 890                        # clip rows below this sit under the subtitle (frame y 1274-1350 on thu-gon-r3-l2): no label there
COLUMN = dict(from_y=476, max_x=800)     # frame y 840 down (clip y 476), TikTok's button column starts at frame x 907 (clip x 810): labels end left of it
THREE_VERSION = '0.187.0'
THREE_PIN = {'three.module.js': '104f56145899722094556490d787aae0617cc2fc3382f31df02d724ea1aee341',
             'three.core.js': '613e370f76638fdef83926642bf256dc9615684922de1ce1f63a8583e5d78578'}
FORBIDDEN = ('Date', 'performance.now', 'Math.random', 'requestAnimationFrame', 'setTimeout', 'setInterval')   # time may come only from renderAt(t)
DET_TOL = 4                              # the GPU's own rounding (blending, MSAA resolve) moves a pixel by 1-2 levels between two draws of the same t; a scene that depends on more than t moves far more
SOFTWARE_GL = ('swiftshader', 'llvmpipe', 'software', 'microsoft basic render')
SCENE_FILES = ('canh.py', 'canh.mjs', 'giao-thuc.js', 'scene.html', 'giao-thuc-nguon.json')
FONT_DIRS = (HAL / 'fonts', HAL.parent.parent / 'brand' / 'fonts')
TZ = timezone(timedelta(hours=7))
ACTS = [('intro', 0.0, 4.0, 'CÁCH <b>AG-UI</b> HOẠT ĐỘNG'), ('request', 4.0, 8.0, '<b>1</b> YÊU CẦU'),
        ('stream', 8.0, 15.0, '<b>1</b> LUỒNG SỰ KIỆN (SSE)'), ('tools', 15.0, 21.0, 'CÔNG CỤ, STATE: <b>CÙNG LUỒNG</b>'),
        ('swap', 21.0, 26.0, 'ĐỔI FRAMEWORK, <b>APP GIỮ NGUYÊN</b>')]
STILLS = [(2.8, 'hai đầu và làn AG-UI'), (5.8, 'yêu cầu POST RunAgentInput'), (11.6, 'luồng sự kiện SSE'), (14.8, 'Hello from AG-UI! đã lắp xong'),
          (18.6, 'công cụ và state trên cùng luồng'), (23.9, 'đổi framework, app giữ nguyên')]


class Refusal(Exception):
    def __init__(self, msg, fix=''):
        super().__init__(msg)
        self.fix = fix


def wire_name(cls):
    """SDK class name -> wire type: RunStartedEvent / RunStarted -> RUN_STARTED."""
    cls = re.sub(r'Event$', '', cls)
    return re.sub(r'(?<!^)(?=[A-Z])', '_', cls).upper()


def fence(text, first_line):
    """The body of the fenced block whose first line is `first_line` (as the README holds it, newline-terminated), or a refusal."""
    for m in re.finditer(r'^```[^\n]*\n(.*?)^```', text, re.S | re.M):
        if m.group(1).startswith(first_line):
            return m.group(1)
    raise Refusal(f'no fenced block starting with "{first_line}"', 'the README changed: pin the new commit and its fence in giao-thuc-nguon.json')


def events_from_fence(body):
    """Wire event sequence and text deltas of a server fence: every `encoder.encode(XEvent(` in order, a `for x in [..]:` loop repeating the
    encode lines indented under it once per item (its items are the deltas when the loop encodes TextMessageContent)."""
    lines = body.splitlines()
    out, deltas, i = [], [], 0
    while i < len(lines):
        ln = lines[i]
        loop = re.match(r'^(\s*)for \w+ in (\[.*\])\s*:\s*$', ln)
        if loop:
            ind, items = len(loop.group(1)), ast.literal_eval(loop.group(2))
            inner = []
            i += 1
            while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > ind):
                inner += re.findall(r'encoder\.encode\((\w+)\(', lines[i])
                i += 1
            for _ in items:
                out += [wire_name(c) for c in inner]
            if any(wire_name(c) == 'TEXT_MESSAGE_CONTENT' for c in inner):
                deltas += list(items)
            continue
        out += [wire_name(c) for c in re.findall(r'encoder\.encode\((\w+)\(', ln)]
        i += 1
    return out, deltas


def load_sources(path=SOURCES):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check_readme(src, readme_text):
    """The pinned README really holds the events the scene draws (the README text is supplied by hand: the producer itself never fetches)."""
    got = hashlib.sha256(readme_text.encode('utf-8')).hexdigest()
    if got != src['readme']['sha256']:
        raise Refusal(f'README sha256 {got[:12]} is not the pinned {src["readme"]["sha256"][:12]}', 'download the pinned commit, not the branch head')
    body = fence(readme_text, src['fence']['first_line'])
    fsha = hashlib.sha256(body.encode('utf-8')).hexdigest()
    ev, de = events_from_fence(body)
    if ev != src['events'] or de != src['deltas']:
        raise Refusal(f'the fence says {ev} / {de}, the scene draws {src["events"]} / {src["deltas"]}', 'make giao-thuc-nguon.json say what the README says')
    return dict(readme_sha256=got, fence_sha256=fsha, events=ev, deltas=de)


def check_run(src, chay_path):
    """A run record proves the scene's act 3 is the run the viewer installs: it ran the same server fence and printed the same text."""
    p = Path(chay_path)
    if not p.exists():
        raise Refusal(f'events_run names {p}, which does not exist', 'run the chay step of that source first')
    c = json.loads(p.read_text(encoding='utf-8'))
    f = next((x for x in c.get('files', []) if x.get('name') == src['fence']['name']), None)
    if not f:
        raise Refusal(f'{p.name} ran no {src["fence"]["name"]}: the scene would draw events of a server the viewer never ran', 'name the run that saves server.py from the README')
    if f.get('source') != src['readme']['url'] or f.get('sha256') != src['fence']['sha256']:
        raise Refusal(f'{p.name} ran {src["fence"]["name"]} from {f.get("source")} (sha256 {str(f.get("sha256"))[:12]}), the scene is pinned to {src["readme"]["url"]} ({src["fence"]["sha256"][:12]})',
                      'pin the same README commit in giao-thuc-nguon.json and in the script')
    printed = '\n'.join(line for s in c.get('states', []) for line in s.get('output', []))
    said = ''.join(src['deltas'])
    if said not in printed:
        raise Refusal(f'{p.name} never printed "{said}": the run did not stream the events the scene shows', 'rerun the chay step')
    return dict(run=str(p), fence_sha256=f['sha256'], printed=said, captured=c.get('captured'))


def counts_from_demo(path):
    """Event type counts of the demo the viewer watched: demo.json `events.by_type` (halcyon_demo.py), or a flat `events` / `event_counts` {TYPE: n}. None when no demo is named."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise Refusal(f'counts_demo names {p}, which does not exist', 'run the demo step of that source first')
    m = json.loads(p.read_text(encoding='utf-8'))
    ev = m.get('events', m.get('event_counts'))
    order = None
    if isinstance(ev, dict) and isinstance(ev.get('by_type'), dict):         # halcyon_demo.py writes {"total", "by_type", "order", "streams"}
        order = ev.get('order') if isinstance(ev.get('order'), list) else None
        ev = ev['by_type']
    if not isinstance(ev, dict) or not ev or not all(isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0 for k, v in ev.items()):
        raise Refusal(f'{p.name} carries no event counts ("events": {{"TYPE": n}})', 'the demo step must write the type counts of the stream it recorded')
    return dict(counts=ev, order=order, source=str(m.get('source') or p), date=str(m.get('date') or ''), path=str(p))


def _r(x):
    return round(x, 4)


def timeline(src, counts=None):
    """Everything the page draws, as times in seconds. Pure: the same sources give the same dict."""
    acts = {n: (a, b) for n, a, b, _ in ACTS}
    kind = lambda e: 'life' if e.startswith('RUN_') else ('tool' if e.startswith('TOOL_CALL') else ('state' if e.startswith('STATE') else 'text'))
    # act 2: the request climbs while the user's message is on screen
    req = dict(src['request'], t0=4.75, t1=6.55)
    # act 3: the README run, one bead per event; a text bead carries its delta
    run1, di = [], 0
    for i, e in enumerate(src['events']):
        t0 = 8.55 + i * 0.85
        d = None
        if e == 'TEXT_MESSAGE_CONTENT':
            d = src['deltas'][di]; di += 1
        run1.append(dict(name=e, kind=kind(e), delta=d, t0=_r(t0), t1=_r(t0 + 0.95)))
    # act 4: the demo's run, the types the scene names; counts from the demo manifest or names only
    groups = src['demo_kinds']
    tallies, seq = [], []
    for k in ('tool', 'state', 'text'):
        names = groups[k]
        total = sum(counts['counts'].get(n, 0) for n in names) if counts else None
        label = names[0] if len(names) == 1 else 'TOOL_CALL_*'
        tallies.append(dict(label=label, kind=k, total=total))
        seq.append((k, total if total is not None else 1))
    tool_n, state_n, text_n = (n for _, n in seq)
    order = ['life'] + ['tool'] * tool_n
    # state and text interleaved in proportion (the scene does not claim their order; the tallies are the measured part)
    a_s = a_t = 0
    for _ in range(state_n + text_n):
        if a_s < state_n and (a_t >= text_n or (a_s + .5) / state_n <= (a_t + .5) / text_n):
            order.append('state'); a_s += 1
        else:
            order.append('text'); a_t += 1
    order.append('life')
    s0, s1, travel = 15.65, 20.25, 0.75
    step = (s1 - travel - s0) / max(1, len(order) - 1)
    beads = [dict(kind=k, t0=_r(s0 + i * step), t1=_r(s0 + i * step + travel), small=True) for i, k in enumerate(order)]
    for tl in tallies:
        tl['ticks'] = [b['t1'] for b in beads if b['kind'] == tl['kind']]
    if counts:
        line = 'đếm từ 1 lần chạy demo Dojo'
    else:
        line = 'các loại sự kiện của demo Dojo'
    # act 5: four frameworks take the agent's place; after each, a short pulse shows the same lane still serves the app
    swap = [dict(name=n, a=_r(21.0 + i * 1.15)) for i, n in enumerate(src['frameworks'])]
    pulses = []
    for s in swap:
        for j, k in enumerate(('life', 'text', 'life')):
            t0 = s['a'] + 0.35 + j * 0.14
            pulses.append(dict(kind=k, t0=_r(t0), t1=_r(t0 + 0.55), small=True))
    runs = [dict(a=_r(run1[0]['t0'] - 0.3), b=run1[-1]['t1']), dict(a=_r(beads[0]['t0'] - 0.2), b=beads[-1]['t1'])] + \
           [dict(a=_r(p['t0'] - 0.1), b=p['t1']) for p in pulses[::3]]
    duration = ACTS[-1][2]
    return dict(w=W, h=H, fps=FPS, duration=duration, frames=int(round(duration * FPS)),
                acts=[dict(name=n, a=a, b=b, head=h) for n, a, b, h in ACTS], request=req, run1=run1,
                run2=dict(beads=beads, tallies=tallies, source_line=line), pulses=pulses, runs=runs, swap=swap,
                agent_subs=[dict(text=src['server_label'], a=0.6, b=acts['tools'][0]), dict(text=src['demo_label'], a=acts['tools'][0], b=acts['swap'][0])],
                log_y0=296, log_dy=40)


def check_timeline(data, src, counts=None):
    """Proof of diagram: act 3 is the pinned event list in order; act 4's beads and tallies are the demo's counts (or one per kind with no counts)."""
    if [e['name'] for e in data['run1']] != src['events']:
        raise Refusal('act 3 differs from the pinned event list', 'timeline() is broken')
    if [e['delta'] for e in data['run1'] if e['delta'] is not None] != src['deltas']:
        raise Refusal('act 3 deltas differ from the fence', 'timeline() is broken')
    for tl in data['run2']['tallies']:
        n = sum(1 for b in data['run2']['beads'] if b['kind'] == tl['kind'])
        want = tl['total'] if counts else 1
        if n != want or len(tl['ticks']) != n:
            raise Refusal(f'act 4 draws {n} {tl["kind"]} beads, the demo counted {want}', 'timeline() is broken')
        if counts and tl['total'] != sum(counts['counts'].get(x, 0) for x in src['demo_kinds'][tl['kind']]):
            raise Refusal(f'act 4 tally {tl["label"]} is not the demo count', 'timeline() is broken')
    last = max([e['t1'] for e in data['run1']] + [b['t1'] for b in data['run2']['beads']] + [p['t1'] for p in data['pulses']])
    if last > data['duration'] - 0.3:
        raise Refusal(f'a bead lands at {last:.2f} s, too close to the end ({data["duration"]} s)', 'shorten the stream')
    return True


def check_scene_source(text, name='giao-thuc.js'):
    """Determinism: the scene may not read a clock, draw random numbers or run its own loop."""
    code = re.sub(r'//[^\n]*', '', text)
    hit = [w for w in FORBIDDEN if re.search(r'\b' + re.escape(w) + r'\b', code)]
    if hit:
        raise Refusal(f'{name} uses {", ".join(hit)}: a frame must be a function of its time only', 'derive it from t')
    return True


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool_sha():
    h = hashlib.sha256()
    for n in SCENE_FILES:
        h.update(n.encode()); h.update((HERE / n).read_bytes())
    return h.hexdigest()[:16]


def node_dir():
    """Where the chain keeps its node tooling (playwright-core, three): video/ beside this tool, or HALCYON_NODE_DIR."""
    return Path(os.environ.get('HALCYON_NODE_DIR') or HAL.parent)


def three_build(nd):
    r = subprocess.run(['node', '-e', "console.log(require('path').dirname(require.resolve('three')))"], cwd=nd, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise Refusal(f'three.js is not installed where the chain keeps its tooling ({nd})', f'cd {nd} && npm install --no-save --ignore-scripts three@{THREE_VERSION}')
    build = Path(r.stdout.strip())
    for n, want in THREE_PIN.items():
        got = sha(build / n) if (build / n).exists() else 'missing'
        if got != want:
            raise Refusal(f'{build / n} has sha256 {got[:12]}, the pin is three@{THREE_VERSION} {want[:12]}', f'cd {nd} && npm install --no-save --ignore-scripts three@{THREE_VERSION}')
    return build


def png_pixels(path):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, timeout=60)
    if r.returncode:
        raise Refusal(f'could not read {path}', 'check ffmpeg')
    return r.stdout


def determinism(out, rj):
    """Pixels of each frame drawn twice (in the pass and again at the end, in reverse order): largest channel difference and pixels over the tolerance."""
    res = []
    for x in rj.get('determinism', {}).get('frames', []):
        a, b = png_pixels(Path(out) / f'det-{x["f"]}-a.png'), png_pixels(Path(out) / f'det-{x["f"]}-b.png')
        if len(a) != len(b):
            raise Refusal(f'frame {x["f"]} drawn twice has two sizes', 'rerun')
        diffs = [abs(p - q) for p, q in zip(a, b)]
        res.append(dict(f=x['f'], max_diff=max(diffs), over_tol=sum(1 for d in diffs if d > DET_TOL), same_bytes=x['first'] == x['again']))
    rj.setdefault('determinism', {})['pixels'] = res
    return res


def check_render(rj, data):
    """What the renderer measured, gated."""
    gpu = (rj.get('renderer') or '').lower()
    if not gpu or any(s in gpu for s in SOFTWARE_GL):
        raise Refusal(f'WebGL renders in software ({rj.get("renderer")}): no GPU in headless Chrome', 'check the graphics driver; never accept a software rasteriser')
    if rj.get('aborted'):
        raise Refusal(f'the page asked for {rj["aborted"]} address(es) off the local origin: {rj.get("aborted_urls", [])[:3]}', 'serve every file from the scene folder')
    bad_fonts = [f for f, ok in rj.get('fonts', []) if not ok]
    if bad_fonts:
        raise Refusal(f'fonts did not load: {bad_fonts}', 'the brand fonts must be in video/halcyon/fonts or brand/fonts')
    if rj.get('frames') != data['frames']:
        raise Refusal(f'rendered {rj.get("frames")} frames, the timeline has {data["frames"]}', 'rerun')
    det = rj.get('determinism', {})
    if not det.get('pixels') or any(x['max_diff'] > DET_TOL for x in det['pixels']):
        raise Refusal(f'frames rendered twice differ by more than {DET_TOL} levels: {det.get("pixels")}', 'something in the scene depends on more than t')
    lab = rj.get('labels', {})
    if lab.get('violations'):
        raise Refusal('labels outside their place: ' + '; '.join(lab['violations'][:4]), 'move or shrink the label in giao-thuc.js')
    if lab.get('min_size', 0) < MIN_TEXT:
        raise Refusal(f'a label is {lab.get("min_size")} px, the floor is {MIN_TEXT}', 'draw it larger')
    return True


def probe(mp4):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries', 'stream=width,height,nb_read_frames,r_frame_rate,codec_name,pix_fmt',
                        '-of', 'json', str(mp4)], capture_output=True, text=True, timeout=120)
    s = json.loads(r.stdout)['streams'][0]
    return dict(w=s['width'], h=s['height'], frames=int(s['nb_read_frames']), rate=s['r_frame_rate'], codec=s['codec_name'], pix_fmt=s['pix_fmt'])


def decoded_frame(mp4, t):
    """One frame of the encoded clip as RGB bytes, decoded the way the builder reads it (BT.601, tv range)."""
    r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', str(mp4), '-frames:v', '1', '-vf', 'scale=in_color_matrix=bt601:in_range=tv:out_range=pc',
                        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, timeout=120)
    if r.returncode or len(r.stdout) != W * H * 3:
        raise Refusal(f'could not decode the clip at {t} s: {r.stderr.decode("utf-8", "replace")[-300:]}', 'check ffmpeg')
    return r.stdout


def check_encoded(mp4, data):
    """The file is what clip.json will say, its flat ground decodes to the bg the builder fills around it, and no still is a flat frame."""
    p = probe(mp4)
    if (p['w'], p['h'], p['frames'], p['codec']) != (W, H, data['frames'], 'h264') or p['rate'] != f'{FPS}/1':
        raise Refusal(f'the encoded clip is {p}, expected {W}x{H}, {data["frames"]} frames at {FPS}/1, h264', 'check the encoder')
    worst, ink = 0, {}
    for t, _ in STILLS:
        b = decoded_frame(mp4, t)
        corners = [(4, 4), (W - 5, 4), (4, H - 5), (W - 5, H - 5)]
        for x, y in corners:
            o = (y * W + x) * 3
            worst = max(worst, max(abs(b[o + c] - BG[c]) for c in range(3)))
        diff = sum(1 for i in range(0, len(b), 3 * 7) if max(abs(b[i + c] - BG[c]) for c in range(3)) > 6)
        ink[f't{t:g}'] = round(diff / (len(b) // (3 * 7)), 4)
    if worst > 3:
        raise Refusal(f'the clip\'s ground decodes {worst} levels away from bg {BG}: a seam would show around it in the video', 'encode BT.601 tv range like the builder decodes')
    if min(ink.values()) < 0.005:
        raise Refusal(f'a still is flat ground: {ink}', 'the scene drew nothing there')
    return dict(probe=p, bg_max_diff=worst, ink_share=ink)


def render(data, out, nd, build, say=print):
    """Start canh.mjs (Playwright, installed Chrome, GPU), which writes clip.mp4 and render.json in `out`."""
    out = Path(out)
    (out / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    fonts = os.pathsep.join(str(d) for d in FONT_DIRS if d.exists())
    cmd = ['node', str(HERE / 'canh.mjs'), '--scene', str(HERE), '--data', str(out / 'data.json'), '--three', str(build), '--fonts', fonts,
           '--out', str(out), '--node-dir', str(nd)]
    t0 = time.time()
    r = subprocess.run(cmd, cwd=nd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=540)
    for line in (r.stdout or '').splitlines()[-12:]:
        say('  ' + line)
    if r.returncode:
        raise Refusal('the renderer stopped: ' + ((r.stderr or '').strip().splitlines() or ['no message'])[-1], 'read ' + str(out / 'render.err'))
    rj = json.loads((out / 'render.json').read_text(encoding='utf-8'))
    rj['wall_seconds'] = round(time.time() - t0, 1)
    determinism(out, rj)
    return rj


def run(job, out, say=print, now=None):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    src = load_sources()
    scene = job.get('scene') or {}
    if scene.get('name', 'giao-thuc') != 'giao-thuc':
        raise Refusal(f'scene "{scene.get("name")}" is not built; this producer draws "giao-thuc"', 'name the scene giao-thuc')
    check_scene_source((HERE / 'giao-thuc.js').read_text(encoding='utf-8'))
    run_proof = check_run(src, job['events_run']) if job.get('events_run') else None
    counts = counts_from_demo(job.get('counts_demo'))
    data = timeline(src, counts)
    check_timeline(data, src, counts)
    nd = node_dir()
    build = three_build(nd)
    say(f'scene giao-thuc: {data["frames"]} frames at {FPS} fps, {W}x{H}; counts {"from " + counts["source"] if counts else "not given: names only"}')
    rj = render(data, out, nd, build, say)
    check_render(rj, data)
    enc = check_encoded(out / 'clip.mp4', data)
    now = now or datetime.now(TZ)
    man = dict(file='clip.mp4', w=W, h=H, fps=FPS, frames=data['frames'], duration=data['duration'], bg=BG,
               min_text_px=rj['labels']['min_size'], captured=now.isoformat(timespec='seconds'),
               source=f'three.js scene giao-thuc drawn from {src["readme"]["url"]}' + (f' and the demo counts of {counts["source"]}' if counts else ''),
               date=now.strftime('%d/%m/%Y'), tool_sha=tool_sha(),
               stills=[dict(t=t, label=l) for t, l in STILLS],
               segments=[dict(name=a['name'], a=a['a'], b=a['b'], speed=1, real_s=round(a['b'] - a['a'], 3)) for a in data['acts']],
               proof=dict(gpu=dict(renderer=rj['renderer'], vendor=rj.get('vendor')), three=dict(version=THREE_VERSION, sha256=THREE_PIN),
                          offline=dict(served=rj.get('served'), aborted=rj.get('aborted')), determinism=rj['determinism'],
                          labels=dict(min_size=rj['labels']['min_size'], checked_frames=rj['labels']['frames'], safe_bottom=SAFE_BOTTOM, column=COLUMN),
                          events=dict(list=src['events'], readme=src['readme']['url'], readme_sha256=src['readme']['sha256'], fence_sha256=src['fence']['sha256'], run=run_proof),
                          counts=(dict(tallies={t['label']: t['total'] for t in data['run2']['tallies']}, source=counts['source'], date=counts['date']) if counts else None),
                          encoded=enc, render_seconds=rj.get('seconds'), wall_seconds=rj.get('wall_seconds'), encoder='h264_nvenc'))
    (out / 'clip.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    say(f'wrote {out / "clip.json"}: {data["frames"]} frames, GPU "{rj["renderer"]}", smallest text {man["min_text_px"]} px, render {rj.get("seconds")} s')
    return man


def main(argv=None, say=print):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != 'run' or '--job' not in argv or '--out' not in argv:
        say('usage: halcyon_canh.py run --job <job.json> --out <folder>')
        return 2
    job = json.loads(Path(argv[argv.index('--job') + 1]).read_text(encoding='utf-8'))
    try:
        run(job, argv[argv.index('--out') + 1], say)
    except Refusal as e:
        say(f'refused: {e}')
        if e.fix:
            say(f'to fix: {e.fix}')
        return 1
    return 0
