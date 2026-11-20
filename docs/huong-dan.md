# Hướng dẫn: hand-written guides in the stream

A guide is Vietnamese prose the team wrote and the owner approved. It appears in the normal stream of hco.news with the label "Hướng dẫn" on its card (`Hướng dẫn · Halcyon` on the source line) and has its own page at `/tin/<id>/` with a full body. It is in the sitemap and in search like any story.

It skips the newsroom's writer and scoring desk, the translation step and the summary step. The owner's approval, recorded in the file, takes the place of the scoring desk. Nothing else about the pipeline changes for any other story.

## Where and how

One file per guide: `data/huong-dan/<id>.json`, UTF-8, no comments. The file name (without `.json`) must equal `id`, and `id` is `hd-` followed by lowercase letters, digits, `-` or `_`. Merge to `main`; the next Update run (about every 30 minutes) loads it in `build.py`, before the published snapshot is written, and the story pages step archives it.

A file that is incomplete, or has no approval, is **refused**: the build prints `::error title=Guide refused::<file>: <reason>` and the guide is not published (a guide already live is withdrawn at that build). `tests/test_huong_dan.py` loads every committed file, so a bad file fails CI before it reaches `main`.

To withdraw a guide, delete its file **and** add its id to `data/huong-dan/withdrawn.txt` (one id per line, `#` comments allowed). Deleting the file alone removes the guide from the stream, but the story history branch is append-only: it keeps the record, and the page and search entry would stay. A listed id stops counting as a guide everywhere (`is_guide`), so the archived record falls back to the scoring desk, has no decision row and is dropped from pages, sitemap and search at the next run. Delete the guide's images under `site/assets/huong-dan/` too.

## Fields

All fields are required except `image`. Unknown fields are refused.

| Field | Meaning |
| --- | --- |
| `id` | `hd-<slug>`, equal to the file name |
| `title` | The headline, 200 characters at most |
| `published_at` | ISO time with a zone, e.g. `2026-11-20T09:00:00+07:00`, not in the future. The feed shows a story for 72 hours from this time; the page stays |
| `key_points` | 3 or 4 short paragraphs, shown as "Tóm tắt" above the body and used as the page's description |
| `summary_sources` | The pages the steps were checked against: `[{"name": "...", "url": "https://...", "role": "primary"}]` (`role` optional). Shown as "Nguồn:" |
| `body` | Blocks, below |
| `approval` | `{"approved_by": "...", "approved_at": "<ISO time with zone>", "words": "<the owner's own words>"}`; all three, nothing else, `approved_at` not in the future |
| `image` | Optional `https://` URL for the card's picture. Without it the site draws a cover |

The approval stays in the file. The loader checks it, then builds a story that carries only `approved: true`: no published file (story JSON, window and head projections, search index, pages) holds the approver or his words, and a test checks that. Archived pages keep working from that flag.

## Body blocks

Inline text in `text` and `items` supports `**bold**` and `` `code` ``. Everything is escaped; there is no HTML.

```json
{"type": "heading", "text": "Năm bước"}
{"type": "paragraph", "text": "Đoạn văn với **chữ đậm** và `lệnh`."}
{"type": "steps", "items": ["Bước một.", "Bước hai."]}
{"type": "list", "items": ["Một ý.", "Một ý khác."]}
{"type": "code", "language": "bash", "caption": "Tuỳ chọn", "text": "echo xin chao\ncat ket-qua.txt"}
{"type": "image", "src": "assets/huong-dan/man-hinh-buoc-4.png", "alt": "Mô tả ảnh cho người dùng đọc màn hình", "caption": "Tuỳ chọn"}
```

- `steps` are numbered, `list` is bulleted.
- `code` keeps its line breaks and scrolls sideways on a narrow screen; give a `caption` when the reader needs to know where to run it.
- `image.src` is an `https://` URL or `assets/huong-dan/<file>` (png, jpg, webp or svg committed under `site/assets/huong-dan/`). `alt` is required.
- A guide has no "Đọc bài gốc" button: the page is the original.

## Rules the code enforces

- The bypass in the decision gate, the story pages and the search index applies only to a story with `kind` `huong-dan`, source `hco-huong-dan` **and** `approved: true`, which only the loader sets, after the approval check. Anything else still needs a scored decision row.
- `radar.translate` skips guides and `radar.summarize` leaves them alone (they carry desk prose); both are tested.
- Code: `radar/huong_dan.py` (loader, validation, `is_guide`), `build.py` (injection), `radar/story_pages.py` and `site/story.js` (the same body markup for crawlers and for the app), `site/story.css` (`.story-kicker`, `.guide-*`), `site/feed.js` (`srcOf`).
- Example and test fixture: `tests/fixtures/huong-dan/hd-thu-nghiem-fixture.json` (fake content, never copied into `data/`).
