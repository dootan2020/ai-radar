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
DEADLINES = dict(may=60, giong=45 * 60, anh=5 * 60, dung=10 * 60, nhac=5 * 60, canh=10 * 60, demo=5 * 60)   # seconds; captures: 60 s per attempt, see chup_deadline
CLIP_KINDS = ('screen', 'scene3d', 'demo')   # moving-picture beats; halcyon_kich_ban.py owns their contract
BEAT_KINDS = ('capture', 'repo', 'terminal') + CLIP_KINDS + ('number', 'chart', 'list', 'end')
LIFT_ENV = 'HALCYON_LIFT_DB'                 # optional: the music lift in silent spans, in dB (tron-nhac.py's default is 12)
CLIP_PRODUCER_MARK = re.compile(r'^CLIP_PRODUCER\s*=', re.M)
SOURCE_KEYS = ('urls', 'hco', 'follow', 'occurrence', 'open', 'source', 'date', 'locale', 'ua', 'max_rows')
REPO_SOURCE_KEYS = ('repo', 'branch')   # a source is a page to capture (`urls`), a GitHub repository to record (`repo`) or commands to run (`run`), never two of them
RUN_SOURCE_KEYS = ('run',)
SCENE_SOURCE_KEYS = ('name', 'events_from', 'counts_from')
DEMO_SOURCE_KEYS = ('entry', 'page', 'say', 'expect')

# The producers of moving pictures, registered up front so that the pull request that builds one only writes its own tool (MOT-LENH.md, "Moving pictures").
# `tool`: the file in this folder; a producer counts as built when that file holds a line `CLIP_PRODUCER = 1` (the tool says so itself, this table is never edited);
# `step`: the chain step name prefix; `beat`: the beat kind that uses it; `source`: the key of the source it reads; `dir`: Ctx attribute of its output folder.
PRODUCERS = {
    'run': dict(tool='halcyon_chay.py', step='chay', beat='screen', source='run', dir='chay', pr='C (terminal footage)'),
    'scene': dict(tool='halcyon_canh.py', step='canh', beat='scene3d', source='scene', dir='canh', pr='D (three.js scene)'),
    'demo': dict(tool='halcyon_demo.py', step='demo', beat='demo', source='demo', dir='demo', pr='E (Dojo recorder)'),
}


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
        self.repos = {}      # ref -> dict(repo, branch, paths (every path opened by any beat, in order), chain {path: bool}, beats [dict(name, open)])
        self.runs = {}       # ref -> dict(run (the source's `run` block as checked), steps {step: [phrases to highlight]}, blocks [[step, ...]] (screen beats), beats [name])
        self.scenes = {}     # ref -> dict(scene (the source's `scene` block), beats [name])
        self.demos = {}      # ref -> dict(demo (the source's `demo` block), beats [name])
        self.clips = {}      # clip key -> parse_clip_beat's info (every screen, scene3d and demo beat of the script)
        self.silent = []     # [dict(info, before)]: the silent paragraphs in order; `before` = how many voiced paragraphs come before it
        self.say = []        # the voiced paragraphs only
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


def chay_module():
    return load_module('halcyon_chay', HERE / 'halcyon_chay.py')


def check_run_source(ref, s):
    """A source of commands to run (CHAY.md): the whole `run` block is checked here, with no network, by the same code that runs it."""
    where = f'sources["{ref}"]'
    extra = [k for k in s if k not in RUN_SOURCE_KEYS]
    if extra:
        raise Refusal('kiem-kich-ban', f'{where} has unknown key(s) {", ".join(extra)}', f'a run source takes: {", ".join(RUN_SOURCE_KEYS)}')
    cm = chay_module()
    try:
        return cm.check_run(s['run'], f'{where}.run')
    except cm.Refusal as r:
        raise Refusal('kiem-kich-ban', f'{where}.run: {r.kind}: {r.why}', r.fix or 'see CHAY.md')


def check_scene_source(ref, s, sources):
    """A three.js scene source: {"scene": {"name": ..., "events_from": <a run source>, "counts_from": <a demo source>}}; the producer builds the clip (MOT-LENH.md)."""
    where = f'sources["{ref}"]'
    S = 'kiem-kich-ban'
    extra = [k for k in s if k != 'scene']
    if extra:
        raise Refusal(S, f'{where} has unknown key(s) {", ".join(extra)}', 'a scene source takes "scene" only')
    sc = s['scene']
    if not isinstance(sc, dict):
        raise Refusal(S, f'{where}.scene must be an object', 'write {"name": "<scene name>", "events_from": "<run source>", "counts_from": "<demo source>"}')
    extra = [k for k in sc if k not in SCENE_SOURCE_KEYS]
    if extra:
        raise Refusal(S, f'{where}.scene has unknown key(s) {", ".join(extra)}', f'allowed keys: {", ".join(SCENE_SOURCE_KEYS)}')
    if not (isinstance(sc.get('name'), str) and re.fullmatch(r'[\w.-]+', sc['name'])):
        raise Refusal(S, f'{where}.scene.name is missing or not a name', 'write the name of the scene the producer draws: letters, digits, dot, dash and underscore only')
    for key, need_key in (('events_from', 'run'), ('counts_from', 'demo')):
        if key in sc:
            other = sources.get(sc[key]) if isinstance(sc[key], str) else None
            if not (isinstance(other, dict) and need_key in other):
                raise Refusal(S, f'{where}.scene.{key} "{sc[key]}" is not a source with "{need_key}"', f'name a source of this script that has "{need_key}"')


def check_demo_source(ref, s):
    """A recorded-demo source: {"demo": {"entry": <public page the viewer can reach>, "page": <the page recorded>, "say": <what the script types>, "expect": {...}}}."""
    where = f'sources["{ref}"]'
    S = 'kiem-kich-ban'
    extra = [k for k in s if k != 'demo']
    if extra:
        raise Refusal(S, f'{where} has unknown key(s) {", ".join(extra)}', 'a demo source takes "demo" only')
    d = s['demo']
    if not isinstance(d, dict):
        raise Refusal(S, f'{where}.demo must be an object', 'write {"entry": "https://...", "page": "https://...", "say": "...", "expect": {...}}')
    extra = [k for k in d if k not in DEMO_SOURCE_KEYS]
    if extra:
        raise Refusal(S, f'{where}.demo has unknown key(s) {", ".join(extra)}', f'allowed keys: {", ".join(DEMO_SOURCE_KEYS)}')
    for k in ('entry', 'page'):
        u = d.get(k)
        p = urlparse(u) if isinstance(u, str) else None
        if not p or p.scheme != 'https' or not p.hostname or p.hostname in ('localhost', '127.0.0.1', '::1'):
            raise Refusal(S, f'{where}.demo.{k} is {json.dumps(u, ensure_ascii=False)}, not a public https address', 'the demo recorder opens public pages only')
    need_str(d.get('say'), f'{where}.demo.say')
    if not (isinstance(d.get('expect'), dict) and d['expect']):
        raise Refusal(S, f'{where}.demo.expect is missing', 'say what must be true after the demo ran (the recorder refuses otherwise), for example {"events": [...], "effect": "..."}')


def check_clip_beat(plan, sources, b, name):
    """A screen, scene3d or demo beat: the contract is halcyon_kich_ban.parse_clip_beat's; here its source is checked too. Returns the parsed beat. No network."""
    S = 'kiem-kich-ban'
    info, bad = kich_ban_module().parse_clip_beat(b)
    if bad:
        raise Refusal(S, f'{name}: {bad[0]}', bad[1])
    kind, ref = info['kind'], info['ref']
    key_src = PRODUCERS[{'screen': 'run', 'scene3d': 'scene', 'demo': 'demo'}[kind]]['source']
    src = sources.get(ref)
    if not isinstance(src, dict) or key_src not in src:
        raise Refusal(S, f'{name}: {kind} "{ref}" has no source with "{key_src}"', f'add "sources": {{"{ref}": {{"{key_src}": {{...}}}}}} (MOT-LENH.md, "Moving pictures")')
    if kind == 'screen':
        run = check_run_source(ref, src)
        bad_steps = [x for x in info['steps'] if x >= len(run['steps'])]
        if bad_steps:
            raise Refusal(S, f'{name}.screen.steps {bad_steps} are not steps of "{ref}" (it has 0 to {len(run["steps"]) - 1})', 'the steps of the source\'s run are numbered from 0, in order')
        ent = plan.runs.setdefault(ref, dict(run=run, steps={}, blocks=[], beats=[]))
        ent['beats'].append(name)
        if info['steps'] not in ent['blocks']:
            ent['blocks'].append(info['steps'])
    elif kind == 'scene3d':
        check_scene_source(ref, src, sources)
        plan.scenes.setdefault(ref, dict(scene=src['scene'], beats=[]))['beats'].append(name)
    else:
        check_demo_source(ref, src)
        plan.demos.setdefault(ref, dict(demo=src['demo'], beats=[]))['beats'].append(name)
    plan.clips.setdefault(info['key'], info)
    return info


def check_terminal_beat(plan, sources, b, name):
    """A terminal beat: {"kind": "terminal", "headline": [...], "terminal": {"ref": ..., "step": N, "bands": [{"text": ..., "anchor": ...}]}}; no network."""
    S = 'kiem-kich-ban'
    t = b.get('terminal')
    if not isinstance(t, dict):
        raise Refusal(S, f'{name} has no "terminal" block', 'give it {"ref": <a source with "run">, "step": <number of a step of the run, from 0>}')
    ref = need_str(t.get('ref'), f'{name}.terminal.ref')
    src = sources.get(ref)
    if not isinstance(src, dict) or 'run' not in src:
        raise Refusal(S, f'{name}: terminal "{ref}" has no source with "run"', f'add "sources": {{"{ref}": {{"run": {{...}}}}}} (CHAY.md): the commands the video shows, run for real')
    run = check_run_source(ref, src)
    step = t.get('step')
    if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step < len(run['steps']):
        raise Refusal(S, f'{name}.terminal.step must be a number from 0 to {len(run["steps"]) - 1}', 'the steps of the source\'s run are numbered from 0, in order')
    ent = plan.runs.setdefault(ref, dict(run=run, steps={}, blocks=[], beats=[]))
    ent['beats'].append(name)
    phrases = ent['steps'].setdefault(step, [])
    for bd in t.get('bands', []):
        text = need_str(bd.get('text') if isinstance(bd, dict) else None, f'{name}.terminal.bands[].text')
        if text not in phrases:
            phrases.append(text)


def check_source(ref, s, sources=None):
    where = f'sources["{ref}"]'
    if not isinstance(s, dict):
        raise Refusal('kiem-kich-ban', f'{where} must be an object', f'give it "urls": ["https://..."] and, if needed, {", ".join(SOURCE_KEYS[1:])}; or "repo": "owner/name" for a repo beat; or "run": {{...}} for a terminal beat')
    if 'scene' in s or 'demo' in s:
        if any(k in s for k in ('urls', 'repo', 'run')) or ('scene' in s and 'demo' in s):
            raise Refusal('kiem-kich-ban', f'{where} mixes "scene" or "demo" with another kind of source', 'a source is one of: a page to capture, a repository to record, commands to run, a scene, a demo')
        return check_demo_source(ref, s) if 'demo' in s else check_scene_source(ref, s, sources or {})
    if 'run' in s:
        if any(k in s for k in ('urls', 'repo')):
            raise Refusal('kiem-kich-ban', f'{where} has "run" and also "urls" or "repo"', 'a source is one of: a page to capture, a repository to record, commands to run')
        return check_run_source(ref, s)
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
    ent = plan.repos.setdefault(ref, dict(paths=[], chain={}, beats=[]))
    ent['beats'].append(dict(name=name, open=[e['path'] for e in entries]))
    for e in entries:
        if e['path'] not in ent['paths']:
            ent['paths'].append(e['path'])
            ent['chain'][e['path']] = e['chain']
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
    kbm = kich_ban_module()
    for pi, p in enumerate(paras, 1):
        where = f'paragraph {pi}'
        if isinstance(p, dict) and p.get('silent'):
            bad = kbm.silent_problem([x if isinstance(x, dict) else {} for x in paras], pi - 1, where)
            if bad:
                raise Refusal(S, bad[0], bad[1])
            b = p['beats'][0]
            info = check_clip_beat(plan, sources, b, f'{where}, beat 1' + (f' ("{b["name"]}")' if b.get('name') else ''))
            plan.silent.append(dict(info=info, before=len(plan.say)))
            last = info['kind']
            continue
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
                              'the one-command chain makes capture beats (a verbatim sentence from a public page), repo beats, terminal beats (commands it runs for real) and card beats (number, chart, list, end) only; '
                              'a hand-made recording belongs to the manual lane. Replace the beat with a capture of a page passage or a card')
            if kind not in BEAT_KINDS:
                raise Refusal(S, f'{name} has kind "{kind}"', f'kinds the chain makes: {", ".join(BEAT_KINDS)}')
            last = kind
            if kind == 'repo':
                check_repo_beat(plan, sources, b, name)
                continue
            if kind == 'terminal':
                check_terminal_beat(plan, sources, b, name)
                continue
            if kind in CLIP_KINDS:
                check_clip_beat(plan, sources, b, name)
                continue
            if kind != 'capture':
                continue
            c = b.get('capture')
            if not isinstance(c, dict):
                raise Refusal(S, f'{name} has no "capture" block', 'give it {"ref": ..., "quote": ...}')
            ref, quote = need_str(c.get('ref'), f'{name}.capture.ref'), squash(need_str(c.get('quote'), f'{name}.capture.quote'))
            if not re.fullmatch(r'[\w.-]+', ref):
                raise Refusal(S, f'{name}: capture ref "{ref}" may hold letters, digits, dot, dash and underscore only', 'rename the ref')
            if isinstance(sources.get(ref), dict) and any(k in sources[ref] for k in ('repo', 'run', 'scene', 'demo')):
                raise Refusal(S, f'{name}: capture "{ref}" is a {next(k for k in ("repo", "run", "scene", "demo") if k in sources[ref])} source', 'a capture takes a page address ("urls"); to show a repository use a repo beat, to show commands a terminal beat, or give this capture its own source')
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
    for ref in list(plan.scenes) + list(plan.demos):
        check_source(ref, sources[ref], sources)
    for ref in sources:
        if ref not in plan.refs and ref not in plan.repos and ref not in plan.runs and ref not in plan.scenes and ref not in plan.demos:
            plan.warnings.append(f'sources["{ref}"] is not used by any capture beat')
    check_post(kb.get('post'))
    return plan


def check_repo_seconds(kb, plan, run_dir):
    """Seconds, for a script whose voice already exists: the assembler's floors for every repo beat, run on the voice timing in `<run>/cong-viec/giong` when it was made
    from exactly these `say` texts. Returns True when the check ran, False when there is no such voice yet (the seconds are known only after the voice, so the first run
    meets them at `lap-rap`). The refusal is the assembler's own, with the seconds each page needs."""
    timing_path = Path(run_dir) / 'cong-viec' / ('lang' if plan.silent else 'giong') / 'giong-day-du-timing.json'
    if not plan.repos or not timing_path.exists():
        return False
    timing = load_json(timing_path)
    g = load_module('halcyon_giong_seconds', HERE / 'halcyon_giong.py')
    if [b.get('text_spoken') for b in timing.get('beats', [])] != [g.voice_text(s) for s in plan.say]:
        return False
    kbm = kich_ban_module()
    try:
        run = kbm.Run(kb, timing, {'captures': {}}, Path(run_dir) / 'cong-viec' / 'dung', timing_path, {None: Path(run_dir) / 'cong-viec' / 'quay' / 'quay.json'})
        run.tokens(); run.edges()
        for bt in run.beats:
            if bt['spec'].get('kind') == 'repo':
                run.repo_beat(bt, f'beat {bt["id"]}')
    except SystemExit as e:
        raise Refusal('kiem-kich-ban', str(e).removeprefix('kich-ban: '),
                      'lengthen the `say` text of the paragraph (the voice is made again), open fewer pages, or move an anchor (the voice is kept): the message names the seconds each page needs')
    return True


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
    ] + [dict(nguon=f'cong-viec/quay/{r["ref"]}/*', dich='6 - Nguồn/anh-quay-repo', tien_to=f'{pre}{r["ref"]}-') for r in c.get('repos', [])] + [
        dict(nguon=f'cong-viec/chay/{r["ref"]}/{pat}', dich='6 - Nguồn/chay-lenh', tien_to=f'{pre}{r["ref"]}-') for r in c.get('runs', []) for pat in ('chay.json', '*.png', 'log/*.log')] + [
        dict(nguon=pk + 'xem-truoc-dien-thoai/' + c['tiktok_mp4'], dich='7 - Thông số dựng', ten=pre + 'ban-xem-truoc-giao-dien-tiktok.mp4'),
        dict(nguon='cong-viec/dung/video.json', dich='7 - Thông số dựng', ten=pre + 'video.json'),
        dict(nguon='cong-viec/dung/video-plan.json', dich='7 - Thông số dựng', ten=pre + 'video-plan.json'),
        dict(nguon='cong-viec/dung/video-render.json', dich='7 - Thông số dựng', ten=pre + 'video-render.json'),
        dict(nguon='cong-viec/nhac/' + c['music_json'], dich='7 - Thông số dựng', ten=pre + 'nhac.json'),
        dict(nguon=pk + 'tom-tat.md', dich='7 - Thông số dựng', ten=pre + 'tom-tat-mot-lenh.md'),
    ] + ([dict(nguon='cong-viec/lang/giong-day-du.wav', dich='3 - Âm thanh', ten=pre + 'giong-doc-co-im-lang.wav'),
          dict(nguon='cong-viec/lang/giong-day-du-timing.json', dich='4 - Kịch bản và phụ đề', ten=pre + 'giong-doc-co-im-lang-timing.json')] if c.get('silent') else []) + [
        dict(nguon='cong-viec/' + x['manifest'], dich='6 - Nguồn/canh-chuyen-dong', ten=f'{pre}{x["key"].replace(":", "-")}.json') for x in c.get('clips', [])]
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
         '- Chữ, màu tương phản, khung an toàn: bộ dựng từ chối nếu sai. Video dài đúng số khung, có hình và tiếng; nhạc trộn không đổi hình, độ to lệch dưới 0,3 LU.']
    if c.get('repos'):
        L += ['- Mỗi thư mục và tệp mở trong video có thật ở commit ghi dưới đây, và các dòng hiện trên màn hình khớp danh sách của chính GitHub (API); mỗi trang có trong kế hoạch của bộ dựng, đủ lâu để nhìn.']
    if c.get('runs'):
        L += ['- Mỗi dòng lệnh và kết quả hiện trên màn hình là đầu ra thật của lệnh đó, chạy trong thư mục tạm trong lần dựng này (exit 0, có đủ chữ kịch bản cần). '
              'Mỗi gói cài đều tồn tại trên pypi.org hoặc registry.npmjs.org, trỏ đúng về kho mã nguồn kịch bản khai, và đúng phiên bản đã kiểm; chỉ cài từ hai kho chính thức, npm không chạy script cài đặt, pip chỉ cài wheel.',
              '- Thư mục tạm đã xoá, không còn tiến trình nào chạy sót (máy đọc lại sau khi dừng).']
    if c.get('silent'):
        L += ['- Đoạn không lời (' + ', '.join(f'{x["a"]}-{x["b"]} s' for x in c['silent']) + '): không có giọng, không có phụ đề (máy đọc lại: không có chữ phụ đề nào, không có từ nào, tệp tiếng im lặng tuyệt đối); '
              'nhạc nền được nâng lên trong các đoạn đó, độ to chung của phần có giọng không đổi quá 0,3 LU.']
    L += ['',
         '## Máy chưa kiểm được', '',
         '- Giọng đọc nghe có đúng và tự nhiên không (tên riêng, con số): xem `nghe-lai.txt`.',
         '- Trang gốc có nói đúng điều video kể không, và có còn mới không: ảnh chụp chứng minh câu đó có trên trang, không chứng minh bài đó đúng.']
    if c.get('repos'):
        L += ['- Mấy thư mục kịch bản chọn mở có đáng cho người xem thấy không, và cái tên thư mục có đúng lúc giọng đọc nhắc tới không: xem `anh-tong-quan.jpg`.',
              '- Cách quay: ảnh chụp thật github.com (máy tính để bàn, không đăng nhập). Con trỏ, cuộn và phóng to là bộ dựng vẽ từ các ảnh đó, không phải quay màn hình trực tiếp.']
    if c.get('silent'):
        L += ['- Nhạc nâng lên bao nhiêu thì nghe vừa tai (mặc định +12 dB, đặt bằng HALCYON_LIFT_DB): chỉ tai anh biết.',
              '- Chữ gõ lệnh trong cảnh chạy lệnh (nếu có) là vẽ theo tốc độ cố định, không ai gõ; kết quả lệnh là thật, theo đúng giờ nó hiện ra.']
    if c.get('runs'):
        L += ['- Lệnh có chạy được trên máy của người xem hay không (hệ điều hành, phiên bản Python và Node khác): ảnh chỉ chứng minh nó chạy trên máy Halcyon hôm nay.',
              '- Các gói phụ thuộc (gián tiếp) cũng từ hai kho chính thức nhưng máy không kiểm từng gói; máy ghi phiên bản đã cài, không đọc mã của chúng.']
    L += ['',
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
    if c.get('repos'):
        L += ['', '## Nguồn đã quay (GitHub)', '']
        for r in c['repos']:
            L += [f'- `{r["ref"]}`: {r["repo"]} (nhánh {r["branch"]}, commit `{r["commit"][:12]}`), quay {r["captured"]}']
            L += [f'  - `{p["path"] or "(trang chủ repo)"}`: {p["address"]} (HTTP {p["status"]}' + (f', {p["seconds"]} giây' if p.get('seconds') is not None else '') + ')' for p in r['pages']]
    if c.get('runs'):
        L += ['', '## Nguồn đã chạy (máy)', '']
        for r in c['runs']:
            L += [f'- `{r["ref"]}`: chạy {r["captured"]} ({r["seconds"]} giây); {r["tools"].get("python") or "không dùng Python"}, Node {r["tools"].get("node")}, npm {r["tools"].get("npm")}']
            L += [f'  - lệnh {k["index"]}: `{k["cwd"]}> {k["cmd"]}` exit {k["exit"] if k["exit"] is not None else "(máy chủ, dừng sau khi dùng xong)"}, {k["seconds"]} giây' for k in r['steps']]
            L += [f'  - tệp `{f["name"]}` lấy từ khối mã của {f["source"]} (dòng đầu `{f["fence"]}`), SHA-256 `{f["sha256"][:16]}`' for f in r['files']]
            L += [f'  - gói {p["registry"]} `{p["name"]}` {p["version"]} ({p["repository"]}, đăng {p["published"]}): {p["page"]}' for p in r['packages']]
            L += [f'  - kiểm lỗ hổng: `{k}`: {v}' for k, v in r['audit'].items()]
    L += ['', '## Mã băm đầu vào (SHA-256)', '']
    L += [f'- {k}: `{v}`' for k, v in c['hashes'].items()]
    L += ['', '## Kiểm file cuối', '', f'- ffprobe: {c["probe_text"]}', f'- nhạc: {c["music_text"]}', '']
    if c.get('clips'):
        L += ['', '## Cảnh chuyển động (máy dựng)', ''] + [f'- `{x["key"]}` ({x["kind"]}): `{x["manifest"]}`' for x in c['clips']]
    data = dict(id=c['id'], title=c['title'], made=now_iso(), silent=c.get('silent', []), clips=c.get('clips', []), total_s=c['total_s'], steps=[dict(step=n, status=st, seconds=s, warnings=w, note=nt) for n, st, s, w, nt in rows],
                sources=c['sources'], repos=c.get('repos', []), runs=c.get('runs', []), hashes=c['hashes'], probe=c['probe'], music=c['music_text'], archive_command=c['archive_cmd'], listen_count=n_listen)
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
        self.chup, self.giong, self.dung, self.nhac, self.quay, self.chay = (self.work / x for x in ('chup', 'giong', 'dung', 'nhac', 'quay', 'chay'))
        self.canh, self.demo, self.lang = (self.work / x for x in ('canh', 'demo', 'lang'))   # scene clips, demo recordings, the voice with its silences in
        self.spec = self.dung / 'video.json'
        self.chain_rows, self.chain_total = (lambda: []), (lambda: 0.0)


def tool_hashes(*names):
    return {n: sha_file(HERE / n) for n in names}


def chup_deadline(urls, hco):
    return 60 * 2 * (len(urls) + (1 if hco else 0)) + 30   # 60 s per attempt, two attempts per address, as chup.mjs does


def quay_deadline(paths):
    return 90 * (len(paths) + 1) + 30   # 90 s per page (45 s per attempt, two attempts) and 30 s for the GitHub listing, as the recorder works


def quay_open_args(e):
    """`--open` arguments of halcyon_quay.py: a path, or path#chain when GitHub shows a single-folder chain as one row."""
    args = []
    for p in e['paths']:
        args += ['--open', p + ('#chain' if e['chain'].get(p) else '')]
    return args


def quay_manifest(ctx, ref):
    return load_json(ctx.quay / ref / 'quay.json')


def stamp_age_ok(stamp, now=None):
    try:
        t = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    return ((now or datetime.now(TZ)) - t).total_seconds() <= CAPTURE_MAX_AGE_S


def quay_age_ok(ctx, ref, now=None):
    try:
        return stamp_age_ok(quay_manifest(ctx, ref)['captured'], now)
    except (OSError, KeyError, ValueError):
        return False


def quay_refusal(ref, code, so, se):
    """The refusal halcyon_quay.py printed (`cay: ...` or `quay: <address>: <kind>: <why>`, then maybe `to fix: ...`) as the chain's own refusal."""
    lines = [x.rstrip() for x in se.strip().splitlines() if x.strip()]
    fix = next((x.split(':', 1)[1].strip() for x in reversed(lines) if x.startswith('to fix:')), '')
    said = [x for x in lines if x.startswith(('cay:', 'quay:'))]
    reason = said[-1] if said else (tail(se, 3) or tail(so, 3) or f'halcyon_quay.py exited {code} without a message')
    if not fix:
        outside = any(f': {k}:' in reason for k in ('wall', 'rate-limit', 'status', 'theme', 'timeout', 'limit'))
        fix = ('GitHub refused or throttled the page, which no change to the script fixes: run the same command later; if it stops the same way twice, skip this pick and say why'
               if outside else 'change the "open" list of the repo beat (or "repo" and "branch" of its source) to pages that exist and show what the voice says; the message names the page')
    return Refusal(f'quay:{ref}', reason, fix)


def chay_deadline(run):
    """Every step's own deadline, the server's wait for readiness, and four minutes for the Python environment, the registry checks and the audit."""
    return sum(s['deadline'] for s in run['steps']) + 60 + 240


def chay_manifest(ctx, ref):
    return load_json(ctx.chay / ref / 'chay.json')


def chay_age_ok(ctx, ref, now=None):
    try:
        return stamp_age_ok(chay_manifest(ctx, ref)['captured'], now)
    except (OSError, KeyError, ValueError):
        return False


def chay_refusal(ref, code, so, se):
    """The refusal halcyon_chay.py printed (`chay: <kind>: <why>`, then `to fix: ...`) as the chain's own refusal."""
    lines = [x.rstrip() for x in se.strip().splitlines() if x.strip()]
    fix = next((x.split(':', 1)[1].strip() for x in reversed(lines) if x.startswith('to fix:')), '')
    start = next((i for i, x in enumerate(lines) if x.startswith('chay:')), None)
    said = [x for x in (lines[start:] if start is not None else []) if not x.startswith('to fix:')]
    reason = '\n    '.join(said) if said else (tail(se, 3) or tail(so, 3) or f'halcyon_chay.py exited {code} without a message')
    kind = re.match(r'chay: ([\w-]+):', reason)
    if not fix:
        fix = 'run the same command again later' if kind and kind.group(1) in ('network', 'deadline', 'leftover') else 'change the "run" block of the source (or the beat\'s step); the message names the step and what the real output was'
    return Refusal(f'chay:{ref}', reason, fix)


def producer_ready(name):
    """A producer is built when its tool is in this folder and says so itself with a line `CLIP_PRODUCER = 1`; this table is never edited by the pull request that builds one."""
    tool = HERE / PRODUCERS[name]['tool']
    try:
        return bool(CLIP_PRODUCER_MARK.search(tool.read_text(encoding='utf-8')))
    except OSError:
        return False


def producer_stub(name, ref):
    p = PRODUCERS[name]
    return Refusal(f'{p["step"]}:{ref}', f'producer not built yet: {p["tool"]} cannot make the moving picture for the {p["beat"]} beat of "{ref}" ({p["tool"]} has no line CLIP_PRODUCER = 1)',
                   f'the producer is built by pull request {p["pr"]}; until it lands, a script with a {p["beat"]} beat cannot run (the script itself is checked: --chi-kiem)')


def missing_producers(plan):
    """[(producer name, ref)] the script needs and the chain does not have yet."""
    need = [('run', r) for r, e in plan.runs.items() if e['blocks']] + [('scene', r) for r in plan.scenes] + [('demo', r) for r in plan.demos]
    return [(n, r) for n, r in need if not producer_ready(n)]


def clip_manifest_path(ctx, info):
    """Where the producer of a moving picture writes its manifest (clip.json; demo.json for a demo): the contract C, D and E build to."""
    if info['kind'] == 'screen':
        return ctx.chay / info['ref'] / f'clip-{"-".join(str(x) for x in info["steps"])}.json'
    if info['kind'] == 'scene3d':
        return ctx.canh / info['ref'] / 'clip.json'
    return ctx.demo / info['ref'] / 'demo.json'


def clip_length(ctx, info):
    """Seconds a moving picture lasts: the length of the silence made for it."""
    man = load_json(clip_manifest_path(ctx, info))
    return round(float(info['to'] - info['from']) if info['kind'] == 'demo' else float(man['duration']), 3)


def check_clip_manifest(ctx, info):
    """What the chain needs from a producer's manifest before anything stands on it: the file, its fields, the video it names."""
    path = clip_manifest_path(ctx, info)
    S = f'{PRODUCERS[{"screen": "run", "scene3d": "scene", "demo": "demo"}[info["kind"]]]["step"]}:{info["ref"]}'
    if not path.exists():
        raise Refusal(S, f'the producer finished but wrote no {path.name} for {info["key"]}', 'tell the coordinator: the producer does not follow the manifest contract (MOT-LENH.md)')
    kb = kich_ban_module()
    man = load_json(path)
    miss = [k for k in (kb.DEMO_FIELDS if info['kind'] == 'demo' else kb.CLIP_FIELDS) if man.get(k) in (None, '')]
    if miss:
        raise Refusal(S, f'{path.name} lacks {", ".join(miss)}', 'tell the coordinator: the producer does not follow the manifest contract (MOT-LENH.md)')
    if not (path.parent / man['file']).exists():
        raise Refusal(S, f'{path.name} names {man["file"]}, which is not there', 'tell the coordinator: the producer does not follow the manifest contract (MOT-LENH.md)')
    return man


def clip_age_ok(ctx, info, now=None):
    try:
        return stamp_age_ok(load_json(clip_manifest_path(ctx, info))['captured'], now)
    except (OSError, KeyError, ValueError):
        return False


def producer_refusal(p, ref, code, so, se):
    """The refusal a producer tool printed (`<prefix>: <kind>: <why>`, then `to fix: ...`) as the chain's own."""
    lines = [x.rstrip() for x in se.strip().splitlines() if x.strip()]
    fix = next((x.split(':', 1)[1].strip() for x in reversed(lines) if x.startswith('to fix:')), '')
    said = [x for x in lines if not x.startswith('to fix:')][-4:]
    reason = '\n    '.join(said) if said else (tail(so, 3) or f'{p["tool"]} exited {code} without a message')
    return Refusal(f'{p["step"]}:{ref}', reason, fix or 'run the same command again later; if it stops the same way twice, the message names the cause')


def step_producer(ctx, name, ref):
    """canh / demo: run the producer tool (`run --job <job.json> --out <folder>`), then check the manifests it promised."""
    p = PRODUCERS[name]
    if not producer_ready(name):
        raise producer_stub(name, ref)
    e = (ctx.plan.scenes if name == 'scene' else ctx.plan.demos)[ref]
    out = getattr(ctx, p['dir']) / ref
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    job = dict(ref=ref, **{p['source']: e[p['source']]})
    if name == 'scene':
        sc = e['scene']
        if sc.get('events_from'):
            job['events_run'] = str(ctx.chay / sc['events_from'] / 'chay.json')
        if sc.get('counts_from'):
            job['counts_demo'] = str(ctx.demo / sc['counts_from'] / 'demo.json')
    write_json(out / 'job.json', job)
    cmd = [sys.executable, '-I', '-X', 'utf8', HERE / p['tool'], 'run', '--job', out / 'job.json', '--out', out]
    code, so, se = run_process(cmd, DEADLINES['canh' if name == 'scene' else 'demo'], ctx.logs / f'{p["step"]}-{ref}', step=f'{p["step"]}:{ref}')
    if code:
        raise producer_refusal(p, ref, code, so, se)
    for info in ctx.plan.clips.values():
        if info['ref'] == ref and PRODUCERS[{'screen': 'run', 'scene3d': 'scene', 'demo': 'demo'}[info['kind']]]['step'] == p['step']:
            check_clip_manifest(ctx, info)
    return warnings_in(so) + warnings_in(se)


def step_kiem_nguon_clip(ctx):
    """Before anything slow: the moving pictures the script asks for have a producer in the chain."""
    miss = missing_producers(ctx.plan)
    if miss:
        raise producer_stub(*miss[0])
    return []


def screen_infos(ctx, ref):
    return [i for i in ctx.plan.clips.values() if i['kind'] == 'screen' and i['ref'] == ref]


def step_chay(ctx, ref):
    """Run the commands of the source for real in a throwaway folder (halcyon_chay.py): a log, one picture per step, the packages checked and pinned."""
    e = ctx.plan.runs[ref]
    if e['blocks'] and not producer_ready('run'):
        raise producer_stub('run', ref)
    out = ctx.chay / ref
    shutil.rmtree(out, ignore_errors=True)
    ctx.chay.mkdir(parents=True, exist_ok=True)
    job = ctx.chay / f'{ref}.job.json'
    jd = dict(ref=ref, run=ctx.kb['sources'][ref]['run'], bands={str(k): v for k, v in e['steps'].items()})
    if e['blocks']:
        jd['blocks'] = e['blocks']          # the step lists of the screen beats: one clip each, written as clip-<steps>.json next to chay.json (MOT-LENH.md)
    write_json(job, jd)
    cmd = [ctx.cfg['gpu_python'], '-I', '-X', 'utf8', HERE / 'halcyon_chay.py', 'run', '--job', job, '--out', out]
    code, so, se = run_process(cmd, chay_deadline(e['run']) + 120 * len(e['blocks']), ctx.logs / f'chay-{ref}', step=f'chay:{ref}')
    if code:
        raise chay_refusal(ref, code, so, se)
    for info in screen_infos(ctx, ref):
        check_clip_manifest(ctx, info)
    return warnings_in(so) + warnings_in(se)


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


def step_quay(ctx, ref):
    """GitHub's own listing of the repo at one commit, then one signed-out desktop still per page, then the comparison of the two (halcyon_quay.py run)."""
    e = ctx.plan.repos[ref]
    shutil.rmtree(ctx.quay / ref, ignore_errors=True)
    ctx.quay.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, '-X', 'utf8', HERE / 'halcyon_quay.py', 'run', '--repo', e['repo'], '--ref', ref, '--out', ctx.quay] + quay_open_args(e)
    if e.get('branch'):
        cmd += ['--branch', e['branch']]
    code, so, se = run_process(cmd, quay_deadline(e['paths']), ctx.logs / f'quay-{ref}', step=f'quay:{ref}')
    if code:
        raise quay_refusal(ref, code, so, se)
    return warnings_in(so) + warnings_in(se)


def merged_captures(ctx):
    """The manifest the assembler reads: every ref of the script, picture paths relative to the spec's folder."""
    caps = {}
    for ref in ctx.plan.refs:
        ent = capture_info(ctx, ref)['entry']
        ent = dict(ent, file=os.path.relpath(ctx.chup / ref / ent['file'], ctx.dung).replace('\\', '/'))
        caps[ref] = ent
    kb = kich_ban_module()
    for ref in ctx.plan.runs:
        for st in chay_manifest(ctx, ref)['states']:
            ent = dict(st['entry'], file=os.path.relpath(ctx.chay / ref / st['entry']['file'], ctx.dung).replace('\\', '/'))
            caps[kb.terminal_key(ref, st['step'])] = ent
    return dict(captures=caps)


def step_lap_rap(ctx):
    ctx.dung.mkdir(parents=True, exist_ok=True)
    write_json(ctx.chup / 'captures.json', merged_captures(ctx))
    cmd = [sys.executable, '-X', 'utf8', HERE / 'halcyon_kich_ban.py', ctx.script, '--timing', timing_dir(ctx) / 'giong-day-du-timing.json', '--out', ctx.spec]
    if ctx.plan.refs or ctx.plan.runs:
        cmd += ['--captures', ctx.chup / 'captures.json']
    if ctx.plan.clips:
        write_json(ctx.work / 'clips.json', {k: str(clip_manifest_path(ctx, i)) for k, i in ctx.plan.clips.items()})
        cmd += ['--clips', ctx.work / 'clips.json']
    for ref in ctx.plan.repos:
        cmd += ['--quay', f'{ref}={ctx.quay / ref / "quay.json"}']
    code, so, se = run_process(cmd, 120, ctx.logs / 'lap-rap', step='lap-rap')
    if code:
        raise Refusal('lap-rap', (tail(se, 8) or tail(so, 8)),
                      'the assembler\'s message names the beat, the field or the words; change the script (captions, anchors, quotes, kickers), not the tools. '
                      'The voice is kept: only a change to a `say` text makes it again')
    return warnings_in(so)


def repo_picture_hashes(base, lay):
    """A repo picture is the recorder's manifest and every still it names (one per page): all of them decide the render, so all of them are hashed."""
    mf = base / lay['manifest']
    out = {lay['manifest']: sha_file(mf)}
    pages = load_json(mf)['pages']
    for p in (pages.values() if isinstance(pages, dict) else pages):
        out[os.path.relpath(mf.parent / p['picture'], base).replace('\\', '/')] = sha_file(mf.parent / p['picture'])
    return out


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
            elif isinstance(lay, dict) and lay.get('kind') == 'repo':
                pics.update(repo_picture_hashes(base, lay))
            elif isinstance(lay, dict) and lay.get('kind') == 'clip':
                mf = base / lay['manifest']
                pics[lay['manifest']] = sha_file(mf)
                pics[os.path.relpath(mf.parent / load_json(mf)['file'], base).replace('\\', '/')] = sha_file(mf.parent / load_json(mf)['file'])
    return dict(spec=sha_file(ctx.spec), files=files, pictures=pics,
                builder=tool_hashes('dung-video-gpu.py', 've_halcyon.py', 'halcyon_spec.py', 'halcyon_repo_walk.py'), fonts=sha_tree(HERE / 'fonts'),
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


SEG_MIN_FRAMES = 18   # 0.6 s: the least the builder's camera gives the last page of a walk; a shorter segment is a bug in the builder, not a taste


def repo_plan_problems(spec, plan):
    """The second witness for every repo beat: the builder's plan holds one segment per page of the script's walk, in its order, each long enough to be seen."""
    pbeats = {b['id']: b for b in plan.get('beats', [])}
    out = []
    for b in spec.get('beats', []):
        pic = b.get('picture')
        if not (isinstance(pic, dict) and pic.get('kind') == 'repo'):
            continue
        pb = pbeats.get(b['id'])
        if not pb or pb.get('kind') != 'repo':
            out.append(f'beat {b["id"]} is not a repo beat in the plan')
            continue
        segs = (pb.get('notes') or {}).get('segments') or []
        want = [w['page'] for w in pic['walk']]
        if [s['page'] for s in segs] != want:
            out.append(f'beat {b["id"]}: the plan shows the pages {[s["page"] for s in segs]}, the script walks {want}')
            continue
        out += [f'beat {b["id"]}: page "{s["page"] or "home"}" is on screen {s["frames"][1] - s["frames"][0]} frames, under {SEG_MIN_FRAMES}' for s in segs if s['frames'][1] - s['frames'][0] < SEG_MIN_FRAMES]
    return out


def silent_problems(spec, plan, timing, voice_wav=None, lm=None):
    """The second witness for silent spans: inside one the builder's plan holds no caption unit, no word is heard, and the voice file is quiet; every span has its silent beat
    and every silent beat its span. (The first witness is the assembler, which makes both from the same silences.)"""
    sil = spec.get('silences', [])
    quiet = [b for b in spec.get('beats', []) if b.get('captions') is False]
    out = []
    for s in sil:
        a, b = s['a'], s['b']
        out += [f'a caption unit "{u["T"]}" is on screen from {u["s"]} to {u["e"]} s, inside the silent span {a}-{b}' for u in plan.get('units', []) if u['s'] < b - 1e-6 and u['e'] > a + 1e-6]
        out += [f'the word "{w["w"]}" is heard at {w["s"]} s, inside the silent span {a}-{b}' for w in timing.get('words_whisper_medium', []) if w['s'] < b - 1e-6 and w['e'] > a + 1e-6]
        if voice_wav and lm:
            db = lm.peak_dbfs(voice_wav, a, b)
            if db > lm.NO_VOICE_DBFS:
                out.append(f'the voice file is {db} dBFS inside the silent span {a}-{b} (limit {lm.NO_VOICE_DBFS})')
        if not any(abs(q['a'] - a) < 0.05 and abs(q['b'] - b) < 0.05 for q in quiet):
            out.append(f'the silent span {a}-{b} has no beat with "captions": false at those times')
    for q in quiet:
        if not any(abs(q['a'] - s['a']) < 0.05 and abs(q['b'] - s['b']) < 0.05 for s in sil):
            out.append(f'beat {q["id"]} has no captions but no silent span covers {q["a"]}-{q["b"]}')
    return out


def step_kiem_anh(ctx):
    d = ctx.dung / 'video-stills'
    for f in ('contact-sheet.jpg', 'phone-size-390.png'):
        if not (d / f).exists() or (d / f).stat().st_size < 1000:
            raise Refusal('kiem-anh', f'the stills folder has no {f}', 'tell the coordinator')
    if not list(d.glob('*-tt.jpg')):
        raise Refusal('kiem-anh', 'the stills folder has no TikTok-overlay preview', 'tell the coordinator')
    stale = ([r for r in ctx.plan.refs if not capture_age_ok(ctx, r)] + [f'{r} (repo)' for r in ctx.plan.repos if not quay_age_ok(ctx, r)]
             + [f'{r} (run)' for r in ctx.plan.runs if not chay_age_ok(ctx, r)] + [f'{k} (clip)' for k, i in ctx.plan.clips.items() if not clip_age_ok(ctx, i)])
    if stale:
        raise Refusal('kiem-anh', f'capture(s) {", ".join(stale)} are older than {CAPTURE_MAX_AGE_S // 3600} hours or have no time', 'run the command again: stale captures are taken again')
    spec, plan = load_json(ctx.spec), load_json(ctx.dung / 'video-plan.json')
    bad = repo_plan_problems(spec, plan)
    if bad:
        raise Refusal('kiem-anh', 'the builder\'s plan does not hold the walk the script asked for: ' + '; '.join(bad), 'tell the coordinator: the builder dropped or reordered a page of a repo beat')
    if ctx.plan.silent or spec.get('silences'):
        lm = load_module('halcyon_lang', HERE / 'halcyon_lang.py')
        bad = silent_problems(spec, plan, load_json(ctx.dung / spec['timing']), ctx.lang / 'giong-day-du.wav', lm)
        if bad:
            raise Refusal('kiem-anh', 'a silent span is not silent: ' + '; '.join(bad), 'tell the coordinator: the builder drew a subtitle, or the voice was heard, where the script has none')
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


def nhac_lift_args(spec, environ=None):
    """The silent spans of the spec as tron-nhac.py arguments: the bed is lifted there (+12 dB unless HALCYON_LIFT_DB says another number)."""
    args = []
    for s in spec.get('silences', []):
        args += ['--silence', f'{s["a"]}:{s["b"]}']
    lift = (environ if environ is not None else os.environ).get(LIFT_ENV)
    return args + (['--lift-db', str(lift)] if args and lift else [])


def step_nhac(ctx):
    spec = load_json(ctx.spec)
    ctx.nhac.mkdir(parents=True, exist_ok=True)
    out = nhac_path(ctx, spec)
    env = dict(os.environ, HALCYON_MUSIC_TRACK=ctx.cfg['music'])
    cmd = [sys.executable, '-X', 'utf8', HERE / 'tron-nhac.py', ctx.dung / spec['out']['clean'], '--out', out] + nhac_lift_args(spec)
    code, so, se = run_process(cmd, DEADLINES['nhac'], ctx.logs / 'nhac', env=env, step='nhac')
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
    repos = []
    for ref in ctx.plan.repos:
        m = quay_manifest(ctx, ref)
        repos.append(dict(ref=ref, repo=m['repo'], branch=m['branch'], commit=m['commit'], captured=m['captured'],
                          pages=[dict(path=p['path'], address=p['final'], status=p['status'], seconds=p.get('seconds')) for p in m['pages']]))
    runs = []
    for k, i in ctx.plan.clips.items():
        m = load_json(clip_manifest_path(ctx, i))
        srcs.append(dict(ref=k, url=m['source'], http='-', captured=m['captured'], picture=m['file'], matched=None))
    for ref in ctx.plan.runs:
        m = chay_manifest(ctx, ref)
        runs.append(dict(ref=ref, captured=m['captured'], seconds=m['seconds'], tools=m['tools'], files=m['files'], steps=m['steps'], packages=list(m['packages'].values()),
                         audit=m['audit'], leftover=m['leftover_processes_after'], deleted=m['throwaway_folder_deleted']))
    write_text(ctx.work / 'nguon.txt', ''.join(f'{s["ref"]}\t{s["url"]}\tHTTP {s["http"]}\tchụp {s["captured"]}\n' for s in srcs)
               + ''.join(f'{r["ref"]}\tchạy thật\t{k["cmd"]}\texit {k["exit"]}\n' for r in runs for k in r['steps'])
               + ''.join(f'{r["ref"]}\t{p["page"]}\t{p["name"]} {p["version"]}\n' for r in runs for p in r['packages'])
               + ''.join(f'{r["ref"]}\t{p["address"]}\tHTTP {p["status"]}\tquay {r["captured"]}\tcommit {r["commit"]}\n' for r in repos for p in r['pages']))
    fm, pm = ffprobe_facts(final), ffprobe_facts(clean)
    bad = check_render(fm, spec['duration'])
    if bad:
        raise Refusal('goi', 'the final mp4: ' + '; '.join(bad), 'tell the coordinator')
    music = (ctx.nhac / 'nhac-ket-qua.txt').read_text(encoding='utf-8').strip().splitlines()
    hashes = {'script (kich-ban.json)': sha_file(ctx.script), 'say texts': sha_json(ctx.plan.say), 'voice wav': sha_file(ctx.giong / 'giong-day-du.wav'),
              'timing file': sha_file(ctx.giong / 'giong-day-du-timing.json'), 'video.json': sha_file(ctx.spec)}
    for ref in ctx.plan.refs:
        hashes[f'capture {ref} (picture)'] = sha_file(ctx.chup / ref / capture_info(ctx, ref)['entry']['file'])
    for k, i in ctx.plan.clips.items():
        hashes[f'moving picture {k} (manifest)'] = sha_file(clip_manifest_path(ctx, i))
    for r in repos:
        hashes[f'repo {r["ref"]} (quay.json)'] = sha_file(ctx.quay / r['ref'] / 'quay.json')
    for r in runs:
        hashes[f'run {r["ref"]} (chay.json)'] = sha_file(ctx.chay / r['ref'] / 'chay.json')
        hashes.update({f'run {r["ref"]} file {f["name"]}': f['sha256'] for f in r['files']})
    if ctx.plan.silent:
        hashes['voice wav with silences'] = sha_file(ctx.lang / 'giong-day-du.wav')
        hashes['timing file with silences'] = sha_file(ctx.lang / 'giong-day-du-timing.json')
    hashes['mp4 no music'] = sha_file(clean)
    hashes['mp4 with music'] = sha_file(final)
    slug = Path(spec['out']['clean']).stem[len(spec['name']) + 1:]
    mins = spec['duration']
    c = dict(id=ctx.kb['id'], title=ctx.kb['title'], date_iso=datetime.now(TZ).strftime('%Y-%m-%d'), run_dir=str(ctx.run), slug=slug,
             final_mp4=names['final'], plain_mp4=names['plain'], tiktok_mp4=names['tiktok'], post_file=names['post'], music_json=final.with_suffix('.json').name,
             duration_text=f'{mins:g} s'.replace('.', ','), say=ctx.plan.say,
             silent=[dict(key=x['info']['key'], a=y['a'], b=y['b']) for x, y in zip(ctx.plan.silent, spec.get('silences', []))],
             clips=[dict(key=k, kind=i['kind'], manifest=str(clip_manifest_path(ctx, i).relative_to(ctx.work)).replace('\\', '/')) for k, i in ctx.plan.clips.items()], listen_count=len(rep.get('listen', [])), sources=srcs, repos=repos, runs=runs, hashes=hashes,
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
    if ctx.plan.clips:
        steps.append(Step('kiem-nguon-clip', step_kiem_nguon_clip, always=True, what='checking that the producers of the moving pictures are built'))
    for ref in ctx.plan.refs:
        e = ctx.plan.refs[ref]
        steps.append(Step(f'chup:{ref}', lambda c, r=ref: step_chup(c, r),
                          inputs=lambda c, r=ref, e=e: dict(urls=e['urls'], hco=e['hco'], quote=e['quote'], bands=e['bands'], options=e['options'], tool=tool_hashes('chup.mjs')),
                          outputs=lambda c, r=ref: [c.chup / r / f'{r}.capture.json', c.chup / r / f'{r}.png'],
                          valid=lambda c, r=ref: capture_age_ok(c, r), what=f'capturing {ref}'))
    for ref in ctx.plan.repos:
        e = ctx.plan.repos[ref]
        steps.append(Step(f'quay:{ref}', lambda c, r=ref: step_quay(c, r),
                          inputs=lambda c, e=e: dict(repo=e['repo'], branch=e.get('branch'), paths=[[p, bool(e['chain'].get(p))] for p in e['paths']],
                                                     tools=tool_hashes('halcyon_quay.py', 'quay-repo.mjs', 'chup.mjs')),
                          outputs=lambda c, r=ref: [c.quay / r / 'quay.json', c.quay / r / 'cay.json'],
                          valid=lambda c, r=ref: quay_age_ok(c, r), what=f'recording {e["repo"]} on github.com'))
    for ref in ctx.plan.runs:
        e = ctx.plan.runs[ref]
        steps.append(Step(f'chay:{ref}', lambda c, r=ref: step_chay(c, r),
                          inputs=lambda c, r=ref, e=e: dict(run=c.kb['sources'][r]['run'], bands={str(k): v for k, v in e['steps'].items()}, blocks=e['blocks'], tool=tool_hashes('halcyon_chay.py'),
                                                            font=sha_file(HERE / 'fonts' / 'JetBrainsMono-Medium.ttf')),
                          outputs=lambda c, r=ref: [c.chay / r / 'chay.json'] + [clip_manifest_path(c, i) for i in screen_infos(c, r)],
                          valid=lambda c, r=ref: chay_age_ok(c, r), what=f'running the commands of {ref} for real (installs packages into a throwaway folder)'))
    for name, plans in (('demo', ctx.plan.demos), ('scene', ctx.plan.scenes)):
        P = PRODUCERS[name]
        for ref, e in plans.items():
            steps.append(Step(f'{P["step"]}:{ref}', lambda c, n=name, r=ref: step_producer(c, n, r),
                              inputs=lambda c, n=name, r=ref, e=e: dict(source=e[PRODUCERS[n]['source']], tool=(sha_file(HERE / PRODUCERS[n]['tool']) if (HERE / PRODUCERS[n]['tool']).exists() else '-'),
                                                                        upstream=sorted(i for i in ((e[PRODUCERS[n]['source']].get('events_from'), e[PRODUCERS[n]['source']].get('counts_from')) if n == 'scene' else ()) if i)),
                              outputs=lambda c, r=ref: [clip_manifest_path(c, i) for i in c.plan.clips.values() if i['ref'] == r and i['kind'] != 'screen'],
                              valid=lambda c, r=ref: all(clip_age_ok(c, i) for i in c.plan.clips.values() if i['ref'] == r and i['kind'] != 'screen'),
                              what=f'making the {PRODUCERS[name]["beat"]} "{ref}"'))
    voice_inputs = lambda c: dict(say=c.plan.say, approved=sha_file(HERE / 'giong-da-nghe.txt'), tools=tool_hashes('lam-giong.py', 'halcyon_giong.py'),
                                  tts=sha_file(HERE.parent / 'scripts' / 'omnivoice_tts.py'),
                                  reference=sha_file(Path(c.cfg['profiles']) / VOICE_PROFILE / 'reference.wav'))
    steps.append(Step('giong', step_giong, inputs=voice_inputs, what='making the voice (about four minutes)',
                      outputs=lambda c: [c.giong / 'giong-day-du.wav', c.giong / 'giong-day-du-timing.json', c.giong / 'giong-ket-qua.json']))
    if ctx.plan.silent:
        steps.append(Step('lang', step_lang, inputs=lambda c: dict(inserts=silence_inserts(c), voice=sha_file(c.giong / 'giong-day-du.wav'), timing=sha_file(c.giong / 'giong-day-du-timing.json'),
                                                                  tool=tool_hashes('halcyon_lang.py')),
                          what='putting the silence of the silent paragraphs into the voice', outputs=lambda c: [c.lang / 'giong-day-du.wav', c.lang / 'giong-day-du-timing.json']))
    steps += [Step('lap-rap', step_lap_rap, always=True, what='assembling the spec'),
              Step('anh', step_anh, inputs=builder_inputs, what='drawing the stills', outputs=lambda c: [c.dung / 'video-stills' / 'contact-sheet.jpg', c.dung / 'video-plan.json']),
              Step('kiem-anh', step_kiem_anh, always=True, what='checking the stills and the age of the captures'),
              Step('dung', step_dung, inputs=builder_inputs, what='rendering on the GPU',
                   outputs=lambda c: [c.dung / load_json(c.spec)['out'][k] for k in ('clean', 'tiktok')] + [c.dung / 'video-render.json']),
              Step('nhac', step_nhac, inputs=lambda c: dict(video=sha_file(c.dung / load_json(c.spec)['out']['clean']), track=sha_file(c.cfg['music']), tool=tool_hashes('tron-nhac.py'),
                                              lift=nhac_lift_args(load_json(c.spec))),
                   what='mixing the music bed', outputs=lambda c: [nhac_path(c)]),
              Step('goi', step_goi, always=True, what='building the approval pack')]
    return steps


def voiced_script(ctx):
    """The script the voice tool reads: a silent paragraph has no `say`, so it is left out here (the full script stays what the assembler reads)."""
    if not ctx.plan.silent:
        return ctx.script
    path = ctx.work / 'kich-ban-giong.json'
    write_json(path, dict(ctx.kb, paragraphs=[p for p in ctx.kb['paragraphs'] if not p.get('silent')]))
    return path


def silence_inserts(ctx):
    return [dict(before=x['before'], dur=clip_length(ctx, x['info']), key=x['info']['key']) for x in ctx.plan.silent]


def step_lang(ctx):
    """Put the silence of every silent paragraph into the voice (halcyon_lang.py), at the right gap, and move the timing after it; the files go to <run>/cong-viec/lang."""
    lm = load_module('halcyon_lang', HERE / 'halcyon_lang.py')
    try:
        t, w, new = lm.run(ctx.giong / 'giong-day-du-timing.json', ctx.giong / 'giong-day-du.wav', silence_inserts(ctx), ctx.lang)
    except lm.Refusal as r:
        raise Refusal('lang', str(r), 'the silence goes between two voiced paragraphs and every clip needs its manifest; change the order of the paragraphs, or tell the coordinator')
    return [f'silent {s["key"]}: {s["a"]} to {s["b"]} s' for s in new['silences']]


def timing_dir(ctx):
    return ctx.lang if ctx.plan.silent else ctx.giong


def step_giong(ctx):
    cmd = [sys.executable, '-X', 'utf8', HERE / 'lam-giong.py', voiced_script(ctx), '--out', ctx.giong]
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
        say(f'script ok: {len(plan.say)} voice paragraphs, {len(plan.refs)} capture(s): {", ".join(plan.refs) or "none"}'
            + (f'; {len(plan.repos)} repo recording(s): {", ".join(plan.repos)}' if plan.repos else '')
            + (f'; {len(plan.runs)} run(s) of commands: {", ".join(plan.runs)}' if plan.runs else '')
            + (f'; {len(plan.silent)} silent block(s): {", ".join(x["info"]["key"] for x in plan.silent)}' if plan.silent else '')
            + (f'; {len(plan.scenes)} scene(s): {", ".join(plan.scenes)}' if plan.scenes else '') + (f'; {len(plan.demos)} demo(s): {", ".join(plan.demos)}' if plan.demos else ''))
        for name, ref in missing_producers(plan):
            say(f'warning: {producer_stub(name, ref).reason} (a real run stops at step kiem-nguon-clip)')
        if a.chi_kiem:
            if check_repo_seconds(kb, plan, run_dir):
                say('repo beats: the seconds fit the voice already made')
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
