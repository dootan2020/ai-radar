# Showing a GitHub repository (`repo` beat: `quay:<ref>` in the one command)

When a video introduces a GitHub repository, the owner wants to see that repository on screen and see its folders opened (20/11/2026: "làm video nào mà giới thiệu repo github thì em chủ động quay màn hình repo đó trong github mở chi tiết các thư mục của repo đó"; "nên quay ở dạng desktop nhé"). The chain does it without a live screen recording, which cannot be checked: it takes **one signed-out desktop still of each page**, proves each still against GitHub's own listing, and lets the GPU builder play the stills as a recording (camera, pointer, scroll, page change).

```
script (repo beat)  ->  quay:<ref>  ->  giong  ->  lap-rap  ->  anh  ->  kiem-anh  ->  dung  ->  nhac  ->  goi
                        (before the voice, so a wrong folder name costs seconds, not four minutes)
```

| piece | file | what it does |
| --- | --- | --- |
| script contract and walk times | `halcyon_kich_ban.py`, [KICH-BAN.md](KICH-BAN.md) 1a and 7 | the `repo` beat, the `repo` source, the floors, the walk written into the spec |
| listing, recorder, comparison | `halcyon_quay.py` (`cay`, `compare`, `run`), `quay-repo.mjs` | GitHub's listing at one commit, the stills, the proof |
| picture kind and camera | `dung-video-gpu.py`, `halcyon_repo_walk.py`, [SPEC.md](SPEC.md) | window, camera, pointer, page change |
| wiring | `halcyon_mot_lenh.py` | the step, reuse, the second witness in `kiem-anh`, the pack |

## The step `quay:<ref>`
One step per `repo` source, placed after the `chup:` steps and before `giong`. It runs `python halcyon_quay.py run --repo <owner/name> [--branch b] --open <path> ... --ref <ref> --out <run>/cong-viec/quay` as a subprocess with a deadline of 90 s per page plus 30 s, killed with its whole process tree on expiry.

1. **`cay`** (standard library, anonymous API, no token): the repo (public, default branch), the branch's commit, the recursive file tree at that commit (one call), and the first line of each file to open. Three calls plus one per file. GitHub allows 60 anonymous calls an hour per address; a run says when the limit resets and stops, it never asks for a token.
2. **`quay-repo.mjs`**: installed Chrome, fresh profile, 1280 x 800 css px at scale 2 (2560 px wide stills), desktop, light, not signed in. Per page (home, each folder, each file): open the address, decline a cookie banner, scroll once so lazy images load, read the file list from the page by its links (`/tree/` and `/blob/` addresses), one full-page screenshot (at most 5000 css px tall). At most six page loads per repo, 0.8 s apart, 45 s per attempt, one retry on a timeout or 5xx, one wait of `Retry-After` (30 s at most) on 429.
3. **The comparison** (pure Python, tested offline): every page of the manifest is the page asked for, and shows what GitHub holds.

It writes `<run>/cong-viec/quay/<ref>/cay.json`, `quay.json` (repo, branch, commit, capture time, per page the requested and final address, status, title, the rows with their rectangles and font sizes, the boxes the camera can aim at, the README and code font sizes) and `0.png`, `1.png`, ... one per page, in the order of the walk. A refusal writes no stills.

### Reuse
The step is reused when its inputs are unchanged (the repo, branch, the pages and whether each is opened as a collapsed chain, and the hashes of `halcyon_quay.py`, `quay-repo.mjs` and `chup.mjs`) **and** `quay.json` is under 6 hours old, the same rule as a capture. After a change to the script's `open` list only `quay:<ref>` and what depends on it run again; a change to a `say` text never touches it. The builder's step (`anh`, `dung`) hashes the manifest and **every** still, not one file, so a new recording never reuses an old render.

### What it refuses (each stops the chain at `quay:<ref>` with `to fix:`)
| kind | when | to fix |
| --- | --- | --- |
| `repo`, `renamed`, `branch` | the repo does not exist or is private; it has moved (the message names the new name); no such branch | the source |
| `path`, `parent`, `chain` | an `open` path is not in the repo at that commit (the message lists what the folder does hold; nothing is substituted); a parent is a file; a `chain` entry's skipped folders hold more than one thing | the `open` list |
| `listing`, `row` | a row on screen that GitHub's listing does not hold, or fewer rows than it lists (retried once from a fresh listing when a push landed in between); the row to open next is missing, collapsed into a deeper row (`apps` shown as `apps/x`: open that, or write `"chain": true`), or below the picture | the `open` list, or run again |
| `file` | the first line of a code file is not the first line on screen; a binary or over-1 MB file | another file |
| `address`, `blank` | the page is not the page asked for; a still is flat (under 0.5% ink) or has the wrong size | run again |
| `status`, `wall`, `theme`, `rate-limit`, `timeout`, `limit` | GitHub answered something other than 200, sent the page to a sign-in, shows the dark theme (never converted), throttled, or the API limit is used up | not a script problem: run the same command later; if it stops the same way twice, skip the pick and say why |

There is no silent fallback: no other folder, no capture in place of the walk, no video without the repo beat. A stop that repeats for a wall or a limit means the pick is skipped and reported.

## After the stills
- `lap-rap` passes `--quay <ref>=<quay.json>` for each repo and the assembler writes the walk (when each page opens, anchors, floors).
- `anh`/`dung`: the builder plays the stills ([SPEC.md](SPEC.md), "Repo picture"). It refuses a window that is flat, text under 22 frame px, a camera step faster than its speed cap, and a page too short for its camera; its message names the beat, the page and the seconds.
- `kiem-anh`: the second witness. The builder's plan must hold one segment per page of each repo beat, in the script's order, none under 18 frames; the stills must be under 6 hours old.
- `goi`: `tom-tat.md` lists "Nguồn đã quay (GitHub)" (repo, branch, commit, time, each page's address, HTTP status and seconds), one line under "Máy đã kiểm" (each folder opened exists at that commit and the rows on screen match GitHub's own listing) and two under "Máy chưa kiểm được" (whether these are the folders worth showing; that the pointer, scroll and zoom are drawn from still pictures). The stills, `cay.json` and `quay.json` go to "6 - Nguồn/anh-quay-repo" in `luu-tru.json`.

## What this cannot show
That the folders chosen are the ones worth showing, or that the voice names the folder that is on screen at that moment: the contact sheet has one still per opened page, and the session that wrote the script looks at it. That the README is the README the story is about (a rendered markdown file is proved by address and title only). A GIF in a README is one frame. Whether GitHub changes its markup: rows are found by their addresses, not class names, and a change that hides them stops the run with `listing`.

## Setup and tests
`npm install --no-package-lock` once inside `video/` (installs `playwright-core`; Chrome is the installed one, or `CHROME_PATH`). Tests (no network, GPU or Chrome for the pure parts): `python -m unittest tests.test_halcyon_quay tests.test_halcyon_mot_lenh tests.test_halcyon_kich_ban tests.test_halcyon_repo_walk`. A live check of one repo: `python video/halcyon/halcyon_quay.py run --repo owner/name --open folder --open folder/file.md --ref demo --out <folder>`.
