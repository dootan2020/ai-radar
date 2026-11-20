"""Halcyon terminal beat (`chay:<ref>` in the one command): run the real commands of a follow-along in a throwaway folder and draw the real log as stills.

    python halcyon_chay.py run --job job.json --out <folder>

The job: {"ref": ..., "run": <the `run` block of a source, CHAY.md>, "bands": {"<step>": ["phrase on screen", ...]}}. It writes `<folder>/chay.json` (every command, its
exit code and output, the packages checked and pinned, the tools, one capture-shaped entry per step) and `<folder>/s<step>.png` (the picture of each step: 1170 px wide, the
builder's capture picture), then deletes the throwaway folder `<folder>/work` and keeps `<folder>/log`.

Standard library only, except that drawing imports Pillow (the GPU interpreter has it). Every refusal is `chay: <kind>: <why>` then `to fix: ...` on stderr, exit 1, and nothing
is left running. The safety gates are the point of this file: a follow-along installs third-party packages, so what may run is a short allow list, every package is
checked against its official registry before it is installed, and everything happens inside the throwaway folder with a scrubbed environment (CHAY.md)."""
import argparse
import codecs
import hashlib
import io
import math
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIP_PRODUCER = 1
REPO = HERE.parents[1]
TZ = timezone(timedelta(hours=7))
FONT = HERE / 'fonts' / 'JetBrainsMono-Medium.ttf'
# the picture: a 390 css px phone at scale 3, monospace 16 css px = 48 px, drawn on a character grid (the font's hinted advance at 48 px is 29 px)
WIDTH, FONT_PX, CHAR_W, LINE_H, BASE_UP, PAD_X, PAD_Y, COLS = 1170, 48, 29, 68, 51, 63, 72, 36
PIC_W = 763                  # pic_w of layout thu-gon-r3 in ve_halcyon.py: the width the builder gives a capture (tests/test_halcyon_chay.py compares the two)
MIN_FRAME_PX = 28            # the least text height on the frame (builder px) the owner's phone allows; 48 * 763 / 1170 = 31.3
MAX_ROWS, MAX_ROWS_CAP = 8, 12
BG, PROMPT, CMD, OUT, NOTE, MARK = (13, 17, 23), (126, 231, 135), (230, 237, 243), (160, 170, 182), (125, 133, 144), (255, 209, 102)
DOC_HOSTS = ('raw.githubusercontent.com',)
PYPI, NPM = 'https://pypi.org', 'https://registry.npmjs.org'
PYPI_INDEX, NPM_REGISTRY = 'https://pypi.org/simple/', 'https://registry.npmjs.org/'
DOWNLOAD_HOSTS = ('pypi.org', 'files.pythonhosted.org', 'registry.npmjs.org')
STEP_DEADLINE, STEP_DEADLINE_CAP = 120, 300
READY_DEADLINE = 60
ALLOWED_EXE = ('pip', 'uvicorn', 'npm', 'npx', 'python', 'node')
# words that are never part of a follow-along step. Each one is refused by name so the message says why (the allow list would refuse them too).
DANGER = {
    'sudo': 'privilege', 'su': 'privilege', 'doas': 'privilege', 'runas': 'privilege', 'start-process': 'privilege', 'gsudo': 'privilege',
    'set-executionpolicy': 'security', 'add-mppreference': 'security', 'set-mppreference': 'security', 'netsh': 'security', 'setx': 'security', 'reg': 'security',
    'schtasks': 'security', 'sc': 'security', 'certutil': 'security', 'bitsadmin': 'security', 'mshta': 'security', 'rundll32': 'security', 'regsvr32': 'security',
    'msiexec': 'security', 'winget': 'install', 'choco': 'install', 'scoop': 'install', 'apt': 'install', 'apt-get': 'install', 'brew': 'install',
    'curl': 'download', 'wget': 'download', 'iwr': 'download', 'invoke-webrequest': 'download', 'iex': 'download', 'invoke-expression': 'download',
    'powershell': 'shell', 'pwsh': 'shell', 'cmd': 'shell', 'bash': 'shell', 'sh': 'shell', 'zsh': 'shell',
    'rm': 'delete', 'del': 'delete', 'rmdir': 'delete', 'rd': 'delete', 'format': 'delete', 'chmod': 'delete', 'chown': 'delete', 'taskkill': 'delete'}
GLOBAL_FLAGS = ('-g', '--global', '--user', '--system', '--location=global', '--break-system-packages', '--root', '--prefix', '--target', '-t')
REGISTRY_FLAGS = ('--registry', '--index-url', '-i', '--extra-index-url', '--find-links', '-f', '--trusted-host', '--proxy', '--cert', '--no-index')
PKG_PIP = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}(==\d+(\.\d+)*([a-z]+\d*)?)?')
PKG_NPM = re.compile(r'(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*(@\d+\.\d+\.\d+)?')
ARCHIVES = ('.whl', '.zip', '.tar', '.tar.gz', '.tgz', '.egg')
SAFE_NAME = re.compile(r'[\w][\w.-]{0,59}')
ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07')
SECRET_NAME = re.compile(r'(?i)KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE')
ENV_KEEP = ('PATH', 'PATHEXT', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'OS', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
            'PROGRAMDATA', 'COMMONPROGRAMFILES', 'LANG', 'LC_ALL')


class Refusal(Exception):
    def __init__(self, kind, why, fix=''):
        super().__init__(why)
        self.kind, self.why, self.fix = kind, why, fix

    def __str__(self):
        return f'chay: {self.kind}: {self.why}' + (f'\nto fix: {self.fix}' if self.fix else '')


def now_iso():
    return datetime.now(TZ).isoformat(timespec='seconds')


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ the script's run block (no network): every refusal here is made before anything runs
def check_command(cmd, file_names, npm_installed=()):
    """One step's command. Returns dict(form, argv, packages, registry) or raises Refusal. The form is one of pip-install, npm-install, npm-init, npm-pkg, npx, uvicorn, python, node."""
    if not isinstance(cmd, str) or not cmd.strip():
        raise Refusal('command', 'a step has no command', 'give every step "cmd": "<one command>"')
    if re.search(r'[&|;]', cmd):
        raise Refusal('chain', f'"{cmd}" chains or pipes commands (& | ;)', 'one command per step; write each part as its own step (Windows PowerShell 5.1 does not take && either)')
    if re.search(r'[<>]', cmd):
        raise Refusal('redirect', f'"{cmd}" redirects input or output', 'a step is one plain command, with no redirection')
    if re.search(r'[`$(){}^%!"\'\n\r\\]', cmd):
        raise Refusal('shell', f'"{cmd}" holds a shell character (` $ ( ) {{ }} ^ % ! quotes, a backslash or a line break)', 'write the command with plain words only')
    argv = cmd.split()
    for w in argv:
        base = w.lower()
        if base in DANGER:
            raise Refusal('danger', f'"{w}" is refused ({DANGER[base]}): a follow-along never uses it', 'remove the step; the chain runs pip, uvicorn, npm, npx, python and node only')
    for w in argv:
        if w in GLOBAL_FLAGS or any(w.startswith(f + '=') for f in GLOBAL_FLAGS if f.startswith('--')):
            raise Refusal('global', f'"{w}" installs outside the throwaway folder', 'install into the folder only: drop the flag')
        if w in REGISTRY_FLAGS or any(w.startswith(f + '=') for f in REGISTRY_FLAGS if f.startswith('--')):
            raise Refusal('registry', f'"{w}" names another package source', 'packages come from pypi.org and registry.npmjs.org only: drop the flag')
    if any('://' in w for w in argv):
        raise Refusal('address', f'"{cmd}" holds an address', 'a step takes no web address (no download, no install from a link)')
    for w in argv[1:]:
        if '..' in w or w.startswith(('/', '~', '.')) or re.match(r'[A-Za-z]:', w) and not re.match(r'[\w]+:[\w]+$', w):
            raise Refusal('path', f'"{w}" is a path outside the throwaway folder', 'name files by their plain name (the files of the run block)')
    exe, rest = argv[0], argv[1:]
    exe_l = re.sub(r'\.(exe|cmd|bat)$', '', exe.lower())
    if exe_l not in ALLOWED_EXE:
        raise Refusal('command', f'"{exe}" is not a command a follow-along may run (allowed: {", ".join(ALLOWED_EXE)})', 'use one of the allowed commands, or tell the coordinator the follow-along needs another')
    bad_flag = lambda ws, ok=(): next((w for w in ws if w.startswith('-') and w not in ok), None)
    if exe_l == 'pip':
        if not rest or rest[0] != 'install' or len(rest) < 2:
            raise Refusal('command', f'"{cmd}": only `pip install <package> ...` is allowed', 'write `pip install <package> ...`')
        if bad_flag(rest[1:]):
            raise Refusal('flag', f'"{bad_flag(rest[1:])}" is not an allowed flag of pip install (none is)', 'drop the flag')
        pk = rest[1:]
        for p in pk:
            if not PKG_PIP.fullmatch(p) or p.lower().endswith(ARCHIVES):
                raise Refusal('package', f'"{p}" is not a plain package name (name or name==1.2.3)', 'a path, an archive, a link or a version range is not allowed')
        return dict(form='pip-install', argv=argv, packages=pk, registry='pypi')
    if exe_l == 'npm':
        if rest[:1] == ['init'] and rest[1:] == ['-y']:
            return dict(form='npm-init', argv=argv, packages=[], registry=None)
        if rest[:2] == ['pkg', 'set'] and len(rest) == 3 and rest[2] in ('type=module', 'type=commonjs'):
            return dict(form='npm-pkg', argv=argv, packages=[], registry=None)
        if rest[:1] in (['install'], ['i']) and len(rest) >= 2:
            if bad_flag(rest[1:]):
                raise Refusal('flag', f'"{bad_flag(rest[1:])}" is not an allowed flag of npm install (none is)', 'drop the flag')
            for p in rest[1:]:
                if not PKG_NPM.fullmatch(p) or p.lower().endswith(ARCHIVES):
                    raise Refusal('package', f'"{p}" is not a plain npm package name (name, @scope/name or either with @1.2.3)', 'a path, an archive, a link or a tag is not allowed')
            return dict(form='npm-install', argv=argv, packages=rest[1:], registry='npm')
        raise Refusal('command', f'"{cmd}": npm may only `init -y`, `pkg set type=module` or `install <package> ...`', 'other npm commands (run, exec, publish, config, ...) are not allowed')
    if exe_l == 'npx':
        if not rest or bad_flag(rest):
            raise Refusal('command', f'"{cmd}": npx takes a package installed earlier in the run and a file', 'write `npx <package> <file>`')
        if rest[0] not in [re.sub(r'@\d.*$', '', p) for p in npm_installed] and rest[0] not in npm_installed:
            raise Refusal('npx', f'"npx {rest[0]}" would fetch and run a package that no earlier step installed', 'npx runs only a package an earlier `npm install` step installed')
        if any(w not in file_names for w in rest[1:]):
            raise Refusal('command', f'"{cmd}": npx may be given only files of the run block', 'name only files of the run block')
        return dict(form='npx', argv=argv, packages=[], registry=None)
    if exe_l == 'uvicorn':
        if not rest or not re.fullmatch(r'(\w+):(\w+)', rest[0]) or f'{rest[0].split(":")[0]}.py' not in file_names:
            raise Refusal('command', f'"{cmd}": uvicorn needs `<module>:<app>` where <module>.py is a file of the run block', 'write `uvicorn server:app --port 8000`')
        extra = rest[1:]
        if extra and not (len(extra) == 2 and extra[0] == '--port' and extra[1].isdigit() and 1024 <= int(extra[1]) <= 65535):
            raise Refusal('flag', f'"{" ".join(extra)}" is not allowed after uvicorn (only `--port <1024-65535>`)', 'drop it')
        return dict(form='uvicorn', argv=argv, packages=[], registry=None)
    if exe_l in ('python', 'node'):
        if len(rest) != 1 or rest[0] not in file_names or rest[0].startswith('-'):
            raise Refusal('command', f'"{cmd}": {exe_l} may run a file of the run block only, with no flags (no -c, -e, -m)', f'write `{exe_l} <file>`')
        return dict(form=exe_l, argv=argv, packages=[], registry=None)
    raise Refusal('command', f'"{cmd}" is not allowed', 'see CHAY.md')


def source_repo(url):
    m = re.match(r'https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/', url)
    return f'{m.group(1)}/{m.group(2)}' if m else None


def check_run(run, where='run'):
    """The whole run block. Returns the normalised block (steps parsed). No network."""
    if not isinstance(run, dict):
        raise Refusal('run', f'{where} must be an object', 'give it {"files": [...], "steps": [...]}')
    extra = [k for k in run if k not in ('files', 'steps', 'packages', 'max_rows')]
    if extra:
        raise Refusal('run', f'{where} has unknown key(s) {", ".join(extra)}', 'allowed: files, steps, packages, max_rows')
    files, steps = run.get('files'), run.get('steps')
    if not isinstance(files, list) or not files:
        raise Refusal('run', f'{where}.files is empty', 'list the files to write, each taken from a fenced block of a public README')
    if not isinstance(steps, list) or not steps:
        raise Refusal('run', f'{where}.steps is empty', 'list the commands to run, in order')
    max_rows = run.get('max_rows', MAX_ROWS)
    if not (isinstance(max_rows, int) and not isinstance(max_rows, bool) and 3 <= max_rows <= MAX_ROWS_CAP):
        raise Refusal('run', f'{where}.max_rows must be a whole number from 3 to {MAX_ROWS_CAP}', 'fix the value')
    names, seen = [], set()
    for i, f in enumerate(files):
        w = f'{where}.files[{i}]'
        if not isinstance(f, dict) or any(k not in ('name', 'dir', 'from', 'fence') for k in f):
            raise Refusal('file', f'{w} must be {{"name", "from", "fence"}} (and optionally "dir")', 'fix the entry')
        if not isinstance(f.get('name'), str) or not SAFE_NAME.fullmatch(f['name']):
            raise Refusal('file', f'{w}.name must be a plain file name', 'letters, digits, dot, dash and underscore only; no folder')
        if 'dir' in f and (not isinstance(f['dir'], str) or not re.fullmatch(r'[\w-]{1,30}', f['dir'])):
            raise Refusal('file', f'{w}.dir must be one plain folder name', 'letters, digits, dash and underscore only')
        u = urllib.parse.urlparse(f.get('from') if isinstance(f.get('from'), str) else '')
        if u.scheme != 'https' or u.hostname not in DOC_HOSTS:
            raise Refusal('file', f'{w}.from must be an https address on {", ".join(DOC_HOSTS)}', 'a file is taken from the raw README of a public repository')
        if not isinstance(f.get('fence'), str) or not f['fence'].strip() or '\n' in f['fence']:
            raise Refusal('fence', f'{w}.fence must be the first line of the fenced block the file is taken from', 'for example "# server.py"')
        key = (f.get('dir', '.'), f['name'])
        if key in seen:
            raise Refusal('file', f'{w}: {key[1]} is listed twice', 'one entry per file')
        seen.add(key)
        names.append(f['name'])
    project = source_repo(files[0]['from'])
    pk_in = run.get('packages', {})
    if not isinstance(pk_in, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch(r'[\w.-]+/[\w.-]+', v) for k, v in pk_in.items()):
        raise Refusal('run', f'{where}.packages must map a package name to the GitHub repository ("owner/name") it must come from', 'for example {"fastapi": "fastapi/fastapi"}')
    parsed, npm_installed = [], []
    for i, s in enumerate(steps):
        w = f'{where}.steps[{i}]'
        if not isinstance(s, dict) or any(k not in ('cmd', 'cwd', 'serve', 'ready', 'port', 'expect', 'deadline') for k in s):
            raise Refusal('run', f'{w} must be {{"cmd": ...}} with optional cwd, serve, ready, port, expect, deadline', 'fix the step')
        c = check_command(s.get('cmd'), names, npm_installed)
        cwd = s.get('cwd', '.')
        if cwd != '.' and not (isinstance(cwd, str) and re.fullmatch(r'[\w-]{1,30}', cwd)):
            raise Refusal('path', f'{w}.cwd "{cwd}" is not one plain folder name inside the throwaway folder', 'use a plain folder name or leave it out')
        if s.get('serve'):
            if not isinstance(s.get('ready'), str) or not s['ready'].strip():
                raise Refusal('run', f'{w}: a serve step needs "ready": the text its output prints when it is ready', 'for example "Uvicorn running"')
        elif 'ready' in s or 'port' in s:
            raise Refusal('run', f'{w}: "ready" and "port" belong to a serve step', 'add "serve": true, or remove them')
        if 'port' in s and not (isinstance(s['port'], int) and 1024 <= s['port'] <= 65535):
            raise Refusal('run', f'{w}.port must be a number from 1024 to 65535', 'fix the value')
        if 'expect' in s and not (isinstance(s['expect'], list) and all(isinstance(x, str) and x for x in s['expect'])):
            raise Refusal('run', f'{w}.expect must be a list of texts the real output must hold', 'fix the list')
        dl = s.get('deadline', STEP_DEADLINE)
        if not (isinstance(dl, int) and not isinstance(dl, bool) and 10 <= dl <= STEP_DEADLINE_CAP):
            raise Refusal('run', f'{w}.deadline must be 10 to {STEP_DEADLINE_CAP} seconds', 'fix the value')
        for p in c['packages']:
            bare = re.sub(r'(==|@)\d.*$', '', p) if c['registry'] == 'pypi' else re.sub(r'(?<=.)@\d.*$', '', p)
            if bare not in pk_in and not project:
                raise Refusal('package', f'{w}: no expected repository for package "{bare}"', f'add "packages": {{"{bare}": "owner/name"}}')
            if c['registry'] == 'npm':
                npm_installed.append(bare)
        parsed.append(dict(index=i, cmd=s['cmd'], cwd=cwd, serve=bool(s.get('serve')), ready=s.get('ready'), port=s.get('port'), expect=s.get('expect', []), deadline=dl, **{k: c[k] for k in ('form', 'argv', 'packages', 'registry')}))
    ports = [p['port'] for p in parsed if p['serve'] and p['port']]
    if len(set(ports)) != len(ports):
        raise Refusal('run', f'{where}: two serve steps use the same port', 'one port each')
    return dict(files=files, steps=parsed, packages=pk_in, project=project, max_rows=max_rows)


# ------------------------------------------------------------------ fenced blocks and packages
def fenced_blocks(text):
    """The fenced code blocks of a markdown text: [(language, text)], in order."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = re.match(r'\s*(`{3,}|~{3,})\s*([\w+-]*)', lines[i])
        if not m:
            i += 1
            continue
        fence, lang, body = m.group(1), m.group(2), []
        i += 1
        while i < len(lines) and not re.match(r'\s*' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*$', lines[i]):
            body.append(lines[i])
            i += 1
        out.append((lang, '\n'.join(body)))
        i += 1
    return out


def take_fence(blocks, marker, name):
    """The one block whose first non-blank line is `marker`; its text verbatim, ending in a line break."""
    hit = [t for _, t in blocks if (next((x.strip() for x in t.splitlines() if x.strip()), '') == marker.strip())]
    if not hit:
        raise Refusal('fence', f'no fenced block of the source starts with "{marker}" (file {name})', 'the file must come from a fenced block: name the block by its first line')
    if len(hit) > 1:
        raise Refusal('fence', f'{len(hit)} fenced blocks start with "{marker}" (file {name})', 'name the block by a first line that only one block has')
    return hit[0].rstrip('\n') + '\n'


def fence_tokens(blocks):
    toks = set()
    for _, t in blocks:
        toks.update(x for x in re.split(r'[\s"\'(),;=]+', t) if x)
    return toks


def http_get(url, accept='application/json', timeout=25):
    host = urllib.parse.urlparse(url).hostname
    if host not in DOC_HOSTS + ('pypi.org', 'registry.npmjs.org'):
        raise Refusal('address', f'{url} is not an address the chain may read', 'registries and raw READMEs only')
    req = urllib.request.Request(url, headers={'Accept': accept, 'User-Agent': 'halcyon-chay'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise Refusal('network', f'{url}: HTTP {e.code}', 'the page or package is not there: check the address and the package name' if e.code == 404 else 'run the command again later')
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Refusal('network', f'{url}: {e}', 'run the command again later')


def http_json(url):
    return json.loads(http_get(url).decode('utf-8'))


def github_repos(urls):
    out = set()
    for u in urls:
        for m in re.finditer(r'github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?]|$)', u or ''):
            out.add(f'{m.group(1)}/{m.group(2)}'.lower())
    return out


def vet_package(registry, spec, expected, fetch_json=http_json):
    """The check before an install: the package exists on its official registry, the version to install exists and is not yanked or deprecated, and the registry's own
    metadata points at the GitHub repository the script says it comes from (a look-alike name fails here). Returns the record chay.json keeps."""
    if registry == 'pypi':
        name, _, pin = spec.partition('==')
        doc = fetch_json(f'{PYPI}/pypi/{urllib.parse.quote(name.lower())}/json')
        info = doc.get('info', {})
        ver = pin or info.get('version')
        if pin:
            if pin not in doc.get('releases', {}):
                raise Refusal('package-version', f'pypi.org has no {name} {pin}', 'pin a version that exists')
            files = doc['releases'][pin]
        else:
            files = doc.get('urls', [])
        if not files or all(f.get('yanked') for f in files):
            raise Refusal('package-yanked', f'{name} {ver} has no usable files on pypi.org (yanked or empty)', 'pin another version')
        urls = list((info.get('project_urls') or {}).values()) + [info.get('home_page') or '', info.get('package_url') or '']
        page = f'{PYPI}/project/{name.lower()}/{ver}/'
        published = (files[0].get('upload_time_iso_8601') or '')[:10]
        deprecated = False
    else:
        name, pin = (spec[:-len(spec.rsplit('@', 1)[1]) - 1], spec.rsplit('@', 1)[1]) if re.search(r'(?<=.)@\d', spec) else (spec, None)
        doc = fetch_json(f'{NPM}/{urllib.parse.quote(name, safe="@").replace("/", "%2F")}')
        ver = pin or (doc.get('dist-tags') or {}).get('latest')
        v = (doc.get('versions') or {}).get(ver)
        if not v:
            raise Refusal('package-version', f'registry.npmjs.org has no {name} {ver}', 'pin a version that exists')
        repo = v.get('repository') or doc.get('repository') or {}
        urls = [repo.get('url') if isinstance(repo, dict) else repo, doc.get('homepage') or '', (doc.get('bugs') or {}).get('url') if isinstance(doc.get('bugs'), dict) else '']
        page = f'https://www.npmjs.com/package/{name}/v/{ver}'
        published = ((doc.get('time') or {}).get(ver) or '')[:10]
        deprecated = bool(v.get('deprecated'))
    if deprecated:
        raise Refusal('package-deprecated', f'{name} {ver} is marked deprecated on its registry', 'pick another package or version')
    found = github_repos(urls)
    if expected.lower() not in found:
        raise Refusal('typosquat', f'{name} on {registry} points at {", ".join(sorted(found)) or "no GitHub repository"}, not at {expected}; it may be a look-alike of the real package',
                      'check the name against the project\'s own README; if it is the right package, fix "packages" in the run block')
    return dict(registry=registry, name=name, version=ver, page=page, repository=expected, published=published or None)


# ------------------------------------------------------------------ the throwaway folder
def kill_tree(p):
    if p.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)
        if p.poll() is None:
            p.kill()
    else:
        p.kill()
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass


def processes_under(path):
    """PIDs of processes whose command line names the throwaway folder (Windows; elsewhere none is looked for). The reading-back of 'nothing is left running'."""
    if os.name != 'nt':
        return []
    p = str(path).lower().replace("'", "''")
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine.ToLower().Contains('" + p + "') } | ForEach-Object { $_.ProcessId }")
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', ps], capture_output=True, text=True, timeout=60)
    return [int(x) for x in r.stdout.split() if x.isdigit()]


def scrubbed_env(work, venv_scripts=None, base=None):
    """A fresh environment: a short allow list of the machine's variables, nothing whose name holds KEY, TOKEN, SECRET (and kin), every home and temp folder inside the
    throwaway folder, the official registries only, no install scripts, wheels only."""
    base = os.environ if base is None else base
    env = {k: v for k, v in ((k.upper(), v) for k, v in base.items()) if k in ENV_KEEP and not SECRET_NAME.search(k)}
    repo = str(REPO).lower()
    parts = [x for x in env.get('PATH', '').split(os.pathsep) if x and not str(Path(x).resolve()).lower().startswith(repo)]
    if venv_scripts:
        parts.insert(0, str(venv_scripts))
    env['PATH'] = os.pathsep.join(parts)
    home = Path(work) / 'home'
    roaming, local = 'APP' + 'DATA', 'LOCAL' + 'APP' + 'DATA'      # the Windows per-user folder variables, written in pieces so no machine-specific word sits in the source
    for d in ('tmp', 'npm-cache', 'pip-cache', 'roaming', 'local'):
        (home / d).mkdir(parents=True, exist_ok=True)
    env.update({roaming: str(home / 'roaming'), local: str(home / 'local')}, USERPROFILE=str(home), HOME=str(home), TEMP=str(home / 'tmp'), TMP=str(home / 'tmp'), TMPDIR=str(home / 'tmp'),
               PIP_INDEX_URL=PYPI_INDEX, PIP_CONFIG_FILE=os.devnull, PIP_REQUIRE_VIRTUALENV='1', PIP_ONLY_BINARY=':all:', PIP_NO_INPUT='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
               PIP_CACHE_DIR=str(home / 'pip-cache'), PYTHONNOUSERSITE='1', PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               npm_config_registry=NPM_REGISTRY, npm_config_ignore_scripts='true', npm_config_userconfig=str(home / 'userrc'), npm_config_globalconfig=str(home / 'globalrc'),
               npm_config_cache=str(home / 'npm-cache'), npm_config_update_notifier='false', npm_config_progress='false', npm_config_yes='false')
    if venv_scripts:
        env['VIRTUAL_ENV'] = str(Path(venv_scripts).parent)
    leaked = [k for k in env if SECRET_NAME.search(k)]
    if leaked:
        raise Refusal('environment', f'the scrubbed environment still holds {", ".join(leaked)}', 'tell the coordinator')
    return env


def remove_tree(path, tries=5):
    def onerr(func, p, _):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    for n in range(tries):
        shutil.rmtree(path, onerror=onerr)
        if not Path(path).exists():
            return True
        time.sleep(1 + n)
    return not Path(path).exists()


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def read_log(path):
    try:
        return Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def clean_output(text):
    """The lines of a log as a terminal would leave them: escape codes dropped, a carriage return overwrites its line, tabs spread, blank lines and trailing spaces dropped."""
    out = []
    for line in ANSI.sub('', text.replace('\r\n', '\n')).split('\n'):
        line = line.split('\r')[-1].expandtabs(4).rstrip()
        if line.strip():
            out.append(line)
    return out


# ------------------------------------------------------------------ rows and pictures
def wrap(text, cols, indent=''):
    """Greedy wrap at spaces; a word longer than a row is cut. Continuation rows carry `indent`."""
    rows, cur = [], ''
    for word in text.split(' '):
        while len(word) > cols - (len(indent) if rows else 0):
            room = cols - (len(indent) if rows else 0) - len(cur)
            if cur and room < 8:
                rows.append(cur)
                cur = indent
                continue
            head, word = word[:room], word[room:]
            cur += head
            rows.append(cur)
            cur = indent
        add = (' ' if cur.strip() else '') + word
        if len(cur) + len(add) > cols:
            rows.append(cur)
            cur = indent + word
        else:
            cur += add
    rows.append(cur)
    return [r.rstrip() for r in rows]


def build_rows(cmd, output_lines, max_rows, cols=COLS):
    """The terminal of one step: the prompt and command, then the end of the real output. Whole earlier lines are dropped behind a marked row; a last line too long to fit is
    cut and marked with `...`. Returns rows [{kind, text}] and the number of lines left out."""
    rows = [dict(kind='cmd', text=t) for t in wrap('$ ' + cmd, cols, '  ')]
    if len(rows) > max_rows // 2:
        raise Refusal('too-tall', f'the command "{cmd}" needs {len(rows)} rows of {cols} characters', 'use a shorter command or raise run.max_rows')
    room = max_rows - len(rows)
    lines = [wrap(x, cols, '  ') for x in output_lines]
    keep, used = [], 0
    for ls in reversed(lines):
        if used + len(ls) > room - (1 if len(keep) < len(lines) else 0) and keep:
            break
        if used + len(ls) > room:
            ls = ls[:max(room - 1, 1)] if room > 1 else ls[:1]
            ls[-1] = ls[-1][:cols - 3].rstrip() + '...'
        keep.insert(0, ls)
        used += len(ls)
    dropped = len(lines) - len(keep)
    if dropped:
        # the marker takes a row: drop more lines from the front if the kept ones now leave no room for it
        while keep and used + 1 > room:
            used -= len(keep.pop(0))
            dropped += 1
        rows.append(dict(kind='note', text=f'[... {dropped} earlier lines]'))
    rows += [dict(kind='out', text=t) for ls in keep for t in ls]
    return rows, dropped


def layout(rows, bands):
    """The picture's geometry: focus rows, shown rows, and a rect for each phrase of `bands` that lies on one row. Pure; the numbers are where `draw` puts the ink."""
    top = PAD_Y
    foc = [top, top + len(rows) * LINE_H]
    height = foc[1] + PAD_Y
    found, marks = [], []
    for ph in bands:
        hit = [(i, r['text'].find(ph)) for i, r in enumerate(rows) if r['kind'] != 'note' and ph in r['text']]
        if not hit:
            raise Refusal('band', f'"{ph}" is not on one row of the picture of this step', 'the highlighted words must be in the output that is shown (and not wrapped over two rows)')
        i, c = hit[-1]
        found.append(dict(rect=[PAD_X + c * CHAR_W, top + i * LINE_H, len(ph) * CHAR_W, LINE_H], text=ph))
        marks.append((i, c, len(ph)))
    return dict(height=height, focus=foc, u_rows=[foc[0] - 24, foc[1] + 12], bands=found, marks=marks)


def check_text_size():
    px = FONT_PX * PIC_W / WIDTH
    if px < MIN_FRAME_PX:
        raise Refusal('text-size', f'text would be {px:.1f} px on the frame, under {MIN_FRAME_PX}', 'use a larger font in the picture')
    return px


def check_glyphs(rows):
    sys.path.insert(0, str(HERE))
    import importlib.util
    s = importlib.util.spec_from_file_location('halcyon_kich_ban_glyphs', HERE / 'halcyon_kich_ban.py')
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    have = m.font_chars(FONT)
    miss = sorted({c for r in rows for c in r['text'] if ord(c) not in have and not c.isspace()})
    if miss:
        raise Refusal('glyph', f'the terminal font has no glyph for {" ".join(repr(c) for c in miss)}', 'the real output holds a character the font cannot draw: choose another step or trim it')


def draw(rows, geo, path):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(str(FONT), FONT_PX)
    img = Image.new('RGB', (WIDTH, geo['height']), BG)
    d = ImageDraw.Draw(img)
    for i, r in enumerate(rows):
        y = PAD_Y + i * LINE_H + BASE_UP
        for c, ch in enumerate(r['text']):
            if ch == ' ':
                continue
            col = (MARK if any(i == mi and mc <= c < mc + ml for mi, mc, ml in geo['marks']) else PROMPT if (r['kind'] == 'cmd' and i == 0 and c == 0)
                   else CMD if r['kind'] == 'cmd' else NOTE if r['kind'] == 'note' else OUT)
            d.text((PAD_X + c * CHAR_W, y), ch, font=font, fill=col, anchor='ls')
    img.save(path, optimize=True)   # a phrase to highlight is drawn in MARK here: the builder's highlighter is made for light pages and hardly shows on this dark one
    return img.size


# ------------------------------------------------------------------ the run
def start(argv, cwd, env, log):
    exe = shutil.which(argv[0], path=env['PATH'])
    if not exe:
        raise Refusal('command', f'"{argv[0]}" is not on the PATH of the throwaway environment', 'install the tool on the machine (python, node and npm are needed)')
    if Path(exe).resolve().as_posix().lower().startswith(REPO.as_posix().lower()):
        raise Refusal('location', f'"{exe}" is inside the repository checkout; nothing runs from there', 'tell the coordinator')
    p = subprocess.Popen([exe] + argv[1:], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    cast = Path(log).with_suffix('.cast')
    began = time.monotonic()
    def record():
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        with p.stdout, open(log, 'wb') as f, open(cast, 'w', encoding='utf-8', newline='\n') as c:
            while True:
                chunk = p.stdout.read1(4096)
                if not chunk:
                    break
                f.write(chunk)
                f.flush()
                value = decoder.decode(chunk)
                if value:
                    c.write(json.dumps([round(time.monotonic() - began, 6), value], ensure_ascii=False) + '\n')
            value = decoder.decode(b'', final=True)
            if value:
                c.write(json.dumps([round(time.monotonic() - began, 6), value], ensure_ascii=False) + '\n')
    p._reader = threading.Thread(target=record, daemon=True)
    p._reader.start()
    return p


def read_cast(path, log):
    """Read a timestamped pipe recording and prove it reproduces the saved output."""
    events = [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]
    if any(not isinstance(e, list) or len(e) != 2 or not isinstance(e[0], (int, float)) or e[0] < 0 or
           not isinstance(e[1], str) for e in events):
        raise Refusal('cast', f'{path} has an invalid event')
    if any(b[0] < a[0] for a, b in zip(events, events[1:])):
        raise Refusal('cast', f'{path} timestamps run backward')
    if ''.join(e[1] for e in events) != Path(log).read_bytes().decode('utf-8', errors='replace'):
        raise Refusal('cast', f'{path} does not reproduce {log}')
    return events


def footage_timeline(steps, budget=18.0, hold=2.5):
    """Pure playback plan. Each step is typed, then its recorded output arrives at its original offsets."""
    if not steps or budget <= hold:
        raise Refusal('footage', 'a block needs steps and room for its final hold')
    real = sum(len(s['cmd']) / 18 + max(s['seconds'], s['events'][-1][0] if s['events'] else 0) for s in steps)
    speed = max(1, math.ceil(real / (budget - hold)))
    at, segments = 0.0, []
    for s in steps:
        typing = len(s['cmd']) / 18
        recorded = max(s['seconds'], s['events'][-1][0] if s['events'] else 0)
        length = typing + recorded
        segments.append(dict(name=f'step-{s["index"]}', a=at, b=at + length / speed,
                             speed=speed, real_s=round(recorded, 6), typing_s=typing, step=s))
        at += length / speed
    return segments, at + hold


def speed_label(speed):
    return 'TỐC ĐỘ THẬT x1' if speed == 1 else f'TUA NHANH x{speed}'


def draw_footage_frame(segment, local_s, real_clock, width=762, height=850, max_rows=MAX_ROWS):
    """Draw terminal ink at final clip pixels, with the original font and colours."""
    from PIL import Image, ImageDraw, ImageFont
    cmd = segment['step']['cmd']
    real_t = max(0, local_s * segment['speed'])
    typed = cmd[:min(len(cmd), int(real_t * 18))]
    output_t = real_t - segment['typing_s']
    output = ''.join(value for t, value in segment['step']['events'] if t <= output_t)
    rows, _ = build_rows(typed, clean_output(output), max_rows)
    img = Image.new('RGB', (width, height), BG)
    d = ImageDraw.Draw(img)
    mono = ImageFont.truetype(str(FONT), 31)
    label_font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf' if os.name == 'nt' else 'DejaVuSans.ttf', 30)
    d.text((37, 18), speed_label(segment['speed']), font=label_font, fill=MARK)
    d.text((width - 38, 18), f'{real_clock:05.1f}s', font=label_font, fill=CMD, anchor='ra')
    d.line((37, 65, width - 37, 65), fill=NOTE, width=2)
    for i, row in enumerate(rows):
        y = 111 + i * 57
        if y + 31 > height - 20:
            raise Refusal('footage', 'terminal rows do not fit the clip window')
        for c, ch in enumerate(row['text']):
            if ch != ' ':
                amber = any(ch != ' ' and c >= pos and c < pos + len(ph) for ph in segment['step'].get('expect', [])
                            for pos in [row['text'].find(ph)] if pos >= 0)
                color = MARK if amber else PROMPT if row['kind'] == 'cmd' and i == 0 and c == 0 else CMD if row['kind'] == 'cmd' else NOTE if row['kind'] == 'note' else OUT
                d.text((38 + c * 19, y), ch, font=mono, fill=color)
    return img


def make_footage(run_dir, first_step, last_step, out=None, ffmpeg=None, encoder='h264_nvenc', manifest_name='clip.json'):
    """Create one silent block from inclusive step indexes in a completed chay run.

    Returns the manifest path. `out` defaults to `<run_dir>/clip-<first>-<last>`.
    `ffmpeg` names the installed encoder executable; `encoder` permits offline CPU validation.
    """
    run_dir = Path(run_dir).resolve()
    data = json.loads((run_dir / 'chay.json').read_text(encoding='utf-8'))
    states = data['states']
    if not (0 <= first_step <= last_step < len(states)):
        raise Refusal('footage', 'the requested step range is outside this run')
    steps = []
    for state in states[first_step:last_step + 1]:
        n = state['step']
        log = run_dir / 'log' / f'step-{n}.log'
        events = read_cast(log.with_suffix('.cast'), log)
        steps.append(dict(index=n, cmd=state['cmd'], seconds=state['seconds'], events=events,
                          expect=next(s['expect'] for s in data['steps'] if s['index'] == n)))
    max_rows = data.get('max_rows', MAX_ROWS)
    check_glyphs([dict(kind='out', text=line) for s in steps
                  for line in clean_output(''.join(v for _, v in s['events']))] +
                 [r for s in steps for r in build_rows(s['cmd'], [], max_rows)[0]])
    segments, duration = footage_timeline(steps)
    fps, width, height = 25, 762, 850
    frames = math.ceil(duration * fps)
    if frames / fps > 40:
        raise Refusal('footage', 'the block exceeds the clip duration limit')
    out = Path(out).resolve() if out else run_dir / f'clip-{first_step}-{last_step}'
    out.mkdir(parents=True, exist_ok=True)
    video = out / ('terminal.mp4' if manifest_name == 'clip.json' else f'terminal-{first_step}-{last_step}.mp4')
    executable = ffmpeg or shutil.which('ffmpeg')
    if not executable:
        raise Refusal('footage', 'ffmpeg is unavailable', 'pass ffmpeg=<installed executable>')
    command = [str(executable), '-y', '-loglevel', 'error', '-nostats', '-f', 'image2pipe', '-vcodec', 'png', '-r', str(fps),
               '-i', '-', '-an', '-c:v', encoder, '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)]
    p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for frame in range(frames):
            t = frame / fps
            seg = next((s for s in segments if t < s['b']), segments[-1])
            local = min(max(0, t - seg['a']), seg['b'] - seg['a'])
            clock = sum(s['real_s'] for s in segments if s['b'] <= t) + min(seg['real_s'], max(0, local * seg['speed'] - seg['typing_s']))
            img = draw_footage_frame(seg, local, clock, width, height, max_rows)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            try:
                p.stdin.write(buf.getvalue())
            except BrokenPipeError:
                raise Refusal('footage', 'ffmpeg stopped before it could read the frames: ' +
                              p.stderr.read().decode('utf-8', errors='replace')[-500:])
        p.stdin.close()
        error = p.stderr.read().decode('utf-8', errors='replace')
        if p.wait() != 0:
            raise Refusal('footage', f'ffmpeg failed: {error[-500:]}')
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stderr.close()
    manifest = dict(file=video.name, w=width, h=height, fps=fps, frames=frames, duration=frames / fps,
                    bg=list(BG), min_text_px=30, captured=data['captured'], source=str(run_dir / 'chay.json'),
                    date=datetime.now(TZ).strftime('%d/%m/%Y'), tool_sha=sha(Path(__file__).read_bytes()),
                    stills=[dict(t=0.4, label='command'), dict(t=max(0, frames / fps - 1.0), label='result')],
                    segments=[{k: s[k] for k in ('name', 'a', 'b', 'speed', 'real_s')} for s in segments],
                    proof=dict(cast_logs=[sha((run_dir / 'log' / f'step-{s["index"]}.cast').read_bytes()) for s in steps],
                               step_range=[first_step, last_step], real_seconds=sum(s['real_s'] for s in segments)))
    path = out / manifest_name
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    return path


def tool_version(argv, cwd, env):
    try:
        r = subprocess.run([shutil.which(argv[0], path=env['PATH'])] + argv[1:], cwd=cwd, env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        return (r.stdout or r.stderr).strip().splitlines()[0][:100]
    except (OSError, IndexError, subprocess.TimeoutExpired, TypeError):
        return 'unknown'


def footage_blocks(job):
    """Validate the chain's inclusive, consecutive step lists before starting a run."""
    blocks = job.get('blocks', [])
    if not isinstance(blocks, list):
        raise Refusal('footage', 'blocks must be a list of step lists')
    count = len(job['run'].get('steps', []))
    for block in blocks:
        if (not isinstance(block, list) or not block or
                any(type(n) is not int or n < 0 or n >= count for n in block) or
                any(b != a + 1 for a, b in zip(block, block[1:]))):
            raise Refusal('footage', 'each block must contain consecutive step indexes in range')
    return blocks


def run(job, out, fetch_text=lambda u: http_get(u, 'text/plain'), fetch_json=http_json, say=print):
    """Everything, in order: no-network checks, the documents, the packages, the files, the steps, the stills. Returns the chay.json dict."""
    ref = job['ref']
    spec = check_run(job['run'])
    clip_blocks = footage_blocks(job)
    out = Path(out).resolve()
    work = out / 'work'
    if REPO in (out, *out.parents) or str(out).lower().startswith(str(REPO).lower() + os.sep):
        raise Refusal('location', f'{out} is inside the repository checkout; the run folder must be outside it', 'use a --out folder outside the repository')
    check_text_size()
    shutil.rmtree(out, ignore_errors=True)
    (out / 'log').mkdir(parents=True)
    work.mkdir()
    servers, procs, started = [], [], time.time()
    notes = ['blank lines are dropped, escape codes removed, a carriage return overwrites its line, tabs become spaces',
             'only the end of a long output is drawn: the marked row says how many earlier lines were left out']
    result = dict(ref=ref, started=now_iso(), max_rows=spec['max_rows'])
    try:
        # the documents and the files taken from their fenced blocks
        docs, blocks = {}, {}
        for f in spec['files']:
            if f['from'] not in docs:
                raw = fetch_text(f['from'])
                raw = raw if isinstance(raw, bytes) else raw.encode('utf-8')
                docs[f['from']] = dict(sha256=sha(raw), bytes=len(raw))
                blocks[f['from']] = fenced_blocks(raw.decode('utf-8', errors='replace'))
        files_out = []
        for f in spec['files']:
            text = take_fence(blocks[f['from']], f['fence'], f['name'])
            dest = work / f.get('dir', '.') / f['name']
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(text.encode('utf-8'))
            files_out.append(dict(name=f['name'], dir=f.get('dir', '.'), source=f['from'], fence=f['fence'], sha256=sha(text.encode('utf-8')), lines=text.count('\n')))
        # the packages: named by the source's own blocks, then checked at their official registry
        toks = set().union(*(fence_tokens(b) for b in blocks.values()))
        vetted = {}
        for st in spec['steps']:
            for p in st['packages']:
                bare = re.sub(r'==\d.*$', '', p) if st['registry'] == 'pypi' else re.sub(r'(?<=.)@\d.*$', '', p)
                if bare not in toks:
                    raise Refusal('package-source', f'"{bare}" is not named in any fenced block of the source', 'only packages the source\'s own commands name may be installed')
                if p not in vetted:
                    vetted[p] = vet_package(st['registry'], p, spec['packages'].get(bare) or spec['project'], fetch_json)
                    say(f'  checked {st["registry"]} {vetted[p]["name"]} {vetted[p]["version"]} ({vetted[p]["repository"]})')
        # ports free, environment
        for st in spec['steps']:
            if st['serve'] and st['port'] and port_busy(st['port']):
                raise Refusal('port', f'port {st["port"]} is already in use on this machine', 'stop what holds the port (find it with Get-NetTCPConnection -LocalPort ' + str(st['port']) + ') and run again')
        need_py = any(s['form'] in ('pip-install', 'uvicorn', 'python') for s in spec['steps'])
        env = scrubbed_env(work)
        scripts = None
        if need_py:
            r = subprocess.run([sys.executable, '-m', 'venv', str(work / '.venv')], env=env, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
            scripts = work / '.venv' / ('Scripts' if os.name == 'nt' else 'bin')
            if r.returncode or not scripts.exists():
                raise Refusal('venv', f'could not make the Python environment: {(r.stderr or r.stdout).strip()[-300:]}', 'tell the coordinator')
            env = scrubbed_env(work, scripts)
        states = []
        # the steps
        for st in spec['steps']:
            cwd = work / st['cwd']
            cwd.mkdir(parents=True, exist_ok=True)
            log = out / 'log' / f'step-{st["index"]}.log'
            t0 = time.time()
            p = start(st['argv'], cwd, env, log)
            procs.append(p)
            if st['serve']:
                servers.append(p)
                end = time.time() + READY_DEADLINE
                while time.time() < end and st['ready'] not in read_log(log) and p.poll() is None:
                    time.sleep(0.3)
                text = read_log(log)
                if st['ready'] not in text:
                    raise Refusal('serve', f'step {st["index"]} ({st["cmd"]}) never printed "{st["ready"]}" (exit {p.poll()}):\n    ' + '\n    '.join(clean_output(text)[-6:]), 'the server did not start: read the log in the run folder')
                if st['port'] and not port_busy(st['port']):
                    raise Refusal('serve', f'step {st["index"]} printed "{st["ready"]}" but nothing listens on port {st["port"]}', 'fix "port"')
                code = None
            else:
                try:
                    code = p.wait(timeout=st['deadline'])
                except subprocess.TimeoutExpired:
                    kill_tree(p)
                    raise Refusal('deadline', f'step {st["index"]} ({st["cmd"]}) ran over its {st["deadline"]} second deadline and was killed', 'run again; if it repeats, the step does not finish by itself')
                p._reader.join()
                text = read_log(log)
                if code:
                    raise Refusal('exit', f'step {st["index"]} ({st["cmd"]}) exited with {code}:\n    ' + '\n    '.join(clean_output(text)[-8:]), 'a follow-along shows only commands that succeed: fix the step or the run block')
            lines = clean_output(text)
            miss = [x for x in st['expect'] if x not in '\n'.join(lines)]
            if miss:
                raise Refusal('expect', f'step {st["index"]} ({st["cmd"]}) did not print "{miss[0]}"; its real output ends:\n    ' + '\n    '.join(lines[-6:]), 'change "expect" to what the command really prints, or fix the step')
            st.update(code=code, seconds=round(time.time() - t0, 1), lines=lines)
        # after the steps: where every download came from, what was installed
        origin_bad = []
        for st in spec['steps']:
            for m in re.finditer(r'https?://([\w.-]+)', '\n'.join(st['lines'])):
                if m.group(1) not in DOWNLOAD_HOSTS and m.group(1) not in ('127.0.0.1', 'localhost') and st['registry']:
                    origin_bad.append(m.group(1))
        if origin_bad:
            raise Refusal('registry', f'an install printed an address outside the official registries: {origin_bad[0]}', 'packages come from pypi.org and registry.npmjs.org only')
        pins = dict(pip={}, npm={})
        if need_py:
            r = subprocess.run([str(scripts / ('python.exe' if os.name == 'nt' else 'python')), '-m', 'pip', 'freeze', '--all'], env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
            pins['pip'] = {l.split('==')[0].lower(): l.split('==')[1] for l in r.stdout.splitlines() if '==' in l}
        audit = {}
        for lock in sorted(work.rglob('package-lock.json')):
            if 'node' + '_modules' in lock.parts:
                continue
            data = json.loads(lock.read_text(encoding='utf-8'))
            cwdk = str(lock.parent.relative_to(work)).replace('\\', '/')
            pins['npm'][cwdk] = {k.split('node' + '_modules/')[-1]: v.get('version') for k, v in data.get('packages', {}).items() if k}
            bad = [k for k, v in data.get('packages', {}).items() if k and v.get('resolved') and not v['resolved'].startswith(NPM_REGISTRY)]
            if bad:
                raise Refusal('registry', f'npm resolved {bad[0]} from {data["packages"][bad[0]]["resolved"]}, not from {NPM_REGISTRY}', 'packages come from the official registry only')
            r = subprocess.run([shutil.which('npm', path=env['PATH']), 'audit', '--omit=dev', '--json'], cwd=lock.parent, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
            try:
                audit[cwdk] = json.loads(r.stdout).get('metadata', {}).get('vulnerabilities', {})
            except ValueError:
                audit[cwdk] = 'npm audit gave no result'
        audit['pip'] = 'pip-audit is not installed: versions recorded only' if not (scripts and shutil.which('pip-audit', path=str(scripts))) else 'pip-audit present but not run by the chain'
        warns = []
        for k, v in audit.items():
            if isinstance(v, dict) and v.get('total'):
                warns.append(f'warning: npm audit ({k}) reports {v["total"]} known vulnerabilities in what this run installed: {v}')
        installed = {}
        for p, rec in vetted.items():
            have = pins['pip'].get(rec['name'].lower().replace('_', '-')) if rec['registry'] == 'pypi' else next((m.get(rec['name']) for m in pins['npm'].values() if m.get(rec['name'])), None)
            if have != rec['version']:
                raise Refusal('version', f'{rec["name"]}: checked {rec["version"]} but the install holds {have}', 'the registry moved during the run, or the latest does not fit this Python: run again, or pin the version in the command (name==1.2.3 or name@1.2.3)')
            installed[p] = dict(rec, installed=have)
        result['tools'] = dict(python=tool_version(['python', '--version'], work, env) if need_py else None, node=tool_version(['node', '--version'], work, env), npm=tool_version(['npm', '--version'], work, env))
        # the pictures
        every = [r for st in spec['steps'] for r in build_rows(st['cmd'], st['lines'], spec['max_rows'])[0]]
        check_glyphs(every)
        captured = now_iso()
        for st in spec['steps']:
            rows, dropped = build_rows(st['cmd'], st['lines'], spec['max_rows'])
            geo = layout(rows, job.get('bands', {}).get(str(st['index']), []))
            png = out / f's{st["index"]}.png'
            size = draw(rows, geo, png)
            text = '\n'.join(r['text'] for r in rows)
            states.append(dict(step=st['index'], cmd=st['cmd'], cwd=st['cwd'], serve=st['serve'], exit=st['code'], seconds=st['seconds'], lines_total=len(st['lines']), lines_left_out=dropped,
                               output=st['lines'][-60:], rows=rows, picture=png.name, size=list(size),
                               entry=dict(file=png.name, focus=dict(rows=geo['focus']), u_rows=geo['u_rows'], source='Chạy thật trên máy Halcyon', date=datetime.now(TZ).strftime('%d/%m/%Y'),
                                          captured=captured, bands=geo['bands'], text=text)))
        result.update(finished=now_iso(), captured=captured, files=files_out, documents=docs, packages=installed, pins=pins, audit=audit, warnings=warns, notes=notes, states=states,
                      environment=dict(passed=sorted(env), registries=[PYPI_INDEX, NPM_REGISTRY], install_scripts='ignored (npm ignore-scripts)', python_wheels_only=True),
                      steps=[dict(index=s['index'], cmd=s['cmd'], cwd=s['cwd'], exit=s['code'], seconds=s['seconds'], serve=s['serve'], expect=s['expect']) for s in spec['steps']])
    finally:
        for p in servers:
            kill_tree(p)
        for q in procs:
            kill_tree(q)
            try:
                q._reader.join(timeout=5)
            except (OSError, AttributeError):
                pass
        left = processes_under(work)
        for pid in left:
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        result['leftover_processes_killed'] = len(left)
        result['leftover_processes_after'] = len(processes_under(work))
        gone = remove_tree(work)
        result['throwaway_folder_deleted'] = gone
        result['seconds'] = round(time.time() - started, 1)
        if 'states' in result:
            (out / 'chay.json').write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    if result['leftover_processes_after']:
        raise Refusal('leftover', f'{result["leftover_processes_after"]} process(es) still run from the throwaway folder', 'tell the coordinator; stop them before anything else')
    if not gone:
        result['warnings'].append(f'warning: the throwaway folder {work} could not be deleted')
    for block in clip_blocks:
        name = 'clip-' + '-'.join(map(str, block)) + '.json'
        make_footage(out, block[0], block[-1], out=out, manifest_name=name)
    return result


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--job', required=True)
    r.add_argument('--out', required=True)
    f = sub.add_parser('footage')
    f.add_argument('--run', required=True)
    f.add_argument('--first', required=True, type=int)
    f.add_argument('--last', required=True, type=int)
    f.add_argument('--out')
    f.add_argument('--ffmpeg')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'footage':
            print(make_footage(a.run, a.first, a.last, out=a.out, ffmpeg=a.ffmpeg))
            return 0
        job = json.loads(Path(a.job).read_text(encoding='utf-8'))
        res = run(job, a.out)
    except Refusal as e:
        print(e, file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f'chay: job: {e}', file=sys.stderr)
        return 2
    for w in res.get('warnings', []):
        print(w)
    print(f'chay: {res["ref"]}: {len(res["states"])} step(s) ran for real in {res["seconds"]} s; {len(res["packages"])} package(s) checked and pinned; '
          f'{res["leftover_processes_after"]} process(es) left; throwaway folder deleted: {res["throwaway_folder_deleted"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
