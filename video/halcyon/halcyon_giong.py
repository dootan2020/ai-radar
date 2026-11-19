"""Halcyon voice step, the parts that need no audio tool: the reading gate, the listen list and the timing-file writer.

Standard library only, so CI runs it without ffmpeg, Whisper or the voice model. The step that uses those is lam-giong.py (not imported here).

The gate compares the words of the script's `say` text with the words Whisper heard in the FINAL wav. Both sides are folded so that spelling
variants that are not mispronunciations do not count: case, the place of a tone mark (tuỳ / tùy), digits against Vietnamese number words
(bảy mươi hai = 72, một trăm mười lăm phẩy tám = 115,8, 193 ngàn = một trăm chín mươi ba ngàn), a word split in two (ChatGPT = chat GPT) and the
respellings in the ear-approved file. It refuses when a run of GATE_RUN or more script words is not heard, when more than GATE_RATE of the script
words are not heard, when the voice said GATE_RUN or more extra words in a row, or when the voice has not as many paragraphs as the script.
Whisper can prove that a word was said, never that it was said well: the listen list is what the owner's ear is for.
"""
import difflib
import json
import re
import unicodedata
from fractions import Fraction

GATE_RUN = 4
GATE_RATE = 0.10
SHOW_WORDS = 14

WORD = re.compile(r'\d+(?:[.,]\d+)*|[^\W\d_]+')
TONES = {'̀': '1', '́': '2', '̃': '3', '̉': '4', '̣': '5'}


def fail(msg):
    raise SystemExit(f'giong: {msg}')


def key(word):
    """Lower case, tone mark moved to the end: 'tuỳ' and 'tùy' give the same key, 'ma' and 'má' do not."""
    d = unicodedata.normalize('NFD', word.lower())
    tone = ''.join(TONES[c] for c in d if c in TONES)
    return unicodedata.normalize('NFC', ''.join(c for c in d if c not in TONES)) + ('#' + tone if tone else '')


DIGITS = {key(w): n for w, n in dict(không=0, một=1, mốt=1, hai=2, ba=3, bốn=4, tư=4, năm=5, lăm=5, sáu=6, bảy=7, bẩy=7, tám=8, chín=9).items()}
SCALES = {key(w): n for w, n in {'nghìn': 10 ** 3, 'ngàn': 10 ** 3, 'triệu': 10 ** 6, 'tỷ': 10 ** 9, 'tỉ': 10 ** 9}.items()}
K_TEN, K_TENS, K_HUNDRED = key('mười'), key('mươi'), key('trăm')
K_ZERO_TENS = {key('linh'), key('lẻ')}
K_POINT = {key('phẩy'), key('chấm')}
K_HALF = key('rưỡi')
K_UNITS = {key(w) for w in ('giây', 'phút', 'ngày', 'tuần', 'tháng')}


def parse_int(ks):
    """The integer a run of Vietnamese number words says, or None when the run is not one number."""
    total = part = 0
    digit = None
    for k in ks:
        if k in DIGITS:
            if digit is not None:
                return None
            digit = DIGITS[k]
        elif k == K_TEN:
            if digit is not None:
                return None
            part += 10
        elif k == K_TENS and digit is not None:
            part += digit * 10
            digit = None
        elif k == K_HUNDRED and digit is not None:
            part += digit * 100
            digit = None
        elif k in K_ZERO_TENS:
            continue
        elif k in SCALES and (part or digit):
            total += (part + (digit or 0)) * SCALES[k]
            part, digit = 0, None
        else:
            return None
    return total + part + (digit or 0)


def number_at(ks, i):
    """(end, value) of the longest number spoken in words starting at ks[i], or None."""
    n = len(ks)
    for j in range(min(n, i + 14), i, -1):
        v = parse_int(ks[i:j])
        if v is None:
            continue
        v = Fraction(v)
        if j + 1 < n and ks[j] in K_POINT and ks[j + 1] in DIGITS:
            k, ds = j + 1, ''
            while k < n and ks[k] in DIGITS:
                ds += str(DIGITS[ks[k]])
                k += 1
            v += Fraction(int(ds), 10 ** len(ds))
            j = k
            if j < n and ks[j] in SCALES:
                v *= SCALES[ks[j]]
                j += 1
        return j, v
    return None


def item(raw, para=None, s=None, e=None, name=False):
    it = dict(raw=raw, key=key(raw), para=para, s=s, e=e, width=1, name=name, val=None, digits=None, dec=False, kind='word')
    if raw[0].isdigit() or (len(raw) > 1 and raw[0] in ',.' and raw[1:].isdigit()):
        txt = raw.replace(',', '.')
        dec = txt.startswith('.')
        if re.fullmatch(r'\d{1,3}(\.\d{3})+', txt):
            txt = txt.replace('.', '')
        it.update(val=Fraction(txt.lstrip('.') if dec else txt), digits=txt.lstrip('.'), dec=dec, kind='num')
    return it


def number_item(parts, v):
    first, last = parts[0], parts[-1]
    return dict(raw=' '.join(p['raw'] for p in parts), key='N:' + str(v), para=first['para'], s=first['s'], e=last['e'],
                width=sum(p['width'] for p in parts), name=False, val=v, digits=None, dec=False, kind='num')


def collapse_numbers(items):
    out, i, n = [], 0, len(items)
    while i < n:
        it = items[i]
        if it['kind'] == 'num' and not it['dec']:
            v, j = it['val'], i + 1
            if j < n and items[j]['dec'] and v.denominator == 1:
                v += Fraction(int(items[j]['digits']), 10 ** len(items[j]['digits']))
                j += 1
            if j < n and items[j]['key'] in SCALES:
                v *= SCALES[items[j]['key']]
                j += 1
            out.append(number_item(items[i:j], v))
            i = j
            continue
        if it['kind'] == 'word':
            ks = [x['key'] for x in items]
            r = number_at(ks, i)
            if r:
                j, v = r
                # "mười giây rưỡi" and "mười rưỡi" are written 10,5: the half belongs to the number (not after "giờ": that is a time, 8:30)
                half = j
                if ks[j:j + 1] == [K_HALF]:
                    half = j + 1
                elif ks[j:j + 1] and ks[j] in K_UNITS and ks[j + 1:j + 2] == [K_HALF]:
                    half = j + 2
                if half > j:
                    v, j = v + Fraction(1, 2), half
                out.append(number_item(items[i:j], v))
                i = j
                continue
        out.append(it)
        i += 1
    return out


# -- the ear-approved respellings: `say words => accepted Whisper reading | another reading`
def load_approved(text):
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if '=>' not in line:
            fail(f'approved-words file, line {n}: write "say words => what Whisper writes | another reading"')
        say, heard = line.split('=>', 1)
        sk = tuple(key(w) for w in WORD.findall(say))
        hk = [tuple(key(w) for w in WORD.findall(h)) for h in heard.split('|')]
        if not sk or not all(hk):
            fail(f'approved-words file, line {n}: both sides need words')
        out.append(dict(say=sk, label=' '.join(WORD.findall(say.lower())), heard=[h for h in hk if h] + [sk]))
    return out


def collapse_phrases(items, phrases, side):
    """Fold each approved phrase (script side: the say words; heard side: any accepted reading) into one token with the phrase's label."""
    out, i, n = [], 0, len(items)
    while i < n:
        for p in phrases:
            for ks in ([p['say']] if side == 'script' else p['heard']):
                if tuple(x['key'] for x in items[i:i + len(ks)]) == ks:
                    parts = items[i:i + len(ks)]
                    out.append(dict(number_item(parts, 0), key='A:' + p['label'], val=None, kind='ok', label=p['label']))
                    i += len(ks)
                    break
            else:
                continue
            break
        else:
            out.append(items[i])
            i += 1
    return out


# -- a word is a name worth hearing when it is capitalised inside a sentence, has a capital after its first letter, or cannot be one Vietnamese syllable
SYLLABLE = re.compile(r'(?:ngh|ng|nh|gh|gi|kh|ph|th|tr|ch|qu|[bcdđghklmnpqrstvx])?[aăâeêioôơuưy]{1,3}(?:ch|ng|nh|[cmnpt])?')


def looks_foreign(word, sentence_start):
    if len(word) > 1 and any(c.isupper() for c in word[1:]):
        return True
    if word[0].isupper() and not sentence_start and word.isascii():  # a capitalised Vietnamese word has a diacritic (Hàn Quốc, Bộ Nội vụ)
        return True
    base = key(word).split('#')[0]
    return len(base) > 1 and not SYLLABLE.fullmatch(base)


def script_items(say, phrases):
    out = []
    for p, text in enumerate(say):
        for m in WORD.finditer(text):
            before = text[:m.start()].rstrip()
            it = item(m.group(0), para=p)
            if it['kind'] == 'word':
                it['name'] = looks_foreign(m.group(0), not before or before[-1] in '.?!')
            out.append(it)
    return collapse_phrases(collapse_numbers(out), phrases, 'script')


def heard_items(words, phrases):
    out = []
    for w in words:
        for t in WORD.findall(w['w']):
            raw = w['w'].strip() if re.fullmatch(r'[.,]\d+', w['w'].strip()) else t
            out.append(item(raw, s=w['s'], e=w['e']))
    return collapse_phrases(collapse_numbers(out), phrases, 'heard')


def align(script, heard):
    """script index -> heard index. Equal words, plus a split word (chatgpt = chat gpt) whose pieces join to the same letters."""
    sm = difflib.SequenceMatcher(a=[t['key'] for t in script], b=[h['key'] for h in heard], autojunk=False)
    m, used = {}, set()
    for tag, a1, a2, b1, b2 in sm.get_opcodes():
        if tag == 'equal' or (tag == 'replace' and ''.join(t['key'] for t in script[a1:a2]) == ''.join(h['key'] for h in heard[b1:b2])):
            for k in range(a2 - a1):
                m[a1 + k] = min(b1 + k, b2 - 1)
            used.update(range(b1, b2))
    return m, used


def shown(items, limit=SHOW_WORDS):
    ws = [x['raw'] for x in items]
    return ' '.join(ws[:limit]) + (' ...' if len(ws) > limit else '')


def clock(t):
    return f'{t:.1f} s'


def check_reading(say, words, beats=None, approved=(), run=GATE_RUN, rate=GATE_RATE):
    """say: the script's voice text, one string per paragraph. words: Whisper [{w, s, e}] of the final wav. beats: [{start, end}] per voice paragraph.
    Returns a report; report['problems'] is empty when the voice said the script."""
    script, heard = script_items(say, approved), heard_items(words, approved)
    m, used = align(script, heard)
    total = sum(t['width'] for t in script)
    problems, runs, bad = [], [], [i for i in range(len(script)) if i not in m]
    if beats is not None and len(beats) != len(say):
        problems.append(f'the script has {len(say)} paragraphs but the voice has {len(beats)}; the pauses between paragraphs are not all over 0.5 s, or a paragraph was not read')

    def where(p):
        return f'paragraph {p + 1}' + (f' ({beats[p]["start"]:.2f}-{beats[p]["end"]:.2f} s)' if beats is not None and p < len(beats) else '')

    def gap(i, j):  # the heard words between the matched neighbours of script[i:j]
        before = [m[k] for k in range(i - 1, -1, -1) if k in m]
        after = [m[k] for k in range(j, len(script)) if k in m]
        a, b = (before[0] + 1 if before else 0), (after[0] if after else len(heard))
        span = heard[a:b]
        t = span[0]['s'] if span else (heard[a - 1]['e'] if a else 0.0)
        return span, t

    residual, k = [], 0
    while k < len(bad):
        j = k
        while j + 1 < len(bad) and bad[j + 1] == bad[j] + 1:
            j += 1
        toks = script[bad[k]:bad[j] + 1]
        span, t = gap(bad[k], bad[j] + 1)
        residual.append(dict(t=round(t, 2), para=toks[0]['para'], say=shown(toks), heard=shown(span) or '(nothing)', width=sum(x['width'] for x in toks)))
        k = j + 1
    longest = max([r['width'] for r in residual] + [0])
    for r in residual:
        if r['width'] >= run:
            problems.append(f'{r["width"]} script words in a row were not heard, {where(r["para"])}, near {clock(r["t"])}: "{r["say"]}"; heard there: "{r["heard"]}"')
    unmatched = sum(r['width'] for r in residual)
    if total and unmatched / total > rate:
        problems.append(f'{unmatched} of the {total} script words ({unmatched / total:.1%}) were not heard, more than the {rate:.0%} allowed: '
                        + '; '.join(f'"{r["say"]}" ({where(r["para"])}, {clock(r["t"])})' for r in residual[:8]))
    extra = [i for i in range(len(heard)) if i not in used]
    k = 0
    while k < len(extra):
        j = k
        while j + 1 < len(extra) and extra[j + 1] == extra[j] + 1:
            j += 1
        if j - k + 1 >= run:
            ex = heard[extra[k]:extra[j] + 1]
            problems.append(f'the voice said {len(ex)} words in a row that are not in the script, near {clock(ex[0]["s"])}: "{shown(ex)}"')
        k = j + 1
    return dict(ok=not problems, problems=problems, words=total, unmatched=unmatched, rate=round(unmatched / total, 4) if total else 0.0,
                longest_run=longest, residual=residual, listen=listen_list(script, heard, m, residual), approved=approved_hits(script, heard, m))


def approved_hits(script, heard, m):
    hits = {}
    for i, t in enumerate(script):
        if t['kind'] == 'ok' and i in m:
            hits.setdefault(t['label'], []).append(round(heard[m[i]]['s'], 1))
    return hits


def listen_list(script, heard, m, residual):
    """The words worth hearing, by time: every unmatched stretch, then names (capitalised, Latin-letter words) and numbers, grouped by word."""
    items = [dict(r, kind='not heard') for r in residual]
    groups = {}
    for i, t in enumerate(script):
        if i not in m or t['kind'] == 'ok' or not (t['name'] or t['kind'] == 'num'):
            continue
        end = m[i + 1] if i + 1 in m and m[i + 1] > m[i] else m[i] + 1  # a split word (chat GPT) shows all its pieces
        said = shown(heard[m[i]:end], 4)
        if t['kind'] == 'num' and t['width'] < 2 and not any(c.isdigit() for c in said):
            continue  # one number word Whisper also wrote as a word (không, một): nothing to check
        g = groups.setdefault((t['kind'], t['key']), dict(kind='number' if t['kind'] == 'num' else 'name', say=t['raw'], heard=[], times=[], para=t['para']))
        g['times'].append(round(heard[m[i]]['s'], 2))
        g['heard'].append(said)
    for g in groups.values():
        g['t'] = g['times'][0]
        g['heard'] = ' / '.join(dict.fromkeys(g['heard']))
        items.append(g)
    return sorted(items, key=lambda x: x['t'])


LISTEN_KIND = {'not heard': 'không nghe thấy', 'name': 'tên', 'number': 'số'}


def format_listen(listen, approved=None):
    """The listen list the owner reads, in Vietnamese: where in the track, what kind of word, what the script says, what Whisper wrote."""
    lines = []
    for x in listen:
        ts = ', '.join(f'{t:.1f}'.replace('.', ',') for t in x.get('times', [x['t']]))
        lines.append(f'- {ts} giây  [{LISTEN_KIND.get(x["kind"], x["kind"])}] kịch bản nói "{x["say"]}", máy nghe ra "{x["heard"]}"')
    if approved:
        lines.append('- tên anh đã nghe và duyệt, không liệt kê lại: ' + '; '.join(f'{k} ({", ".join(f"{t:.1f}".replace(".", ",") for t in v)} giây)' for k, v in approved.items()))
    return '\n'.join(lines)

def gate(say, words, beats=None, approved=()):
    rep = check_reading(say, words, beats, approved)
    if rep['problems']:
        fail('the voice did not say the script, so no timing file was written\n  ' + '\n  '.join(rep['problems'])
             + '\nre-read it: change the say text of the paragraph (a respelling) or run the step again; do not edit the words list')
    return rep


# -- the final wav's paragraphs and the timing file
def paragraphs_from_silences(ffmpeg_stderr, duration, expected, min_gap=0.5):
    """[{start, end}] per voice paragraph from `silencedetect=noise=-35dB:d=0.12`: the silences over min_gap s separate paragraphs."""
    starts = [float(x) for x in re.findall(r'silence_start: ([\d.]+)', ffmpeg_stderr)]
    ends = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', ffmpeg_stderr)]
    gaps = [(a, b) for a, b in zip(starts, ends) if b - a > min_gap]
    if len(gaps) + 1 != expected:
        fail(f'found {len(gaps) + 1} paragraphs in the final wav, the script has {expected}; the pauses between paragraphs are not all over {min_gap} s, '
             f'or a paragraph holds a long silence')
    edges = [0.0] + [x for g in gaps for x in g] + [duration]
    return [dict(start=round(edges[2 * i], 3), end=round(edges[2 * i + 1], 3)) for i in range(expected)]


def build_timing(wav_name, sample_rate, duration, loudness, pause, spans, words, say, show):
    """The timing file as the builder and halcyon_kich_ban.py read it (the format of the published giong-day-du-timing.json)."""
    return dict(file=wav_name, sample_rate=sample_rate, duration_s=round(duration, 2), loudness=loudness, pause_between_beats_s=pause,
                beats=[dict(beat=i + 1, start=s['start'], end=s['end'], text_shown=show[i], text_spoken=say[i]) for i, s in enumerate(spans)],
                words_whisper_medium=words)


def write_json(path, obj):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write('\n')
