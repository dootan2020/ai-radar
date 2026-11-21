# One command: from a script file to a finished short and an approval pack (`mot-lenh.py`)

```
python video/halcyon/mot-lenh.py <kich-ban.json> --out <run folder> [--chi-kiem]
```
`--chi-kiem` only checks the script and the settings (seconds) and stops. When the run folder already holds a voice made from exactly these `say` texts, it also runs the assembler's floors on every repo beat, so a beat too short for its pages is refused with the seconds it needs before anything else is spent ([QUAY.md](QUAY.md)); with no voice yet the seconds are not known and the first run meets them at `lap-rap`. Exit 0 = the pack is built, exit 2 = stopped at a named step. Nothing is posted and nothing is archived. The logic that needs no audio, GPU or network is `halcyon_mot_lenh.py` (standard library only, `tests/test_halcyon_mot_lenh.py`); the real steps are the existing tools called as subprocesses with deadlines. Their behaviour is not changed: the assembler, voice gate and capture finder refuse exactly as before.

## What it runs, in this order (cheapest refusal first)
| step | what | deadline | reused when |
| --- | --- | --- | --- |
| `kiem-kich-ban` | every refusal that needs nothing but the script (below) | seconds | always runs |
| `kiem-may` | the settings and tools named below; CUDA through the GPU interpreter, `h264_nvenc` in ffmpeg | 60 s | always runs |
| `chup:<ref>` | `chup.mjs`, one per capture ref ([CHUP.md](CHUP.md)) | 60 s per attempt, two attempts per address | its inputs are unchanged **and** the capture is under 6 hours old |
| `quay:<ref>` | `halcyon_quay.py run`, one per `repo` source: GitHub's listing at one commit, a signed-out desktop still of each page, the comparison of the two ([QUAY.md](QUAY.md)) | 90 s per page + 30 s | its inputs are unchanged (repo, branch, the pages and how they are opened, the three tools) **and** the stills are under 6 hours old |
| `chay:<ref>` | `halcyon_chay.py run`, one per `run` source: the commands of a follow-along run for real in a throwaway folder (packages checked at pypi.org / registry.npmjs.org first, pinned, installed with no install scripts), the real log drawn as terminal stills ([CHAY.md](CHAY.md)) | every step's own deadline + 5 min | the run block, the tool and the font are unchanged **and** `chay.json` is under 6 hours old |
| `giong` | `lam-giong.py` ([GIONG.md](GIONG.md)): voice and Whisper paragraph by paragraph (a failing paragraph is made again alone), mastering, gate, timing file | 45 min | the `say` texts, `giong-da-nghe.txt`, the voice tools and the reference voice are unchanged |
| `lap-rap` | `halcyon_kich_ban.py` ([KICH-BAN.md](KICH-BAN.md)): the spec | seconds | always runs |
| `anh` | `dung-video-gpu.py --stills` | 5 min | the spec, its voice, timing words, pictures (for a repo beat: the manifest and **every** still), the builder's code (with `halcyon_repo_walk.py`) and fonts are unchanged |
| `kiem-anh` | the contact sheet and phone previews exist; no capture or repo still older than 6 hours; the builder's plan holds one segment per page of every repo beat, in the script's order, none under 18 frames | seconds | always runs |
| `dung` | `dung-video-gpu.py --render`, then ffprobe (1080x1920, frames = duration x 30, audio present) | 10 min | same inputs as `anh` |
| `nhac` | `tron-nhac.py` (its own refusals: picture, length, loudness shift, peak) | 5 min | the mp4, the track and the tool are unchanged |
| `goi` | the pack, the post text, the listen list, the summary, the archive manifest | seconds | always runs |

A step over its deadline is killed with its whole process tree; its log stays in `cong-viec/nhat-ky/`. The first failure stops the chain with `mot-lenh: STOPPED at step <name>: <reason>` and `to fix: <what to change>`; the same text is in `cong-viec/loi-cuoi.txt`. **After a fix, run the same command again**: finished steps whose inputs did not change are reused and the output says `reused (inputs unchanged ...)`. Changing a caption's `/`, a kicker, an anchor or a headline never redoes the voice; changing a `say` text does. A capture, and the stills of a repo, are taken again after 6 hours, which changes their pictures and so redraws the stills and render (the voice stays).

Reuse state is `cong-viec/trang-thai.json` (a content hash per step). Delete a step's entry, or the file, to force a redo.

## Settings (never a path in code)
| Variable | Names |
| --- | --- |
| `HALCYON_PYTHON` | the GPU interpreter (default `%USERPROFILE%\.venvs\halcyon-gpu\Scripts\python.exe`) |
| `HALCYON_OMNIVOICE_PYTHON`, `HALCYON_VOICE_PROFILES` | as [GIONG.md](GIONG.md) |
| `HALCYON_MUSIC_TRACK` | the "Voice Over Under" mp3 ([README.md](README.md)) |

Also: `ffmpeg`, `ffprobe`, `node`, `magick` on `PATH`; `npm install` once inside `video/` (installs `playwright-core`; the repository tracks no lock file, so do not commit one); an NVIDIA GPU. `kiem-may` names every missing item in one message. The builder's scratch (`TEMP`) is moved into `cong-viec/tmp/`.

## The script
The format is [KICH-BAN.md](KICH-BAN.md) plus two blocks the chain reads (section 7 there): `sources` (where each capture ref is captured) and `post` (the text posted with the video). `tests/fixtures/halcyon/mot-lenh/kich-ban.json` is a complete example: video 05 with its hand-made hook replaced by a capture of the same help page passage.

Refused before anything runs (`kiem-kich-ban`): a `recording` beat or any beat with a `picture` (the chain makes capture, repo, terminal and card beats only; a `terminal` beat or `run` source that breaks [CHAY.md](CHAY.md), an unsafe command included, is refused here too; a hand-made recording or photo belongs to the manual lane); a `repo` beat or source that breaks the contract of [KICH-BAN.md](KICH-BAN.md) 1a and 7; a capture ref with no `sources` entry, a non-public address (not http(s), localhost), an unknown source key, one ref with two different quotes; no end beat last; a `post` with a link, a source line, a music credit, a blank line, or bad hashtags.

## The run folder
```
<run folder>/
  cong-viec/            work files: kich-ban.json (copy), chup/<ref>/, quay/<ref>/ (cay.json, quay.json, the page stills), giong/, dung/ (video.json, stills, mp4s), nhac/, nhat-ky/ (logs), trang-thai.json, nguon.txt
  goi-duyet/            the approval pack
```
## The approval pack (`goi-duyet/`)
| file | for |
| --- | --- |
| `tom-tat.md` | the owner's one-minute steps first (Vietnamese), then what the machine checked and could not, seconds per step (and which steps were reused), every warning any step printed, the source addresses with capture times, for a repo beat "Nguồn đã quay (GitHub)" (repo, branch, commit, time, and each page's address, status and seconds) and how the footage was made, the SHA-256 of the inputs and of both mp4 files, the ffprobe line, the loudness the music step reported, the archive command. `tom-tat.json` is the same as data |
| `halcyon-<id>-<slug>-co-nhac.mp4` | the video to post (with the music bed) |
| `halcyon-<id>-<slug>-khong-nhac.mp4` | the same without music (spare) |
| `noi-dung-dang.txt` | the post text in the owner's format of 19/11/2026: `Tiêu đề:` and the title, `Nội dung đăng:` and the body, then the hashtag line; no source line, no link, no per-platform variants, no music credit |
| `nghe-lai.txt` | the listen list in Vietnamese: the words to hear, by second in the video |
| `anh-tong-quan.jpg` | the contact sheet: every scene |
| `xem-truoc-dien-thoai/` | each scene on a phone with TikTok's overlay, `phone-size-390.png`, and the builder's TikTok-overlay preview mp4 |
| `luu-tru.json` | the manifest for `luu-tru-video.py`; every item waits for approval (a repo's stills, `cay.json` and `quay.json` go to "6 - Nguồn/anh-quay-repo", prefixed with the repo's ref) |

After the owner approves, archiving is one command, which the summary prints with the manifest's full path: `py -3.12 "<video archive>\_he-thong\luu-tru-video.py" "<run folder>\goi-duyet\luu-tru.json" --duyet` (add `--thu` first for a dry run). It copies into the eight numbered folders and sets the row to "Đã duyệt, chưa đăng". This command never runs it.

## Silent paragraphs and moving pictures
A script may hold **silent paragraphs** (`{"silent": true, "beats": [...]}`, [KICH-BAN.md](KICH-BAN.md) 8) and the beat kinds `screen`, `scene3d` and `demo`. The owner's words, 21/11/2026 04:27: no voice and no subtitle while the install is watched, and show what the repository really does (or draw it moving).

**Sources.** `"sources": {"thu": {"run": {...}}}` (CHAY.md) for `screen`; `{"scene": {"name": "giao-thuc", "events_from": "<run source>", "counts_from": "<demo source>"}}` for `scene3d` (`events_from` and `counts_from` optional, each must name a source of the right kind); `{"demo": {"entry": "https://...", "page": "https://...", "say": "<what the script types>", "expect": {...}}}` for `demo` (public https addresses only, never localhost). All three are checked offline by `--chi-kiem`.

**Producers.** Each moving picture is made by one tool, registered in `PRODUCERS` (`halcyon_mot_lenh.py`) so that no later change edits that file: `run` -> `halcyon_chay.py` (step `chay:<ref>`, `screen` beats), `scene` -> `halcyon_canh.py` (step `canh:<ref>`), `demo` -> `halcyon_demo.py` (step `demo:<ref>`). A tool says it is built with a line `CLIP_PRODUCER = 1`; until then the chain stops at step `kiem-nguon-clip` (the first slow step; `--chi-kiem` only warns) with `producer not built yet: ... is built by pull request C|D|E`. A producer is run as `<tool> run --job <job.json> --out <folder>` and must write, in `<folder>` (`cong-viec/chay/<ref>`, `cong-viec/canh/<ref>`, `cong-viec/demo/<ref>`), the manifest named below, or the chain refuses (`the producer finished but wrote no ...`):
- `screen`: one `clip-<steps joined by ->.json` per entry of the job's `blocks` (a list of step lists; the job is the chay job plus `blocks`), next to `chay.json`.
- `scene3d`: `clip.json`; the job carries `scene`, `events_run` (path of the run's `chay.json`) and `counts_demo` (path of the demo's `demo.json`) when the source names them. A demo runs before a scene, a run before both.
- `demo`: `demo.json` and the webm it names (`file`, relative to the manifest).
Manifest fields: KICH-BAN.md 8 (a clip manifest also carries `min_text_px`, `stills`, `segments`, `proof`, `tool_sha` for the builder and the pack). Manifests older than six hours are refused at `kiem-anh`, like captures.

**Silence and music.** After `giong` (voiced paragraphs only: the voice tool is given a copy of the script without the silent ones) the `lang` step writes `cong-viec/lang/giong-day-du.wav` and its timing; `lap-rap` reads that timing and `--clips`. `halcyon_lang.py` refuses a silence that is not between two voiced paragraphs, two in one gap, or one under 0.5 s, and checks its own result (the voice outside the silences is the same samples, the silences are digital silence, every word moved by exactly the silence before it). `tron-nhac.py` gets `--silence A:B` for each span of `spec.silences` and lifts the bed by **+12 dB** there (0.4 s ramps; the adviser's addition, the owner will judge by ear; `HALCYON_LIFT_DB` sets another number). The loudness guard then compares the voiced part only (spans and 0.2 s around them left out; it still refuses a move above 0.3 LU), refuses an input that is louder than -60 dBFS inside a span, and refuses a lifted bed outside -30 to -16 LUFS measured inside the spans.

Whisper word ends overrun: a word that starts before a silence but ends up to 0.5 s after the cut is cut at the silence when the original voice there is quiet (at most -45 dBFS), and is listed in `word_ends_cut_at_silence` in the timing file; a longer overrun, or speech energy there, still refuses the step.

**Second witness (`kiem-anh`).** Inside every silent span: no caption unit in the builder's plan (`video-plan.json` `units`), no word heard in the timing file, the voice file quieter than -60 dBFS; every span has a beat with `captions: false` at the same times and every such beat a span. The builder ends the last caption unit before a span at the span's start (`halcyon_spec.end_units_at_silences`), so the plan it writes is truthful; a unit or word that really falls inside a span is still refused.

**Pack.** `tom-tat.md` lists the silent spans and the moving pictures with their manifests, and says what the machine cannot know: whether the music lift sounds right, and that typed commands in a screen clip are drawn at a fixed rate (the output and its times are the real ones). `luu-tru.json` archives the manifests and the voice with its silences.

## Warnings
A warning is a line a step printed that says so: it contains `warn`, `not gated`, `not drawn`, `not measured`, `under 4.5`, `refus`, `skipp` or `note(s):` (an empty `unit notes` is not one); a capture's failed attempts and fallbacks are warnings too. The summary lists each distinct warning once with the steps that printed it. With the current layout (thu-gon-r3-l2, the script default since 19/11/2026) expect `source chip not drawn` on every capture beat (the owner's 18-19/11 decision dropped the chip), a PyTorch `NumPy array is not writable` line, and, on the 05 script, card kicker contrast of 3.97 to 3.98:1 on layout thu-gon-r3-l2 (4.08 to 4.1 on the earlier thu-gon-r2); printed, not refused, by the builder: read them, do not ignore new ones. The full output of each step is in `cong-viec/nhat-ky/<step>.out` and `.err`.

## What it cannot show
Listening: the voice gate proves words were said, not said well, and a name Whisper heard right in one take can be wrong in the next. A capture proves the sentence is on the page now, not that the page is true or that the story's date is recent (no check of the page's date). Taste of the picture is for the contact sheet and the owner. For a repo beat the machine proves the folders exist at the commit and the rows on screen are GitHub's own; it cannot judge whether those are the folders worth showing, and the pointer, scroll and zoom are drawn by the builder from still pictures, not a live screen recording (the pack says so). The first ten automatic videos are each approved by the owner (decision of 19/11/2026).

## Runbook for the session that writes the script
1. From the pick the site made, read the story and its sources; decide the beats (which are captures of a public page passage, which are cards: number, chart, list), the headlines, kickers, the `say` respellings of names and numbers.
2. Write `kich-ban.json` ([KICH-BAN.md](KICH-BAN.md), `sources`, `post`). Every capture's quote must be a sentence the page shows word for word; a video that introduces a GitHub repo carries a `repo` beat that opens its folders (KICH-BAN.md 1a has a full example), and its paragraph must be long enough for the pages (the floors, seconds named by the assembler); if the evidence is a hand-made recording or photo, change the beat or do the manual lane.
3. `python video/halcyon/mot-lenh.py kich-ban.json --out <run folder> --chi-kiem`, then the same without `--chi-kiem` (about eight minutes the first time, mostly the voice).
4. On a stop: read the named step and `to fix` (a `quay:<ref>` stop names the page and what GitHub showed; a wall, limit or timeout is not the script's fault: run again later, and skip the pick if it stops the same way twice), change the script, run the same command again. Do not edit the tools or the work files; a step that reads wrong is for the coordinator.
5. When it says DONE: open `anh-tong-quan.jpg` and one phone preview yourself, read `tom-tat.md` (warnings, sources, loudness) and `nghe-lai.txt`. Judge: do the pictures show what the voice says, is the claim what the sources say, does anything look cut off. The machine cannot hear the voice: say so.
6. Hand the owner the pack (`tom-tat.md` first, the mp4, `nghe-lai.txt`, `noi-dung-dang.txt`). His one tap is the approval; until then nothing is archived or posted.
7. After the approval: run the archive command, post with the owner's tools or by his instruction (his music credit is his to add), then record the posting.
Still the session's own judgement: the story, the beats and wording, which quote proves which beat, how to respell a name, whether to re-capture or change a source after a refusal, and what to tell the owner about anything odd. Run `python -m unittest tests.test_halcyon_mot_lenh tests.test_halcyon_giong tests.test_halcyon_kich_ban tests.test_halcyon_chup` after changing any of the tools.
