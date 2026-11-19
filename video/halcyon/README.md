# Halcyon short-video builder

One JSON spec in, a 1080x1920, 30 fps news short out (GPU only). This folder holds the builder; the format of the spec is in [SPEC.md](SPEC.md). It is separate from the older Node renderer in `video/` (`render.js`).

| File | Role |
| --- | --- |
| `dung-video-gpu.py` | The builder: `<spec.json> --stills` (a still per beat/state, contact sheet, phone previews, `<stem>-plan.json`) or `--render` (clean mp4 and a TikTok-overlay preview mp4, `<stem>-render.json`). |
| `ve_halcyon.py` | Drawing code (Pillow) the builder loads: skin, kicker row, caption geometry, neural-mesh field, safe-frame gates. |
| `halcyon_spec.py` | Spec loading and validation. Standard library only; covered by `tests/test_halcyon_video_tool.py`. |
| `halcyon_kich_ban.py` | Script to spec: `kich-ban.json` + voice timing + capture manifest -> `video.json`, with refusals. Standard library only; contract in [KICH-BAN.md](KICH-BAN.md), tested by `tests/test_halcyon_kich_ban.py`. |
| `do-doan-giong.py` | Measures the voice paragraphs of a final wav (silences over 0.5 s) and writes them into the timing file's `beats`. Needs ffmpeg. |
| `kiem-hoi-quy.py` | Regression compare of two `-plan.json` files (`RESULT: EQUAL` or the differences). |
| `tron-nhac.py` | Puts the channel's music bed under a finished mp4 (not part of the builder). |
| `run.ps1` | `run.ps1 -Spec <spec.json> -Mode --stills|--render` with the GPU interpreter. |

## Requirements (not installed by this repo)

- An NVIDIA GPU with CUDA, NVDEC and NVENC; Python with `torch` (CUDA build), `numpy`, `Pillow`; `ffmpeg` and `ffprobe` with `h264_nvenc`, and ImageMagick (`magick`) on `PATH`. The builder stops when CUDA or NVENC is missing; there is no CPU fallback.
- The interpreter is read from `HALCYON_PYTHON` (default `%USERPROFILE%\.venvs\halcyon-gpu\Scripts\python.exe`). Run it isolated: `& $env:HALCYON_PYTHON -I -X utf8 video/halcyon/dung-video-gpu.py <spec.json> --stills`.
- Scratch files go to `%TEMP%\halcyon-video\<spec name>\` (set `TEMP` to move them).

## Assets

- Fonts: `fonts/` holds Barlow Condensed Bold and ExtraBold (SIL Open Font License, texts alongside). Be Vietnam Pro comes from `brand/fonts/`, the wordmark from `brand/logo/coral-tile/logos/`. Segoe UI is read from the Windows font folder for the phone previews only.
- Music bed (`tron-nhac.py`): the track ("Voice Over Under", Kevin MacLeod, CC BY 4.0, attribution required in every post) is not committed. Set `HALCYON_MUSIC_TRACK` to the mp3, or put it at `video/halcyon/music/Voice Over Under.mp3` (git-ignored).
- A spec's inputs (voice wav, Whisper timing json, captures, recordings) are never committed; every path in a spec is relative to the spec file.

## Check

```powershell
python -m unittest tests.test_halcyon_video_tool
```

This runs without a GPU. Rebuild proof of a published video: run `--stills`, then `kiem-hoi-quy.py` on the old and new `-plan.json` (must read EQUAL), then `--render` and compare the mp4 with `ffmpeg -i <mp4> -map 0:v -f md5 -`.
