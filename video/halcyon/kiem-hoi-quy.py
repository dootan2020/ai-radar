"""Timing regression check: compare the <stem>-plan.json a build just wrote with an earlier one (the committed or pre-change copy).

Run: $HALCYON_PYTHON -I -X utf8 kiem-hoi-quy.py <new-plan.json> <old-plan.json> <out.txt>
Equal means: frames and fps; every caption unit (T, s, e, wstart); every beat (id, f0, f1, switch frames); every highlighter band frame.
Geometry (rects, picture size, chip size, notes) is expected to change when the layout changes and is not compared.
This replaces the earlier per-frame pixel comparison of two mp4 files, which can no longer pass once the layout moves; the audio hash
(ffmpeg -i <mp4> -map 0:a -f md5 -) and the coordinator's side-by-side look at the stills cover what this does not.
Exit 0 when everything is equal, 1 when anything differs; a missing key raises."""
import sys
sys.dont_write_bytecode = True
import json
from pathlib import Path

new = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
old = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
out = Path(sys.argv[3])
diffs, checked = [], 0


def eq(what, a, b):
    global checked
    checked += 1
    if a != b:
        diffs.append(f'{what}: new {a} != old {b}')


for key in ('frames', 'fps', 'lead', 'fade_frames'):
    eq(key, new[key], old[key])
eq('number of caption units', len(new['units']), len(old['units']))
for i, (a, b) in enumerate(zip(new['units'], old['units'])):
    for key in ('T', 's', 'e', 'wstart'):
        eq(f'unit {i} "{b["T"]}" {key}', a[key], b[key])
eq('number of beats', len(new['beats']), len(old['beats']))
for a, b in zip(new['beats'], old['beats']):
    for key in ('id', 'f0', 'f1', 'level', 'kind', 'switch'):
        eq(f'beat {b["id"]} {key}', a[key], b[key])
eq('beats with bands', sorted(new['bands']), sorted(old['bands']))
for bid, bl in old['bands'].items():
    nl = new['bands'].get(bid, [])
    eq(f'beat {bid} band count', len(nl), len(bl))
    for n, (a, b) in enumerate(zip(nl, bl)):
        eq(f'beat {bid} band {n} frame', a['frame'], b['frame'])
lines = [f'new: {Path(sys.argv[1]).name}   old: {Path(sys.argv[2]).name}',
         f'{checked} comparisons over {len(old["units"])} caption units, {len(old["beats"])} beats, {sum(len(v) for v in old["bands"].values())} bands',
         'RESULT: ' + ('EQUAL' if not diffs else f'{len(diffs)} DIFFERENCES')] + diffs
out.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
print('\n'.join(lines))
sys.exit(1 if diffs else 0)
