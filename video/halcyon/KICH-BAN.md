# From a script to a builder spec (`kich-ban.json` -> `video.json`)

`halcyon_kich_ban.py` turns three inputs into the `video.json` that `dung-video-gpu.py` reads ([SPEC.md](SPEC.md)), with no hand editing. Standard library only (it reads the fonts' cmap tables itself), so it runs and is tested without a GPU.

```
python halcyon_kich_ban.py kich-ban.json --timing <voice folder>/giong-day-du-timing.json [--captures captures.json] --out video.json
```
Paths inside the output are relative to `--out`. The voice file is the timing file's `file` field, next to the timing file. Every refusal is `kich-ban: <what is wrong and what to change>` and nothing is written.

**One rule for choices.** The script is the only place a person's or agent's choice lives. Where a rule can supply a value, the script may still write one, and then it wins over the rule: caption line breaks (`/`), `kicker`, `chip`, `source`, `tail`, a band's time (`at`), an `occurrence`. With no explicit value the rule applies.

## 1. The script (`kich-ban.json`)
```
{ "id": "05", "title": "...", "outlet": "TechCrunch", "date": "17/11/2026",
  "tiktok_caption": ["line 1", "line 2 #tags"],
  "slug": "...", "chip_prefix": "Ảnh chụp", "tail": 0.70, "word_aliases": {}, "layout": "thu-gon-r3-l2", "drop_kickers": true,   (all optional)
  "paragraphs": [ { "say": "text for the voice, numbers as words",
                    "show": "caption text, numerals allowed, \"/\" marks a line break",
                    "numbers": {"8:30": "tám giờ rưỡi"},                      (optional, see 3)
                    "beats": [ {beat}, ... ] } ] }
```
One paragraph = one voice paragraph (the voice step writes one blank-line paragraph per entry). Write `say` and `show` as the words are written (`AI`, `GitHub`, `apps`, `Claude Code`, `video`, `30 USD`): the voice step respells the words of the default table for the voice only ([GIONG.md](GIONG.md) § Default readings: `AI` is read "Ây-ai", `GitHub` "Git hắp", `apps` "áp", `code` "cốt", `hook` "húc", `USD` "đô la Mỹ", and the other brands and terms listed there), so write the English spelling and respell only a word that table lacks; your own respelling in `say` wins. A paragraph has one beat, or several: the later ones carry `"from_sentence": k` (sentence k, counted from 0, a sentence ends at a word ending in `. ? !`). The first paragraph's first beat is the hook, the last beat must be `{"kind": "end"}`.

Beat kinds (every beat may carry `name`, `id`; otherwise ids are `1`, `2a`, `2b`, ...):
| kind | fields |
|---|---|
| `capture` | `headline` [2 lines], `kicker`, `chip` (else `<chip_prefix>: <source>, <date>` from the manifest), `headline_anchor` (reveals line 2), `capture: {ref, quote, bands: [{text, anchor? \| at?, occurrence?}]}`; `ref` names a manifest entry, `quote` is the verbatim sentence captured |
| `repo` | `headline` [2 lines], `kicker`, `chip` (else `<chip_prefix>: GitHub`), `repo: {ref, open}`; the repository's pages shown one after another, see 1a |
| `terminal` | `headline` [2 lines], `kicker`, `chip` (else `Chạy thật: <date>`), `level`, `headline_anchor`, `terminal: {ref, step, bands: [{text, anchor? \| at?}]}`; the picture of one step of a run the chain made for real, drawn as a capture (key `<ref>-s<step>` in the manifest, whose `text` is the quote), see 1b and [CHAY.md](CHAY.md) |
| `recording` | `headline`, `kicker`, `chip_line`, `picture` (copied as is: a hand-made screen recording is an input file, outside the chain) |
| `number` | `kicker`, `line1`, `line2`, `source`, `anchor` (reveals line 2) |
| `chart` | `kicker`, `rows: [{name, value, bar, anchor?}]`, `bar_full`, `note` + `note_anchor`, `source` |
| `list` | `kicker`, `title`, `rows: [{text, anchor}]`, `source` |
| `end` | nothing; copies the first beat's chip and picture |

### 1a. The `repo` beat (a walk through a GitHub repository)
```
"sources": { "plannotator": { "repo": "backnotprop/plannotator" } }                     (optional "branch"; default = the repo's default branch)

{ "kind": "repo", "headline": ["...", "..."], "kicker": "...",
  "repo": { "ref": "plannotator",
            "open": ["packages", {"path": "packages/server", "anchor": "server"}, "package.json"] } }
```
A full paragraph, as video 06's second script (backnotprop/plannotator) uses it: the voice says the respelled words (`húc` for hook; `apps` needs none, the default table reads it "áp"), the subtitle keeps the written ones, each anchor is a word of the shown (written) text that the voice says at that moment (`apps`), and the beat is the paragraph's only beat.
```
"sources": { "gh-repo": { "repo": "backnotprop/plannotator" } },
{ "say": "Nó chạy trên máy bạn, gắn vào các trợ lý AI viết cốt phổ biến hiện nay. Mở dự án này trên Git hắp ra, bạn sẽ thấy mỗi trợ lý có một chỗ gắn riêng. Tất cả nằm trong thư mục apps. Vào trong đó, mỗi trợ lý là một thư mục con, như thư mục húc. Mở thư mục đó ra, cuộn xuống từ từ, đọc thử vài dòng đầu, và tệp hướng dẫn sẽ chỉ bạn cách cài đặt từng bước.",
  "show": "Nó chạy trên máy bạn, / gắn vào các trợ lý / AI viết code / phổ biến hiện nay. / Mở dự án này trên GitHub ra, / bạn sẽ thấy mỗi trợ lý / có một chỗ gắn riêng. / Tất cả nằm trong thư mục apps. / Vào trong đó, mỗi trợ lý / là một thư mục con, / như thư mục hook. / Mở thư mục đó ra, / cuộn xuống từ từ, / đọc thử vài dòng đầu, / và tệp hướng dẫn sẽ chỉ bạn / cách cài đặt từng bước.",
  "beats": [ { "kind": "repo", "name": "Mở thư mục apps trên GitHub", "headline": ["Mở thẳng repo", "xem từng thư mục"], "kicker": "Theo GitHub của Plannotator", "level": "FOOT",
              "repo": { "ref": "gh-repo", "open": [ { "path": "apps", "anchor": "apps" }, { "path": "apps/hook", "anchor": "hook" }, { "path": "apps/hook/README.md", "anchor": "tệp" } ] } } ] }
```
The voice names a folder and the page opens at that word: `apps` when it says apps, `apps/hook` when it says hook, the README at "tệp". Home lasts until the first anchor (here about 8 s: it carries the opening look and the camera's push-in), so write the sentences before the first folder name long enough for the home floor. Moving an anchor never redoes the voice; changing a `say` text does.

- **Which repo**: `sources[ref].repo`, `owner/name`. One ref is one repo; several beats may share it, each with its own `open`. A source has `repo` or `urls`, never both.
- **What is shown**: every repo beat starts on the repo home page (name, description, stars, the first rows of the file list). `open` lists the folders and files to open, as paths from the repo root, in the order they are shown. `open: []` is the home page alone. A file ends a descent; `README.md` is a file like any other (write it as a path).
- **Where a page is opened from**: its parent folder, which is the repo root or an earlier entry of the same list. When the parent is the page on screen the row is tapped; when it is an earlier page the view slides back to it first (its own `via: "back"` entry in the walk).
- **GitHub's single-folder chains**: a folder that holds only one folder is shown as ONE row linking to the deepest folder (`.agents/skills` on a page that lists `.agents`; there is no page for `.agents` to open). Such a path may skip its intermediate folders only when it says so: `{"path": ".agents/skills", "chain": true}`. It is then opened from the nearest earlier entry that is its ancestor, or from the root. Without `chain` the parent must be listed (refused otherwise); the script cannot see the chain, so the `cay` step checks the skipped folders against GitHub.
- **Limits**: at most 5 entries in one beat, and at most 5 different paths over all the beats of one repo (the recorder loads at most six pages per repo).
- **When each page opens** (the assembler, `repo_beat`): an entry with an `anchor` (spoken words in the beat, like every anchor; `occurrence` as usual) opens at the anchor's time. Between two anchored entries, and over the whole beat when none has an anchor, every page gets its floor and the time above the floors is shared equally. The floors are the constants `FLOOR` in `halcyon_kich_ban.py`, by window (`level`: FOOT is the tall window, HOOK the short one of an opening beat), in seconds. They are the least the builder's camera needs ([SPEC.md](SPEC.md), measured on PR #277) plus 0.1 s, taken for a row that needs a pan, so a beat that passes here is never refused by the builder for time: home page 2.15 (FOOT) / 3.15 (HOOK), a page opened by a tap that something is opened from 2.2 / 3.25, a slide back 1.15, a page nothing is opened from (the last page of the beat, or one followed by a slide back) 0.7, and on the home page of the first repo beat of the video the opening whole-width look before the camera pushes in, +2.25 / +2.9. Rows that are already in view need less, never more. A beat that cannot give its pages their floors is refused with the seconds needed; so is an anchor that leaves a page under its floor or puts pages out of order.
- **What the assembler writes**: the beat's picture is `{"kind": "repo", "manifest": "<recorder manifest, relative to the spec>", "walk": [{"page": "", "a": 0.0}, {"page": "packages", "a": 2.92, "via": "tap"}, {"page": "", "a": 6.5, "via": "back"}, ...]}`. `page` is a path from the repo root (`""` = home); `a` is the second the page starts to appear in the video; a page lasts until the next entry's `a` (the last one until the beat's end). The recorder manifest is `--quay <quay.json>` (every repo beat) or `--quay <ref>=<quay.json>` (one per ref); the assembler only writes its path.
- `level` is HOOK unless the beat says otherwise; **write `"level": "FOOT"` on every repo beat that is not the opening one**, which gives the page the tall window (about 11 file rows) and the floors above for FOOT. `wm` on the first and last beat, like a capture beat. The end beat copies the first beat's chip and picture as usual.

An **anchor** is the spoken words (one or more, in the `show` text) that trigger a reveal. It is searched only among the words of its own beat; not found, or found twice with no `occurrence`, refuses.

### 1b. The `terminal` beat (commands run for real)
A follow-along shows the commands and what they print. `halcyon_chay.py` (step `chay:<ref>`) runs them in a throwaway folder and writes one picture and one manifest entry per step; the entry is a capture entry (`file`, `focus.rows`, `u_rows`, `source`, `date`, `captured`, `bands`) plus `text`, the text drawn. The beat names the step; the assembler turns it into the same `capture` picture, bands and chip rules as a capture beat, so the builder needs no change. Refused here: a `terminal` block without `ref` or with a `step` that is not a whole number from 0; a step with no picture in the manifest; a band text that is not on the picture (`no band "..."`). The contract, the files, and every safety gate are in [CHAY.md](CHAY.md).

## 2. The timing file (slice 2 writes it)
`giong-day-du-timing.json` as the builder already reads it, plus two things the assembler relies on:
- `words_whisper_medium`: `[{w, s, e}]`, Whisper words of the FINAL wav (start and end, seconds).
- `beats`: `[{beat, start, end}]`, one entry per voice paragraph, **measured on the final wav** (speech start and end of each paragraph). The cut between two beats is the midpoint of the gap between one paragraph's `end` and the next one's `start`. Published video 03's timing file held the paragraph spans of the raw synthesis, up to 0.05 s off the final wav because one paragraph was spliced; the spans must come from the final wav (the silences over 0.5 s of `silencedetect=noise=-35dB:d=0.12`). Slice 2 owns this measurement.
- `duration_s` (wav length) and `file` (the wav's name).

## 3. What each spec field comes from
| field | source |
|---|---|
| `name`, `out` | `halcyon-<id>`; slug of `title` (or `slug`) |
| `duration` | `duration_s` + `tail` (0.70). Published tails were 0.68, 0.71 (frames are the same) |
| `voice`, `timing` | the timing file's location |
| `word_aliases` | the script's, plus every spelling difference between a `show` word and the Whisper word at the same place that normalisation does not remove (paired position by position in a mismatching block; an unequal block pairs only its first words) |
| `captions` | `show` split at `/`; a paragraph without a `/` is split by rule: a unit per clause (after `, : ;`), wrapped greedily to 22 characters. The rule matched 28% (05) and 27% (03) of the published lines, all of them fit; rhythm is a choice, write the `/` when it matters |
| beat `a`, `b` | paragraph gap midpoints; inside a paragraph, the midpoint between the Whisper end of the last word of one sentence and the Whisper start of the first word of the next; first = 0, last = `duration` |
| `text.cuts`, band `at` | Whisper start of the anchor's first word minus 0.08 s, rounded to 0.01 s; a chart row, or list/number reveal without `anchor`, shows at the beat start; a band with no `anchor`/`at` uses the first word of its text if that is spoken in the beat, otherwise it refuses |
| `picture`, bands' `rect` | the capture manifest entry named by `ref` (section 4); a repo beat: the walk of 1a |
| `level`, `mark`, `lift`, `kicker_size` | constants: capture/repo/recording beats HOOK; `wm` on the first and last beat; lift 24 on the first and the end beat; kicker size 26; cards have no `level` |
| `chip` | explicit, else `<chip_prefix>: <source>, <date>` of the manifest entry; at most 43 characters |
| card `kicker`, `source` | `kicker` upper-cased; `source` explicit, else `Nguồn: <outlet>, <date>` (a list card has none unless given) |
| `layout`, `drop_kickers` | `thu-gon-r3-l2` (owner 19/11/2026 22:54, "Chọn +2 dòng"), `true`. r3-l2 = thu-gon-r2 with the subtitle 312 px higher (its lowest ink then ends at y 1350, 343 px above y 1693), the headline block drawn on the opening beat only (lifted 262 px more) and none on the other picture beats; the ending card moves up with it. Posted videos keep naming `thu-gon-r2` in their own spec and rebuild as before |

## 4. The capture manifest (`captures.json`, slice 3 writes it)
```
{"captures": { "<ref>": { "file": "g-2b.png", "focus": {"rows": [445, 1124]}   or   {"lines": [0, 5], "band_rows": [1300, 1860]},
                           "u_rows": [410, 1132], "source": "Quyền riêng tư Gemini", "date": "18/11/2026", "captured": "2026-11-18T09:00:00+07:00",
                           "bands": [{"rect": [x, y, w, h], "text": "tạm thời"}, ...] } } }
```
`file` is relative to the spec (copied as is). `focus` and `u_rows` are the builder's `picture` fields; `u_rows` must contain `focus.rows`. `source` and `date` make the chip; `captured` is the capture time (the final command checks its age). `bands` are one rect per wrapped line of the quoted phrase, with the text in the rect (the source's language). One entry may serve several beats; a beat picks the bands it wants by `text`. A capture with no bands is allowed.

## 5. Refusals (each has a test in `tests/test_halcyon_kich_ban.py`)
| situation | message names |
|---|---|
| a caption unit would start on a later equal word (the voice dropped its first word: the builder searches forward and attaches silently) | the unit, the time it would get, the window it should be in |
| a digit group on screen the voice does not say (voice text has no such digits and no number words of that value; a card may recap another paragraph) | the group and the text; declare `numbers: {"8:30": "tám giờ rưỡi"}` (section 1), whose phrase must be in the voice text |
| a character with no glyph in Barlow Condensed (upper-cased caps text) or Be Vietnam Pro (kicker, chip, source) | the character and the font file |
| a band text not contained in the beat's `quote` | the band and beat |
| anchor not spoken in the beat, ambiguous, or its word not heard; band time unknown | the anchor and the beat's words |
| a repo beat with no recorder manifest; a bad `open` list (the same contract as the chain's check, 7); a beat too short for the floors of its pages; anchors out of order; an anchor that leaves a page under its floor | the beat, the page and the seconds |
| script paragraphs differ from the timing file's; beat shorter than zero; bad `from_sentence`; chip over 43 characters; unknown `ref`; manifest field missing, `u_rows` not containing the focus | the field |

Not checked here (they need Pillow, the GPU or the network, so they stay with the builder and later slices): contrast and safe frame (the builder refuses), a page that is a cookie wall or stale, voice pronunciation, a name read wrongly.

## 6. Proof on two published videos
Reproduced from their scripts, timing and manifests in `tests/fixtures/halcyon/<id>/` (text only, already published), checked by the test and, with the GPU, by `--stills` plus `kiem-hoi-quy.py`:
- Video 05 and video 03: `RESULT: EQUAL` against the published plan, and every still identical by hash to the published one (65 files for 05, 40 for 03).
- The assembled spec equals the published one except: `duration` (28.49 against 28.5, 30.31 against 30.29: the rule tail, same frame count), a band time written as `at` seconds where the published spec named the caption words, a reveal written in seconds where it named a caption word (the frames equal the published plan's, tested), and video 03's card beat has no `level: CARD` (the builder's default for a card).
- The published 03 `v1/video.json` is newer than its generator `gen-spec.py`: it focuses on `rows` (and other `u_rows`) where the generator wrote `lines` and `band_rows`. The manifest carries the published values.

## 7. What the one command adds to the script (`mot-lenh.py`, [MOT-LENH.md](MOT-LENH.md))
Two top-level blocks the assembler ignores and the chain reads. Both are checked before anything runs.
```
"sources": { "<ref>": { "urls": ["https://...", "https://... (fallback)"], "hco": "https://hco.news/tin/...",   (urls required, the rest optional)
                        "open": "<heading to expand>", "follow": false, "occurrence": 1 | "last", "source": "chip label", "date": "dd/mm/yyyy",
                        "locale": "vi-VN", "ua": "iphone", "max_rows": 700 } },
"post": { "title": "one line", "body": "one block; single line breaks, no blank line", "hashtags": ["#AI", "#halcyon"] }
```
- `sources` has one entry per capture `ref` used by a beat. The sentence captured is the beat's `capture.quote`; the phrases highlighted are the texts of the beat's `capture.bands` (a phrase that wraps over two lines comes back as one band per line, so name the bands by their line texts, as in the published 05 script). One ref is one picture of one sentence: a second beat that needs another sentence needs its own ref. The options are `chup.mjs`'s ([CHUP.md](CHUP.md)).
- A **repo source** is `{"repo": "owner/name", "branch": "main"}` (branch optional) and nothing else. The chain's script check (`kiem-kich-ban`, no network) refuses, each with a `to fix:` line: `repo` that is not `owner/name`; a source with both `urls` and `repo` (or `branch` without `repo`); a repo beat with no `repo` block, no `open` key, or whose ref has no source or a source without `repo`; an `open` path that is empty, absolute, holds `..` (or `.`) or a backslash or an empty part, or repeats; a parent that is neither the root nor an earlier entry (unless `chain`); more than 5 entries in a beat, or more than 5 different paths over the beats of one repo; a capture beat whose ref is a repo source. The shared rules are `parse_open` and `repo_problem` in `halcyon_kich_ban.py`; the chain's check calls them.
- `post` is the text posted with the video, in the owner's format of 19/11/2026: the chain writes `Tiêu đề:`, the title, `Nội dung đăng:`, the body, then the hashtag line. No source line, no link, no per-platform variants, no music credit line (all refused).
- A **run source** is `{"run": {"files": [...], "steps": [...], "packages": {...}}}` and nothing else ([CHAY.md](CHAY.md)); the chain's script check refuses an unsafe or malformed run block, a terminal beat whose ref has no `run` source or whose `step` is out of range, and a capture beat whose ref is a run source, before anything runs.
- The chain makes `capture`, `repo`, `terminal` and card beats (`number`, `chart`, `list`, `end`) only. A `recording` beat, or any beat with a `picture`, is refused: a hand-made recording or photo is an input file outside the chain.