"""Silence for silent paragraphs (halcyon_lang.py): put a stretch of digital silence into the finished voice track and move every time after it. Standard library only.

    python halcyon_lang.py --timing giong-day-du-timing.json --wav giong-day-du.wav --insert 2:17.0:thu-s0.1 [--insert ...] --out-dir lang/

The voice is made from the voiced paragraphs only (a silent paragraph has no `say`), so the voice has gaps where the script has silent paragraphs. `--insert K:SECONDS[:KEY]`
puts SECONDS of silence into the gap before voiced paragraph K (counted from 0; K from 1 to the last), at the middle of that gap, which is also where the assembler cuts
between two voiced paragraphs. The words and paragraph spans after the insert move later by the same time and the timing file gets `silences: [{a, b, key}]`, the seconds
the video is silent (no voice, no subtitle). The voice before and after the insert is byte for byte what it was (checked). The contract and the gates are in KICH-BAN.md and MOT-LENH.md."""
import argparse
import array
import json
import math
import sys
import wave
from pathlib import Path

NO_VOICE_DBFS = -60.0            # the loudest sample inside a silent span may not be above this
EPS = 1e-9
OVERRUN_S = 0.5               # Whisper's word end may run this far past the measured end of the speech, into the pause, and still be cut at the pause
QUIET_DBFS = -45.0             # the loudest sample of the original voice in that overrun may not be above this: above it, speech really is there


class Refusal(Exception):
    pass


def fail(msg):
    raise Refusal(msg)


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        p = w.getparams()
        if p.sampwidth != 2:
            fail(f'{path} is {p.sampwidth * 8}-bit; the voice track is 16-bit PCM (halcyon: ffmpeg mastering writes it)')
        return p, w.readframes(p.nframes)


def write_wav(path, params, frames):
    with wave.open(str(path), 'wb') as w:
        w.setparams(params._replace(nframes=0))
        w.writeframes(frames)


def check_inserts(timing, inserts):
    """Each insert is dict(before=K, dur=seconds, key=text); K counts the voiced paragraphs of `timing` from 0 and must name a gap between two of them, once."""
    n = len(timing.get('beats', []))
    seen = set()
    for i in inserts:
        k, d = i['before'], i['dur']
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= n - 1:
            fail(f'a silence is asked before voiced paragraph {k}, but the voice has {n} paragraphs; a silence goes between two of them (1 to {n - 1})')
        if k in seen:
            fail(f'two silences are asked in the same gap (before voiced paragraph {k}); make it one block')
        if not (isinstance(d, (int, float)) and not isinstance(d, bool) and 0.5 <= d <= 120):
            fail(f'the silence before voiced paragraph {k} lasts {d} s; it must be between 0.5 and 120 s')
        seen.add(k)
    return sorted(inserts, key=lambda i: i['before'])


def gap_middle(timing, k):
    """Middle of the pause between voiced paragraph k-1 and k: where the assembler cuts, and where the silence goes."""
    a, b = timing['beats'][k - 1]['end'], timing['beats'][k]['start']
    if not b > a:
        fail(f'voiced paragraphs {k - 1} and {k} have no pause between them in the timing file ({a} to {b} s)')
    return (a + b) / 2


def shift_timing(timing, marks):
    """The timing file with every time after a mark moved later. marks: [dict(at, dur, key)] in seconds of the OLD voice, sorted. Returns the new timing."""
    def moved(t):
        return round(t + sum(m['dur'] for m in marks if m['at'] < t - EPS), 3)
    out = json.loads(json.dumps(timing))
    out['words_whisper_medium'] = [dict(w, s=moved(w['s']), e=moved(w['e'])) for w in timing['words_whisper_medium']]
    out['beats'] = [dict(b, start=moved(b['start']), end=moved(b['end'])) for b in timing['beats']]
    out['duration_s'] = round(timing['duration_s'] + sum(m['dur'] for m in marks), 3)
    sil, before = [], 0.0
    for m in marks:
        a = round(m['at'] + before, 3)
        sil.append(dict(a=a, b=round(a + m['dur'], 3), key=m.get('key')))
        before += m['dur']
    out['silences'] = sil
    return out


def clip_overruns(timing, params, frames, marks):
    """Whisper word ends are known to overrun. A word that starts before a silence is put in but ends after it (by at most OVERRUN_S) is cut at the silence
    when the ORIGINAL voice there is quiet (the energy, not Whisper, says the speech is over); where it is not quiet, or the overrun is longer, the word stays
    as it is and the check refuses the silence. Returns (timing with those word ends cut, [dict(index, w, was, now)])."""
    out = json.loads(json.dumps(timing))
    clipped = []
    for i, w in enumerate(out['words_whisper_medium']):
        for m in marks:
            if w['s'] < m['at'] - EPS and m['at'] + EPS < w['e'] <= m['at'] + OVERRUN_S:
                if peak_of(params, frames, m['at'], w['e']) <= QUIET_DBFS:
                    clipped.append(dict(index=i, w=w['w'], was=w['e'], now=round(m['at'], 3)))
                    w['e'] = round(m['at'], 3)
                break
    return out, clipped


def insert_silences(timing, wav_in, inserts, wav_out):
    """Write `wav_out` (the voice with the silences in) and return the new timing. Marks are rounded to whole samples so the timing and the wav agree to the sample."""
    inserts = check_inserts(timing, inserts)
    params, frames = read_wav(wav_in)
    rate, width, ch = params.framerate, params.sampwidth, params.nchannels
    unit = width * ch
    marks, parts, pos = [], [], 0
    for i in inserts:
        at = round(gap_middle(timing, i['before']) * rate)
        n = round(i['dur'] * rate)
        if at < pos or at > params.nframes:
            fail(f'the gap before voiced paragraph {i["before"]} lies outside the voice track')
        parts += [frames[pos * unit:at * unit], bytes(n * unit)]
        pos = at
        marks.append(dict(at=at / rate, dur=n / rate, key=i.get('key')))
    parts.append(frames[pos * unit:])
    write_wav(wav_out, params, b''.join(parts))
    timing, clipped = clip_overruns(timing, params, frames, marks)
    new = shift_timing(timing, marks)
    if clipped:
        new['word_ends_cut_at_silence'] = clipped
    return new


def peak_dbfs(wav, a, b):
    """The loudest sample between a and b seconds, in dBFS (-200 for digital silence)."""
    params, frames = read_wav(wav)
    return peak_of(params, frames, a, b)


def peak_of(params, frames, a, b):
    s = array.array('h')
    s.frombytes(frames)
    ch = params.nchannels
    lo, hi = max(0, round(a * params.framerate)) * ch, min(params.nframes, round(b * params.framerate)) * ch
    peak = max((abs(x) for x in s[lo:hi]), default=0)
    return -200.0 if peak == 0 else round(20 * math.log10(peak / 32768), 2)


def check_result(timing_in, timing_out, wav_in, wav_out):
    """The gates of the step, read back from the files it wrote: durations add up, the voice outside the silences is the same samples, the silences are digital silence,
    every word and span moved by exactly the silence before it. Returns a list of problems (empty when right)."""
    problems = []
    pi, fi = read_wav(wav_in)
    po, fo = read_wav(wav_out)
    sil = timing_out.get('silences', [])
    total = sum(round((s['b'] - s['a']) * po.framerate) for s in sil)
    if po.nframes != pi.nframes + total:
        problems.append(f'the new voice has {po.nframes} samples, expected {pi.nframes + total}')
    if abs(timing_out['duration_s'] - po.nframes / po.framerate) > 0.01:
        problems.append(f'the timing says {timing_out["duration_s"]} s but the voice file lasts {po.nframes / po.framerate:.3f} s')
    unit, pos, cut = pi.sampwidth * pi.nchannels, 0, 0
    for s in sil:
        a, b = round(s['a'] * po.framerate), round(s['b'] * po.framerate)
        keep = a - cut                       # voice samples copied before this silence
        if fo[cut * unit:a * unit] != fi[pos * unit:(pos + keep) * unit]:
            problems.append(f'the voice before the silence at {s["a"]} s is not the original voice')
        if any(fo[a * unit:b * unit]):
            problems.append(f'the silence at {s["a"]} s is not digital silence')
        pos, cut = pos + keep, b
    if fo[cut * unit:] != fi[pos * unit:]:
        problems.append('the voice after the last silence is not the original voice')
    cut = {c['index']: c for c in timing_out.get('word_ends_cut_at_silence', [])}
    for c in cut.values():
        wi = timing_in['words_whisper_medium'][c['index']]
        if round(wi['e'], 3) != c['was'] or not 0 < c['was'] - c['now'] <= OVERRUN_S + EPS:
            problems.append(f'the word "{c["w"]}" is cut at a silence by more than the {OVERRUN_S} s a word end may overrun')
        elif peak_dbfs(wav_in, c['now'], c['was']) > QUIET_DBFS:
            problems.append(f'the word "{c["w"]}" is cut at a silence but the voice is not quiet there ({c["now"]}-{c["was"]} s): speech is heard')
    for k, (wi, wo) in enumerate(zip(timing_in['words_whisper_medium'], timing_out['words_whisper_medium'])):
        if k in cut:
            continue
        if round(wo['e'] - wo['s'], 2) != round(wi['e'] - wi['s'], 2):
            problems.append(f'the word "{wi["w"]}" changed length')
            break
    for s in sil:
        if any(w['s'] < s['b'] - EPS and w['e'] > s['a'] + EPS for w in timing_out['words_whisper_medium']):
            problems.append(f'a word is heard inside the silence at {s["a"]} s')
        db = peak_dbfs(wav_out, s['a'], s['b'])
        if db > NO_VOICE_DBFS:
            problems.append(f'the voice track is {db} dBFS inside the silence at {s["a"]} s (limit {NO_VOICE_DBFS})')
    return problems


def run(timing_path, wav_path, inserts, out_dir):
    """The chain's step: returns (timing_out_path, wav_out_path, new timing)."""
    timing = json.loads(Path(timing_path).read_text(encoding='utf-8'))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wav_out = out / Path(wav_path).name
    new = insert_silences(timing, wav_path, inserts, wav_out)
    new['file'] = wav_out.name
    bad = check_result(timing, new, wav_path, wav_out)
    if bad:
        fail('; '.join(bad))
    tpath = out / Path(timing_path).name
    with open(tpath, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return tpath, wav_out, new


def parse_insert(text):
    parts = text.split(':', 2)
    try:
        return dict(before=int(parts[0]), dur=float(parts[1]), key=parts[2] if len(parts) > 2 else None)
    except (ValueError, IndexError):
        fail(f'--insert {text!r} must read K:SECONDS[:KEY], for example 2:17.0:thu-s0.1')


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--timing', required=True)
    ap.add_argument('--wav', required=True)
    ap.add_argument('--insert', action='append', required=True, metavar='K:SECONDS[:KEY]')
    ap.add_argument('--out-dir', required=True)
    a = ap.parse_args(argv)
    try:
        t, w, new = run(a.timing, a.wav, [parse_insert(x) for x in a.insert], a.out_dir)
    except Refusal as r:
        print(f'lang: {r}', file=sys.stderr)
        return 2
    print(f'wrote {w} and {t}: {len(new["silences"])} silence(s): ' + ', '.join(f'{s["a"]}-{s["b"]} s' for s in new['silences']) + f'; voice now {new["duration_s"]} s')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
