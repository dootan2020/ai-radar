# From script text to a finished voice (`lam-giong.py`)

One command turns the `say` text of a script (`kich-ban.json`, format in [KICH-BAN.md](KICH-BAN.md)) into the channel voice track and the `giong-day-du-timing.json` that `halcyon_kich_ban.py` reads, and refuses a voice that did not say the script.

```
python lam-giong.py kich-ban.json --out <folder> [--approved giong-da-nghe.txt]
```
Writes into `<folder>`: `giong-day-du.wav` (48 kHz mono, -15 LUFS, peak -1.5 dBTP), `giong-day-du-timing.json`, `nghe-lai.txt` (the listen list), `giong-ket-qua.json` (gate report and step times), plus the work files (`tts-raw*.wav/json`, `whisper-words.json`, `loi-doc-tts.txt`, `loi-hien-thi.txt`, logs). Then `halcyon_kich_ban.py <script> --timing <folder>/giong-day-du-timing.json ...`.

## Settings (never a path in code)
| Variable | Names |
|---|---|
| `HALCYON_OMNIVOICE_PYTHON` | the Python with OmniVoice and faster-whisper installed (runs synthesis and Whisper) |
| `HALCYON_VOICE_PROFILES` | the folder that holds the profile folder `vhn-giong-tin-ai` (`profile.toml`, `reference.wav`; the reference audio is not in the repo) |

Also needed: `ffmpeg` and `ffprobe` on `PATH`; the voice model and Whisper medium already in the local Hugging Face cache (everything runs offline). The voice, speed 0.93, 0.3 s pause between paragraphs, CPU, and the mastering chain are the settings the published voices used and are not options.

## Steps
1. `loi-doc-tts.txt` (the voice text: the `say` paragraphs with the default readings below applied, one blank line between) and `loi-hien-thi.txt`.
2. Synthesis, `video/scripts/omnivoice_tts.py synthesize --split-paragraphs --pause-ms 300 --speed 0.93 --offline` (one chunk per paragraph, `fix_omnivoice` inside). Deadline 20 minutes, then the process tree is killed and the log tail printed.
3. ffmpeg: `highpass=f=70`, compressor, `loudnorm I=-15 TP=-1.5 LRA=4`, 48 kHz mono. Refuses outside -16..-14 LUFS or a peak above -1 dBTP.
4. Whisper medium (CPU int8, Vietnamese, word times) on the FINAL wav. Deadline 10 minutes.
5. The voice paragraphs measured on the final wav: silences over 0.5 s (`silencedetect=-35dB:d=0.12`) separate them; `beats` hold the speech start and end of each. Refuses when the count is not the script's.
6. The gate (below).
7. The timing file (`file`, `sample_rate`, `duration_s`, `loudness`, `pause_between_beats_s`, `beats`, `words_whisper_medium`) and the listen list.

Measured on video 05 (7 paragraphs, 27.5 s of voice, CPU): synthesis 227 s and 277 s in two runs, mastering 1-2 s, Whisper 23 s, the rest under 0.1 s: about 4-5 minutes.

## Default readings (`PRONUNCIATIONS` in `halcyon_giong.py`)
The voice says some written words differently from how they are spelled. One table, applied to the voice text only (what is synthesised, what the gate expects, `text_spoken` in the timing file). The subtitle (`show`), cards and post text keep the written word.

| Written | Voice text | Owner |
|---|---|---|
| `AI` | `Ây-ai` | 20/11/2026 08:12: "A thấy có từ "AI" thì đọc là "Ây-ai" trong tiếng việt." |
| `GitHub` | `Git hắp` | 20/11/2026: "Git đọc là "Git hắp"" and "Ở giọng đọc thôi, còn sub karaoke vẫn ghi là GitHub" |

Whole word and case-sensitive, so the Vietnamese "ai" (who) and "Ai" are untouched. A script author's own respelling in `say` wins: the written word is then no longer in the text, so nothing is replaced. To add a word, add one pair to the table. The gate folds a reading into one token: it accepts Whisper writing the spoken words ("Ây ai") or the written word exactly ("AI", case-sensitive) and puts it on the listen list with what Whisper wrote. The karaoke maps the subtitle word to the heard word(s) by position; Whisper wrote "AI" for it in the proof run, so the subtitle word and the heard word are one to one.
## The gate (`halcyon_giong.py`, standard library only)
Compares the script's voice text (`say` with the default readings applied) with the Whisper words of the final wav. Not counted as a difference: case, the place of a tone mark (tuỳ / tùy), digits against number words (bảy mươi hai = 72, một trăm mười lăm phẩy tám = 115,8, 193 ngàn, mười giây rưỡi = 10,5), a word split in two (ChatGPT / chat GPT), and the readings listed in `giong-da-nghe.txt`. It refuses (exit 2, no timing file) when
- a run of 4 or more script words is not heard,
- more than 10 % of the script words are not heard,
- the voice said 4 or more extra words in a row (a loop or a stutter; this rule is an addition to the design note's two),
- the voice has not as many paragraphs as the script.

Each message names the words, the paragraph with its time span, and the time in the track, for example `5 script words in a row were not heard, paragraph 2 (4.58-8.29 s), near 5.9 s: "tạm thời cũng bị giữ"; heard there: "..."`. Whisper can prove a word was said, not that it was said well; the gate does not replace the owner's ear.

## The listen list (`nghe-lai.txt`)
The words the owner should hear, by time in the track: every stretch the gate found different (`not heard`, with what Whisper wrote), every name (capitalised outside a sentence start without a Vietnamese diacritic, a capital after the first letter, or a Latin-letter word that is not one Vietnamese syllable) and every number, grouped by word with all its times. A number word Whisper also wrote as a word (không, một) is not listed. Names in `giong-da-nghe.txt` are left out and summarised on one line.

**Adding a name.** After the owner has heard a word in a finished track and accepts it, add one line to `giong-da-nghe.txt`: `say words => what Whisper wrote | another reading` (copy both from the listen list). The entry hides the name only while Whisper writes one of the listed readings. Today's entries are the respellings the published video 04 script used; the published files record that the video went out, not a separate verdict per name.

## What this cannot show
Listening. The gate and the list are leads for the ear. Whisper heard a name right in one take and wrong in the next (ChatGPT: "chat GPT", "JPT", "chatpt" in three takes of the same text), so every new take of a name is a new thing to hear.

## Tests
`python -m unittest tests.test_halcyon_giong` (no audio tools; the Whisper word lists of published videos 05 and 03 stand in for the voice). `lam-giong.py` is not imported by any test.
