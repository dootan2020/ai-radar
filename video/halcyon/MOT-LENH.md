# One command: from a script file to a finished short and an approval pack (`mot-lenh.py`)

```
python video/halcyon/mot-lenh.py <kich-ban.json> --out <run folder> [--chi-kiem]
```
`--chi-kiem` only checks the script and the settings (seconds) and stops. Exit 0 = the pack is built, exit 2 = stopped at a named step. Nothing is posted and nothing is archived. The logic that needs no audio, GPU or network is `halcyon_mot_lenh.py` (standard library only, `tests/test_halcyon_mot_lenh.py`); the real steps are the existing tools called as subprocesses with deadlines. Their behaviour is not changed: the assembler, voice gate and capture finder refuse exactly as before.

## What it runs, in this order (cheapest refusal first)
| step | what | deadline | reused when |
| --- | --- | --- | --- |
| `kiem-kich-ban` | every refusal that needs nothing but the script (below) | seconds | always runs |
| `kiem-may` | the settings and tools named below; CUDA through the GPU interpreter, `h264_nvenc` in ffmpeg | 60 s | always runs |
| `chup:<ref>` | `chup.mjs`, one per capture ref ([CHUP.md](CHUP.md)) | 60 s per attempt, two attempts per address | its inputs are unchanged **and** the capture is under 6 hours old |
| `giong` | `lam-giong.py` ([GIONG.md](GIONG.md)): voice, mastering, Whisper, gate, timing file | 20 min | the `say` texts, `giong-da-nghe.txt`, the voice tools and the reference voice are unchanged |
| `lap-rap` | `halcyon_kich_ban.py` ([KICH-BAN.md](KICH-BAN.md)): the spec | seconds | always runs |
| `anh` | `dung-video-gpu.py --stills` | 5 min | the spec, its voice, timing words, pictures, the builder's code and fonts are unchanged |
| `kiem-anh` | the contact sheet and phone previews exist; no capture older than 6 hours | seconds | always runs |
| `dung` | `dung-video-gpu.py --render`, then ffprobe (1080x1920, frames = duration x 30, audio present) | 10 min | same inputs as `anh` |
| `nhac` | `tron-nhac.py` (its own refusals: picture, length, loudness shift, peak) | 5 min | the mp4, the track and the tool are unchanged |
| `goi` | the pack, the post text, the listen list, the summary, the archive manifest | seconds | always runs |

A step over its deadline is killed with its whole process tree; its log stays in `cong-viec/nhat-ky/`. The first failure stops the chain with `mot-lenh: STOPPED at step <name>: <reason>` and `to fix: <what to change>`; the same text is in `cong-viec/loi-cuoi.txt`. **After a fix, run the same command again**: finished steps whose inputs did not change are reused and the output says `reused (inputs unchanged ...)`. Changing a caption's `/`, a kicker, an anchor or a headline never redoes the voice; changing a `say` text does. A capture is taken again after 6 hours, which changes its picture and so redraws the stills and render (the voice stays).

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

Refused before anything runs (`kiem-kich-ban`): a `recording` beat or any beat with a `picture` (the chain makes capture beats and card beats only; a hand-made recording or photo belongs to the manual lane); a capture ref with no `sources` entry, a non-public address (not http(s), localhost), an unknown source key, one ref with two different quotes; no end beat last; a `post` with a link, a source line, a music credit, a blank line, or bad hashtags.

## The run folder
```
<run folder>/
  cong-viec/            work files: kich-ban.json (copy), chup/<ref>/, giong/, dung/ (video.json, stills, mp4s), nhac/, nhat-ky/ (logs), trang-thai.json, nguon.txt
  goi-duyet/            the approval pack
```
## The approval pack (`goi-duyet/`)
| file | for |
| --- | --- |
| `tom-tat.md` | the owner's one-minute steps first (Vietnamese), then what the machine checked and could not, seconds per step (and which steps were reused), every warning any step printed, the source addresses with capture times, the SHA-256 of the inputs and of both mp4 files, the ffprobe line, the loudness the music step reported, the archive command. `tom-tat.json` is the same as data |
| `halcyon-<id>-<slug>-co-nhac.mp4` | the video to post (with the music bed) |
| `halcyon-<id>-<slug>-khong-nhac.mp4` | the same without music (spare) |
| `noi-dung-dang.txt` | the post text in the owner's format of 19/11/2026: `Tiêu đề:` and the title, `Nội dung đăng:` and the body, then the hashtag line; no source line, no link, no per-platform variants, no music credit |
| `nghe-lai.txt` | the listen list in Vietnamese: the words to hear, by second in the video |
| `anh-tong-quan.jpg` | the contact sheet: every scene |
| `xem-truoc-dien-thoai/` | each scene on a phone with TikTok's overlay, `phone-size-390.png`, and the builder's TikTok-overlay preview mp4 |
| `luu-tru.json` | the manifest for `luu-tru-video.py`; every item waits for approval |

After the owner approves, archiving is one command, which the summary prints with the manifest's full path: `py -3.12 "<video archive>\_he-thong\luu-tru-video.py" "<run folder>\goi-duyet\luu-tru.json" --duyet` (add `--thu` first for a dry run). It copies into the eight numbered folders and sets the row to "Đã duyệt, chưa đăng". This command never runs it.

## Warnings
A warning is a line a step printed that says so: it contains `warn`, `not gated`, `not drawn`, `not measured`, `under 4.5`, `refus`, `skipp` or `note(s):` (an empty `unit notes` is not one); a capture's failed attempts and fallbacks are warnings too. The summary lists each distinct warning once with the steps that printed it. With the current layout (thu-gon-r3-l2, the script default since 19/11/2026) expect `source chip not drawn` on every capture beat (the owner's 18-19/11 decision dropped the chip), a PyTorch `NumPy array is not writable` line, and, on the 05 script, card kicker contrast of 3.97 to 3.98:1 on layout thu-gon-r3-l2 (4.08 to 4.1 on the earlier thu-gon-r2); printed, not refused, by the builder: read them, do not ignore new ones. The full output of each step is in `cong-viec/nhat-ky/<step>.out` and `.err`.

## What it cannot show
Listening: the voice gate proves words were said, not said well, and a name Whisper heard right in one take can be wrong in the next. A capture proves the sentence is on the page now, not that the page is true or that the story's date is recent (no check of the page's date). Taste of the picture is for the contact sheet and the owner. The first ten automatic videos are each approved by the owner (decision of 19/11/2026).

## Runbook for the session that writes the script
1. From the pick the site made, read the story and its sources; decide the beats (which are captures of a public page passage, which are cards: number, chart, list), the headlines, kickers, the `say` respellings of names and numbers.
2. Write `kich-ban.json` ([KICH-BAN.md](KICH-BAN.md), `sources`, `post`). Every capture's quote must be a sentence the page shows word for word; if the evidence is a hand-made recording or photo, change the beat or do the manual lane.
3. `python video/halcyon/mot-lenh.py kich-ban.json --out <run folder> --chi-kiem`, then the same without `--chi-kiem` (about eight minutes the first time, mostly the voice).
4. On a stop: read the named step and `to fix`, change the script, run the same command again. Do not edit the tools or the work files; a step that reads wrong is for the coordinator.
5. When it says DONE: open `anh-tong-quan.jpg` and one phone preview yourself, read `tom-tat.md` (warnings, sources, loudness) and `nghe-lai.txt`. Judge: do the pictures show what the voice says, is the claim what the sources say, does anything look cut off. The machine cannot hear the voice: say so.
6. Hand the owner the pack (`tom-tat.md` first, the mp4, `nghe-lai.txt`, `noi-dung-dang.txt`). His one tap is the approval; until then nothing is archived or posted.
7. After the approval: run the archive command, post with the owner's tools or by his instruction (his music credit is his to add), then record the posting.
Still the session's own judgement: the story, the beats and wording, which quote proves which beat, how to respell a name, whether to re-capture or change a source after a refusal, and what to tell the owner about anything odd. Run `python -m unittest tests.test_halcyon_mot_lenh tests.test_halcyon_giong tests.test_halcyon_kich_ban tests.test_halcyon_chup` after changing any of the tools.
