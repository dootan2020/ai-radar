"""One command from the spoken text of a script to a finished voice track and the timing file the spec assembler reads.

    python lam-giong.py <kich-ban.json> --out <folder> [--approved <giong-da-nghe.txt>]

Steps (the wall time of each is printed): 1 text files from the script's `say`/`show`, 2 synthesis with the channel voice, 3 mastering,
4 Whisper words of the final wav, 5 the voice paragraphs measured on the final wav, 6 the reading gate (halcyon_giong.py), 7 the timing file and
the listen list. The gate failing writes no timing file and exits 2. Needs ffmpeg and ffprobe on PATH and two settings, never a path in code:
  HALCYON_OMNIVOICE_PYTHON   the Python that has OmniVoice and faster-whisper installed (it runs steps 2 and 4)
  HALCYON_VOICE_PROFILES     the folder that holds the voice profile folder `vhn-giong-tin-ai` (profile.toml, reference.wav)
Offline: the voice model and Whisper medium must already be in the local Hugging Face cache. The voice, speed, pause and mastering are the
settings the published voices used and are not options. Deadlines: 20 minutes for synthesis, 10 for Whisper; a step that overruns is killed.
Standard library only here; the Whisper step re-runs this file under HALCYON_OMNIVOICE_PYTHON with --whisper-only."""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOICE, SPEED, PAUSE_MS = 'vhn-giong-tin-ai', '0.93', 300
MASTER = 'highpass=f=70,acompressor=threshold=0.06:ratio=3:attack=5:release=80:makeup=2,loudnorm=I=-15:TP=-1.5:LRA=4'
TTS_DEADLINE, WHISPER_DEADLINE, FFMPEG_DEADLINE = 20 * 60, 10 * 60, 120


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


def whisper_only(wav, out):
    from faster_whisper import WhisperModel
    model = WhisperModel('medium', device='cpu', compute_type='int8', local_files_only=True)
    segs, _ = model.transcribe(wav, language='vi', word_timestamps=True, vad_filter=False, beam_size=5)
    words = [{'w': w.word.strip(), 's': round(w.start, 3), 'e': round(w.end, 3)} for s in segs for w in s.words]
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(words, f, ensure_ascii=False, indent=0)


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
    voice = [g.voice_text(s) for s in say]   # the channel's default readings (AI -> Ây-ai, GitHub -> Git hắp); `say` and `show` stay as written
    approved = g.load_approved(Path(a.approved).read_text(encoding='utf-8')) if a.approved and Path(a.approved).exists() else []
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    py = setting('HALCYON_OMNIVOICE_PYTHON', 'the Python that has OmniVoice and faster-whisper')
    profiles = setting('HALCYON_VOICE_PROFILES', 'the folder that holds the voice profile folder ' + VOICE)
    if not (Path(profiles) / VOICE / 'reference.wav').exists():
        fail(f'the voice profile {VOICE} (reference.wav) is not in the folder HALCYON_VOICE_PROFILES names')
    steps = Steps()

    with steps('1 text'):
        (out / 'loi-doc-tts.txt').write_text('\n\n'.join(voice) + '\n', encoding='utf-8', newline='\n')
        (out / 'loi-hien-thi.txt').write_text('\n\n'.join(show) + '\n', encoding='utf-8', newline='\n')

    raw, raw_json = out / 'tts-raw.wav', out / 'tts-raw.json'
    with steps('2 synthesis'):
        for f in (raw, raw_json, out / 'tts-raw_corrected.wav'):
            f.unlink(missing_ok=True)
        run([py, '-X', 'utf8', str(HERE.parent / 'scripts' / 'omnivoice_tts.py'), 'synthesize', '--text-file', str(out / 'loi-doc-tts.txt'),
             '--output', str(raw), '--voice-name', VOICE, '--profiles-dir', profiles, '--language', 'vi', '--device', 'cpu', '--speed', SPEED,
             '--split-paragraphs', '--pause-ms', str(PAUSE_MS), '--timing-file', str(raw_json), '--offline'], TTS_DEADLINE, str(out / 'tts'), 'synthesis')
        if not raw.exists() or not raw_json.exists():
            fail(f'synthesis wrote no {raw.name}; log {out / "tts.err"}')
        chunks = json.loads(raw_json.read_text(encoding='utf-8')).get('chunk_count')
        if chunks != len(say):
            fail(f'the voice read {chunks} chunks for {len(say)} paragraphs; see {out / "tts.err"}')
        src = out / 'tts-raw_corrected.wav'
        src = src if src.exists() else raw

    final = out / 'giong-day-du.wav'
    with steps('3 mastering'):
        r = probe(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(src), '-af', MASTER, '-ar', '48000', '-ac', '1', str(final)])
        if r.returncode:
            fail('ffmpeg mastering failed: ' + r.stderr.strip()[-300:])
        m = probe(['ffmpeg', '-nostats', '-i', str(final), '-af', MASTER.split(',')[-1] + ':print_format=json', '-f', 'null', '-']).stderr
        j = json.loads(re.search(r'\{[^{}]*\}', m[m.rindex('[Parsed_loudnorm'):]).group(0))
        duration = float(probe(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(final)]).stdout)
        if not -16.0 <= float(j['input_i']) <= -14.0 or float(j['input_tp']) > -1.0:
            fail(f"the mastered voice measures {j['input_i']} LUFS, true peak {j['input_tp']} dBTP; the channel's voice is -15 LUFS (-16 to -14), peak at most -1")
        loudness = f"{j['input_i']} LUFS, true peak {j['input_tp']} dBTP, LRA {j['input_lra']}"

    words_path = out / 'whisper-words.json'
    with steps('4 whisper'):
        words_path.unlink(missing_ok=True)
        run([py, '-X', 'utf8', str(Path(__file__).resolve()), '--whisper-only', str(final), str(words_path)], WHISPER_DEADLINE, str(out / 'whisper'), 'Whisper')
        words = json.loads(words_path.read_text(encoding='utf-8'))

    with steps('5 paragraphs'):
        sil = probe(['ffmpeg', '-hide_banner', '-i', str(final), '-af', 'silencedetect=noise=-35dB:d=0.12', '-f', 'null', '-']).stderr
        spans = g.paragraphs_from_silences(sil, duration, len(say))

    with steps('6 gate'):
        rep = g.check_reading(voice, words, spans, approved)
        seg = json.loads(raw_json.read_text(encoding='utf-8')).get('segments', [])
        rep['raw_spans_differ'] = [i + 1 for i, (s, q) in enumerate(zip(spans, seg)) if abs(s['start'] - q['start']) > 0.5 or abs(s['end'] - q['end']) > 0.5]
        rep['steps_s'] = dict(steps.rows)
        g.write_json(out / 'giong-ket-qua.json', rep)

    if rep['problems']:
        print('\n'.join('  ' + p for p in rep['problems']))
        print('\nlisten list so far:\n' + g.format_listen(rep['listen'], rep['approved']))
        fail(f'the voice did not say the script, so no timing file was written (report: {out / "giong-ket-qua.json"}); '
             'change the say text of the paragraph (a respelling) and run again')

    with steps('7 timing'):
        timing = g.build_timing(final.name, 48000, duration, loudness, PAUSE_MS / 1000, spans, words, voice, show)
        g.write_json(out / 'giong-day-du-timing.json', timing)
        text = g.format_listen(rep['listen'], rep['approved'])
        (out / 'nghe-lai.txt').write_text(text + '\n', encoding='utf-8', newline='\n')

    print(f'\nvoice {duration:.2f} s, {loudness}; {rep["words"]} script words, {rep["unmatched"]} not heard ({rep["rate"]:.1%}), longest run {rep["longest_run"]}')
    print(f'beats on the final wav: ' + ', '.join(f'{s["start"]:.2f}-{s["end"]:.2f}' for s in spans))
    if rep['raw_spans_differ']:
        print(f'note: paragraphs {rep["raw_spans_differ"]} differ by more than 0.5 s from the raw synthesis spans (the final wav was measured; look for a paragraph that held a long silence)')
    print('listen list (nghe-lai.txt):\n' + text)
    print('wall time: ' + ', '.join(f'{n} {t} s' for n, t in steps.rows) + f'; total {round(time.time() - steps.t0, 1)} s')
    print(f'timing file: {out / "giong-day-du-timing.json"}')


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--whisper-only':
        whisper_only(sys.argv[2], sys.argv[3])
    else:
        main(sys.argv[1:])
