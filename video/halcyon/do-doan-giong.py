"""Write the voice paragraphs of a final wav into a timing file: python do-doan-giong.py <final.wav> <timing.json> <out.json>

The paragraph gaps are the silences over 0.5 s (ffmpeg silencedetect, -35 dB, 0.12 s). `beats` gets one {beat, start, end} per paragraph: speech start
and end, so the cut between two beats (halcyon_kich_ban.py) is the middle of the gap, as measured on the final file. Stops when the number of paragraphs
found is not the number the timing file already lists (if it has `beats`) or the number given with --paragraphs."""
import json
import re
import subprocess
import sys

wav, timing, out = sys.argv[1:4]
want = int(sys.argv[sys.argv.index('--paragraphs') + 1]) if '--paragraphs' in sys.argv else None
o = subprocess.run(['ffmpeg', '-hide_banner', '-i', wav, '-af', 'silencedetect=noise=-35dB:d=0.12', '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8').stderr
starts = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', o)]; ends = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', o)]
gaps = [(a, b) for a, b in zip(starts, ends) if b - a > 0.5]
t = json.load(open(timing, encoding='utf-8'))
want = want or len(t.get('beats', [])) or None
if want and len(gaps) + 1 != want:
    sys.exit(f'do-doan-giong: found {len(gaps) + 1} paragraphs in {wav}, expected {want}; the pauses between paragraphs are not all over 0.5 s, or a paragraph holds one')
edges = [0.0] + [x for g in gaps for x in g] + [t['duration_s']]
t['beats'] = [dict(beat=i + 1, start=round(edges[2 * i], 3), end=round(edges[2 * i + 1], 3)) for i in range(len(gaps) + 1)]
with open(out, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(t, f, ensure_ascii=False, indent=1)
print(len(t['beats']), 'paragraphs')