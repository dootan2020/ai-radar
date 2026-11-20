"""Assemble a Halcyon builder spec (video.json) from a script, the voice timing and a capture manifest. Standard library only.

    python halcyon_kich_ban.py kich-ban.json --timing giong-day-du-timing.json [--captures captures.json] --out video.json

The contract (inputs, what each spec field comes from, every refusal) is in KICH-BAN.md. A person's or agent's choice lives in the script
only; anything a rule cannot know may be written there and then wins over the rule. Every step is right or stops with `kich-ban: ...`
and a message that says what to change; nothing is guessed silently."""
import difflib
import json
import os
import re
import struct
import sys
import unicodedata
from pathlib import Path

LEAD = 0.08                      # the builder lights a word 0.08 s before its Whisper start (dung-video-gpu.LEAD)
TAIL = 0.70                      # silence after the voice; published tails were 0.68-0.72
CHIP_MAX = 43                    # a chip longer than this does not fit at 21 px (measured 18/11)
LAYOUT, FIELDS = 'thu-gon-r3-l2', ('layout', 'drop_kickers')
ROOT = Path(__file__).resolve().parents[2]
FONTS = {'caps': [Path(__file__).parent / 'fonts' / 'BarlowCondensed-Bold.ttf', Path(__file__).parent / 'fonts' / 'BarlowCondensed-ExtraBold.ttf'],
         'small': [ROOT / 'brand' / 'fonts' / 'BeVietnamPro-Medium.ttf', ROOT / 'brand' / 'fonts' / 'BeVietnamPro-SemiBold.ttf']}
SENT_END = re.compile(r'[.?!…]["”’)]*$')
DIGITS = re.compile(r'\d+(?:[.,:]\d+)*')
# the repo beat: a walk through the pages of a GitHub repository (the recorder takes a still of each page, the builder plays them)
REPO_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}')
BRANCH_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9._/-]{0,199}')
MAX_OPEN = 5                     # entries in one repo beat, and distinct paths over all beats of one repo (the recorder loads at most six pages per repo)
# Least seconds a page stays on screen, by the window the beat is drawn in (HOOK is the short window of the opening beat, FOOT the tall one). Each
# value is the least the builder's camera needs (measured on PR #277: home 2.05 / 3.05, a page whose next row needs a pan 2.1 / 3.15, a slide back
# 1.05, the last page 0.6, and the opening whole-width glimpse 2.25 / 2.9 on top of the home page) plus 0.1 s, because `a` is rounded to 0.01 s and
# the builder counts whole frames. They are the worst case (a row that needs a pan), so a script that passes `--chi-kiem` is never refused by
# the builder for time. `last` is a page nothing is opened from (the last page of the beat, or one followed by a slide back).
FLOOR = dict(FOOT=dict(home=2.15, tap=2.2, back=1.15, last=0.7, glimpse=2.25),
             HOOK=dict(home=3.15, tap=3.25, back=1.15, last=0.7, glimpse=2.9))
OPEN_KEYS = ('path', 'anchor', 'occurrence', 'chain')


def fail(msg):
    raise SystemExit(f'kich-ban: {msg}')


def need(d, key, where):
    if not isinstance(d, dict) or key not in d or d[key] in (None, ''):
        fail(f'{where}.{key} is missing')
    return d[key]


# ---------------- words: the builder's own normalisation, so a match here is a match there ----------------
def bnorm(aliases, s):
    s = s.lower().strip(',.:;?!“”"%*')
    return aliases.get(s, aliases.get(s.replace('.', ''), s.replace('.', '')))


def nrm(aliases, w):
    return unicodedata.normalize('NFC', re.sub(r'[^\w]', '', bnorm(aliases, w).lower()))


def plain(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w]+', ' ', unicodedata.normalize('NFC', s).lower())).strip()


def slugify(title):
    t = unicodedata.normalize('NFD', title.lower().replace('đ', 'd'))
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', ''.join(c for c in t if unicodedata.category(c) != 'Mn'))).strip('-')


def align(display, heard, aliases):
    """display token i -> index of the heard word it matches, or None (difflib over the normalised words, as the builder's map_words)."""
    nd = [nrm(aliases, w) for w in display]; nh = [nrm(aliases, h['w']) for h in heard]
    sm = difflib.SequenceMatcher(None, nd, nh, autojunk=False)
    idx = [None] * len(display)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            idx[a + k] = b + k
    return idx, sm


def derive_aliases(display, heard, aliases):
    """Spelling differences between the script and Whisper that normalisation does not remove: alias the display word to the heard one, pairing
    the two sides of every mismatching block position by position. Returns the new aliases (never overriding one the script gave)."""
    out = dict(aliases)
    for _ in range(2):
        _, sm = align(display, heard, out)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != 'replace':
                continue
            same = (i2 - i1) == (j2 - j1)          # unequal blocks ("10,5 giây" heard as "10 5 x"): only the first words are the same word
            for k in range(min(i2 - i1, j2 - j1) if same else 1):
                key = display[i1 + k].lower().strip(',.:;?!“”"%*'); val = heard[j1 + k]['w'].lower().strip(',.:;?!“”"%*')
                if key and val and key not in out and nrm({}, key) != nrm({}, val):
                    out[key] = val
    return out


# ---------------- Vietnamese number words (for the digits-versus-voice check) ----------------
DIG = {'không': 0, 'một': 1, 'mốt': 1, 'hai': 2, 'ba': 3, 'bốn': 4, 'tư': 4, 'năm': 5, 'lăm': 5, 'sáu': 6, 'bảy': 7, 'tám': 8, 'chín': 9}


def spoken_values(say):
    vals, run = set(), []
    words = [w for clause in re.split(r'[,.;:?!…]', say) for w in plain(clause).split() + ['.']]   # a comma ends a number: "hai, ba" is 2 and 3
    for w in words:
        if w in DIG or w in ('mười', 'mươi', 'trăm', 'linh', 'lẻ', 'nghìn', 'ngàn'):
            run.append(w); continue
        if run:
            total = part = 0; pend = None
            for r in run:
                if r in DIG:
                    if pend is not None:
                        part += pend
                    pend = DIG[r]
                elif r == 'mười':
                    if pend is not None:
                        part += pend
                    pend = 10
                elif r == 'mươi':
                    part += (pend or 1) * 10; pend = None
                elif r == 'trăm':
                    part += (pend or 1) * 100; pend = None
                elif r in ('nghìn', 'ngàn'):
                    total += (part + (pend or 0) or 1) * 1000; part = 0; pend = None
            vals.add(total + part + (pend or 0)); run = []
    return vals


def check_digits(texts, say, numbers, where):
    """Every digit group shown must be spoken: written the same in the voice text, the value of number words in it, or declared in `numbers`."""
    values = spoken_values(say); sp = plain(say)
    for t in texts:
        for g in DIGITS.findall(t):
            if g in numbers:
                if plain(numbers[g]) not in sp:
                    fail(f'{where}: numbers["{g}"] says "{numbers[g]}", which is not in the voice text of this paragraph')
                continue
            if g in say or (g.isdigit() and int(g) in values):
                continue
            fail(f'{where}: "{g}" is on screen in "{t}" but the voice does not say it (the voice text has no "{g}" and no number words with that value); '
                 f'fix the script, or declare how it is spoken: numbers: {{"{g}": "<the words in the voice text>"}}')


# ---------------- glyphs: read the fonts' cmap tables, so a missing glyph is refused instead of drawn as .notdef ----------------
def font_chars(path):
    d = Path(path).read_bytes()
    nt = struct.unpack('>H', d[4:6])[0]; off = None
    for i in range(nt):
        tag, _, o, _ = struct.unpack('>4sIII', d[12 + 16 * i:28 + 16 * i])
        if tag == b'cmap':
            off = o
    if off is None:
        fail(f'font {Path(path).name} has no cmap table')
    chars = set()
    for i in range(struct.unpack('>H', d[off + 2:off + 4])[0]):
        pid, eid, so = struct.unpack('>HHI', d[off + 4 + 8 * i:off + 12 + 8 * i]); s = off + so
        fmt = struct.unpack('>H', d[s:s + 2])[0]
        if fmt == 4:
            sc = struct.unpack('>H', d[s + 6:s + 8])[0] // 2
            ends = struct.unpack(f'>{sc}H', d[s + 14:s + 14 + 2 * sc]); starts = struct.unpack(f'>{sc}H', d[s + 16 + 2 * sc:s + 16 + 4 * sc])
            for a, b in zip(starts, ends):
                chars.update(range(a, b + 1))
        elif fmt == 12:
            for g in range(struct.unpack('>I', d[s + 12:s + 16])[0]):
                a, b, _ = struct.unpack('>III', d[s + 16 + 12 * g:s + 28 + 12 * g]); chars.update(range(a, b + 1))
    chars.discard(0xFFFF)
    return chars


def check_glyphs(strings, cls_fonts=FONTS):
    """strings: [(class, where, text)]; class caps (Barlow, drawn upper-case) or small (Be Vietnam Pro)."""
    have = {c: [font_chars(p) for p in ps] for c, ps in cls_fonts.items()}
    for cls, where, text in strings:
        for ch in (text.upper() if cls == 'caps' else text):
            if ch.isspace() or ch == '/':
                continue
            for p, cs in zip(cls_fonts[cls], have[cls]):
                if ord(ch) not in cs:
                    fail(f'{where}: the character {ch!r} (U+{ord(ch):04X}) in "{text}" has no glyph in {Path(p).name}; it would be drawn as an empty box. Replace it in the script')


# ---------------- captions ----------------
def rule_pieces(show):
    """No "/" written: a unit per clause (break after a comma, colon or semicolon), wrapped greedily to 22 characters."""
    pieces = []
    for sent in re.split(r'(?<=[.?!…])\s+', show.strip()):
        clause = []
        for w in sent.split():
            clause.append(w)
            if w[-1] in ',:;' or w == sent.split()[-1]:
                line = ''
                for c in clause:
                    if line and len(line) + 1 + len(c) > 22:
                        pieces.append(line); line = c
                    else:
                        line = (line + ' ' + c).strip()
                pieces.append(line); clause = []
    return pieces


def paragraph_pieces(show):
    return [p.strip() for p in show.split('/') if p.strip()] if '/' in show else rule_pieces(show)


# ---------------- the repo beat: contract (offline, shared with the chain's script check) ----------------
def repo_problem(repo, branch=None):
    """The `repo` (and optional `branch`) of a source: None when fine, else (reason, what to change)."""
    if not isinstance(repo, str) or not REPO_NAME.fullmatch(repo) or repo.split('/')[1] in ('.', '..'):
        return (f'"repo" is {json.dumps(repo, ensure_ascii=False)}, not owner/name',
                'write the repository as owner/name, for example "backnotprop/plannotator" (not an address, no .git)')
    if branch is not None and (not isinstance(branch, str) or not BRANCH_NAME.fullmatch(branch) or '..' in branch or branch.endswith(('/', '.lock'))):
        return (f'"branch" is {json.dumps(branch, ensure_ascii=False)}, not a branch name', 'write the branch as it appears in the repository address, for example "main"; leave it out for the default branch')
    return None


def parse_open(open_):
    """The `open` list of a repo beat, in the order the pages are shown -> ([{path, parent, anchor, occurrence, chain}], None), or (None, (reason, fix)).

    A path is from the repo root. Every beat starts on the repo home, and a path is reached from its parent folder: the parent is the root or an
    earlier entry. GitHub shows a folder that holds only one folder as ONE row, linking to the deepest folder ("a/b" on the page of "a"'s
    parent, no page for "a"); such an entry is written {"path": "a/b", "chain": true} and is reached from the nearest earlier entry that is
    its ancestor, or from the root. The skipped folders are not checked here (no network); the `cay` step checks them against GitHub."""
    if not isinstance(open_, list):
        return None, ('"open" is not a list', 'write "open": [] (the home page only) or a list of folder and file paths from the repo root')
    if len(open_) > MAX_OPEN:
        return None, (f'"open" has {len(open_)} entries; the most one beat may open is {MAX_OPEN}', 'open fewer pages in one beat, or split the walk over two beats')
    out, seen = [], []
    for n, e in enumerate(open_):
        w = f'open[{n}]'
        e = dict(path=e) if isinstance(e, str) else e
        if not isinstance(e, dict):
            return None, (f'{w} is neither a path nor an object', 'write each entry as "folder/file" or {"path": "folder/file", "anchor": "spoken words"}')
        extra = [k for k in e if k not in OPEN_KEYS]
        if extra:
            return None, (f'{w} has unknown key(s) {", ".join(extra)}', f'allowed keys: {", ".join(OPEN_KEYS)}')
        path = e.get('path')
        if not isinstance(path, str) or not path.strip():
            return None, (f'{w}.path is missing or empty', 'write the path from the repo root, for example "packages/server"')
        if path.startswith('/'):
            return None, (f'{w}.path "{path}" is absolute', 'write the path from the repo root, with no leading slash')
        if '\\' in path:
            return None, (f'{w}.path "{path}" holds a backslash', 'separate the folders with "/"')
        segs = path.split('/')
        if '' in segs:
            return None, (f'{w}.path "{path}" has an empty part (a double or trailing slash)', 'write folders and files separated by single slashes, with no slash at the end')
        if '.' in segs or '..' in segs:
            return None, (f'{w}.path "{path}" holds "." or ".."', 'write the real path from the repo root; a path may not climb out of it')
        if path in seen:
            return None, (f'{w}.path "{path}" is already opened earlier in this list', 'open each page once; to come back to it, open the next path under another folder')
        if 'anchor' in e and not (isinstance(e['anchor'], str) and e['anchor'].strip()):
            return None, (f'{w}.anchor is empty', 'write the spoken words that open this page, or leave "anchor" out')
        if 'occurrence' in e and not (isinstance(e['occurrence'], int) and not isinstance(e['occurrence'], bool) and e['occurrence'] >= 0):
            return None, (f'{w}.occurrence must be a number from 0', 'fix the value')
        if 'chain' in e and not isinstance(e['chain'], bool):
            return None, (f'{w}.chain must be true or false', 'fix the value')
        parent = '/'.join(segs[:-1])
        if parent and parent not in seen:
            near = next((a for a in ('/'.join(segs[:k]) for k in range(len(segs) - 1, 0, -1)) if a in seen), '')
            if not e.get('chain'):
                page = f'"{near}"' if near else 'the repo root'
                return None, (f'{w}.path "{path}" is opened from "{parent}", which is neither the repo root nor an earlier entry of this list',
                              f'put "{parent}" before it in the list; or, if GitHub shows "{path}" as one row on the page of {page} '
                              f'(a folder that holds only one folder), write {{"path": "{path}", "chain": true}}')
            parent = near
        seen.append(path)
        out.append(dict(path=path, parent=parent, anchor=e.get('anchor'), occurrence=e.get('occurrence'), chain=bool(e.get('chain'))))
    return out, None


def terminal_key(ref, step):
    """The capture-manifest key of the picture of step `step` of the run `ref` (halcyon_chay.py writes one entry per step)."""
    return f'{ref}-s{step}'


# ---------------- moving-picture beats: screen, scene3d, demo (contract shared with the chain's script check) ----------------
CLIP_KINDS = ('screen', 'scene3d', 'demo')
CLIP_FIELDS = ('file', 'w', 'h', 'fps', 'frames', 'duration', 'captured', 'source', 'date')   # what a clip producer's manifest (clip.json) must say; MOT-LENH.md has the rest
DEMO_FIELDS = ('file', 'duration', 'captured', 'source', 'date')                              # the demo producer's manifest (demo.json)
REC_W_SRC, REC_H_SRC = 390, 844                                                               # the builder's recording size: a demo rect is in these pixels
CLIP_TOL = 0.05                                                                               # seconds a silent beat may differ from its clip


def clip_key(kind, ref, steps=None):
    """The key of one moving picture in the clips file (--clips) and in the timing file's `silences`."""
    if kind == 'screen':
        return f'screen:{ref}:' + '-'.join(str(x) for x in steps)
    return f'{kind}:{ref}'


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_clip_beat(sp):
    """A screen, scene3d or demo beat -> ({kind, ref, steps, key, from, to, rect}, None), or (None, (reason, fix)). No files are read.

    screen:  {"kind": "screen",  "screen":  {"ref": <a run source>, "steps": [0, 1]}}               the commands of those steps, played back to back
    scene3d: {"kind": "scene3d", "scene3d": {"ref": <a scene source>}}                               the three.js clip of a scene source
    demo:    {"kind": "demo",    "demo":    {"ref": <a demo source>, "from": 2.0, "to": 21.5, "rect": [x0, y0, x1, y1]}}   the part of a recorded page, rect in the 390x844 recording"""
    kind = sp.get('kind') if isinstance(sp, dict) else None
    b = sp.get(kind) if kind in CLIP_KINDS else None
    if not isinstance(b, dict):
        return None, (f'a {kind} beat has no "{kind}" block', f'write {{"kind": "{kind}", "{kind}": {{"ref": ...}}}} (MOT-LENH.md)')
    ref = b.get('ref')
    if not isinstance(ref, str) or not re.fullmatch(r'[\w.-]+', ref):
        return None, (f'{kind}.ref is {json.dumps(ref, ensure_ascii=False)}', 'give the name of a source: letters, digits, dot, dash and underscore only')
    info = dict(kind=kind, ref=ref, steps=None, key=None, **{'from': None, 'to': None, 'rect': None})
    allowed = {'screen': ('ref', 'steps'), 'scene3d': ('ref',), 'demo': ('ref', 'from', 'to', 'rect')}[kind]
    extra = [k for k in b if k not in allowed]
    if extra:
        return None, (f'{kind} has unknown key(s) {", ".join(extra)}', f'allowed keys: {", ".join(allowed)}')
    if kind == 'screen':
        st = b.get('steps')
        if not (isinstance(st, list) and st and all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in st) and all(x < y for x, y in zip(st, st[1:]))):
            return None, (f'screen.steps is {json.dumps(st)}', 'write the numbers of the run\'s steps to play, from 0, increasing, for example [0, 1]')
        info['steps'] = st
    if kind == 'demo':
        a, z, r = b.get('from'), b.get('to'), b.get('rect')
        if not (is_num(a) and is_num(z) and 0 <= a < z):
            return None, (f'demo.from/to are {json.dumps(a)} and {json.dumps(z)}', 'write the seconds of the recording to show: "from" at least 0 and below "to"')
        if not (isinstance(r, list) and len(r) == 4 and all(is_num(x) for x in r) and 0 <= r[0] < r[2] <= REC_W_SRC and 0 <= r[1] < r[3] <= REC_H_SRC):
            return None, (f'demo.rect is {json.dumps(r)}', f'write [x0, y0, x1, y1] inside the {REC_W_SRC}x{REC_H_SRC} recording: the part of the page the voice is about')
        info.update({'from': a, 'to': z, 'rect': r})
    info['key'] = clip_key(kind, ref, info['steps'])
    return info, None


def silent_problem(paras, n, where):
    """None when paragraph n is a valid silent paragraph, else (reason, what to change): no voice and no subtitle, one moving picture, never first or last, never next to
    another silent paragraph."""
    p = paras[n]
    if p.get('silent') is not True:
        return f'{where}.silent must be true (or left out)', 'write "silent": true, or remove the key'
    for k in ('say', 'show'):
        if k in p:
            return (f'{where} is silent but has "{k}": a silent paragraph has no voice and no subtitle',
                    f'remove "{k}", or remove "silent" to make it a voiced paragraph')
    if n in (0, len(paras) - 1):
        return f'{where} is silent but is the {"first" if n == 0 else "last"} paragraph', 'the video opens and closes on the voice: put a voiced paragraph there'
    if paras[n - 1].get('silent'):
        return f'{where} is silent like the paragraph before it', 'make the two one block: one silent paragraph with one picture'
    if n + 1 < len(paras) and paras[n + 1].get('silent'):
        return f'{where} is silent like the paragraph after it', 'make the two one block: one silent paragraph with one picture'
    bl = p.get('beats')
    if not (isinstance(bl, list) and len(bl) == 1 and isinstance(bl[0], dict) and bl[0].get('kind') in CLIP_KINDS):
        return f'{where}.beats must be exactly one beat of kind {", ".join(CLIP_KINDS)}', 'a silent paragraph is as long as its one moving picture'
    return None


# ---------------- inputs ----------------
def load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        fail(f'{what} not found: {path}')
    except json.JSONDecodeError as e:
        fail(f'{what} {path} is not valid JSON: {e}')


def check_manifest(man):
    caps = need(man, 'captures', 'captures manifest')
    for key, c in caps.items():
        w = f'captures[{key}]'
        for f in ('file', 'source', 'date', 'captured', 'u_rows', 'focus'):
            need(c, f, w)
        foc = c['focus']
        if not ('rows' in foc or 'lines' in foc):
            fail(f'{w}.focus needs "rows": [a, b] or "lines": [a, b] (with optional "band_rows")')
        if not (len(c['u_rows']) == 2 and c['u_rows'][0] < c['u_rows'][1]):
            fail(f'{w}.u_rows must be [gap above, gap below] with the first smaller')
        if 'rows' in foc and not (c['u_rows'][0] <= foc['rows'][0] < foc['rows'][1] <= c['u_rows'][1]):
            fail(f'{w}.u_rows {c["u_rows"]} must contain the focus rows {foc["rows"]}')
        for n, b in enumerate(c.get('bands', [])):
            r = need(b, 'rect', f'{w}.bands[{n}]'); need(b, 'text', f'{w}.bands[{n}]')
            if not (len(r) == 4 and r[2] > 0 and r[3] > 0):
                fail(f'{w}.bands[{n}].rect must be [x, y, w, h] with a positive size')
    return caps


class Run:
    """One assembly: the script, the voice timing, the manifest; fills spec and notes."""

    def __init__(self, kb, timing, manifest, out_dir, timing_path, quay=None, clips=None):
        self.kb, self.t, self.caps, self.out_dir, self.timing_path = kb, timing, manifest, Path(out_dir), Path(timing_path)
        self.quay = quay
        self.clips = clips or {}           # clip key -> path of its manifest (clip.json, or demo.json for a demo)
        self.notes = []
        self.heard = need(timing, 'words_whisper_medium', 'timing file')
        self.paras = need(kb, 'paragraphs', 'script')
        spans = need(timing, 'beats', 'timing file')
        self.silent = [bool(p.get('silent')) for p in self.paras]
        for n, sil in enumerate(self.silent):
            bad = silent_problem(self.paras, n, f'paragraphs[{n}]') if sil else None
            if bad:
                fail(f'{bad[0]}; {bad[1]}')
        voiced = self.silent.count(False)
        if len(spans) != voiced:
            fail(f'the script has {voiced} voiced paragraphs but the timing file measured {len(spans)} voice paragraphs; they must match one to one '
                 f'(a silent paragraph has no voice and is not counted)')
        self.spans = spans
        self.silences = timing.get('silences', [])
        if len(self.silences) != len(self.silent) - voiced:
            fail(f'the script has {len(self.silent) - voiced} silent paragraphs but the timing file has {len(self.silences)} silences; '
                 f'the silence is put into the voice by halcyon_lang.py (the chain\'s `lang` step) before the spec is assembled')
        self.slot, vi, si = {}, 0, 0         # paragraph -> its voice span (voiced) or its silence (silent)
        for n, sil in enumerate(self.silent):
            self.slot[n] = ('silence', si) if sil else ('voice', vi)
            si, vi = si + sil, vi + (not sil)

    # -- tokens
    def tokens(self):
        self.pieces, self.toks, self.pspan = [], [], []
        for n, p in enumerate(self.paras):
            where = f'paragraphs[{n}]'
            if self.silent[n]:
                self.pieces.append([]); self.pspan.append((len(self.toks), len(self.toks)))
                continue
            need(p, 'say', where); need(p, 'show', where); need(p, 'beats', where)
            pcs = paragraph_pieces(p['show']); self.pieces.append(pcs)
            a = len(self.toks)
            for pc in pcs:
                self.toks += pc.split()
            self.pspan.append((a, len(self.toks)))
        self.aliases = derive_aliases(self.toks, self.heard, {k.lower(): v for k, v in self.kb.get('word_aliases', {}).items()})
        self.idx, _ = align(self.toks, self.heard, self.aliases)

    def start_of(self, i, where):
        if self.idx[i] is None:
            fail(f'{where}: the word "{self.toks[i]}" of the script was not heard in the voice; check the voice text or the word')
        return self.heard[self.idx[i]]['s']

    def sentences(self, n):
        a, b = self.pspan[n]; starts = [a]
        for i in range(a, b - 1):
            if SENT_END.search(self.toks[i]):
                starts.append(i + 1)
        return starts

    # -- beats of a paragraph: [(first token, last token+1)] and the cut times
    def edges(self):
        def times(n):
            what, i = self.slot[n]
            return (self.silences[i]['a'], self.silences[i]['b']) if what == 'silence' else (self.spans[i]['start'], self.spans[i]['end'])
        cuts = [0.0]
        for n in range(len(self.paras) - 1):
            (_, e0), (s1, _) = times(n), times(n + 1)
            if self.silent[n]:
                cuts.append(round(e0, 2))               # the silence ends: the voice (or the next picture) starts
            elif self.silent[n + 1]:
                cuts.append(round(s1, 2))               # the silence starts
            else:
                cuts.append(round((e0 + s1) / 2, 2))
        self.pcut = cuts
        self.duration = round(float(need(self.t, 'duration_s', 'timing file')) + float(self.kb.get('tail', TAIL)), 2)
        self.beats = []
        for n, p in enumerate(self.paras):
            if self.silent[n]:
                bb = p['beats'][0]
                self.beats.append(dict(n=n, k=0, spec=bb, ta=self.pspan[n][0], tb=self.pspan[n][0], a=self.pcut[n], last=True, id=bb.get('id') or str(n + 1)))
                continue
            bl = p['beats']; sents = self.sentences(n); a, b = self.pspan[n]
            firsts = [0] + [bb.get('from_sentence') for bb in bl[1:]]
            for k, f in enumerate(firsts):
                where = f'paragraphs[{n}].beats[{k}]'
                if f is None or not isinstance(f, int) or (k and f <= firsts[k - 1]) or f >= len(sents):
                    fail(f'{where}.from_sentence must be a sentence number, counted from 0, increasing, below {len(sents)} (this paragraph has {len(sents)} sentences)')
            for k, bb in enumerate(bl):
                ta = sents[firsts[k]]; tb = sents[firsts[k + 1]] if k + 1 < len(bl) else b
                a_t = self.pcut[n] if k == 0 else self.sentence_cut(ta, a, f'paragraphs[{n}].beats[{k}]')
                self.beats.append(dict(n=n, k=k, spec=bb, ta=ta, tb=tb, a=a_t, last=(k + 1 == len(bl)),
                                       id=bb.get('id') or (str(n + 1) + ('abcdefgh'[k] if len(bl) > 1 else ''))))
        for i, bt in enumerate(self.beats):
            bt['b'] = self.beats[i + 1]['a'] if i + 1 < len(self.beats) else self.duration
            if not bt['b'] > bt['a']:
                fail(f'beat {bt["id"]} would last {bt["b"] - bt["a"]:.2f} s: its cut times are out of order')

    def sentence_cut(self, t, floor, where):
        """Midpoint of the silence between the last word of the earlier sentence and the first of this one, from the Whisper word times."""
        before = next((i for i in range(t - 1, floor - 1, -1) if self.idx[i] is not None), None)
        after = next((i for i in range(t, len(self.toks)) if self.idx[i] is not None), None)
        if before is None or after is None:
            fail(f'{where}: cannot place the cut between sentences, no word next to it was heard')
        return round((self.heard[self.idx[before]]['e'] + self.heard[self.idx[after]]['s']) / 2, 2)

    # -- an anchor: where a reveal happens
    def anchor(self, bt, phrase, occurrence, where):
        words = [nrm(self.aliases, w) for w in phrase.split()]
        hits = [i for i in range(bt['ta'], bt['tb'] - len(words) + 1) if [nrm(self.aliases, w) for w in self.toks[i:i + len(words)]] == words]
        if not hits:
            fail(f'{where}: the anchor "{phrase}" is not among the words spoken in beat {bt["id"]} ("{" ".join(self.toks[bt["ta"]:bt["tb"]])}")')
        if len(hits) > 1 and occurrence is None:
            fail(f'{where}: the anchor "{phrase}" occurs {len(hits)} times in beat {bt["id"]}; write a longer phrase or "occurrence": 0..{len(hits) - 1}')
        return round(self.start_of(hits[occurrence or 0], where) - LEAD, 2)

    def cut(self, bt, spec, where, key='anchor'):
        if spec.get(key) is None:
            return bt['a']
        return max(self.anchor(bt, spec[key], spec.get('occurrence'), where), bt['a'])

    def expected_window(self, i):
        """Where the builder should find token i: at its aligned word (1.5 s slack), or, when the voice has no such word, between its neighbours."""
        if self.idx[i] is not None:
            s = self.heard[self.idx[i]]['s']; return s, s, 1.5
        prev = next((self.heard[self.idx[j]]['s'] for j in range(i - 1, -1, -1) if self.idx[j] is not None), 0.0)
        nxt = next((self.heard[self.idx[j]]['s'] for j in range(i + 1, len(self.toks)) if self.idx[j] is not None), float('inf'))
        return prev, nxt, 0.3

    # -- captions and the later-equal-word check
    def captions(self):
        caps = [pc for pcs in self.pieces for pc in pcs]
        ptr, flat = 0, 0
        for pc in caps:
            key = bnorm(self.aliases, pc.split()[0])
            hit = next((i for i in range(ptr, len(self.heard)) if bnorm(self.aliases, self.heard[i]['w']) == key), None)
            if hit is None:
                fail(f'caption "{pc}": its first word is not in the voice after word {ptr}; the builder would stop here')
            lo, hi, tol = self.expected_window(flat)
            if not lo - tol <= self.heard[hit]['s'] <= hi + tol:
                fail(f'caption "{pc}" would start at {self.heard[hit]["s"]:.2f} s, on a later "{pc.split()[0]}" than the one it belongs to '
                     f'(expected between {lo:.2f} and {hi:.2f} s); the voice probably dropped its first word. Change the voice text or start the line on another word')
            ptr = hit + 1; flat += len(pc.split())
        return caps

    # -- beats to spec
    def terminal_cap(self, bt):
        """A terminal beat is drawn as a capture of the picture its run step made: the quote is the text of that picture, the bands are the highlighted phrases."""
        sp = bt['spec']; t = need(sp, 'terminal', f'beat {bt["id"]}'); where = f'beat {bt["id"]}.terminal'
        ref = need(t, 'ref', where)
        if not isinstance(t.get('step'), int) or isinstance(t['step'], bool) or t['step'] < 0:
            fail(f'{where}.step must be the number of a step of the run (from 0)')
        key = terminal_key(ref, t['step'])
        if key not in self.caps:
            fail(f'{where}: step {t["step"]} of run "{ref}" has no picture in the manifest (it has: {", ".join(self.caps)})')
        return dict(ref=key, quote=need(self.caps[key], 'text', f'captures[{key}]'), bands=t.get('bands', []))

    def capture_beat(self, bt, first):
        sp = bt['spec']; cap = self.terminal_cap(bt) if sp.get('kind') == 'terminal' else need(sp, 'capture', f'beat {bt["id"]}'); ref = need(cap, 'ref', f'beat {bt["id"]}.capture')
        if ref not in self.caps:
            fail(f'beat {bt["id"]}: capture "{ref}" is not in the capture manifest (it has: {", ".join(self.caps)})')
        c = self.caps[ref]; quote = plain(need(cap, 'quote', f'beat {bt["id"]}.capture'))
        pic = dict(kind='capture', file=c['file']); pic.update(c['focus']); pic['u_rows'] = c['u_rows']
        wanted = cap.get('bands', [dict(text=b['text']) for b in c.get('bands', [])])
        bands = []
        for n, w in enumerate(wanted):
            where = f'beat {bt["id"]}.capture.bands[{n}]'
            m = [b for b in c.get('bands', []) if plain(b['text']) == plain(need(w, 'text', where))]
            if not m:
                fail(f'{where}: no band "{w["text"]}" in manifest capture "{ref}" (it has: {", ".join(b["text"] for b in c.get("bands", []))})')
            if plain(m[0]['text']) not in quote:
                fail(f'{where}: the band text "{m[0]["text"]}" is not in the quote of this beat; the highlighter would mark words the quote does not contain')
            first = m[0]['text'].split()[0]
            if 'at' in w:
                at = w['at']
            elif 'anchor' in w:
                at = self.anchor(bt, w['anchor'], w.get('occurrence'), where)
            elif self.has_word(bt, first):
                at = self.anchor(bt, first, w.get('occurrence'), where)
            else:
                fail(f'{where}: the first word of "{m[0]["text"]}" is not spoken in this beat, so its time is unknown; give "anchor": "<spoken words>" or "at": <seconds>')
            bands.append(dict(rect=m[0]['rect'], at=at))
        return pic, bands, c

    def repo_beat(self, bt, where):
        """The picture of a repo beat: {"kind": "repo", "manifest": <recorder manifest, relative to the spec>, "walk": [{page, a, via?}, ...]}.

        `page` is a path from the repo root ("" = home); `a` is the second the page starts to appear; a page lasts until the next entry's `a` (the last
        one until the beat's end). `via` is "tap" (opened from the page before it) or "back" (slide back to an earlier page); home has none.
        Times: an entry with an anchor starts at the anchor; between two anchored entries (the whole beat when none has one) every page gets its
        floor and the time above the floors is shared equally, so a beat that fits its pages never fails on an uneven split. A slide back is its
        own entry. The walk emitter is the one place that writes entries: a field for the builder (a camera target, say) is added to `walk` below."""
        rp = need(bt['spec'], 'repo', where)
        ref = need(rp, 'ref', where + '.repo')
        entries, bad = parse_open(rp.get('open'))
        if bad:
            fail(f'{where}.repo: {bad[0]}; {bad[1]}')
        quay = (self.quay.get(ref) or self.quay.get(None)) if isinstance(self.quay, dict) else self.quay
        if not quay:
            fail(f'{where}: this is a repo beat but no recorder manifest was given for "{ref}"; pass --quay <quay.json> (or --quay {ref}=<quay.json>)')
        first_repo = next(b for b in self.beats if b['spec'].get('kind') == 'repo')['id'] == bt['id']
        fl = FLOOR.get(bt['spec'].get('level', 'HOOK'), FLOOR['HOOK'])
        slots = [dict(page='', via=None, floor=fl['home'] + (fl['glimpse'] if first_repo else 0), at=bt['a'], fixed=True, what='the home page')]
        cur = ''
        for n, e in enumerate(entries):
            if e['parent'] != cur:
                slots.append(dict(page=e['parent'], via='back', floor=fl['back'], at=None, fixed=False, what=f'the slide back to "{e["parent"] or "home"}"'))
            at = max(self.anchor(bt, e['anchor'], e['occurrence'], f'{where}.repo.open[{n}]'), bt['a']) if e['anchor'] else None
            slots.append(dict(page=e['path'], via='tap', floor=fl['tap'], at=at, fixed=at is not None, what=f'the page "{e["path"]}"'))
            cur = e['path']
        for k, s in enumerate(slots):          # a page nothing is opened from needs only its last-page time; the home page of a beat that opens nothing keeps its own
            if s['via'] == 'tap' and (k + 1 == len(slots) or slots[k + 1]['via'] == 'back'):
                s['floor'] = fl['last']
        need_s, have = sum(s['floor'] for s in slots), bt['b'] - bt['a']
        if have + 1e-9 < need_s:
            parts = ', '.join('%s %.1f' % (s['what'], s['floor']) for s in slots)
            fail(f'{where}: the voice gives this beat {have:.2f} s but its {len(slots)} pages need at least {need_s:.1f} s ({parts}); '
                 f'lengthen the paragraph, or open fewer pages')
        marks = [k for k, s in enumerate(slots) if s['fixed']] + [len(slots)]
        for k0, k1 in zip(marks, marks[1:]):
            t0 = slots[k0]['at']; t1 = slots[k1]['at'] if k1 < len(slots) else bt['b']
            if not t1 > t0:
                fail(f'{where}: {slots[k1]["what"] if k1 < len(slots) else "the end of the beat"} would start at {t1:.2f} s, not after {slots[k0]["what"]} at {t0:.2f} s; '
                     f'anchors must follow the order of the "open" list, each inside the beat')
            extra = ((t1 - t0) - sum(s['floor'] for s in slots[k0:k1])) / (k1 - k0)   # the time above the floors, shared equally
            used = 0.0
            for k in range(k0, k1):
                slots[k]['raw'] = t0 + used + (k - k0) * extra
                slots[k]['at'] = round(slots[k]['raw'], 2)
                used += slots[k]['floor']
        for k, s in enumerate(slots):
            dur = (slots[k + 1]['raw'] if k + 1 < len(slots) else bt['b']) - s['raw']
            if dur + 1e-9 < s['floor']:
                fail(f'{where}: {s["what"]} would be on screen {dur:.2f} s, under its floor of {s["floor"]:.1f} s; the anchors leave it too little room: '
                     f'move an anchor, lengthen the paragraph, or open fewer pages')
        walk = [dict(page=s['page'], a=s['at'], **({'via': s['via']} if s['via'] else {})) for s in slots]
        return dict(kind='repo', manifest=os.path.relpath(quay, self.out_dir).replace('\\', '/'), walk=walk)

    def clip_manifest(self, info, where):
        """The manifest of a moving picture: (dict, path). The chain's producers write it; the checks here are the ones every consumer needs."""
        path = self.clips.get(info['key'])
        if not path:
            fail(f'{where}: no manifest for the {info["kind"]} "{info["key"]}" was given; pass --clips <clips.json> naming it (the chain\'s producer step writes it)')
        man = load_json(path, f'manifest of {info["key"]}')
        for fld in (DEMO_FIELDS if info['kind'] == 'demo' else CLIP_FIELDS):
            need(man, fld, f'manifest of {info["key"]}')
        if not (is_num(man['duration']) and man['duration'] > 0):
            fail(f'{where}: the manifest of {info["key"]} has duration {man["duration"]!r}')
        if info['kind'] != 'demo' and abs(man['duration'] - man['frames'] / man['fps']) > 1 / man['fps'] + 1e-3:
            fail(f'{where}: the manifest of {info["key"]} says {man["frames"]} frames at {man["fps"]} fps but duration {man["duration"]} s; one of them is wrong')
        return man, Path(path)

    def clip_beat(self, bt, d, where, silent):
        """screen / scene3d: the picture is the producer's clip, played from its start; demo: a recording of the page, the part from..to, focused on rect."""
        sp = bt['spec']
        info, bad = parse_clip_beat(sp)
        if bad:
            fail(f'{where}: {bad[0]}; {bad[1]}')
        man, mpath = self.clip_manifest(info, where)
        rel = lambda p: os.path.relpath(p, self.out_dir).replace('\\', '/')
        if info['kind'] == 'demo':
            if info['to'] > man['duration'] + 1e-6:
                fail(f'{where}: demo.to is {info["to"]} s but the recording of "{info["ref"]}" lasts {man["duration"]} s')
            length = info['to'] - info['from']
            pic = dict(kind='recording', file=rel(mpath.parent / man['file']), start=float(info['from']), dur=round(length, 3), rect=info['rect'])
            chip = sp.get('chip') or f'Demo công khai: {man["source"]}, {man["date"]}'
        else:
            length = man['duration']
            pic = dict(kind='clip', manifest=rel(mpath), start=0.0, dur=man['duration'])
            chip = sp.get('chip') or (f'Chạy thật: {man["date"]}' if info['kind'] == 'screen' else f'{self.kb.get("chip_prefix", "Ảnh chụp")}: {man["source"]}, {man["date"]}')
        have = bt['b'] - bt['a']
        if silent and abs(have - length) > CLIP_TOL:
            fail(f'{where}: the silent beat lasts {have:.2f} s but its picture lasts {length:.2f} s; the silence is made as long as the picture, so the timing file or the clip changed after the `lang` step')
        if not silent and length > have + CLIP_TOL:
            fail(f'{where}: its picture lasts {length:.2f} s but the voice gives the beat {have:.2f} s, so the end of the picture would be cut; lengthen the paragraph or shorten the picture')
        if len(chip) > CHIP_MAX:
            fail(f'{where}: the chip "{chip}" is {len(chip)} characters; the limit is {CHIP_MAX} (longer chips shrink below 21 px)')
        d['level'] = sp.get('level', 'HOOK' if info['kind'] == 'demo' else 'FOOT')
        d['chip'] = dict(text=chip); d['picture'] = pic
        if silent:
            d['captions'] = False
        return chip

    def has_word(self, bt, w):
        return any(nrm(self.aliases, x) == nrm(self.aliases, w) for x in self.toks[bt['ta']:bt['tb']])

    def build(self):
        self.tokens(); self.edges()
        captions = self.captions(); out = []; strings = []
        kb = self.kb; outlet = need(kb, 'outlet', 'script'); date = need(kb, 'date', 'script'); prefix = kb.get('chip_prefix', 'Ảnh chụp')
        first_chip = None
        for i, bt in enumerate(self.beats):
            sp = bt['spec']; kind = need(sp, 'kind', f'beat {bt["id"]}'); where = f'beat {bt["id"]}'
            d = dict(id=bt['id'], name=sp.get('name', bt['id']), a=bt['a'], b=bt['b'])
            texts = []; silent = self.silent[bt['n']]; say = '' if silent else self.paras[bt['n']]['say']; nums = self.paras[bt['n']].get('numbers', {})
            wm = i == 0 or i == len(self.beats) - 1
            if kind in ('capture', 'recording', 'repo', 'terminal'):
                head = need(sp, 'headline', where)
                if len(head) != 2:
                    fail(f'{where}.headline must be two lines')
                d['level'] = sp.get('level', 'HOOK')
                if wm: d['mark'] = 'wm'
                tx = dict(kind='block', lines=[h.upper() for h in head], kicker=sp.get('kicker', f'Theo {outlet} · {date}' if i == 0 else f'Theo {outlet}'), kicker_size=26)
                if i == 0: tx['lift'] = 24
                if 'headline_anchor' in sp:
                    tx['cuts'] = [self.cut(bt, sp, where + '.headline_anchor', 'headline_anchor')]
                texts += head
                if kind in ('capture', 'terminal'):
                    pic, bands, c = self.capture_beat(bt, i == 0)
                    chip = sp.get('chip') or (f'Chạy thật: {c["date"]}' if kind == 'terminal' else f'{prefix}: {c["source"]}, {c["date"]}')
                    d['chip'] = dict(text=chip); tx_pic = pic
                elif kind == 'repo':
                    chip = sp.get('chip') or f'{prefix}: GitHub'
                    d['chip'] = dict(text=chip); tx_pic = self.repo_beat(bt, where); bands = []
                else:
                    d['chip'] = dict(line=need(sp, 'chip_line', where)); tx_pic = need(sp, 'picture', where); bands = []; chip = None
                if chip and len(chip) > CHIP_MAX:
                    fail(f'{where}: the chip "{chip}" is {len(chip)} characters; the limit is {CHIP_MAX} (longer chips shrink below 21 px)')
                d['text'] = tx; d['picture'] = tx_pic
                if bands: d['bands'] = bands
                if i == 0: first_chip = d['chip']
                strings += [('small', where + '.chip', chip or d['chip']['line']), ('small', where + '.kicker', tx['kicker'])]
            elif kind in CLIP_KINDS:
                if wm:
                    d['mark'] = 'wm'
                chip = self.clip_beat(bt, d, where, silent)
                strings.append(('small', where + '.chip', chip))
                if sp.get('headline'):
                    head = sp['headline']
                    if len(head) != 2:
                        fail(f'{where}.headline must be two lines')
                    d['text'] = dict(kind='block', lines=[h.upper() for h in head], kicker=sp.get('kicker', f'Theo {outlet}'), kicker_size=26)
                    texts += head
                    strings.append(('small', where + '.kicker', d['text']['kicker']))
            elif kind in ('number', 'chart', 'list'):
                kick = need(sp, 'kicker', where).upper()
                src = sp.get('source', f'Nguồn: {outlet}, {date}')
                if kind == 'number':
                    tx = dict(kind='number', kicker=kick, line1=need(sp, 'line1', where).upper(), line2=need(sp, 'line2', where).upper(), source=src, cuts=[self.cut(bt, sp, where)])
                    texts += [tx['line1'], tx['line2']]
                elif kind == 'chart':
                    rows = need(sp, 'rows', where)
                    tx = dict(kind='chart', kicker=kick, rows=[dict(name=r['name'].upper(), value=r['value'].upper(), bar=r['bar']) for r in rows],
                              bar_full=sp.get('bar_full', max(r['bar'] for r in rows)), source=src)
                    tx['cuts'] = [self.cut(bt, r, f'{where}.rows[{n}]') for n, r in enumerate(rows)]
                    if sp.get('note'):
                        tx['note'] = sp['note']; tx['cuts'].append(self.cut(bt, sp, where + '.note_anchor', 'note_anchor') if sp.get('note_anchor') else fail(f'{where}: a chart note needs "note_anchor"'))
                    texts += [r['name'] + ' ' + r['value'] for r in rows]
                else:
                    rows = need(sp, 'rows', where)
                    tx = dict(kind='list', kicker=kick, title=need(sp, 'title', where).upper(), rows=[r['text'].upper() for r in rows],
                              cuts=[self.cut(bt, r, f'{where}.rows[{n}]') for n, r in enumerate(rows)])
                    if sp.get('source'): tx['source'] = sp['source']
                    texts += [tx['title']] + tx['rows']
                d['text'] = tx
                strings += [('small', where + '.kicker', kick), ('small', where + '.source', src)]
            elif kind == 'end':
                tx = dict(kind='end', kicker=sp.get('kicker', 'những mẩu tin AI ngắn gọn'), line1='ĐỌC ĐẦY ĐỦ:', line2='HCO.NEWS', lift=24)
                d.update(level='HOOK', mark='wm', chip=first_chip, text=tx, picture=dict(kind='same_as', beat=self.beats[0]['id']))
                strings.append(('small', where + '.kicker', tx['kicker']))
            else:
                fail(f'{where}.kind "{kind}" is not one of capture, repo, recording, terminal, screen, scene3d, demo, number, chart, list, end')
            if kind == 'end' and i != len(self.beats) - 1:
                fail(f'{where}: the end beat must be the last beat')
            if kind != 'end':
                check_digits(texts, ' '.join(p.get('say', '') for p in self.paras), {k: v for p in self.paras for k, v in p.get('numbers', {}).items()}, where)   # a card may recap what an earlier paragraph said
                strings += [('caps', where, t) for t in texts]
            if kind in ('number', 'chart', 'list') and 'level' in sp:
                d['level'] = sp['level']
            out.append(d)
        for n, p in enumerate(self.paras):
            if not self.silent[n]:
                check_digits(self.pieces[n], p['say'], p.get('numbers', {}), f'paragraphs[{n}].show')
        strings += [('caps', 'captions', c) for c in captions]
        check_glyphs(strings)
        spec = dict(name=f'halcyon-{need(kb, "id", "script")}', duration=self.duration)
        out_dir = self.out_dir
        try:
            rel = lambda p: os.path.relpath(p, out_dir).replace('\\', '/')
            spec['voice'] = rel(self.timing_path.parent / need(self.t, 'file', 'timing file')); spec['timing'] = rel(self.timing_path)
        except ValueError:
            fail('the timing file and the output folder are on different drives; put them on one drive')
        if self.aliases: spec['word_aliases'] = self.aliases
        spec['tiktok_caption'] = need(kb, 'tiktok_caption', 'script')
        slug = kb.get('slug') or slugify(need(kb, 'title', 'script'))
        spec['out'] = dict(clean=f'{spec["name"]}-{slug}.mp4', tiktok=f'{spec["name"]}-{slug}-tiktok.mp4')
        spec['captions'] = captions
        if self.silences:
            spec['silences'] = [dict(a=s['a'], b=s['b']) for s in self.silences]
        spec['beats'] = out
        spec['layout'] = kb.get('layout', LAYOUT); spec['drop_kickers'] = kb.get('drop_kickers', True)
        return spec


def assemble(kb, timing, manifest, out_dir, timing_path, quay=None, clips=None):
    """quay: the repo recorder's manifest path, or {ref: path} ({None: path} serves every ref); only repo beats use it.
    clips: {clip key: manifest path}; only screen, scene3d and demo beats use it."""
    return Run(kb, timing, manifest, out_dir, timing_path, quay, clips).build()


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('script'); ap.add_argument('--timing', required=True); ap.add_argument('--captures'); ap.add_argument('--out', required=True)
    ap.add_argument('--clips', help='JSON file {clip key: manifest path} for screen, scene3d and demo beats (relative paths are from the file)')
    ap.add_argument('--quay', action='append', default=[], help='repo recorder manifest: PATH for every repo beat, or REF=PATH (repeatable)')
    a = ap.parse_args(argv)
    man = check_manifest(load_json(a.captures, 'captures manifest')) if a.captures else {}
    kb = load_json(a.script, 'script'); out = Path(a.out).resolve()
    quay = {}
    for q in a.quay:
        m = re.fullmatch(r'([\w.-]+)=(.+)', q)
        quay.update({m.group(1): Path(m.group(2)).resolve()} if m else {None: Path(q).resolve()})
    clips = {}
    if a.clips:
        cp = Path(a.clips).resolve()
        clips = {k: str((cp.parent / v).resolve()) for k, v in load_json(cp, 'clips file').items()}
    spec = assemble(kb, load_json(a.timing, 'timing file'), man, out.parent, Path(a.timing).resolve(), quay, clips)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'wrote {out}: {len(spec["beats"])} beats, {len(spec["captions"])} caption lines, duration {spec["duration"]}, {len(spec.get("word_aliases", {}))} word aliases')


if __name__ == '__main__':
    main(sys.argv[1:])
