"""Halcyon video spec loading: the JSON file the builder reads (see SPEC.md). Standard library only, so it can be tested without a GPU.

Loaded by dung-video-gpu.py. A missing field or file stops the run with a message naming it (`spec: beats[4].text.rows is missing`).
Every path in a spec is relative to the spec file."""
import json
import os
from pathlib import Path


def need(d, key, where):
    if not isinstance(d, dict) or key not in d or d[key] in (None, ''):
        raise SystemExit(f'spec: {where}.{key} is missing')
    return d[key]


def need_file(base, rel, where):
    p = (base / rel).resolve()
    if not p.exists():
        raise SystemExit(f'spec: {where} points to a file that does not exist: {p}')
    return p


def load_spec(path, fps, default_layout):
    path = Path(path).resolve(); base = path.parent
    d = json.loads(path.read_text(encoding='utf-8'))
    S = dict(path=path, base=base, name=need(d, 'name', 'spec'))
    S['duration'] = float(need(d, 'duration', 'spec')); S['total'] = round(S['duration'] * fps)
    S['voice'] = need_file(base, need(d, 'voice', 'spec'), 'spec.voice')
    timing = json.loads(need_file(base, need(d, 'timing', 'spec'), 'spec.timing').read_text(encoding='utf-8'))
    key = d.get('timing_words', 'words_whisper_medium')
    S['words'] = need(timing, key, 'timing file')
    S['aliases'] = d.get('word_aliases', {})
    S['captions'] = need(d, 'captions', 'spec')
    S['tiktok_caption'] = need(d, 'tiktok_caption', 'spec')
    out = need(d, 'out', 'spec')
    S['out_clean'] = base / need(out, 'clean', 'spec.out'); S['out_tt'] = base / need(out, 'tiktok', 'spec.out')
    S['beats'] = need(d, 'beats', 'spec')
    S['silences'] = d.get('silences', [])           # [{a, b}]: the spans with no voice and no subtitle (silent paragraphs)
    S['layout'] = d.get('layout', default_layout)   # layout preset in ve_halcyon.LAYOUTS: A (default), hien-tai (the earlier layout, for comparison)
    S['mesh_motion'] = d.get('mesh_motion', True)     # true = the default preset (nhe), a preset name (rat-nhe, nhe), {"amplitude": [lo, hi], "period": [lo, hi]}, false = the mesh stays at its home positions
    S['pattern'] = d.get('pattern')                      # field pattern in ve_halcyon.PATTERNS: mang-no-ron (default, white neural mesh), cham (the dot grid)
    S['field'] = d.get('field')                       # colour field in ve_halcyon.FIELDS: chu-muc (default on layout A), dac (the dense field of the earlier layout A)
    S['drop_kickers'] = bool(d.get('drop_kickers', False))   # true: a headline block (kind block, no wordmark pill) is drawn without its kicker line; beats with the wordmark pill keep theirs
    S['pill_gate'] = d.get('pill_gate', 'refuse')      # thu-gon-2 only: refuse (default) or print
    S['tmp'] = Path(os.environ.get('TEMP', '.')) / 'halcyon-video' / S['name']
    return S


# ---------------- clip pictures (picture.kind "clip") ----------------
# A clip is a finished moving picture made by the chain's own producers (terminal footage, the three.js scene, a scripted demo), written next to a
# manifest (`clip.json`) that records where it came from. The builder places it 1:1, never scaled, and refuses a file without that record.
CLIP_MAX_S = 40.0                                # a clip longer than this would hold about 1 MB a frame on the GPU for too long
CLIP_MIN_TEXT_PX = 28                            # the smallest text a clip may carry, in frame px (the producers measure it and write it down)
CLIP_TEXT = ('file', 'captured', 'source', 'date', 'tool_sha')
CLIP_FIELDS = CLIP_TEXT + ('w', 'h', 'fps', 'frames', 'duration', 'bg', 'min_text_px', 'stills', 'segments', 'proof')


def load_clip_manifest(path, where='clip'):
    """Read and check a clip manifest (`clip.json`). Returns the dict plus `path` (the manifest) and `video` (the clip file, resolved beside it).
    Every provenance field the producer writes must be there and sensible; a hand-made file has none of them, so it stops here."""
    path = Path(path).resolve()
    if not path.exists():
        raise SystemExit(f'spec: {where}: the clip manifest does not exist: {path}')
    try:
        m = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as e:
        raise SystemExit(f'spec: {where}: {path.name} is not JSON ({e})')
    if not isinstance(m, dict):
        raise SystemExit(f'spec: {where}: {path.name} must be a JSON object')
    for k in CLIP_FIELDS:
        if k not in m or m[k] in (None, ''):
            raise SystemExit(f'spec: {where}: {path.name} has no "{k}": a clip must come from the chain and carry its provenance (hand-made footage is refused)')
    for k in CLIP_TEXT:
        if not isinstance(m[k], str) or not m[k].strip():
            raise SystemExit(f'spec: {where}: {path.name} "{k}" must be a non-empty string')
    for k in ('w', 'h', 'frames'):
        if isinstance(m[k], bool) or not isinstance(m[k], int) or m[k] <= 0:
            raise SystemExit(f'spec: {where}: {path.name} "{k}" must be a positive integer')
    if m['w'] % 2 or m['h'] % 2:
        raise SystemExit(f'spec: {where}: {path.name} is {m["w"]}x{m["h"]}: both sides must be even (NV12)')
    for k in ('fps', 'duration', 'min_text_px'):
        if isinstance(m[k], bool) or not isinstance(m[k], (int, float)) or m[k] <= 0:
            raise SystemExit(f'spec: {where}: {path.name} "{k}" must be a positive number')
    bg = m['bg']
    if not (isinstance(bg, list) and len(bg) == 3 and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in bg)):
        raise SystemExit(f'spec: {where}: {path.name} "bg" must be [r, g, b], each 0-255')
    if not isinstance(m['stills'], list) or not all(isinstance(s, dict) and isinstance(s.get('t'), (int, float)) and isinstance(s.get('label'), str) for s in m['stills']):
        raise SystemExit(f'spec: {where}: {path.name} "stills" must be a list of {{"t": seconds, "label": text}}')
    if not isinstance(m['segments'], list):
        raise SystemExit(f'spec: {where}: {path.name} "segments" must be a list')
    if not isinstance(m['proof'], dict) or not m['proof']:
        raise SystemExit(f'spec: {where}: {path.name} "proof" must be a non-empty object (what the producer measured)')
    if abs(m['duration'] - m['frames'] / m['fps']) > 1.0 / m['fps'] + 1e-6:
        raise SystemExit(f'spec: {where}: {path.name} says {m["frames"]} frames at {m["fps"]} fps but a duration of {m["duration"]} s')
    if m['duration'] > CLIP_MAX_S:
        raise SystemExit(f'spec: {where}: the clip lasts {m["duration"]} s, the cap is {CLIP_MAX_S:g} s (about 1 MB a frame on the GPU)')
    if m['min_text_px'] < CLIP_MIN_TEXT_PX:
        raise SystemExit(f'safe frame: {where}: the clip carries text as small as {m["min_text_px"]} frame px (floor {CLIP_MIN_TEXT_PX}); the producer must draw it larger')
    video = (path.parent / m['file']).resolve()
    if not video.exists():
        raise SystemExit(f'spec: {where}: {path.name} names a clip file that does not exist: {video}')
    return dict(m, path=path, video=video)


def plan_clip(man, pic, win, frame_w, wmax, x_min, where):
    """Where and when a clip beat plays. `win` = (top, bottom) of the beat's picture window. The clip is placed 1:1, centred in the window and on the
    frame; it must fit the window and the picture column. Returns x_at, y_at, the source span (src0, sdur), the source rate and frame count."""
    src0 = float(need(pic, 'start', where)); sdur = float(need(pic, 'dur', where))
    if src0 < 0 or sdur <= 0:
        raise SystemExit(f'spec: {where}: start must be 0 or more and dur above 0')
    if src0 + sdur > man['duration'] + 1e-6:
        raise SystemExit(f'spec: {where}: start {src0:g} + dur {sdur:g} runs past the end of the clip ({man["duration"]:g} s)')
    w, h = man['w'], man['h']; top, bottom = win
    if h > bottom - top:
        raise SystemExit(f'safe frame: {where}: the clip is {h} px high, the window is {bottom - top} px (y {top}-{bottom}); a clip is never scaled, so the producer must draw it smaller')
    x_at = (frame_w - w) // 2; y_at = (top + bottom) // 2 - h // 2
    if w > wmax or x_at < x_min:
        raise SystemExit(f'safe frame: {where}: the clip is {w} px wide, the picture column holds {wmax} px (x {x_min}-{x_min + wmax}); a clip is never scaled')
    return dict(x_at=x_at, y_at=y_at, src0=src0, sdur=sdur, sfps=float(man['fps']), sframes=man['frames'])


def end_units_at_silences(units, silences):
    """A caption unit ends where the voice ends, not where the next unit starts: a unit that would last through a silent span is cut at the span's start `a`,
    so the plan never holds a subtitle inside a silence. A unit that starts inside a span is a fault of the spec and is left for the witness to refuse."""
    for u in units:
        for sp in silences:
            if u['s'] < sp['a'] - 1e-6 < u['e'] and u['e'] > sp['a'] + 1e-6:
                u['e'] = sp['a']
    return units


def beat_captions(sp, where):
    """The beat flag `captions`: true (default) or false (no subtitle drawn during this beat)."""
    v = sp.get('captions', True)
    if not isinstance(v, bool):
        raise SystemExit(f'spec: {where}.captions must be true or false')
    return v