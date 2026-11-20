# scene3d: the AG-UI diagram (`scene3d` beats)

A 26 s three.js scene, drawn frame by frame in headless Chrome and encoded on the GPU, that shows how AG-UI works: the app sends **one request** (`POST` with `RunAgentInput`), the agent answers with **one stream of typed events** over HTTP SSE, the app reacts to each event as it lands (the reply assembles chunk by chunk, a tool is called, the shared state fills), and **any agent framework** can take the agent's place while the app stays as it is. Labels are short and Vietnamese; event names stay as they travel on the wire.

## Entry point
`video/halcyon/halcyon_canh.py run --job <job.json> --out <folder>` (step `canh:<ref>` of `halcyon_mot_lenh.py`, which runs it with `python -I -X utf8`). The file says `CLIP_PRODUCER = 1`. It writes `<folder>/clip.json` and `clip.mp4` (plus `data.json`, `render.json`, `render.err`, the determinism PNG pairs).

Job fields: `scene` (`{"name": "giao-thuc", ...}`; another name is refused), optional `events_run` (a run's `chay.json`), optional `counts_demo` (a demo's `demo.json`).

| file | what |
|---|---|
| `canh.py` | timeline (pure, tested), source proofs, gates, `clip.json` |
| `canh.mjs` | Playwright + installed Chrome (GPU, ANGLE D3D11), serves the page from disk under `http://canh.local/`, aborts and counts every other request, `renderAt(t)` per frame, screenshots at final size, pipes PNGs to `h264_nvenc` |
| `scene.html`, `giao-thuc.js` | the page and the scene: every pixel a function of `t` |
| `giao-thuc-nguon.json` | the facts the scene draws and where each comes from (pinned README commit, fence sha256, event list, frameworks) |

## Where the numbers come from
- **Act 3 (8-15 s)**: the seven events of the README's `server.py` (commit `1de7b128`): `RUN_STARTED`, `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT` x3 (`"Hello "`, `"from "`, `"AG-UI!"`), `TEXT_MESSAGE_END`, `RUN_FINISHED`. `canh.events_from_fence` parses them from the fence (the `for` loop expanded); `check_readme` proves the pinned README holds them (the README is supplied by hand, the producer never fetches). With `events_run`, the run record must have saved `server.py` from the same URL with the same sha256 and printed `Hello from AG-UI!`, so the diagram is the run the viewer installs.
- **Act 4 (15-21 s)**: the demo's own run. With `counts_demo`, `demo.json` (halcyon_demo.py) carries `"events": {"total", "by_type": {"TYPE": n}, "order": [types by first appearance], "streams"}` (a flat `{"TYPE": n}` or `event_counts` is read too). The scene shows `TOOL_CALL_*` (START+ARGS+END+RESULT), `STATE_SNAPSHOT`, `TEXT_MESSAGE_CONTENT`: one bead per counted event, tallies ticking as they land. **Ordered:** the three kinds leave in the order of their first appearance in that stream (`order`; in the 21/11/2026 run: STATE_SNAPSHOT, then TOOL_CALL, then TEXT_MESSAGE_CONTENT), and the tallies are listed in that order. **Aggregated:** the events of one kind travel as one group, because the manifest keeps first appearances and counts, not the place of every event (later snapshots may have interleaved with the tool call in the real stream). `RUN_STARTED` leaves first and `RUN_FINISHED` last, as in every AG-UI run. Without a demo the act names the types only, in the table's order; a stream that lacks one of the three kinds is refused.
- **Act 5 (21-26 s)**: LangGraph, CrewAI, Google ADK, Microsoft Agent Framework, from the README's integrations table.

## Gates (each refuses, the chain stops with `to fix:`)
| gate | refuses when |
|---|---|
| proof of diagram | act 3 differs from the pinned list; act 4's beads or tallies differ from the demo counts; a run record ran another fence |
| deterministic | `giao-thuc.js` names `Date`, `performance.now`, `Math.random`, `requestAnimationFrame`, `setTimeout` or `setInterval`; three frames drawn again at the end, in reverse order, differ from the pass by more than 4 levels (the GPU's own rounding measured 2) |
| offline | any request leaves `http://canh.local/`; `three.module.js` / `three.core.js` differ from the sha256 pin of three@0.187.0 |
| GPU | the WebGL renderer string is a software rasteriser (SwiftShader, llvmpipe) |
| legible | a label under 28 px, outside the clip, below clip y 890 (the subtitle of thu-gon-r3-l2), right of clip x 800 below clip y 476 (TikTok's button column), or two solid labels overlapping; checked on every frame |
| encoded | the file is not 886x976, 780 frames, 30/1, h264; its ground decodes more than 3 levels from `bg` [16, 24, 40] (a seam would show around the clip); a still is flat ground |

The clip is 886x976 at 30 fps (the builder's rate; it plays clips 1:1) and 26 s; the builder seats it in the FOOT window of thu-gon-r3-l2 (frame y 364-1340), on the same ink as its `bg`.

## Tooling (where three.js lives)
playwright-core and three resolve from the chain's `video/` folder (`HALCYON_NODE_DIR` overrides it). `three` is a dependency of `video/package.json`, pinned at exactly 0.187.0 (MIT, no dependencies, no install scripts), so the chain's ordinary `npm install --ignore-scripts` in `video/` brings it, and it stays for other work (owner, 21/11/2026 04:44: "Giữ lại threejs cho các tác vụ khác"). The producer still checks the sha256 of `three.module.js` and `three.core.js` and refuses a different build. Fonts: Be Vietnam Pro (brand/fonts), Barlow Condensed and JetBrains Mono (video/halcyon/fonts). Chrome: the installed one (`CHROME_PATH` overrides).

Measured 21/11/2026 on the RTX 2060: WebGL `ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 Direct3D11)`, 780 frames in about 27 s (34 ms a frame), 9 files served, 0 aborted.
