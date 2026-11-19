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
    S['layout'] = d.get('layout', default_layout)   # layout preset in ve_halcyon.LAYOUTS: A (default), hien-tai (the earlier layout, for comparison)
    S['mesh_motion'] = d.get('mesh_motion', True)     # true = the default preset (nhe), a preset name (rat-nhe, nhe), {"amplitude": [lo, hi], "period": [lo, hi]}, false = the mesh stays at its home positions
    S['pattern'] = d.get('pattern')                      # field pattern in ve_halcyon.PATTERNS: mang-no-ron (default, white neural mesh), cham (the dot grid)
    S['field'] = d.get('field')                       # colour field in ve_halcyon.FIELDS: chu-muc (default on layout A), dac (the dense field of the earlier layout A)
    S['drop_kickers'] = bool(d.get('drop_kickers', False))   # true: a headline block (kind block, no wordmark pill) is drawn without its kicker line; beats with the wordmark pill keep theirs
    S['pill_gate'] = d.get('pill_gate', 'refuse')      # thu-gon-2 only: refuse (default) or print
    S['tmp'] = Path(os.environ.get('TEMP', '.')) / 'halcyon-video' / S['name']
    return S
