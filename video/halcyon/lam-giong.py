"""One command from the spoken text of a script to a finished voice track and the timing file the spec assembler reads.

    python lam-giong.py <kich-ban.json> --out <folder> [--approved <giong-da-nghe.txt>]

Steps (the wall time of each is printed): 1 text files from the script's `say`/`show`, 2 synthesis of every paragraph with the channel voice and,
for each paragraph on its own, mastering of the joined voice, Whisper on that paragraph's audio and the paragraph check (a paragraph that fails is
made again, up to 3 attempts, and only that paragraph), 3 the voice joined and mastered, 4 the paragraphs measured on the final wav,
5 the reading gate over the whole voice (halcyon_giong.py), 6 the timing file and the listen list. The gate failing writes no timing file and exits 2.
Needs ffmpeg and ffprobe on PATH and two settings, never a path in code:
  HALCYON_OMNIVOICE_PYTHON   the Python that has OmniVoice and faster-whisper installed (it runs the synthesis and Whisper)
  HALCYON_VOICE_PROFILES     the folder that holds the voice profile folder `vhn-giong-tin-ai` (profile.toml, reference.wav)
Offline: the voice model and Whisper medium must already be in the local Hugging Face cache. The voice, speed, pause and mastering are the
settings the published voices used and are not options. Deadlines: 20 minutes for each synthesis round, 10 for each Whisper run; a step that
overruns is killed. Standard library only here; the Whisper step re-runs this file under HALCYON_OMNIVOICE_PYTHON with --whisper-only."""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOICE, SPEED, PAUSE_MS = 'vhn-giong-tin-ai', '0.93', 300
MASTER = 'highpass=f=70,acompressor=threshold=0.06:ratio=3:attack=5:release=80:makeup=2,loudnorm=I=-15:TP=-1.5:LRA=4'
TTS_DEADLINE, WHISPER_DEADLINE, FFMPEG_DEADLINE = 20 * 60, 10 * 60, 120
MAX_ATTEMPTS = 3   # voice takes per paragraph


def fail(msg):
    raise SystemExit(f'giong: {msg}')


def load_gate():
    spec = importlib.util.spec_from_file_location('halcyon_giong', HERE / 'halcyon_giong.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def setting(name, what):
    v = os.environ.get(name)
    if not v:
        fail(f'set {name} to {what}')
    return v


def run(cmd, deadline, log, label):
    """Run cmd with a deadline; stdout and stderr go to <log>.out / <log>.err. Overrun: kill the whole process tree, show the log tail, stop."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    with open(f'{log}.out', 'wb') as out, open(f'{log}.err', 'wb') as err:
        p = subprocess.Popen(cmd, stdout=out, stderr=err, env=env)
        try:
            p.wait(timeout=deadline)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True) if os.name == 'nt' else p.kill()
            p.wait()
            tail = Path(f'{log}.err').read_text(encoding='utf-8', errors='replace').strip().splitlines()[-8:]
            fail(f'{label} ran over its {deadline // 60} minute deadline and was killed; last log lines ({log}.err):\n  ' + '\n  '.join(tail))
    if p.returncode:
        tail = Path(f'{log}.err').read_text(encoding='utf-8', errors='replace').strip().splitlines()[-8:]
        fail(f'{label} failed (exit {p.returncode}); log {log}.err:\n  ' + '\n  '.join(tail))


def probe(args, deadline=FFMPEG_DEADLINE):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=deadline)


def whisper_only(out, wavs):
    """Whisper medium words of every wav, one model session: {wav path: [{w, s, e}]} (times from the start of that wav)."""
    from faster_whisper import WhisperModel
    model = WhisperModel('medium', device='cpu', compute_type='int8', local_files_only=True)
    result = {}
    for wav in wavs:
        # Each wav is one paragraph, and no text of an earlier stretch is carried into the next one: a long-form run that skipped a whole stretch
        # of speech (82 words "not heard" with the audio there) is what this avoids.
        segs, _ = model.transcribe(wav, language='vi', word_timestamps=True, vad_filter=False, beam_size=5, condition_on_previous_text=False)
        result[wav] = [{'w': w.word.strip(), 's': round(w.start, 3), 'e': round(w.end, 3)} for s in segs for w in s.words]
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(result, f, ensure_ascii=False, indent=0)


class Steps:
    def __init__(self):
        self.rows, self.t0 = [], time.time()

    def __call__(self, name):
        steps = self

        class Timer:
            def __enter__(self):
                self.t = time.time()
                print(f'[{name}] ...', flush=True)

            def __exit__(self, et, ev, tb):
                steps.rows.append((name, round(time.time() - self.t, 1)))
                print(f'[{name}] {steps.rows[-1][1]} s', flush=True)
        return Timer()


def join_paragraphs(files, pause_s, out_wav):
    """Join the paragraph wavs with the pause between them (stdlib `wave`; every file has one format). Returns the length of each paragraph in seconds."""
    params, frames, durations = None, [], []
    for f in files:
        with wave.open(str(f), 'rb') as w:
            p = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            if params is None:
                params = p
            elif p != params:
                fail(f'{f} is {p} but the first paragraph is {params}: the paragraphs must share one format')
            frames.append(w.readframes(w.getnframes()))
            durations.append(w.getnframes() / w.getframerate())
    ch, width, rate = params
    gap = b'\x00' * (round(rate * pause_s) * ch * width)
    with wave.open(str(out_wav), 'wb') as o:
        o.setnchannels(ch)
        o.setsampwidth(width)
        o.setframerate(rate)
        o.writeframes(gap.join(frames))
    return durations


def master(src, dst):
    r = probe(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(src), '-af', MASTER, '-ar', '48000', '-ac', '1', str(dst)])
    if r.returncode:
        fail('ffmpeg mastering failed: ' + r.stderr.strip()[-300:])


def measure(final):
    """(loudness text, duration in s) of the mastered voice; refuses a voice outside the channel's loudness."""
    m = probe(['ffmpeg', '-nostats', '-i', str(final), '-af', MASTER.split(',')[-1] + ':print_format=json', '-f', 'null', '-']).stderr
    j = json.loads(re.search(r'\{[^{}]*\}', m[m.rindex('[Parsed_loudnorm'):]).group(0))
    duration = float(probe(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(final)]).stdout)
    if not -16.0 <= float(j['input_i']) <= -14.0 or float(j['input_tp']) > -1.0:
        fail(f"the mastered voice measures {j['input_i']} LUFS, true peak {j['input_tp']} dBTP; the channel's voice is -15 LUFS (-16 to -14), peak at most -1")
    return f"{j['input_i']} LUFS, true peak {j['input_tp']} dBTP, LRA {j['input_lra']}", duration


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('script')
    ap.add_argument('--out', required=True)
    ap.add_argument('--approved', default=str(HERE / 'giong-da-nghe.txt'))
    a = ap.parse_args(argv)
    g = load_gate()
    kb = json.loads(Path(a.script).read_text(encoding='utf-8'))
    paras = kb.get('paragraphs') or fail(f'{a.script} has no paragraphs')
    say = [str(p.get('say', '')).strip() for p in paras]
    if not all(say) or any(re.search(r'\n\s*\n', s) for s in say):
        fail('every paragraph needs a `say` text of its own with no blank line inside (one paragraph = one voice paragraph)')
    show = [re.sub(r'\s+', ' ', str(p.get('show', p['say'])).replace('/', ' ')).strip() for p in paras]
    voice = [g.voice_text(s) for s in say]   # the channel's default readings (GIONG.md table: AI -> Ây-ai, GitHub -> Git hắp, apps -> áp, code -> cốt, ...); `say` and `show` stay as written
    approved = g.load_approved(Path(a.approved).read_text(encoding='utf-8')) if a.approved and Path(a.approved).exists() else []
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    py = setting('HALCYON_OMNIVOICE_PYTHON', 'the Python that has OmniVoice and faster-whisper')
    profiles = setting('HALCYON_VOICE_PROFILES', 'the folder that holds the voice profile folder ' + VOICE)
    if not (Path(profiles) / VOICE / 'reference.wav').exists():
        fail(f'the voice profile {VOICE} (reference.wav) is not in the folder HALCYON_VOICE_PROFILES names')
    steps = Steps()
    n = len(say)

    with steps('1 text'):
        (out / 'loi-doc-tts.txt').write_text('\n\n'.join(voice) + '\n', encoding='utf-8', newline='\n')
        (out / 'loi-hien-thi.txt').write_text('\n\n'.join(show) + '\n', encoding='utf-8', newline='\n')

    pdir = out / 'doan'   # one wav per paragraph take: para-NN-aK.wav = paragraph NN, attempt K
    pdir.mkdir(exist_ok=True)
    for f in pdir.glob('para-*'):
        f.unlink()
    raw, final = out / 'tts-raw.wav', out / 'giong-day-du.wav'
    attempts = [[] for _ in say]    # per paragraph: dicts(n, wav, words, problems, unmatched)
    pending = list(range(n))        # paragraphs not yet through their own check
    for rnd in range(1, MAX_ATTEMPTS + 1):
        with steps(f'2.{rnd} synthesis of paragraph(s) {",".join(str(i + 1) for i in pending)}'):
            for i in pending:
                for f in pdir.glob(f'para-{i + 1:02d}.wav'):
                    f.unlink()
                for f in pdir.glob(f'para-{i + 1:02d}_corrected*'):
                    f.unlink()
            cmd = [py, '-X', 'utf8', str(HERE.parent / 'scripts' / 'omnivoice_tts.py'), 'synthesize', '--text-file', str(out / 'loi-doc-tts.txt'),
                   '--output', str(pdir / 'unused.wav'), '--voice-name', VOICE, '--profiles-dir', profiles, '--language', 'vi', '--device', 'cpu',
                   '--speed', SPEED, '--split-paragraphs', '--pause-ms', str(PAUSE_MS), '--paragraphs-dir', str(pdir),
                   '--only', ','.join(str(i + 1) for i in pending), '--offline']
            run(cmd, TTS_DEADLINE, str(out / f'tts-{rnd}'), 'synthesis')
            for i in pending:
                got = pdir / f'para-{i + 1:02d}_corrected.wav'
                got = got if got.exists() else pdir / f'para-{i + 1:02d}.wav'
                if not got.exists():
                    fail(f'synthesis wrote no audio for paragraph {i + 1}; log {out / f"tts-{rnd}.err"}')
                dest = pdir / f'para-{i + 1:02d}-a{rnd}.wav'
                got.replace(dest)
                attempts[i].append(dict(n=rnd, wav=dest))

        with steps(f'2.{rnd} check of paragraph(s) {",".join(str(i + 1) for i in pending)}'):
            # master the whole voice as it stands (the paragraphs that passed and the new takes), then cut it at the known paragraph edges:
            # Whisper hears each paragraph by itself, in the mastered audio the channel will publish
            cur = [attempts[i][-1]['wav'] for i in range(n)]
            durations = join_paragraphs(cur, PAUSE_MS / 1000, raw)
            master(raw, final)
            windows = g.paragraph_windows(durations, PAUSE_MS / 1000)
            cuts = {}
            for i in pending:
                cut = pdir / f'para-{i + 1:02d}-a{rnd}-48k.wav'
                r = probe(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(final), '-ss', f'{windows[i][0]:.4f}', '-t', f'{durations[i]:.4f}', '-c:a', 'pcm_s16le', str(cut)])
                if r.returncode:
                    fail(f'ffmpeg could not cut paragraph {i + 1}: ' + r.stderr.strip()[-300:])
                cuts[str(cut)] = i
            words_json = out / f'whisper-{rnd}.json'
            words_json.unlink(missing_ok=True)
            run([py, '-X', 'utf8', str(Path(__file__).resolve()), '--whisper-only', str(words_json), *cuts], WHISPER_DEADLINE, str(out / f'whisper-{rnd}'), 'Whisper')
            heard = json.loads(words_json.read_text(encoding='utf-8'))
            for cut, i in cuts.items():
                rep = g.check_paragraph(voice[i], heard[cut], approved, i + 1)
                attempts[i][-1].update(words=heard[cut], problems=rep['problems'], unmatched=rep['unmatched'])
            pending = [i for i in pending if attempts[i][-1]['problems']]
            for i in range(n):
                if attempts[i] and attempts[i][-1]['n'] == rnd:
                    t = attempts[i][-1]
                    print(f'  paragraph {i + 1}, attempt {rnd}: ' + ('ok' if not t['problems'] else 'MAKE AGAIN: ' + '; '.join(t['problems'])), flush=True)
        if not pending:
            break

    chosen = []
    for i in range(n):   # a paragraph still failing after its last attempt keeps its best take; the check of the whole voice below decides
        best = min(attempts[i], key=lambda t: (len(t['problems']), t['unmatched'], -t['n']))
        if best['problems']:
            print(f'  paragraph {i + 1}: still failing after {len(attempts[i])} attempts; kept attempt {best["n"]} ({len(best["problems"])} problem(s))', flush=True)
        chosen.append(best)

    with steps('3 mastering'):
        durations = join_paragraphs([t['wav'] for t in chosen], PAUSE_MS / 1000, raw)
        master(raw, final)
        loudness, duration = measure(final)
        windows = g.paragraph_windows(durations, PAUSE_MS / 1000)
        if abs(duration - windows[-1][1]) > 0.1:
            fail(f'the mastered voice is {duration:.2f} s but its paragraphs end at {windows[-1][1]:.2f} s')

    words = g.join_paragraph_words([t['words'] for t in chosen], windows)
    (out / 'whisper-words.json').write_text(json.dumps(words, ensure_ascii=False, indent=0), encoding='utf-8', newline='\n')

    with steps('4 paragraphs'):
        sil = probe(['ffmpeg', '-hide_banner', '-i', str(final), '-af', 'silencedetect=noise=-35dB:d=0.12', '-f', 'null', '-']).stderr
        spans = g.spans_from_windows(sil, windows)

    with steps('5 gate'):
        rep = g.check_reading(voice, words, spans, approved)
        rep['paragraph_attempts'] = [dict(paragraph=i + 1, attempts=len(attempts[i]), used=chosen[i]['n'], problems=chosen[i]['problems']) for i in range(n)]
        rep['steps_s'] = dict(steps.rows)
        g.write_json(out / 'giong-ket-qua.json', rep)

    if rep['problems']:
        print('\n'.join('  ' + p for p in rep['problems']))
        print('\nlisten list so far:\n' + g.format_listen(rep['listen'], rep['approved']))
        fail(f'the voice did not say the script, so no timing file was written (report: {out / "giong-ket-qua.json"}); '
             f'every paragraph that failed was made again up to {MAX_ATTEMPTS} times; change the say text of the paragraph (a respelling) and run again')

    with steps('6 timing'):
        timing = g.build_timing(final.name, 48000, duration, loudness, PAUSE_MS / 1000, spans, words, voice, show)
        g.write_json(out / 'giong-day-du-timing.json', timing)
        text = g.format_listen(rep['listen'], rep['approved'])
        (out / 'nghe-lai.txt').write_text(text + '\n', encoding='utf-8', newline='\n')

    print(f'\nvoice {duration:.2f} s, {loudness}; {rep["words"]} script words, {rep["unmatched"]} not heard ({rep["rate"]:.1%}), longest run {rep["longest_run"]}')
    print('beats on the final wav: ' + ', '.join(f'{s["start"]:.2f}-{s["end"]:.2f}' for s in spans))
    print('takes per paragraph: ' + ', '.join(f'{x["paragraph"]}:{x["attempts"]}' for x in rep['paragraph_attempts']))
    print('listen list (nghe-lai.txt):\n' + text)
    print('wall time: ' + ', '.join(f'{k} {t} s' for k, t in steps.rows) + f'; total {round(time.time() - steps.t0, 1)} s')
    print(f'timing file: {out / "giong-day-du-timing.json"}')


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == '--whisper-only':
        whisper_only(sys.argv[2], sys.argv[3:])
    else:
        main(sys.argv[1:])
