# From a source address and a sentence to a capture (`chup.mjs`)

`chup.mjs` loads a public page the way a phone does (390x844, scale 3, as published), finds one verbatim sentence in it, writes the screenshot and adds the entry the assembler reads to `captures.json` ([KICH-BAN.md](KICH-BAN.md) section 4). It shows the right sentence or fails loudly: it never shows a different one.

```
cd video && npm install                      # once: playwright-core 1.65.1 (pinned); it drives the Google Chrome already installed, nothing is downloaded
node video/halcyon/chup.mjs --url <address> [--url <next address> ...] --quote "<verbatim sentence>" --ref <name> --out <folder>
        [--band "<phrase>" ...] [--hco <hco.news story address>]
        [--follow] [--max-rows 700] [--occurrence N|last] [--open "<heading to expand>"] [--source "<chip label>"] [--date dd/mm/yyyy]
        [--locale en-US] [--ua iphone] [--timeout 60] [--quote-file f.txt] [--job job.json]
```
`--job` takes the same keys as a JSON file (`urls`, `quote`, `ref`, `out`, `bands`, ...), which avoids shell quoting of Vietnamese text. Output: `<out>/<ref>.png`, the entry merged into `<out>/captures.json` (the manifest the assembler takes with `--captures`; several refs share one file), `<ref>.capture.json` (address used, HTTP status, matched text, seconds, the trail of attempts) and the same JSON on stdout. Exit 0 = captured, 1 = refused (message `chup: <address>: <kind>: <why>`, nothing written), 2 = bad arguments.

## What it writes
`{file, focus: {rows}, u_rows, source, date, captured, bands: [{rect, text}]}`, exactly the fields `check_manifest` requires.
- `rows` runs from the top of the first line to the bottom of the last whole line of the quote's paragraph, as far as `--max-rows` (700 capture px) allows; if the paragraph is longer it starts at the quote's first line. `--follow` also takes the lines after the paragraph (published 05 and 03 pictures did); without it nothing outside the paragraph is shown, so no byline, ad or footer can come in.
- Rows and gaps are measured on the picture with the builder's own definition of ink (`ve_halcyon.ink_bands`: luminance 85 levels from the most common one, x 60-1110, bands of 10 rows). `u_rows` is a row in the blank gap above (24 px above the first line, or the gap's middle if the gap is smaller) and below (12 px, same rule), each with two blank rows beside it, which is what `check_shown` tests. A line set too tight to cut beside is given up, never forced; if nothing can be cut, it refuses.
- `bands`: one rect per wrapped line for each `--band` phrase (the phrase must lie inside the sentence, once), `text` = the words on that line in the page's own characters. Rects are the browser's text rectangles x3 in picture pixels (today's are 4 px smaller on each side than the 18/11 published ones; the builder pads them itself).
- `source` = `--source`, else the page's `og:site_name`, else the host name. `date` = `--date`, else today (Asia/Bangkok) as dd/mm/yyyy: the chip reads "Ảnh chụp: <source>, <date>". `captured` is the screenshot time, +07:00.

## Refusals (each is tested in `tests/test_halcyon_chup.py`)
| situation | kind |
|---|---|
| HTTP status not 200 | `status` |
| bot check, sign-in or paywall, consent wall or error page (title, h1, pop-ups covering part of the screen, or a page with under 400 characters of text) | `wall` |
| the sentence is not in the visible text | `not-found` |
| found only inside a pop-up, banner or pinned bar | `overlay` |
| found more than once and no `--occurrence` | `ambiguous` |
| it runs across two blocks of the page | `multi-block` |
| in the text but takes no room (folded section): use `--open "<heading text>"` | `not-rendered` |
| something else is drawn over it at its lines | `covered` |
| the page moved while capturing | `moving` |
| a line has no ink the builder sees, lines touch, taller than `--max-rows`, no blank row to cut at | `no-ink`, `lines-touch`, `too-tall`, `no-gap` |
Cookie banners are declined (a "Reject"/"Decline"/"Only necessary" button; "Accept" is never clicked). No sign-in, no CAPTCHA. Pinned and sticky elements are hidden for the picture.

## Fallback and time box
Addresses are tried in the order given, then `--hco`, each for the same sentence only. A transient failure (timeout, 5xx, sentence not found, page moving) is tried once more; a 4xx, a wall, an ambiguity or an overlay moves on at once. One attempt is limited to `--timeout` seconds (60). If no address shows the sentence the command stops with `chup: the sentence could not be shown from any of N address(es)`. Each attempt uses a fresh Chrome profile in the system temp folder and deletes it.

## Not covered
Photo-only beats (`rows` of a picture), screen recordings, counters (published Yonhap lead photo, the petition page, the Gemini typing recording) stay hand-made; this step is for text passages.
