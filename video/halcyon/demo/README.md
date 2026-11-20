# Demo recorder (`demo` beat)

`halcyon_demo.py run --job <job.json> --out <folder>` records a public agent demo page by script and writes `demo.webm` (390x844, 25 fps) and `demo.json`; the chain runs it as step `demo:<ref>` (MOT-LENH.md, "Silent paragraphs and moving pictures"). `halcyon_demo.py check --job <job.json>` checks the job only.

Built for the AG-UI Dojo "shared state" demo: `entry` is the Dojo address the viewer can open, `page` is the demo page itself (an iframe of the Dojo; recording it directly gives the same 390 px phone layout), `say` the one sentence typed.

## What the footage shows (about 20-25 s, the agent's own latency decides)
Chat open and empty, the sentence typed key by key, sent; the answer streams (the agent's tool call first, then its text); the chat is closed and the page scrolls to "Agent Scratch pad", which now holds the notes the agent's tool wrote. `demo.json` carries `moments` (seconds of the video), `suggest.chat` and `suggest.notes` (a `from`/`to` and a `rect` in the 390x844 recording for each of the two halves of the footage, the numbers a `demo` beat takes) and `events` (AG-UI event counts of that very run: `by_type`, `order`, `total`; the 3D scene reads them as `counts_demo`).

## Job and expectations
`{"ref", "demo": {"entry", "page", "say", "expect": {"events": ["TOOL_CALL_START", ...], "effect": "notes", "min_notes": 1}}}`. `RUN_STARTED` and `RUN_FINISHED` are always required. Pick a sentence that makes the agent answer briefly: with the plain "Mình thích phở và đạp xe" the answer once ran to a 200-delta wall of text that scrolled the chat; adding "Trả lời ngắn thôi." gave a one-line answer.

## Gates (each has a test with a planted violation, tests/test_halcyon_demo.py)
| gate | refuses when |
|---|---|
| address | `entry` or `page` is not a public https host (localhost, IPs, `.local`) |
| say | the sentence is empty, long, multi-line or holds an address, link, e-mail sign or long number |
| wall | the page shows a bot check, sign-in, cookie wall, a key/password/e-mail field (chup.mjs `wallScan` plus a field scan) |
| navigation | the page tries to open a page of any host but the two named (blocked, then refused) |
| events | no `text/event-stream` POST answered after sending, or the run lacks `RUN_STARTED`, `RUN_FINISHED` or an expected type |
| effect | the scratch pad was not empty before, or holds fewer than `min_notes` notes after, or the answer is empty |
| video | not 390x844 at 25 fps with whole frames, shorter than 8 s, or ends before the scratch pad came into view or more than 4 s after the driving ended |

Safety: headless Chrome, a throwaway profile and video folder deleted afterwards, no cookies kept, no downloads, no permissions, service workers blocked. An attempt lasts 100 s at most and is retried once (the chain gives the step 300 s); a wall is not retried. Two refusals mean the demo is dropped and reported; nothing replaces it.

## Needs
Node, Playwright (`npm install` in `video/`), Chrome (`CHROME_PATH` or the installed one), `ffprobe`. Network tests: `HALCYON_LIVE=1 python -m unittest tests.test_halcyon_demo` types a sentence into the public Dojo; without it, and in CI, only the offline and local-page tests run.

## What it cannot show
That the page is the project's official demo for the claim being made (the script names both addresses); that the agent's answer is good (it is whatever the project's server and model said that minute); that the Dojo is reachable tomorrow.
