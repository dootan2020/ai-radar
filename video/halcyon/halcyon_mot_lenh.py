"""Halcyon one command (mot-lenh.py): a script file in, a finished news short and an approval pack out.

Standard library only. This module holds everything that can be tested without audio, a GPU or the network: the script checks, the step
runner (order, stop at the first failure, reuse of finished steps by content hash), the post text, the Vietnamese pack files and the
archive manifest. The real steps (`real_steps`) call the existing tools as subprocesses with deadlines; nothing here changes what they do.
Contract and runbook: MOT-LENH.md."""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TZ = timezone(timedelta(hours=7))   # Asia/Bangkok
FPS = 30
CAPTURE_MAX_AGE_S = 6 * 3600        # a capture older than this is taken again; at render time it is refused
VOICE_PROFILE = 'vhn-giong-tin-ai'
DEADLINES = dict(may=60, giong=20 * 60, anh=5 * 60, dung=10 * 60, nhac=5 * 60)   # seconds; captures: 60 s per attempt, see chup_deadline
BEAT_KINDS = ('capture', 'repo', 'number', 'chart', 'list', 'end')
SOURCE_KEYS = ('urls', 'hco', 'follow', 'occurrence', 'open', 'source', 'date', 'locale', 'ua', 'max_rows')
REPO_SOURCE_KEYS = ('repo', 'branch')   # a source is a page to capture (`urls`) or a GitHub repository to record (`repo`), never both


class Refusal(Exception):
    """The chain stops here: which step, why, and what to change."""

    def __init__(self, step, reason, change=''):
        super().__init__(reason)
        self.step, self.reason, self.change = step, reason, change

    def __str__(self):
        return f'step {self.step}: {self.reason}' + (f'\n  to fix: {self.change}' if self.change else '')


def now_iso():
    return datetime.now(TZ).isoformat(timespec='seconds')


def today_dmy():
    return datetime.now(TZ).strftime('%d/%m/%Y')


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sha_json(obj):
    return sha_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode('utf-8'))


def sha_tree(path):
    """One hash for a folder or a file (names relative to it, then contents); '-' when it does not exist."""
    p = Path(path)
    if not p.exists():
        return '-'
    if p.is_file():
        return sha_file(p)
    return sha_json({str(f.relative_to(p)): sha_file(f) for f in sorted(p.rglob('*')) if f.is_file()})


def write_text(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1) + '\n')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def squash(s):
    return re.sub(r'\s+', ' ', str(s)).strip()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ the script
class Plan:
    """What the checks learned from the script: the sources to capture, the voice text, the warnings."""

    def __init__(self):
        self.refs = {}       # ref -> dict(urls, hco, quote, bands, options)
        self.repos = {}      # ref -> dict(repo, branch, paths (every path opened by any beat, in order), beats [dict(name, open)])
        self.say = []
        self.warnings = []


def need_str(v, where):
    if not isinstance(v, str) or not v.strip():
        raise Refusal('kiem-kich-ban', f'{where} is missing or empty', f'write {where} as text')
    return v


def kich_ban_module():
    return load_module('halcyon_kich_ban', HERE / 'halcyon_kich_ban.py')


def check_repo_source(ref, s):
    where = f'sources["{ref}"]'
    if 'urls' in s:
        raise Refusal('kiem-kich-ban', f'{where} has both "urls" and "repo"', 'a source is either a page to capture ("urls") or a GitHub repository to record ("repo"); split it into two sources')
    extra = [k for k in s if k not in REPO_SOURCE_KEYS]
    if extra:
        raise Refusal('kiem-kich-ban', f'{where} has unknown key(s) {", ".join(extra)}', f'a repo source takes: {", ".join(REPO_SOURCE_KEYS)}')
    bad = kich_ban_module().repo_problem(s['repo'], s.get('branch'))
    if bad:
        raise Refusal('kiem-kich-ban', f'{where}: {bad[0]}', bad[1])


def check_source(ref, s):
    where = f'sources["{ref}"]'
    if not isinstance(s, dict):
        raise Refusal('kiem-kich-ban', f'{where} must be an object', f'give it "urls": ["https://..."] and, if needed, {", ".join(SOURCE_KEYS[1:])}; or "repo": "owner/name" for a repo beat')
    if 'repo' in s:
        return check_repo_source(ref, s)
    if 'branch' in s:
        raise Refusal('kiem-kich-ban', f'{where} has "branch" but no "repo"', 'branch belongs to a repo source: add "repo": "owner/name", or remove it')
    extra = [k for k in s if k not in SOURCE_KEYS]
    if extra:
        raise Refusal('kiem-kich-ban', f'{where} has unknown key(s) {", ".join(extra)}', f'allowed keys: {", ".join(SOURCE_KEYS)}')
    urls = s.get('urls')
    if not isinstance(urls, list) or not urls:
        raise Refusal('kiem-kich-ban', f'{where}.urls is missing', 'list the public page address(es) to capture, in the order to try them')
    for u in urls + ([s['hco']] if s.get('hco') else []):
        p = urlparse(u) if isinstance(u, str) else None
        if not p or p.scheme not in ('http', 'https') or not p.hostname or p.hostname in ('localhost', '127.0.0.1', '::1'):
            raise Refusal('kiem-kich-ban', f'{where}: "{u}" is not a public http(s) address', 'the capture step opens public pages only')
    if 'follow' in s and not isinstance(s['follow'], bool):
        raise Refusal('kiem-kich-ban', f'{where}.follow must be true or false', 'fix the value')
    if 'occurrence' in s and not (s['occurrence'] == 'last' or (isinstance(s['occurrence'], int) and not isinstance(s['occurrence'], bool))):
        raise Refusal('kiem-kich-ban', f'{where}.occurrence must be a number or "last"', 'fix the value')
    if 'date' in s and not re.fullmatch(r'\d{2}/\d{2}/\d{4}', str(s['date'])):
        raise Refusal('kiem-kich-ban', f'{where}.date must read dd/mm/yyyy', 'fix the value')


def check_post(post):
    if not isinstance(post, dict):
        raise Refusal('kiem-kich-ban', 'the script has no "post" block', 'add "post": {"title": ..., "body": ..., "hashtags": ["#AI", ...]} (see KICH-BAN.md)')
    title, body = need_str(post.get('title'), 'post.title'), need_str(post.get('body'), 'post.body')
    tags = post.get('hashtags')
    if not isinstance(tags, list) or not tags or not all(isinstance(t, str) and re.fullmatch(r'#\w+', t) for t in tags):
        raise Refusal('kiem-kich-ban', 'post.hashtags must be a list of tags such as "#AI" (no spaces)', 'fix the list')
    if '\n' in title:
        raise Refusal('kiem-kich-ban', 'post.title has a line break', 'the title is one line')
    lines = [x.rstrip() for x in body.strip().splitlines()]
    if any(not x.strip() for x in lines):
        raise Refusal('kiem-kich-ban', 'post.body has a blank line', 'the post is one block: join the paragraphs with single line breaks')
    for text in [title] + lines:
        if re.search(r'https?://|www\.', text):
            raise Refusal('kiem-kich-ban', f'post text holds a link ("{squash(text)[:60]}")', 'the owner decided on 19/11/2026: no link in the post text')
        if re.match(r'\s*(Nguồn|Source)\s*:', text, re.I):
            raise Refusal('kiem-kich-ban', f'post text holds a source line ("{squash(text)[:60]}")', 'the owner decided on 19/11/2026: no source line in the post text')
        if re.search(r'Kevin MacLeod|incompetech|CC BY|\b(Nhạc|Music)\s*:', text, re.I):
            raise Refusal('kiem-kich-ban', f'post text holds a music credit ("{squash(text)[:60]}")', 'the owner decided on 19/11/2026: no music credit line (he adds it himself)')


def check_repo_beat(plan, sources, b, name):
    """A repo beat: {"kind": "repo", "headline": [...], "repo": {"ref": ..., "open": [...]}}; every refusal here needs no network."""
    S = 'kiem-kich-ban'
    r = b.get('repo')
    if not isinstance(r, dict):
        raise Refusal(S, f'{name} has no "repo" block', 'give it {"ref": ..., "open": ["folder", "folder/file"]} ("open": [] shows the home page only)')
    ref = need_str(r.get('ref'), f'{name}.repo.ref')
    if not re.fullmatch(r'[\w.-]+', ref):
        raise Refusal(S, f'{name}: repo ref "{ref}" may hold letters, digits, dot, dash and underscore only', 'rename the ref')
    src = sources.get(ref)
    if src is None:
        raise Refusal(S, f'{name}: repo "{ref}" has no entry in "sources"', f'add "sources": {{"{ref}": {{"repo": "owner/name"}}}} so the chain knows which repository to record')
    if not isinstance(src, dict) or 'repo' not in src:
        raise Refusal(S, f'{name}: sources["{ref}"] has no "repo"', 'a repo beat records a GitHub repository: write "repo": "owner/name" in the source (a source with "urls" is for capture beats)')
    if 'open' not in r:
        raise Refusal(S, f'{name}.repo.open is missing', 'write the folders and files to open, or [] to show the home page only')
    entries, bad = kich_ban_module().parse_open(r['open'])
    if bad:
        raise Refusal(S, f'{name}: {bad[0]}', bad[1])
    ent = plan.repos.setdefault(ref, dict(paths=[], beats=[]))
    ent['beats'].append(dict(name=name, open=[e['path'] for e in entries]))
    ent['paths'] += [e['path'] for e in entries if e['path'] not in ent['paths']]
    if len(ent['paths']) > kich_ban_module().MAX_OPEN:
        raise Refusal(S, f'{name}: the beats of repo "{ref}" open {len(ent["paths"])} different pages in all; the recorder takes at most {kich_ban_module().MAX_OPEN} besides the home page',
                      'open fewer different folders and files over the beats of this repo')


def check_script(kb):
    """Every refusal that needs no network, voice or GPU. Returns a Plan."""
    S = 'kiem-kich-ban'
    plan = Plan()
    if not isinstance(kb, dict):
        raise Refusal(S, 'the script is not a JSON object', 'see KICH-BAN.md')
    sid = need_str(kb.get('id'), 'id')
    if not re.fullmatch(r'[\w.-]+', sid):
        raise Refusal(S, f'id "{sid}" may hold letters, digits, dot, dash and underscore only', 'fix the id')
    need_str(kb.get('title'), 'title')
    cap = kb.get('tiktok_caption')
    if not (isinstance(cap, list) and cap and all(isinstance(x, str) for x in cap)):
        raise Refusal(S, 'tiktok_caption must be a list of caption lines', 'see KICH-BAN.md')
    paras = kb.get('paragraphs')
    if not isinstance(paras, list) or not paras:
        raise Refusal(S, 'the script has no paragraphs', 'see KICH-BAN.md')
    sources = kb.get('sources', {})
    if not isinstance(sources, dict):
        raise Refusal(S, '"sources" must be an object keyed by capture ref', 'see MOT-LENH.md')
    quotes = {}
    last = None
    for pi, p in enumerate(paras, 1):
        where = f'paragraph {pi}'
        say = need_str(p.get('say') if isinstance(p, dict) else None, f'{where}.say')
        if re.search(r'\n\s*\n', say):
            raise Refusal(S, f'{where}.say has a blank line', 'one paragraph = one voice paragraph: remove the blank line or split the paragraph')
        need_str(p.get('show'), f'{where}.show')
        plan.say.append(say.strip())
        beats = p.get('beats')
        if not isinstance(beats, list) or not beats:
            raise Refusal(S, f'{where} has no beats', 'give it at least one beat')
        for bi, b in enumerate(beats, 1):
            name = f'{where}, beat {bi}' + (f' ("{b["name"]}")' if isinstance(b, dict) and b.get('name') else '')
            kind = b.get('kind') if isinstance(b, dict) else None
            if kind == 'recording' or (isinstance(b, dict) and 'picture' in b):
                raise Refusal(S, f'{name} needs a hand-made recording or photo ("{kind}")',
                              'the one-command chain makes capture beats (a verbatim sentence from a public page) and card beats (number, chart, list, end) only; '
                              'a hand-made recording belongs to the manual lane. Replace the beat with a capture of a page passage or a card')
            if kind not in BEAT_KINDS:
                raise Refusal(S, f'{name} has kind "{kind}"', f'kinds the chain makes: {", ".join(BEAT_KINDS)}')
            last = kind
            if kind == 'repo':
                check_repo_beat(plan, sources, b, name)
                continue
            if kind != 'capture':
                continue
            c = b.get('capture')
            if not isinstance(c, dict):
                raise Refusal(S, f'{name} has no "capture" block', 'give it {"ref": ..., "quote": ...}')
            ref, quote = need_str(c.get('ref'), f'{name}.capture.ref'), squash(need_str(c.get('quote'), f'{name}.capture.quote'))
            if not re.fullmatch(r'[\w.-]+', ref):
                raise Refusal(S, f'{name}: capture ref "{ref}" may hold letters, digits, dot, dash and underscore only', 'rename the ref')
            if isinstance(sources.get(ref), dict) and 'repo' in sources[ref]:
                raise Refusal(S, f'{name}: capture "{ref}" is a repo source', 'a capture takes a page address ("urls"); to show the repository use a repo beat, or give this capture its own source')
            if ref not in sources:
                raise Refusal(S, f'{name}: capture "{ref}" has no entry in "sources"', f'add "sources": {{"{ref}": {{"urls": ["https://..."]}}}} so the chain knows which page to capture')
            if quotes.setdefault(ref, quote) != quote:
                raise Refusal(S, f'capture ref "{ref}" is used with two different quotes', 'one ref is one picture of one sentence: give the second beat its own ref')
            ent = plan.refs.setdefault(ref, dict(quote=quote, bands=[]))
            for bd in c.get('bands', []):
                t = need_str(bd.get('text') if isinstance(bd, dict) else None, f'{name}.capture.bands[].text')
                if t not in ent['bands']:
                    ent['bands'].append(t)
    if last != 'end':
        raise Refusal(S, 'the last beat is not {"kind": "end"}', 'finish the script with an end beat')
    for ref, ent in plan.refs.items():
        check_source(ref, sources[ref])
        s = sources[ref]
        ent.update(urls=list(s['urls']), hco=s.get('hco'), options={k: s[k] for k in SOURCE_KEYS[2:] if k in s})
    for ref, ent in plan.repos.items():
        check_source(ref, sources[ref])
        ent.update(repo=sources[ref]['repo'], branch=sources[ref].get('branch'))
    for ref in sources:
        if ref not in plan.refs and ref not in plan.repos:
            plan.warnings.append(f'sources["{ref}"] is not used by any capture beat')
    check_post(kb.get('post'))
    return plan


def post_text(post):
    """The text the owner posts with a video, in his format (decision of 19/11/2026): one block, no source line, no link, no music credit."""
    body = '\n'.join(x.rstrip() for x in post['body'].strip().splitlines())
    return f'Tiêu đề:\n{post["title"].strip()}\nNội dung đăng:\n{body}\n{" ".join(post["hashtags"])}\n'


# ------------------------------------------------------------------ settings
def settings(env=None, which=shutil.which, exists=lambda p: Path(p).exists()):
    """The tools and settings the steps need; returns (problems, resolved). Every problem names the setting and what to do."""
    env = os.environ if env is None else env
    problems, res = [], {}
    default_py = str(Path(env.get('USERPROFILE', '~')) / '.venvs' / 'halcyon-gpu' / 'Scripts' / 'python.exe')
    res['gpu_python'] = env.get('HALCYON_PYTHON') or default_py
    if not exists(res['gpu_python']):
        problems.append(f'HALCYON_PYTHON: the GPU interpreter "{res["gpu_python"]}" does not exist; set HALCYON_PYTHON to the Python with torch (CUDA)')
    res['omnivoice_python'] = env.get('HALCYON_OMNIVOICE_PYTHON', '')
    if not res['omnivoice_python'] or not exists(res['omnivoice_python']):
        problems.append('HALCYON_OMNIVOICE_PYTHON: set it to the Python that has OmniVoice and faster-whisper (see GIONG.md)')
    prof = env.get('HALCYON_VOICE_PROFILES', '')
    if not prof or not exists(Path(prof) / VOICE_PROFILE / 'reference.wav'):
        problems.append(f'HALCYON_VOICE_PROFILES: set it to the folder that holds the profile folder {VOICE_PROFILE} (profile.toml, reference.wav; see GIONG.md)')
    res['profiles'] = prof
    track = env.get('HALCYON_MUSIC_TRACK') or str(HERE / 'music' / 'Voice Over Under.mp3')
    if not exists(track):
        problems.append(f'HALCYON_MUSIC_TRACK: the music track "{track}" does not exist; set HALCYON_MUSIC_TRACK to the "Voice Over Under" mp3 (see README.md)')
    res['music'] = track
    for tool in ('ffmpeg', 'ffprobe', 'node', 'magick'):
        if not which(tool):
            problems.append(f'{tool} is not on PATH')
    res['playwright'] = REPO / 'video' / ('node' + '_modules') / 'playwright-core' / 'package.json'
    if not exists(res['playwright']):
        problems.append('playwright-core is not installed: run `npm install` inside video/ (no lock file is committed; see CHUP.md)')
    return problems, res


# ------------------------------------------------------------------ running tools
def kill_tree(p):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)
    else:
        p.kill()


def tail(text, n=10):
    return '\n    '.join([x for x in text.strip().splitlines() if x.strip()][-n:])


def run_process(cmd, deadline, log, env=None, cwd=None, step='?'):
    """Run a tool with a deadline; stdout and stderr go to <log>.out / <log>.err. Overrun: kill the whole tree, keep the log, stop.
    Returns (exit code, stdout, stderr)."""
    Path(log).parent.mkdir(parents=True, exist_ok=True)
    e = dict(os.environ if env is None else env, PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    with open(f'{log}.out', 'wb') as out, open(f'{log}.err', 'wb') as err:
        p = subprocess.Popen([str(c) for c in cmd], stdout=out, stderr=err, env=e, cwd=cwd)
        try:
            p.wait(timeout=deadline)
        except subprocess.TimeoutExpired:
            kill_tree(p)
            p.wait()
            out.flush(), err.flush()
            t = Path(f'{log}.err').read_text(encoding='utf-8', errors='replace') or Path(f'{log}.out').read_text(encoding='utf-8', errors='replace')
            raise Refusal(step, f'ran over its {deadline:g} second deadline and was killed; the log is kept at {log}.err; last lines:\n    {tail(t, 6)}',
                          'run the command again; if it repeats, tell the coordinator (the log shows where it stuck)')
    rd = lambda s: Path(f'{log}.{s}').read_text(encoding='utf-8', errors='replace')
    return p.returncode, rd('out'), rd('err')


WARN_RE = re.compile(r'(?i)warn|not gated|not drawn|not measured|under 4\.5|refus|skipp|\bnote\b|\bnotes?:')


def warnings_in(text):
    """The lines of a tool's output that are warnings: by wording, as documented in MOT-LENH.md."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.search(r'unit notes: \{\s*\}|unit notes: \[\s*\]|unit notes: None', s):
            continue
        if WARN_RE.search(s):
            out.append(s)
    return out


# ------------------------------------------------------------------ the chain
class Step:
    """name; run(ctx) -> list of warnings (or None); inputs(ctx) -> JSON-able dict that decides reuse; outputs(ctx) -> files that must exist;
    always=True: runs every time (cheap); valid(ctx) -> False forces a re-run even when the inputs are unchanged."""

    def __init__(self, name, run, inputs=None, outputs=None, always=False, valid=None, what=''):
        self.name, self.run, self.inputs, self.outputs, self.always, self.valid, self.what = name, run, inputs, outputs, always, valid, what


class Chain:
    def __init__(self, state_path, say=print):
        self.state_path, self.say = Path(state_path), say
        self.state = load_json(self.state_path) if self.state_path.exists() else {'steps': {}}
        self.rows = []      # (name, 'run'|'reused', seconds, warnings, note)
        self.t0 = time.time()

    def save(self):
        write_json(self.state_path, self.state)

    def go(self, steps, ctx):
        for st in steps:
            digest = None
            try:
                if st.inputs and not st.always:
                    digest = sha_json(st.inputs(ctx))
                old = self.state['steps'].get(st.name)
                outs = [Path(p) for p in (st.outputs(ctx) if st.outputs else [])]
                if (old and digest and old.get('digest') == digest and all(p.exists() for p in outs) and (not st.valid or st.valid(ctx))):
                    self.rows.append((st.name, 'reused', old['seconds'], old.get('warnings', []), f'inputs unchanged since {old["finished"]}'))
                    self.say(f'[{st.name}] reused (inputs unchanged; it took {old["seconds"]} s on {old["finished"]})')
                    continue
                self.state['steps'].pop(st.name, None)
                self.save()
                self.say(f'[{st.name}] {st.what or ""} ...')
                t = time.time()
                warns = [str(w) for w in (st.run(ctx) or [])]
                secs = round(time.time() - t, 1)
                missing = [str(p) for p in outs if not Path(p).exists()]
                if missing:
                    raise Refusal(st.name, f'it finished but did not write {", ".join(missing)}', 'tell the coordinator')
            except Refusal as r:
                if r.step in ('?', None):
                    r.step = st.name
                raise
            except Exception as e:
                raise Refusal(st.name, f'unexpected {type(e).__name__}: {e}', 'tell the coordinator; this is a bug in the command, not in the script')
            self.rows.append((st.name, 'run', secs, warns, ''))
            self.say(f'[{st.name}] {secs} s' + (f', {len(warns)} warning(s)' if warns else ''))
            for w in warns:
                self.say(f'    warning: {w}')
            if digest:
                self.state['steps'][st.name] = dict(digest=digest, seconds=secs, warnings=warns, finished=now_iso())
                self.save()
        return self.rows

    def total(self):
        return round(time.time() - self.t0, 1)


# ------------------------------------------------------------------ the listen list, the pack
def listen_text(rep, g):
    """nghe-lai.txt: what the owner must hear, in Vietnamese. rep is giong-ket-qua.json."""
    body = g.format_listen(rep.get('listen', []), rep.get('approved'))
    head = ('Nghe lại những chỗ này trong video (số giây tính từ đầu video). Máy chỉ chứng minh được từ đó có được nói ra, '
            'không chứng minh được nói có đúng không: chỉ tai anh biết.\n')
    if not body.strip():
        return head + '\nKhông có chỗ nào cần nghe riêng. Vẫn nên nghe cả video một lần.\n'
    return head + '\n' + body + '\n'


def safe_name(s, limit=80):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', squash(s)).strip(' .')
    return s[:limit].rstrip(' .')


def archive_manifest(c):
    """luu-tru.json for the video archive tool luu-tru-video.py: every item waits for the owner (`cho_duyet`); `--duyet` archives all."""
    sid, pre = c['id'], f'halcyon-{c["id"]}-'
    pk = 'goi-duyet/'
    items = [
        dict(nguon=pk + c['final_mp4'], dich='1 - Video đăng', ten=pre + c['slug'] + '-co-nhac.mp4'),
        dict(nguon=pk + c['plain_mp4'], dich='1 - Video đăng/Bản không nhạc (dự phòng)', ten=pre + c['slug'] + '.mp4'),
        dict(nguon=pk + c['post_file'], dich='2 - Nội dung đăng', ten=pre + 'noi-dung-dang.txt'),
        dict(nguon='cong-viec/giong/giong-day-du.wav', dich='3 - Âm thanh', ten=pre + 'giong-doc.wav'),
        dict(nguon='cong-viec/giong/giong-day-du-timing.json', dich='4 - Kịch bản và phụ đề', ten=pre + 'giong-doc-timing.json'),
        dict(nguon='cong-viec/giong/loi-doc-tts.txt', dich='4 - Kịch bản và phụ đề', ten=pre + 'loi-doc-tts.txt'),
        dict(nguon='cong-viec/giong/loi-hien-thi.txt', dich='4 - Kịch bản và phụ đề', ten=pre + 'loi-doc-hien-thi.txt'),
        dict(nguon='cong-viec/kich-ban.json', dich='4 - Kịch bản và phụ đề', ten=pre + 'kich-ban.json'),
        dict(nguon='cong-viec/dung/video-stills', dich='5 - Hình ảnh/Khung hình bản cuối', tien_to=pre),
        dict(nguon='cong-viec/nguon.txt', dich='6 - Nguồn', ten=pre + 'nguon.txt'),
        dict(nguon='cong-viec/chup/*/*', dich='6 - Nguồn/anh-chup-bai-goc', tien_to=pre),
        dict(nguon=pk + 'xem-truoc-dien-thoai/' + c['tiktok_mp4'], dich='7 - Thông số dựng', ten=pre + 'ban-xem-truoc-giao-dien-tiktok.mp4'),
        dict(nguon='cong-viec/dung/video.json', dich='7 - Thông số dựng', ten=pre + 'video.json'),
        dict(nguon='cong-viec/dung/video-plan.json', dich='7 - Thông số dựng', ten=pre + 'video-plan.json'),
        dict(nguon='cong-viec/dung/video-render.json', dich='7 - Thông số dựng', ten=pre + 'video-render.json'),
        dict(nguon='cong-viec/nhac/' + c['music_json'], dich='7 - Thông số dựng', ten=pre + 'nhac.json'),
        dict(nguon=pk + 'tom-tat.md', dich='7 - Thông số dựng', ten=pre + 'tom-tat-mot-lenh.md'),
    ]
    for it in items:
        it['cho_duyet'] = True
    try:
        so = int(re.sub(r'\D', '', sid) or 0)
    except ValueError:
        so = 0
    return dict(so=so, ngay=c['date_iso'], ten=c['title'], loai='Tin AI, video đơn', chu_de='', thoi_luong=c['duration_text'],
                trang_thai='Chờ anh duyệt', trang_thai_da_duyet='Đã duyệt, chưa đăng', duyet=False,
                thu_muc=f'{sid} - {c["date_iso"]} - {safe_name(c["title"])}', goc=c['run_dir'],
                ghi_chu='Gói duyệt do mot-lenh.py dựng; chưa đăng. Anh duyệt xong thì chạy lại luu-tru-video.py với --duyet.', muc=items)


def summary_texts(c):
    """tom-tat.md (Vietnamese, the owner's part first) and the same facts as a dict for tom-tat.json."""
    rows = c['rows']
    n_listen = c['listen_count']
    L = [f'# Halcyon {c["id"]}: {c["title"]}', '',
         '## Anh duyệt trong một phút', '',
         f'1. Xem `{c["final_mp4"]}` ({c["duration_text"]}, có nhạc).',
         f'2. Nghe lại {n_listen} chỗ trong `nghe-lai.txt`. Máy không nghe được giọng đọc: chỉ tai anh biết tên riêng và con số đọc đúng hay sai.' if n_listen else
         '2. Máy không nghe được giọng đọc nên không có gì để chỉ cho anh. Anh vẫn nên nghe cả video một lần (`nghe-lai.txt`).',
         '3. Liếc `anh-tong-quan.jpg` (mọi cảnh) và ảnh trong `xem-truoc-dien-thoai/` (cảnh trên khung TikTok).',
         f'4. Đọc `{c["post_file"]}`: đó là chữ sẽ đăng kèm.',
         '5. Duyệt thì lưu trữ bằng một lệnh (chưa đăng, chưa lưu gì cho tới khi chạy):', '',
         f'       {c["archive_cmd"]}', '',
         '## Video nói gì', ''] + [f'{i}. {s}' for i, s in enumerate(c['say'], 1)] + ['',
         '## Máy đã kiểm', '',
         '- Giọng đọc nói đủ kịch bản (Whisper nghe lại: cổng đọc đúng, số đoạn khớp), độ to -15 LUFS.',
         '- Mỗi ảnh chụp trang gốc đúng là câu trích nguyên văn, chụp trong vòng 6 giờ trước khi dựng.',
         '- Chữ, màu tương phản, khung an toàn: bộ dựng từ chối nếu sai. Video dài đúng số khung, có hình và tiếng; nhạc trộn không đổi hình, độ to lệch dưới 0,3 LU.', '',
         '## Máy chưa kiểm được', '',
         '- Giọng đọc nghe có đúng và tự nhiên không (tên riêng, con số): xem `nghe-lai.txt`.',
         '- Trang gốc có nói đúng điều video kể không, và có còn mới không: ảnh chụp chứng minh câu đó có trên trang, không chứng minh bài đó đúng.', '',
         '## Các bước', '', '| bước | trạng thái | giây |', '| --- | --- | --- |']
    for name, status, secs, warns, note in rows:
        L.append(f'| {name} | {"chạy" if status == "run" else "dùng lại"} | {secs if status == "run" else str(secs) + " (lần trước)"} |')
    L += ['', f'Tổng: {c["total_s"]} giây.', '', '## Cảnh báo', '']
    grouped = {}
    for n, st, _, ws_, _ in rows:
        for w in ws_:
            grouped.setdefault(w, []).append(n + (' (từ lần chạy trước)' if st == 'reused' else ''))
    L += [f'- [{", ".join(ns)}] {w}' for w, ns in grouped.items()] or ['- Không có.']
    L += ['', '## Nguồn đã chụp', '']
    L += [f'- `{s["ref"]}`: {s["url"]} (HTTP {s["http"]}, chụp {s["captured"]})' for s in c['sources']] or ['- Không có cảnh chụp trang.']
    L += ['', '## Mã băm đầu vào (SHA-256)', '']
    L += [f'- {k}: `{v}`' for k, v in c['hashes'].items()]
    L += ['', '## Kiểm file cuối', '', f'- ffprobe: {c["probe_text"]}', f'- nhạc: {c["music_text"]}', '']
    data = dict(id=c['id'], title=c['title'], made=now_iso(), total_s=c['total_s'], steps=[dict(step=n, status=st, seconds=s, warnings=w, note=nt) for n, st, s, w, nt in rows],
                sources=c['sources'], hashes=c['hashes'], probe=c['probe'], music=c['music_text'], archive_command=c['archive_cmd'], listen_count=n_listen)
    return '\n'.join(L), data


# ------------------------------------------------------------------ render check
def check_render(facts, duration, fps=FPS):
    """Problems with a rendered mp4: facts from ffprobe_facts()."""
    total = round(duration * fps)
    p = []
    v, a = facts.get('video'), facts.get('audio')
    if not v:
        return ['the mp4 has no video stream']
    if (v['width'], v['height']) != (1080, 1920):
        p.append(f'the picture is {v["width"]}x{v["height"]}, not 1080x1920')
    if v['frames'] != total:
        p.append(f'the video has {v["frames"]} frames, the script\'s {duration} s at {fps} fps is {total}')
    if not a:
        p.append('the mp4 has no audio stream')
    if abs(facts['duration'] - duration) > 0.1:
        p.append(f'the mp4 lasts {facts["duration"]:.2f} s, not {duration} s')
    return p


def ffprobe_facts(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_entries', 'stream=codec_type,codec_name,width,height,nb_read_frames:format=duration',
                        '-of', 'json', str(path)], capture_output=True, text=True, encoding='utf-8', timeout=120)
    if r.returncode:
        raise Refusal('dung', f'ffprobe cannot read {path}: {r.stderr.strip()[-200:]}', 'tell the coordinator')
    j = json.loads(r.stdout)
    v = next((s for s in j['streams'] if s['codec_type'] == 'video'), None)
    a = next((s for s in j['streams'] if s['codec_type'] == 'audio'), None)
    return dict(video=v and dict(codec=v['codec_name'], width=v['width'], height=v['height'], frames=int(v['nb_read_frames'])),
                audio=a and dict(codec=a['codec_name']), duration=float(j['format']['duration']))


def probe_text(f):
    v, a = f['video'], f['audio']
    return f'{v["codec"]} {v["width"]}x{v["height"]}, {v["frames"]} khung, {f["duration"]:.2f} s; tiếng {a["codec"] if a else "KHÔNG CÓ"}'


# ------------------------------------------------------------------ the real steps
class Ctx:
    """Paths and facts shared by the steps of one run."""

    def __init__(self, script, run_dir, plan, kb, cfg):
        self.script_in, self.kb, self.plan, self.cfg = Path(script), kb, plan, cfg
        self.run = Path(run_dir).resolve()
        self.work = self.run / 'cong-viec'
        self.pack = self.run / 'goi-duyet'
        self.logs = self.work / 'nhat-ky'
        self.script = self.work / 'kich-ban.json'
        self.chup, self.giong, self.dung, self.nhac = (self.work / x for x in ('chup', 'giong', 'dung', 'nhac'))
        self.spec = self.dung / 'video.json'
        self.chain_rows, self.chain_total = (lambda: []), (lambda: 0.0)


def tool_hashes(*names):
    return {n: sha_file(HERE / n) for n in names}


def chup_deadline(urls, hco):
    return 60 * 2 * (len(urls) + (1 if hco else 0)) + 30   # 60 s per attempt, two attempts per address, as chup.mjs does


def capture_info(ctx, ref):
    return load_json(ctx.chup / ref / f'{ref}.capture.json')


def capture_age_ok(ctx, ref, now=None):
    try:
        t = datetime.fromisoformat(capture_info(ctx, ref)['entry']['captured'])
    except (OSError, KeyError, ValueError):
        return False
    return ((now or datetime.now(TZ)) - t).total_seconds() <= CAPTURE_MAX_AGE_S


def step_may(ctx):
    problems = []
    py = [ctx.cfg['gpu_python'], '-I', '-X', 'utf8', '-c',
          'import torch,sys; sys.exit(0 if torch.cuda.is_available() else 3)']
    code, _, err = run_process(py, DEADLINES['may'], ctx.logs / 'may-cuda', step='kiem-may')
    if code:
        problems.append('the GPU interpreter cannot use CUDA (torch.cuda.is_available() is false): ' + (tail(err, 2) or 'no output'))
    code, out, _ = run_process(['ffmpeg', '-hide_banner', '-encoders'], 30, ctx.logs / 'may-nvenc', step='kiem-may')
    if 'h264_nvenc' not in out:
        problems.append('ffmpeg has no h264_nvenc encoder (the builder renders on the GPU only)')
    if problems:
        raise Refusal('kiem-may', '; '.join(problems), 'the chain renders on the GPU only (no CPU fallback); fix the machine, not the script')
    return []


def step_chup(ctx, ref):
    e = ctx.plan.refs[ref]
    out = ctx.chup / ref
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    job = dict(urls=e['urls'], quote=e['quote'], ref=ref, out=str(out), bands=e['bands'], hco=e['hco'])
    o = e['options']
    for src, dst in (('follow', 'follow'), ('occurrence', 'occurrence'), ('open', 'open'), ('source', 'source'), ('date', 'date'), ('locale', 'locale'), ('ua', 'ua'), ('max_rows', 'maxRows')):
        if src in o:
            job[dst] = o[src]
    job = {k: v for k, v in job.items() if v not in (None, [])}
    write_json(out / 'job.json', job)
    code, so, se = run_process(['node', HERE / 'chup.mjs', '--job', out / 'job.json'], chup_deadline(e['urls'], e['hco']), ctx.logs / f'chup-{ref}', step=f'chup:{ref}')
    if code:
        raise Refusal(f'chup:{ref}', f'the page does not show the sentence (exit {code}):\n    {tail(se, 8)}',
                      f'check the address(es) in sources["{ref}"].urls and that capture.quote of the beat is a sentence the page shows word for word '
                      f'(add "open": "<heading>" for a folded section, "occurrence" for a sentence that appears twice, or a fallback address)')
    info = json.loads(so)
    return [f'{t["url"]}: {t["kind"]}: {t["why"]} (tried again or fell back)' for t in info.get('trail', []) if not t['ok']]


def merged_captures(ctx):
    """The manifest the assembler reads: every ref of the script, picture paths relative to the spec's folder."""
    caps = {}
    for ref in ctx.plan.refs:
        ent = capture_info(ctx, ref)['entry']
        ent = dict(ent, file=os.path.relpath(ctx.chup / ref / ent['file'], ctx.dung).replace('\\', '/'))
        caps[ref] = ent
    return dict(captures=caps)


def step_lap_rap(ctx):
    ctx.dung.mkdir(parents=True, exist_ok=True)
    write_json(ctx.chup / 'captures.json', merged_captures(ctx))
    cmd = [sys.executable, '-X', 'utf8', HERE / 'halcyon_kich_ban.py', ctx.script, '--timing', ctx.giong / 'giong-day-du-timing.json', '--out', ctx.spec]
    if ctx.plan.refs:
        cmd += ['--captures', ctx.chup / 'captures.json']
    code, so, se = run_process(cmd, 120, ctx.logs / 'lap-rap', step='lap-rap')
    if code:
        raise Refusal('lap-rap', (tail(se, 8) or tail(so, 8)),
                      'the assembler\'s message names the beat, the field or the words; change the script (captions, anchors, quotes, kickers), not the tools. '
                      'The voice is kept: only a change to a `say` text makes it again')
    return warnings_in(so)


def builder_inputs(ctx):
    spec = load_json(ctx.spec)
    base = ctx.dung
    files = {k: sha_file(base / spec[k]) for k in ('voice',) if (base / spec[k]).exists()}
    tm = load_json(base / spec['timing'])
    files['timing'] = sha_json({k: tm.get(k) for k in ('file', 'duration_s', 'words_whisper_medium')} | {'beats': [(b['start'], b['end']) for b in tm.get('beats', [])]})
    pics = {}
    for b in spec.get('beats', []):
        for lay in ([b.get('picture')] if b.get('picture') else []):
            if isinstance(lay, dict) and lay.get('file'):
                pics[lay['file']] = sha_file(base / lay['file'])
    return dict(spec=sha_file(ctx.spec), files=files, pictures=pics,
                builder=tool_hashes('dung-video-gpu.py', 've_halcyon.py', 'halcyon_spec.py'), fonts=sha_tree(HERE / 'fonts'),
                brand=[sha_tree(REPO / 'brand' / 'fonts'), sha_tree(REPO / 'brand' / 'logo' / 'coral-tile' / 'logos')])


def builder_env(ctx):
    tmp = ctx.work / 'tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    return dict(os.environ, TEMP=str(tmp), TMP=str(tmp))


def step_anh(ctx):
    cmd = [ctx.cfg['gpu_python'], '-I', '-X', 'utf8', HERE / 'dung-video-gpu.py', ctx.spec, '--stills']
    code, so, se = run_process(cmd, DEADLINES['anh'], ctx.logs / 'anh', env=builder_env(ctx), cwd=ctx.dung, step='anh')
    if code:
        raise Refusal('anh', tail(se, 10) or tail(so, 10),
                      'the builder\'s message names the beat, the text or the rule (contrast, safe frame, glyph, chip); change the script text or the quote band, not the builder')
    return warnings_in(so) + warnings_in(se)


def step_kiem_anh(ctx):
    d = ctx.dung / 'video-stills'
    for f in ('contact-sheet.jpg', 'phone-size-390.png'):
        if not (d / f).exists() or (d / f).stat().st_size < 1000:
            raise Refusal('kiem-anh', f'the stills folder has no {f}', 'tell the coordinator')
    if not list(d.glob('*-tt.jpg')):
        raise Refusal('kiem-anh', 'the stills folder has no TikTok-overlay preview', 'tell the coordinator')
    stale = [r for r in ctx.plan.refs if not capture_age_ok(ctx, r)]
    if stale:
        raise Refusal('kiem-anh', f'capture(s) {", ".join(stale)} are older than {CAPTURE_MAX_AGE_S // 3600} hours or have no time', 'run the command again: stale captures are taken again')
    return []


def step_dung(ctx):
    cmd = [ctx.cfg['gpu_python'], '-I', '-X', 'utf8', HERE / 'dung-video-gpu.py', ctx.spec, '--render']
    code, so, se = run_process(cmd, DEADLINES['dung'], ctx.logs / 'dung', env=builder_env(ctx), cwd=ctx.dung, step='dung')
    if code:
        raise Refusal('dung', tail(se, 10) or tail(so, 10), 'the builder\'s message names the cause; tell the coordinator if it is not about the script')
    spec = load_json(ctx.spec)
    bad = []
    for key in ('clean', 'tiktok'):
        for pr in check_render(ffprobe_facts(ctx.dung / spec['out'][key]), spec['duration']):
            bad.append(f'{spec["out"][key]}: {pr}')
    if bad:
        raise Refusal('dung', '; '.join(bad), 'tell the coordinator: the render does not match the script')
    return warnings_in(so) + warnings_in(se)


def nhac_path(ctx, spec=None):
    spec = spec or load_json(ctx.spec)
    return ctx.nhac / (Path(spec['out']['clean']).stem + '-co-nhac.mp4')


def step_nhac(ctx):
    spec = load_json(ctx.spec)
    ctx.nhac.mkdir(parents=True, exist_ok=True)
    out = nhac_path(ctx, spec)
    env = dict(os.environ, HALCYON_MUSIC_TRACK=ctx.cfg['music'])
    code, so, se = run_process([sys.executable, '-X', 'utf8', HERE / 'tron-nhac.py', ctx.dung / spec['out']['clean'], '--out', out], DEADLINES['nhac'], ctx.logs / 'nhac', env=env, step='nhac')
    if code:
        raise Refusal('nhac', tail(se, 6) or tail(so, 6), 'the music step refuses when the picture, length or loudness would change; tell the coordinator')
    write_text(ctx.nhac / 'nhac-ket-qua.txt', so)
    return warnings_in(so) + warnings_in(se)


def step_goi(ctx):
    g = load_module('halcyon_giong_pack', HERE / 'halcyon_giong.py')
    spec = load_json(ctx.spec)
    rep = load_json(ctx.giong / 'giong-ket-qua.json')
    clean, tt = ctx.dung / spec['out']['clean'], ctx.dung / spec['out']['tiktok']
    final = nhac_path(ctx, spec)
    if ctx.pack.exists():
        shutil.rmtree(ctx.pack)
    pv = ctx.pack / 'xem-truoc-dien-thoai'
    pv.mkdir(parents=True)
    names = dict(final=final.name, plain=f'{clean.stem}-khong-nhac.mp4', tiktok=tt.name, post='noi-dung-dang.txt')
    shutil.copy2(final, ctx.pack / names['final'])
    shutil.copy2(clean, ctx.pack / names['plain'])
    shutil.copy2(tt, pv / names['tiktok'])
    shutil.copy2(ctx.dung / 'video-stills' / 'contact-sheet.jpg', ctx.pack / 'anh-tong-quan.jpg')
    for f in sorted((ctx.dung / 'video-stills').glob('*-tt.jpg')) + [ctx.dung / 'video-stills' / 'phone-size-390.png']:
        shutil.copy2(f, pv / f.name)
    write_text(ctx.pack / names['post'], post_text(ctx.kb['post']))
    write_text(ctx.pack / 'nghe-lai.txt', listen_text(rep, g))
    # sources
    srcs = []
    for ref in ctx.plan.refs:
        i = capture_info(ctx, ref)
        srcs.append(dict(ref=ref, url=i['url'], http=i['http'], captured=i['entry']['captured'], picture=i['entry']['file'], matched=i.get('matched')))
    write_text(ctx.work / 'nguon.txt', ''.join(f'{s["ref"]}\t{s["url"]}\tHTTP {s["http"]}\tchụp {s["captured"]}\n' for s in srcs))
    fm, pm = ffprobe_facts(final), ffprobe_facts(clean)
    bad = check_render(fm, spec['duration'])
    if bad:
        raise Refusal('goi', 'the final mp4: ' + '; '.join(bad), 'tell the coordinator')
    music = (ctx.nhac / 'nhac-ket-qua.txt').read_text(encoding='utf-8').strip().splitlines()
    hashes = {'script (kich-ban.json)': sha_file(ctx.script), 'say texts': sha_json(ctx.plan.say), 'voice wav': sha_file(ctx.giong / 'giong-day-du.wav'),
              'timing file': sha_file(ctx.giong / 'giong-day-du-timing.json'), 'video.json': sha_file(ctx.spec)}
    for ref in ctx.plan.refs:
        hashes[f'capture {ref} (picture)'] = sha_file(ctx.chup / ref / capture_info(ctx, ref)['entry']['file'])
    hashes['mp4 no music'] = sha_file(clean)
    hashes['mp4 with music'] = sha_file(final)
    slug = Path(spec['out']['clean']).stem[len(spec['name']) + 1:]
    mins = spec['duration']
    c = dict(id=ctx.kb['id'], title=ctx.kb['title'], date_iso=datetime.now(TZ).strftime('%Y-%m-%d'), run_dir=str(ctx.run), slug=slug,
             final_mp4=names['final'], plain_mp4=names['plain'], tiktok_mp4=names['tiktok'], post_file=names['post'], music_json=final.with_suffix('.json').name,
             duration_text=f'{mins:g} s'.replace('.', ','), say=ctx.plan.say, listen_count=len(rep.get('listen', [])), sources=srcs, hashes=hashes,
             probe=dict(final=fm, plain=pm), probe_text=probe_text(fm), music_text=(music[1].strip() if len(music) > 1 else ' '.join(music).strip()) or '(không đọc được)',
             rows=ctx.chain_rows(), total_s=ctx.chain_total(),
             archive_cmd=f'py -3.12 "<kho video>\\_he-thong\\luu-tru-video.py" "{ctx.pack / "luu-tru.json"}" --duyet')
    write_json(ctx.pack / 'luu-tru.json', archive_manifest(c))
    md, data = summary_texts(c)
    write_text(ctx.pack / 'tom-tat.md', md)
    write_json(ctx.pack / 'tom-tat.json', data)
    return []


def real_steps(ctx):
    """The steps in order, cheapest refusals first."""
    steps = [Step('kiem-kich-ban', lambda c: [], always=True, what='checking the script'),
             Step('kiem-may', step_may, inputs=lambda c: {'py': c.cfg['gpu_python']}, always=True, what='checking the GPU and the encoder')]
    for ref in ctx.plan.refs:
        e = ctx.plan.refs[ref]
        steps.append(Step(f'chup:{ref}', lambda c, r=ref: step_chup(c, r),
                          inputs=lambda c, r=ref, e=e: dict(urls=e['urls'], hco=e['hco'], quote=e['quote'], bands=e['bands'], options=e['options'], tool=tool_hashes('chup.mjs')),
                          outputs=lambda c, r=ref: [c.chup / r / f'{r}.capture.json', c.chup / r / f'{r}.png'],
                          valid=lambda c, r=ref: capture_age_ok(c, r), what=f'capturing {ref}'))
    voice_inputs = lambda c: dict(say=c.plan.say, approved=sha_file(HERE / 'giong-da-nghe.txt'), tools=tool_hashes('lam-giong.py', 'halcyon_giong.py'),
                                  tts=sha_file(HERE.parent / 'scripts' / 'omnivoice_tts.py'),
                                  reference=sha_file(Path(c.cfg['profiles']) / VOICE_PROFILE / 'reference.wav'))
    steps.append(Step('giong', step_giong, inputs=voice_inputs, what='making the voice (about four minutes)',
                      outputs=lambda c: [c.giong / 'giong-day-du.wav', c.giong / 'giong-day-du-timing.json', c.giong / 'giong-ket-qua.json']))
    steps += [Step('lap-rap', step_lap_rap, always=True, what='assembling the spec'),
              Step('anh', step_anh, inputs=builder_inputs, what='drawing the stills', outputs=lambda c: [c.dung / 'video-stills' / 'contact-sheet.jpg', c.dung / 'video-plan.json']),
              Step('kiem-anh', step_kiem_anh, always=True, what='checking the stills and the age of the captures'),
              Step('dung', step_dung, inputs=builder_inputs, what='rendering on the GPU',
                   outputs=lambda c: [c.dung / load_json(c.spec)['out'][k] for k in ('clean', 'tiktok')] + [c.dung / 'video-render.json']),
              Step('nhac', step_nhac, inputs=lambda c: dict(video=sha_file(c.dung / load_json(c.spec)['out']['clean']), track=sha_file(c.cfg['music']), tool=tool_hashes('tron-nhac.py')),
                   what='mixing the music bed', outputs=lambda c: [nhac_path(c)]),
              Step('goi', step_goi, always=True, what='building the approval pack')]
    return steps


def step_giong(ctx):
    cmd = [sys.executable, '-X', 'utf8', HERE / 'lam-giong.py', ctx.script, '--out', ctx.giong]
    code, so, se = run_process(cmd, DEADLINES['giong'], ctx.logs / 'giong', step='giong')
    if code:
        lines = [x for x in so.splitlines() if x.startswith('  ')]
        raise Refusal('giong', (tail(se, 8) + ('\n    ' + '\n    '.join(lines[:8]) if lines else '')).strip(),
                      'change the `say` text of the paragraph the message names (a respelling of the name or number it did not say); only a changed `say` makes the voice again')
    return warnings_in(so) + warnings_in(se)


# ------------------------------------------------------------------ the command
def main(argv, say=print):
    import argparse
    ap = argparse.ArgumentParser(description='From a Halcyon script file to a finished short and an approval pack (see MOT-LENH.md).')
    ap.add_argument('script')
    ap.add_argument('--out', required=True, help='the run folder: <out>/cong-viec (work, reuse state, logs) and <out>/goi-duyet (the approval pack)')
    ap.add_argument('--chi-kiem', action='store_true', help='only check the script and the settings, then stop')
    a = ap.parse_args(argv)
    t0 = time.time()
    try:
        kb = json.loads(Path(a.script).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        say(f'mot-lenh: step kiem-kich-ban: cannot read {a.script}: {e}')
        return 2
    run_dir = Path(a.out).resolve()
    chain = None
    try:
        plan = check_script(kb)
        problems, cfg = settings()
        if problems:
            raise Refusal('kiem-may', 'the machine is not ready:\n    ' + '\n    '.join(problems), 'set what is named; none of it is in the script')
        for w in plan.warnings:
            say(f'warning: {w}')
        say(f'script ok: {len(plan.say)} voice paragraphs, {len(plan.refs)} capture(s): {", ".join(plan.refs) or "none"}')
        if a.chi_kiem:
            return 0
        ctx = Ctx(a.script, run_dir, plan, kb, cfg)
        ctx.work.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a.script, ctx.script)
        chain = Chain(ctx.work / 'trang-thai.json', say)
        ctx.chain_rows, ctx.chain_total = (lambda: list(chain.rows)), chain.total
        rows = chain.go(real_steps(ctx), ctx)
    except Refusal as r:
        say(f'\nmot-lenh: STOPPED at {r}')
        if chain:
            write_text(chain.state_path.parent / 'loi-cuoi.txt', f'{now_iso()}\n{r}\n')
        return 2
    say(f'\nDONE in {chain.total()} s. Approval pack: {ctx.pack}')
    for name, status, secs, warns, note in rows:
        say(f'  {name:14} {status:7} {secs:>7} s' + (' (the time it took before)' if status == 'reused' else ''))
    return 0
