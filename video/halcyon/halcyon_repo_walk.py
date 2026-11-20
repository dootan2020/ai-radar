"""Halcyon `repo` picture: the stills manifest (quay.json) and the camera plan. Standard library only, so it is tested without a GPU.

A repo beat plays desktop github.com stills (1280 css wide, scale 2) as a screen recording inside the phone-safe window (763 x hh frame px). The page does
not fit at a readable size, so a camera (a crop of the still: centre cx, cy and width cw, all in css px) moves between targets. Everything here is a pure
function of the frame number: cam_at(seg, f), pointer_at(seg, f). dung-video-gpu.py draws what this module plans.
Rule at every hold: the text the voice talks about is at least PX_MIN frame px high (font css px x window width / camera width), else the plan is refused."""
import math
import re
from pathlib import Path

PX_MIN = 22.0            # named text at a hold: frame px
OVERVIEW_MAX = 36        # frames (1.2 s): the whole page width, so the viewer knows it is desktop GitHub
XF = 6                   # page change: a dip through the page colour, out 3 frames, in 3 (a desktop browser swaps the page; no push animation)
MOVE, HOVER, PRESS = 14, 8, 4   # pointer travel, rest on the row (hover tint), press; the page changes at the end of PRESS
LEAD = MOVE + HOVER + PRESS     # camera is still for the last LEAD frames before a page change
DWELL = 12               # frames the arrival framing stays still before the camera moves on
DWELL_MIN = 6
READ_V = 0.25            # reading pan of the last page: window heights per second
CAP_PAN = 1.2            # peak pan speed cap: window heights per second (design) ...
CAP_ZOOM = 1.6           # ... and peak zoom speed cap: ln(width) per second
PAN_AIM = 0.75           # the plan aims for a peak pan speed of this share of the cap (a move may take longer than the minimum, never shorter)
IDEAL_ZOOM = 1.0         # average zoom speed: ln units per second
ROW_AT = 0.40            # the row to open sits at 40% of the window height
ROW_SEEN = (0.12, 0.88)  # a row already inside this band of the window needs no pan
FEATHER = 24             # frame px


def smooth(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def parse_colour(v):
    """'#rrggbb', 'rgb(r, g, b)', [r, g, b] or None -> (r, g, b)."""
    if v is None:
        return (255, 255, 255)
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return tuple(int(x) for x in v[:3])
    s = str(v).strip()
    m = re.match(r'#([0-9a-fA-F]{6})$', s)
    if m:
        return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', s)
    if m:
        return tuple(int(x) for x in m.groups())
    raise SystemExit(f'quay manifest: background colour "{v}" is not #rrggbb, rgb(r, g, b) or [r, g, b]')


def load_manifest(path):
    """quay.json -> dict(viewport, scale, bg, pages={path: page}); page = dict(picture (absolute Path), type, css_height, rows, regions, fonts).
    rows: [{path, rect [x, y, w, h] css, name [x, y, w, h] css, font_px}]. A missing field stops the run with its name."""
    import json
    path = Path(path)
    d = json.loads(path.read_text(encoding='utf-8'))
    where = f'quay manifest {path.name}'
    for k in ('viewport', 'scale', 'pages'):
        if k not in d:
            raise SystemExit(f'{where}: "{k}" is missing')
    pages = d['pages']
    if isinstance(pages, list):
        pages = {str(p.get('path', p.get('page', ''))): p for p in pages}
    out = {}
    for key, p in pages.items():
        w = f'{where}: page "{key}"'
        for k in ('picture', 'css_height'):
            if k not in p:
                raise SystemExit(f'{w}: "{k}" is missing')
        pic = (path.parent / p['picture']).resolve()
        if not pic.exists():
            raise SystemExit(f'{w}: picture {pic} does not exist')
        rows = []
        for r in p.get('rows', []):
            if r.get('path') in (None, '..') or (key and r['path'] == parent_of(key)):
                continue                                   # the ".." row of a folder page (its link is the parent folder)
            if 'rect' not in r:
                raise SystemExit(f'{w}: row "{r["path"]}" has no "rect"')
            rect = [float(x) for x in r['rect']]
            name = [float(x) for x in r.get('name', r['rect'])]
            rows.append(dict(path=r['path'], rect=rect, name=name, font_px=float(r.get('font_px') or p.get('fonts', {}).get('list') or 14)))
        out[key] = dict(picture=pic, type=p.get('type') or ('home' if key == '' else 'tree'), css_height=float(p['css_height']), rows=rows,
                        regions={k: v for k, v in (p.get('regions') or {}).items() if v and v[2] > 0 and v[3] > 0}, fonts=dict(p.get('fonts') or {}))
    return dict(viewport=float(d['viewport']), scale=float(d['scale']), bg=parse_colour(d.get('bg') or next(iter(pages.values())).get('bg')), pages=out, path=path)


def page_kind(key, page):
    """home, tree, readme (a rendered markdown file) or code."""
    if key == '':
        return 'home'
    if page['type'] == 'tree':
        return 'tree'
    return 'readme' if 'readme' in page['regions'] else 'code'


def font_of(kind, page):
    f = page['fonts']
    return float({'home': f.get('list'), 'tree': f.get('list'), 'readme': f.get('readme'), 'code': f.get('code')}[kind] or {'home': 14, 'tree': 14, 'readme': 16, 'code': 12}[kind])


class Geo:
    """Window geometry: ww x hh frame px; a camera is (cx, cy, cw) in css px of the page."""

    def __init__(self, ww, hh, vp):
        self.ww, self.hh, self.vp = ww, hh, vp

    def z(self, cam):
        return self.ww / cam[2]

    def win_h(self, cam):
        return self.hh / self.z(cam)

    def tl(self, cam):
        return cam[0] - cam[2] / 2, cam[1] - self.win_h(cam) / 2

    def clamp(self, cam, css_h):
        cx, cy, cw = cam
        cw = min(cw, self.vp)
        wh = self.hh / (self.ww / cw)
        cx = min(max(cx, cw / 2), self.vp - cw / 2)
        lo, hi = wh / 2, css_h - wh / 2
        cy = lo if hi < lo else min(max(cy, lo), hi)
        return (cx, cy, cw)


def cam_tl(geo, x0, y0, cw):
    return (x0 + cw / 2, y0 + geo.hh / (geo.ww / cw) / 2, cw)


def lerp_cam(a, b, u):
    lw = math.log(a[2]) + (math.log(b[2]) - math.log(a[2])) * u
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, math.exp(lw))


def move_frames(geo, a, b):
    """Frames an eased (smoothstep, peak 1.5x the average) camera move a -> b needs: (minimum under the pan and zoom caps, the aimed one)."""
    za, zb = geo.z(a), geo.z(b)
    dist = math.hypot(b[0] - a[0], b[1] - a[1])                      # css px, travelled while the zoom runs from za to zb
    dln = abs(math.log(b[2] / a[2]))
    pk = max(6 * (n / 100) * (1 - n / 100) * za * (zb / za) ** (n / 100) for n in range(101))   # peak of d(smoothstep)/du x zoom: frame px per css px per unit of u
    mn = max(dist * pk / (CAP_PAN * geo.hh / 30), 1.5 * dln / (CAP_ZOOM / 30))
    ideal = max(dist * pk / (PAN_AIM * CAP_PAN * geo.hh / 30), dln / (IDEAL_ZOOM / 30))
    if mn <= 0:
        return 0, 0
    return math.ceil(mn), max(math.ceil(mn), math.ceil(ideal), 8)


def cam_at(seg, f):
    """Camera (cx, cy, cw) of a segment at frame f: holds, eased tweens, then the reading pan."""
    cam = seg['cam0']
    for fa, fb, ca, cb in seg['tweens']:
        if f >= fb:
            cam = cb
        elif f >= fa:
            return lerp_cam(ca, cb, smooth((f - fa) / (fb - fa)))
        else:
            break
    rd = seg.get('read')
    if rd and f >= rd['f0']:
        t = f - rd['f0']; R = rd['ramp']
        g = t * t / (2 * R) if t < R else t - R / 2
        cx, cy, cw = cam
        return (cx, min(cy + rd['v'] * g, rd['cy_max']), cw)
    return cam


def pointer_at(seg, f):
    """(x, y, alpha) of the mouse pointer in window frame px, or None; hover tint strength 0..1 and press 0..1 as (hover, press)."""
    p = seg.get('ptr')
    if not p or f < p['move0']:
        return None, 0.0, 0.0
    u = smooth((f - p['move0'] + 1) / MOVE)
    (x0, y0), (x1, y1) = p['p0'], p['p1']
    dx, dy = x1 - x0, y1 - y0
    arc = 0.07 * math.sin(math.pi * u)                     # a hand does not travel in a straight line
    x, y = x0 + dx * u - dy * arc, y0 + dy * u + dx * arc
    alpha = min(1.0, (f - p['move0'] + 1) / 4)
    hover = smooth((f - p['hover0'] + 1) / 4) if f >= p['hover0'] - 3 else 0.0
    press = smooth((f - p['press0'] + 1) / 2) if f >= p['press0'] - 1 else 0.0
    return (x, y, alpha), hover, press


def parent_of(p):
    return p.rsplit('/', 1)[0] if '/' in p else ''


def plan_walk(man, walk, f0, f1, hh, ww, fps=30, default_overview=0.0, where='repo beat'):
    """Segments of the walk. walk: [{"page": "", "a": 0.0}, {"page": "apps", "a": 12.31, "via": "click"}, ...]; a = absolute video seconds, the first step
    starts at the beat's first frame. A step may carry "camera": {"width": css px, "overview": seconds (0 to 1.2), "focus": home|tree|readme|code}.
    Returns dict(segments, holds, stills, max_pan_px_per_frame, pan_cap_px_per_frame, max_zoom_per_frame, zoom_cap_per_frame)."""
    geo = Geo(ww, hh, man['viewport'])
    pages = man['pages']
    if not walk:
        raise SystemExit(f'spec: {where}.picture.walk is empty')
    segs = []
    for i, st in enumerate(walk):
        key = st.get('page')
        if key is None or key not in pages:
            raise SystemExit(f'spec: {where}.walk[{i}].page "{key}" is not in the manifest (pages: {sorted(pages)})')
        if i and 'a' not in st:
            raise SystemExit(f'spec: {where}.walk[{i}].a is missing')
        s = f0 if i == 0 else max(round(float(st['a']) * fps), segs[-1]['s'] + 1)
        segs.append(dict(i=i, page=key, step=st, s=s, e=f1, row=None))
    for i in range(len(segs) - 1):
        segs[i]['e'] = segs[i + 1]['s']
    for sg in segs:
        if sg['e'] - sg['s'] < 1 or sg['s'] >= f1:
            raise SystemExit(f'spec: {where}.walk[{sg["i"]}] ("{sg["page"]}") starts at frame {sg["s"]}, the beat ends at {f1}')
    holds, stills = [], []
    exits = {}                                           # page -> camera it was left on
    pan_pf = zoom_pf = 0.0
    for sg in segs:
        i, key, st = sg['i'], sg['page'], sg['step']
        page = pages[key]; css_h = page['css_height']
        kind = (st.get('camera') or {}).get('focus') or page_kind(key, page)
        font = font_of(kind, page)
        cwant = float((st.get('camera') or {}).get('width') or math.floor(ww * font / PX_MIN))
        cw = min(cwant, man['viewport'])
        if ww / cw * font < PX_MIN - 1e-6:
            raise SystemExit(f'small: {where}.walk[{i}] ("{key}"): camera width {cw:.0f} css px shows {font:g} px text at {ww / cw * font:.1f} frame px, '
                             f'floor {PX_MIN:g}: use a width of {math.floor(ww * font / PX_MIN)} css px or less')
        reg = page['regions']
        if kind == 'home':
            lst = reg.get('list'); x0 = max(0.0, (lst[0] if lst else 32) - 32); y0 = 0.0
        elif kind == 'tree':
            lst = reg.get('list'); x0 = max(0.0, (lst[0] if lst else 337) - 16); y0 = max(0.0, (lst[1] if lst else 294) - 140)
        elif kind == 'readme':
            r = reg.get('readme'); x0 = max(0.0, (r[0] if r else 0) - 24); y0 = max(0.0, (r[1] if r else 0) - 150)
        else:
            r = reg.get('code') or reg.get('readme'); x0 = max(0.0, (r[0] if r else 0) - 40); y0 = max(0.0, (r[1] if r else 0) - 150)
        S = geo.clamp(cam_tl(geo, x0, y0, cw), css_h)
        via = st.get('via') or 'click'
        if via == 'tap':
            via = 'click'
        if via not in ('click', 'back'):
            raise SystemExit(f'spec: {where}.walk[{i}].via "{via}" is not click, tap or back')
        sg['via'] = via if i else None
        last = i == len(segs) - 1
        L = sg['e'] - sg['s']
        cam0 = S
        if i and via == 'back' and key in exits:
            cam0 = exits[key]; S = cam0
        ov = 0
        if i == 0:
            osec = (st.get('camera') or {}).get('overview', default_overview)
            if osec and float(osec) > 1.2 + 1e-9:
                raise SystemExit(f'spec: {where}.walk[0].camera.overview {osec} s: the whole-width view may last 1.2 s at most')
            ov = min(OVERVIEW_MAX, round(float(osec or 0) * fps))
        OV = (geo.clamp(cam_tl(geo, 0, 0, man['viewport']), css_h)) if ov else None
        tween = []; t = sg['s']
        notes = []
        # target of the next page change
        T = S; ptr = None; need_pan = False
        if not last:
            nxt = segs[i + 1]
            row = next((r for r in page['rows'] if r['path'] == nxt['page']), None) if nxt['step'].get('via', 'click') != 'back' else None
            nvia = nxt['step'].get('via') or 'click'
            if nvia != 'back':
                if row is None:
                    raise SystemExit(f'spec: {where}.walk[{i + 1}]: page "{key}" has no row for "{nxt["page"]}" on its still (rows: {[r["path"] for r in page["rows"]][:30]})')
                rcy = row['rect'][1] + row['rect'][3] / 2
                wh = geo.win_h(S)
                top = (S[1] - wh / 2)
                rel = (rcy - top) / wh
                if not (ROW_SEEN[0] <= rel <= ROW_SEEN[1]) or not (S[0] - S[2] / 2 <= row['name'][0] <= S[0] + S[2] / 2 - 40):
                    need_pan = True
                    T = geo.clamp((S[0], rcy - ROW_AT * wh + wh / 2, cw), css_h)
                    if not (T[0] - T[2] / 2 <= row['name'][0] <= T[0] + T[2] / 2 - 40):
                        T = geo.clamp((row['name'][0] + 40 - cw / 2 + cw * 0.15, T[1], cw), css_h)
                sg['row'] = row
        avail = (sg['e'] - (LEAD if not last and sg['row'] is not None else 0)) - sg['s'] if not last else L
        # frames needed
        zmin, zid = move_frames(geo, OV, S) if ov else (0, 0)
        pmin, pid = move_frames(geo, S, T) if need_pan else (0, 0)
        D = DWELL
        def total(ov_, z_, d_, p_):
            return ov_ + z_ + d_ + p_
        if not last:
            use_ov, use_z = ov, zid
            if total(use_ov, use_z, D, pid) > avail:
                use_z = zmin
                if total(use_ov, use_z, D, pid) > avail:
                    D = DWELL_MIN
                    if total(use_ov, use_z, D, pid) > avail:
                        use_ov = 0; use_z = 0
                        if ov:
                            notes.append('overview dropped: the step is too short for it')
            P = pid if total(use_ov, use_z, D, pid) <= avail else pmin
            if total(use_ov, use_z, D, P) > avail:
                need = total(use_ov, use_z, DWELL_MIN, pmin) + (LEAD if sg['row'] is not None else 0)
                raise SystemExit(f'spec: {where}.walk[{i}] ("{key}") lasts {L / fps:.2f} s; the camera needs {need / fps:.2f} s here '
                                 f'(pan {pmin} frames at the speed cap, dwell {DWELL_MIN}, pointer {LEAD}): start the next step later')
            slack = avail - total(use_ov, use_z, D, P)
            D += min(slack, 18)
        else:
            use_ov, use_z = (ov, zid) if ov and ov + zid + DWELL_MIN + 12 <= L else ((ov, zmin) if ov and ov + zmin + DWELL_MIN + 12 <= L else (0, 0))
            if ov and not use_ov:
                notes.append('overview dropped: the step is too short for it')
            P = 0
            if use_ov + use_z + DWELL_MIN + 12 > L:
                raise SystemExit(f'spec: {where}.walk[{i}] ("{key}") lasts {L / fps:.2f} s, under the {(use_ov + use_z + DWELL_MIN + 12) / fps:.2f} s its camera needs')
        # timeline
        if use_ov:
            cam0 = OV; tween.append((t + use_ov, t + use_ov + use_z, OV, S)); t += use_ov + use_z
        arrive_f = t + max(3, D // 2)
        hold_names = t + D
        t += D
        if not last and need_pan:
            tween.append((t, t + P, S, T)); t += P
        sg.update(cam0=cam0, tweens=tween, kind=kind, notes=notes, font=font, cw=cw)
        if last:
            wh = geo.win_h(S)
            rd = dict(f0=t, ramp=15, v=READ_V * wh / 30, cy_max=max(S[1], css_h - wh / 2))
            sg['read'] = rd
        else:
            sg['read'] = None
        # pointer
        if not last and sg['row'] is not None:
            row = sg['row']
            cam = T if need_pan else S
            z = geo.z(cam); x0c, y0c = geo.tl(cam)
            tx = row['name'][0] + min(row['name'][2] * 0.75, 90); ty = row['name'][1] + row['name'][3] / 2 + 3     # the tip sits at the lower right of the name, so the arrow does not cover the letters
            p1 = ((tx - x0c) * z, (ty - y0c) * z)
            p0 = (min(ww - 40, p1[0] + 0.35 * ww), min(hh - 40, p1[1] + 0.35 * hh))
            r = row['rect']
            sg['ptr'] = dict(move0=sg['e'] - LEAD, hover0=sg['e'] - LEAD + MOVE, press0=sg['e'] - PRESS, p0=p0, p1=p1,
                             rect=((r[0] - x0c) * z, (r[1] - y0c) * z, r[2] * z, r[3] * z), path=row['path'])
            if not (0 <= p1[0] <= ww and 0 <= p1[1] <= hh):
                raise SystemExit(f'spec: {where}.walk[{i}]: the row "{row["path"]}" is outside the camera at its hold')
        else:
            sg['ptr'] = None
        # holds and text sizes
        zS = geo.z(S)
        sg['holds'] = [dict(frame=hold_names, kind=kind, text_css=font, text_frame_px=round(font * zS, 1), width_css=round(cw))]
        if not last and need_pan:
            sg['holds'].append(dict(frame=sg['e'] - LEAD, kind=kind, text_css=font, text_frame_px=round(font * geo.z(T), 1), width_css=round(T[2])))
        if use_ov:
            sg['holds'].append(dict(frame=sg['s'] + use_ov - 1, kind='overview', text_css=font, text_frame_px=round(font * geo.z(OV), 1), width_css=round(OV[2]),
                                    exempt=f'whole-width view, {use_ov} frames (max {OVERVIEW_MAX})'))
        for h in sg['holds']:
            if h['kind'] != 'overview' and h['text_frame_px'] < PX_MIN - 0.05:
                raise SystemExit(f'small: {where}.walk[{i}] ("{key}") hold at frame {h["frame"]}: text {h["text_frame_px"]} frame px, floor {PX_MIN:g}')
        exits[key] = cam_at(sg, sg['e'] - 1)
        # stills
        a_f = max(arrive_f, sg['s'] + (XF + 2 if i else 0)); a_f = min(a_f, sg['e'] - 1)
        stills.append((f'{i}-{key or "home"}-arrive', a_f))
        if sg['ptr']:
            stills.append((f'{i}-{key or "home"}-hover', min(sg['ptr']['hover0'] + 5, sg['e'] - 1)))
        elif last:
            stills.append((f'{i}-{key or "home"}-end', sg['e'] - 1))
        holds.extend(dict(h, step=i, page=key) for h in sg['holds'])
        # speed audit
        prev = None
        for f in range(sg['s'], sg['e']):
            c = cam_at(sg, f)
            if prev is not None:
                z = max(geo.z(c), geo.z(prev))
                pan_pf = max(pan_pf, math.hypot(c[0] - prev[0], c[1] - prev[1]) * z)
                zoom_pf = max(zoom_pf, abs(math.log(c[2] / prev[2])))
            prev = c
    cap_px = CAP_PAN * hh / 30; cap_z = CAP_ZOOM / 30
    if pan_pf > cap_px * 1.001 or zoom_pf > cap_z * 1.001:
        raise SystemExit(f'spec: {where}: the camera plan exceeds the speed cap (pan {pan_pf:.1f} px/frame, cap {cap_px:.1f}; zoom {zoom_pf:.4f}, cap {cap_z:.4f})')
    return dict(segments=segs, holds=holds, stills=stills, max_pan_px_per_frame=round(pan_pf, 2), pan_cap_px_per_frame=round(cap_px, 2),
                max_zoom_per_frame=round(zoom_pf, 4), zoom_cap_per_frame=round(cap_z, 4))


def plan_notes(plan):
    """The plan as plain JSON for <spec>-plan.json."""
    r1 = lambda c: [round(x, 1) for x in c]
    segs = [dict(i=s['i'], page=s['page'], frames=[s['s'], s['e']], via=s['via'], focus=s['kind'], camera_width_css=round(s['cw']), start_camera=r1(s['cam0']),
                 moves=[dict(frames=[a, b], to=r1(cb)) for a, b, ca, cb in s['tweens']], reading_pan_from=(s['read']['f0'] if s['read'] else None),
                 pointer=(dict(frames=[s['ptr']['move0'], s['e']], row=s['ptr']['path']) if s['ptr'] else None), notes=s['notes']) for s in plan['segments']]
    return dict(segments=segs, holds=plan['holds'], stills=plan['stills'], max_pan_px_per_frame=plan['max_pan_px_per_frame'], pan_cap_px_per_frame=plan['pan_cap_px_per_frame'],
                max_zoom_per_frame=plan['max_zoom_per_frame'], zoom_cap_per_frame=plan['zoom_cap_per_frame'])


def seg_at(segs, f):
    for sg in segs:
        if sg['s'] <= f < sg['e']:
            return sg
    return segs[-1] if f >= segs[-1]['e'] else segs[0]
