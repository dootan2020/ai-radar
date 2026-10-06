# ai-radar daily short

Generate a vertical “3 tin AI hôm nay” video for Reels, TikTok, and YouTube Shorts. The opening uses A’s bold red headline treatment for two seconds, then returns to B’s calm editorial cards. Voice is cloned from the approved voice 2 sample; scene changes follow measured speech timing.

## One-command daily run

From the repository root, with the local OmniVoice model cache and FFmpeg already available:

```powershell
node video/render.js site/data/radar-ui.json
```

The command selects three stories, writes narration from each Vietnamese headline and the first complete Vietnamese summary sentence, generates and corrects the voice offline, renders the scenes to fit it, and muxes the audio. It writes:

- `video/out/<snapshot-date>.mp4`
- `video/out/<snapshot-date>-narration.txt`
- `video/out/<snapshot-date>.txt` (social caption)

The date is the snapshot timestamp in the machine’s local timezone. Output media is ignored by Git.

The run requires the ready Python 3.11 OmniVoice venv, its cached model, and FFmpeg. Override the two OmniVoice paths with environment variables when their defaults differ:

```powershell
$env:OMNIVOICE_PYTHON = 'C:\path\to\omnivoice-tts\venv\Scripts\python.exe'
$env:OMNIVOICE_CACHE_DIR = 'C:\path\to\omnivoice-tts\huggingface'
$env:FFMPEG_PATH = 'C:\path\to\ffmpeg.exe'
node video/render.js site/data/radar-ui.json
```

No model or package download is performed. OmniVoice receives `--offline`, uses the reference transcript, and runs the copied Fix OmniVoice postprocessor before muxing. If a local `CHROME_PATH` is needed by Remotion, set it before the command.

## Checks

```powershell
cd video
npm test
```

The package tests story selection and audio-driven scene timing.
