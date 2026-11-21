# scene3d: the AG-UI diagram (`scene3d` beats)

A three.js scene (22 s by default), drawn frame by frame in headless Chrome and encoded on the GPU, that shows how AG-UI works: the app sends **one request** (`POST` with `RunAgentInput`), the agent answers with **one stream of typed events** over HTTP SSE, the app reacts to each event as it lands (the reply assembles chunk by chunk, a tool is called, the shared state fills), and the supported agent frameworks all speak **the same connection** (the app's tools and state must still match the agent's). Labels are short and Vietnamese; event names stay as they travel on the wire.

The picture uses three exploded translucent glass plates in a slowly drifting three-quarter view: agent framework, the cyan AG-UI protocol, and app. Each plate has a node lattice, corner brackets and blueprint callouts. The request rises; typed event beads descend through the protocol socket and light the lattice. Twelve framework tiles flip while the protocol stays lit. The app card assembles the reply and reacts to demo snapshots. The stack is roughly 600 px wide, with fixed HTML label rows and an app card above the subtitle boundary.

## Entry point
`video/halcyon/halcyon_canh.py run --job <job.json> --out <folder>` (step `canh:<ref>` of `halcyon_mot_lenh.py`, which runs it with `python -I -X utf8`). The file says `CLIP_PRODUCER = 1`. It writes `<folder>/clip.json` and `clip.mp4` (plus `data.json`, `render.json`, `render.err`, the determinism PNG pairs).

Relative `--job` and `--out` paths resolve from the caller's working directory before use. The renderer receives absolute data/output paths even though Node runs from its dependency directory.

Job fields: `scene` (`{"name": "giao-thuc", ...}`; another name is refused; optional `duration` in s, 18-34, default 22: the acts are authored on a 26 s base and played proportionally, so the clip fits the narration over it), optional `events_run` (a run's `chay.json`), optional `counts_demo` (a demo's `demo.json`).

The script can set that length on its **source**, shared by all beats referring to the clip:

```json
"sources": {
  "giao-thuc": {
    "scene": {"name": "giao-thuc", "events_from": "thu", "counts_from": "dojo", "duration": 25}
  }
}
```

The beat remains `{"kind":"scene3d","scene3d":{"ref":"giao-thuc"}}`. Choose `duration` from the measured beat span in the assembled voice timing; 25 above is an example, not a new default or a measurement of a particular voice. `halcyon_mot_lenh.py` validates the optional number before work and passes it unchanged to the scene job. `halcyon_kich_ban.py` checks an explicitly requested length against the manifest (within one frame), refuses a voiced span that would hold its last frame for more than 0.05 s, and still refuses a clip whose end would be cut. Its refusal names the measured span and source to edit. Re-render `canh:<ref>` after changing the source. Scripts without `duration` retain their existing behavior. Scene module changes also invalidate the chain's producer cache.

| file | what |
|---|---|
| `canh.py` | timeline (pure, tested), source proofs, gates, `clip.json` |
| `canh.mjs` | Playwright + installed Chrome (GPU, ANGLE D3D11), serves the page from disk under `http://canh.local/`, aborts and counts every other request, `renderAt(t)` per frame, screenshots at final size, pipes PNGs to `h264_nvenc` |
| `scene.html`, `giao-thuc.js` | the page and the scene: every pixel a function of `t` |
| `timeline.mjs` | pure frame sampler of `data.json`: flights, arrivals, tallies, state reaction and tile turns |
| `stage.mjs` | pinned WebGL setup, glass primitives, HTML label measurement and explicit transparency ordering |
| `giao-thuc-nguon.json` | the facts the scene draws and where each comes from (pinned README commit, fence sha256, event list, frameworks) |

## Where the numbers come from
- Times below are on the 26 s base; at the default 22 s each is x0.846.
- **Act 3 (8-15 s)**: the seven events of the README's `server.py` (commit `1de7b128`): `RUN_STARTED`, `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT` x3 (`"Hello "`, `"from "`, `"AG-UI!"`), `TEXT_MESSAGE_END`, `RUN_FINISHED`. `canh.events_from_fence` parses them from the fence (the `for` loop expanded); `check_readme` proves the pinned README holds them (the README is supplied by hand, the producer never fetches). With `events_run`, the run record must have saved `server.py` from the same URL with the same sha256 and printed `Hello from AG-UI!`, so the diagram is the run the viewer installs.
- **Act 4 (15-21 s)**: the demo's own run. With `counts_demo`, `demo.json` (halcyon_demo.py) carries `"events": {"total", "by_type": {"TYPE": n}, "order": [types by first appearance], "streams"}` (a flat `{"TYPE": n}` or `event_counts` is read too). The scene shows `TOOL_CALL_*` (START+ARGS+END+RESULT), `STATE_SNAPSHOT`, `TEXT_MESSAGE_CONTENT`: one bead per counted event, tallies ticking as they land. **Ordered:** the three kinds leave in the order of their first appearance in that stream (`order`; in the 21/11/2026 run: STATE_SNAPSHOT, then TOOL_CALL, then TEXT_MESSAGE_CONTENT), and the tallies are listed in that order. **Aggregated:** the events of one kind travel as one group, because the manifest keeps first appearances and counts, not the place of every event (later snapshots may have interleaved with the tool call in the real stream). `RUN_STARTED` leaves first and `RUN_FINISHED` last, as in every AG-UI run. While snapshots land, the app's STATE tag lights and reads `← STATE_SNAPSHOT`: the notes redraw because that event arrived. Without a demo the act names the types only, in the table's order; a stream that lacks one of the three kinds is refused.
- **Act 5 (21-26 s)**: LangGraph, CrewAI, Google ADK, Microsoft Agent Framework, from the README's integrations table, each taking the agent's place on the same lane. Title `ĐỔI FRAMEWORK, CÙNG KẾT NỐI`, chip `cùng giao thức ✓`: the protocol and the connection stay the same; the scene does not claim the app needs no change (its tools and state must match).

## Gates (each refuses, the chain stops with `to fix:`)
| gate | refuses when |
|---|---|
| proof of diagram | act 3 differs from the pinned list; act 4's beads or tallies differ from the demo counts; a run record ran another fence |
| deterministic | any page module (`giao-thuc.js`, `stage.mjs`, `timeline.mjs`) names `Date`, `performance.now`, `Math.random`, `requestAnimationFrame`, `setTimeout` or `setInterval`; three frames drawn again at the end, in reverse order, differ from the pass by more than 4 levels (the GPU's own rounding measured 2) |
| offline | any request leaves `http://canh.local/`; `three.module.js` / `three.core.js` differ from the sha256 pin of three@0.187.0 |
| GPU | the WebGL renderer string is a software rasteriser (SwiftShader, llvmpipe) |
| legible | a label under 28 px, outside the clip, below clip y 890 (the subtitle of thu-gon-r3-l2), right of clip x 800 below clip y 476 (TikTok's button column), or two solid labels overlapping; checked on every frame |
| encoded | the file is not 886x976, duration x 30 frames, 30/1, h264; its ground decodes more than 3 levels from `bg` [16, 24, 40] (a seam would show around the clip); a still is flat ground |

The clip is 886x976 at 30 fps (the builder's rate; it plays clips 1:1), 22 s (660 frames) unless the job says otherwise; the builder seats it in the FOOT window of thu-gon-r3-l2 (frame y 364-1340), on the same ink as its `bg`.

`window.renderAt(t)`, `window.labels()`, `window.sceneInfo`, `window.sceneFonts` and `window.sceneReady` retain the producer contract. Finite times clamp to the clip endpoints; non-finite inputs throw. Every event has a fixed object identity created before the first frame. Animated transforms, colors, opacity and visibility are assigned from the current sample. Glass never writes depth. Lattice links, plate/tile outlines, scan lines, luminous rails and tile markings use merged screen-space capsule quads with a minimum two-CSS-pixel width and a half-pixel alpha transition around a solid core. The visible coverage ends before the triangle boundary; coverage does not depend on MSAA. Plate outlines retain their specified brightness and the front rail has full-opacity layer color, including the cyan protocol highlight. Lattice nodes are opaque, lit sphere instances with the original glossy material response, a visible resting tint and low continuous emission. Their projected diameters vary continuously from 8 to 13.6 pixels with the arrival wave; their matrices and colors are assigned from each current sample. Instance frustum culling is disabled so earlier bounds cannot affect a later seek. Small trail beads retain smooth capsule discs. The stroke quads use explicit painter order without depth testing or writing, so an invisible quad margin cannot occlude another feature. Frustum culling is also disabled for these screen-expanded primitives because centreline bounds omit their pixel margins. Large glow sprites have a broad gradient centre, and STATE color follows its smooth pulse without a threshold flash.

The WebGL scene renders into a 1772x1952 target with MSAA disabled (`samples: 0` and canvas `antialias: false`). A final pass averages exactly four nearest-filtered source texel centres per output pixel, in linear color, then writes sRGB to the 886x976 canvas. There is no temporal accumulation or browser-selected canvas downscaling filter; HTML labels remain at their original final-size coordinates. Current world matrices are updated before callout projection and transparent draw ordering. These construction choices apply at every camera pose and duration; they do not replace shader compilation, visual review or the reverse-seek pixel gate on the production GPU.

## Verification

Run from the repository root, without a browser:

```powershell
python -m unittest tests.test_halcyon_canh tests.test_halcyon_silent
python -m unittest discover -s tests -p 'test_halcyon*.py'
Get-ChildItem video/halcyon/scene3d -Recurse -File -Include *.js,*.mjs | ForEach-Object { node --check $_.FullName; if ($LASTEXITCODE -ne 0) { throw $_.FullName } }
```

The Python suite feeds production-generated timelines into `timeline.test.mjs` using Node. It covers all seven events, delta arrival, the 35/18/22 demo grouping, per-arrival counts, request direction, the protocol crossing, four framework turns, names-only mode and every-frame reverse/shuffled seeks across the duration range, including exact 30 fps samples around frame 412 at 25 s and frame 416 at 25.25 s. The counted 22, 25.25, 26 and 30 s render matrix is covered alongside the 18/34 s endpoints; all 162 node activity values are checked for continuous sub-frame changes around the last README arrival. The four-level refusal boundary is checked explicitly, including the reported six-level failure. Duration tests cover script validation, the emitted producer job, stale manifests, narration coverage, unchanged silent-beat checks and cache invalidation. A producer-boundary test covers relative job/output paths with a different Node working directory.

The coordinator must still render through `halcyon_canh.py` with the real run/demo manifests. Only that render can establish font rectangles and overlaps on every frame, reverse-seek pixel differences, GPU performance, visual fidelity and encoded ground color. Offline unit tests do not certify those gates.

## Tooling (where three.js lives)
playwright-core and three resolve from the chain's `video/` folder (`HALCYON_NODE_DIR` overrides it). `three` is a dependency of `video/package.json`, pinned at exactly 0.187.0 (MIT, no dependencies, no install scripts), so the chain's ordinary `npm install --ignore-scripts` in `video/` brings it, and it stays for other work (owner, 21/11/2026 04:44: "Giữ lại threejs cho các tác vụ khác"). The producer still checks the sha256 of `three.module.js` and `three.core.js` and refuses a different build. Fonts: Be Vietnam Pro (brand/fonts), Barlow Condensed and JetBrains Mono (video/halcyon/fonts). Chrome: the installed one (`CHROME_PATH` overrides).

The previous scene measured 21/11/2026 on the RTX 2060: WebGL `ANGLE (NVIDIA, NVIDIA GeForce RTX 2060 Direct3D11)`, 660 frames in about 21 s (31 ms a frame), 9 files served, 0 aborted. The exploded-layers scene adds two local module routes; its GPU timing needs a fresh measurement.
