import fs from 'fs';
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';
import { spawnSync } from 'child_process';
import { selectThreeStories } from './src/pick-stories.js';
import { audioTimeline, createNarration, wavSpeechSegments, resolveOmniVoicePaths } from './src/daily-audio.js';

export { resolveOmniVoicePaths };

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Helper to format Vietnamese date
function formatVietnameseDate(isoString) {
  const d = new Date(isoString);
  if (isNaN(d.getTime())) throw new Error(`Invalid snapshot generated_at: ${isoString}`);
  const days = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
  return `${days[d.getDay()]}, ${d.getDate()} tháng ${d.getMonth() + 1}, ${d.getFullYear()}`;
}

// Helper to format date slug (YYYY-MM-DD)
function formatDateSlug(isoString) {
  const d = new Date(isoString);
  if (isNaN(d.getTime())) throw new Error(`Invalid snapshot generated_at: ${isoString}`);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {stdio: 'inherit', ...options});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${path.basename(command)} exited with status ${result.status}.`);
  return result;
}

function synthesizeNarration(narrationPath, tempDir) {
  const { python, cache, wrapper, fixOmnivoice, referenceAudio, referenceText } = resolveOmniVoicePaths();
  const rawAudio = path.join(tempDir, 'voice.wav');

  for (const file of [python, wrapper, fixOmnivoice, referenceAudio, referenceText]) {
    if (!fs.existsSync(file)) throw new Error(`Required OmniVoice path does not exist: ${file}`);
  }
  run(python, [
    wrapper, '--cache-dir', cache, 'synthesize', '--text-file', narrationPath,
    '--language', 'Vietnamese', '--ref-audio', referenceAudio,
    '--ref-text-file', referenceText, '--split-paragraphs', '--pause-ms', '1200',
    '--normalize-chunk-levels', '--offline', '--output', rawAudio,
    '--fix-script', fixOmnivoice,
  ], {
    env: { ...process.env, FIX_OMNIVOICE_SCRIPT: fixOmnivoice },
  });
  const correctedAudio = path.join(tempDir, 'voice_corrected.wav');
  if (!fs.existsSync(correctedAudio) || fs.statSync(correctedAudio).size === 0) {
    throw new Error('OmniVoice did not create its corrected WAV output.');
  }
  return correctedAudio;
}

// Fast pre-probe image with timeout
async function probeImage(url, timeoutMs = 2500) {
  if (!url || typeof url !== 'string' || !url.startsWith('http')) return null;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const res = await fetch(url, {
      method: 'HEAD',
      signal: controller.signal,
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' },
    });
    clearTimeout(timer);
    if (res.ok) return url;
    return null;
  } catch {
    return null;
  }
}

export async function main() {
  const startTime = Date.now();

  // 1. Resolve snapshot input file
  let snapshotArg = process.argv[2];
  let snapshotPath;
  if (snapshotArg && !snapshotArg.startsWith('--')) {
    snapshotPath = path.isAbsolute(snapshotArg)
      ? snapshotArg
      : path.resolve(process.cwd(), snapshotArg);
  } else {
    // Default locations
    const candidate1 = path.resolve(__dirname, 'sample/radar-ui.json');
    const candidate2 = path.resolve(__dirname, '../site/data/radar-ui.json');
    snapshotPath = fs.existsSync(candidate1) ? candidate1 : candidate2;
  }

  if (!fs.existsSync(snapshotPath)) {
    console.error(`[ERROR] Snapshot file not found at: ${snapshotPath}`);
    process.exit(1);
  }

  console.log(`[INFO] Reading snapshot: ${snapshotPath}`);
  const rawData = fs.readFileSync(snapshotPath, 'utf8');
  const snapshot = JSON.parse(rawData);
  if (!snapshot || !Array.isArray(snapshot.stories) || !snapshot.generated_at) {
    throw new Error('Snapshot must include generated_at and a stories array.');
  }

  // 2. Select top 3 stories
  const pickedStories = selectThreeStories(snapshot);
  if (!pickedStories || pickedStories.length === 0) {
    console.error('[ERROR] No stories could be selected from snapshot.');
    process.exit(1);
  }
  if (pickedStories.length !== 3 || pickedStories.some(story => !story.title_vi)) {
    throw new Error('Snapshot must supply three selected stories with Vietnamese titles.');
  }

  console.log(`[INFO] Selected ${pickedStories.length} stories for video:`);
  pickedStories.forEach((st, idx) => {
    console.log(`  ${idx + 1}. ${st.title_vi || st.title} (score: ${st.worth_score || 0})`);
  });

  // 3. Probe images
  console.log('[INFO] Verifying story image accessibility...');
  const preparedStories = await Promise.all(
    pickedStories.map(async (st) => {
      const rawImg = st.image && st.image.src ? st.image.src : null;
      const verifiedImg = await probeImage(rawImg);
      return {
        ...st,
        imageUrl: verifiedImg,
      };
    })
  );

  // 4. Determine output date & filenames
  const dateSlug = formatDateSlug(snapshot.generated_at);
  const formattedDate = formatVietnameseDate(snapshot.generated_at);
  const outDir = path.resolve(__dirname, 'out');
  fs.mkdirSync(outDir, { recursive: true });

  const mp4Path = path.join(outDir, `${dateSlug}.mp4`);
  const captionPath = path.join(outDir, `${dateSlug}.txt`);
  const narrationPath = path.join(outDir, `${dateSlug}-narration.txt`);
  const propsJsonPath = path.join(outDir, `props-${dateSlug}.json`);
  const tempDir = fs.mkdtempSync(path.join(outDir, `.daily-${dateSlug}-`));
  const silentVideoPath = path.join(tempDir, 'silent.mp4');
  const muxedVideoPath = path.join(tempDir, 'final.mp4');

  // 5. Generate social caption file (.txt)
  const captionLines = [
    ...preparedStories.map((st, i) => `${i + 1}. ${st.title_vi || st.title}`),
    '',
    'https://dootan2020.github.io/ai-radar',
    '',
    '#airadar #ai #tintucai #congnghe #tech #shorts #reels #tiktok',
  ];
  fs.writeFileSync(captionPath, captionLines.join('\n'), 'utf8');
  console.log(`[INFO] Caption saved: ${captionPath}`);
  const narration = createNarration(preparedStories);
  fs.writeFileSync(narrationPath, narration, 'utf8');
  console.log(`[INFO] Narration saved: ${narrationPath}`);

  try {
    console.log('[INFO] Generating cloned Vietnamese voice with OmniVoice (offline)...');
    const voicePath = synthesizeNarration(narrationPath, tempDir);
    const audioSegments = wavSpeechSegments(fs.readFileSync(voicePath));
    const timeline = audioTimeline(audioSegments);
    console.log('[INFO] Voice segment lengths:');
    audioSegments.forEach((segment, index) => {
      console.log(`  Story ${index + 1}: ${segment.duration.toFixed(2)}s`);
    });

    // 6. Render the B editorial scenes to the measured narration timing.
    const inputProps = {
      stories: preparedStories,
      snapshotDate: formattedDate,
      totalStoriesCount: snapshot.stories.length,
      introFrames: timeline.introFrames,
      outroFrames: timeline.outroFrames,
      storyDurations: timeline.storyDurations,
      totalDurationFrames: timeline.totalFrames,
    };
    fs.writeFileSync(propsJsonPath, JSON.stringify(inputProps, null, 2), 'utf8');

    console.log(`[INFO] Rendering ${ (timeline.totalFrames / 30).toFixed(1)}s editorial video...`);
    const cliPath = path.resolve(__dirname, 'node_modules/@remotion/cli/remotion-cli.js');
    const entryPoint = path.resolve(__dirname, 'src/index.js');

    run(process.execPath, [
      cliPath, 'render', entryPoint, 'AiRadarDailyVideo', silentVideoPath,
      `--props=${propsJsonPath}`, '--muted',
    ], {cwd: __dirname});

    const ffmpeg = process.env.FFMPEG_PATH || 'ffmpeg';
    run(ffmpeg, [
      '-y', '-i', silentVideoPath, '-i', voicePath,
      '-filter_complex', `anullsrc=r=24000:cl=mono:d=${timeline.introFrames / 30}[lead];[1:a]apad=pad_dur=4[voice];[lead][voice]concat=n=2:v=0:a=1[a]`,
      '-map', '0:v:0', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
      '-shortest', muxedVideoPath,
    ]);
    if (!fs.existsSync(muxedVideoPath) || fs.statSync(muxedVideoPath).size === 0) {
      throw new Error('FFmpeg did not create the muxed MP4.');
    }
    fs.renameSync(muxedVideoPath, mp4Path);

    console.log(`[INFO] Video saved: ${mp4Path}`);
  } finally {
    try { fs.unlinkSync(propsJsonPath); } catch {}
    fs.rmSync(tempDir, {recursive: true, force: true});
  }

  const durationSec = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`\n========================================`);
  console.log(`[SUCCESS] Video render completed in ${durationSec}s`);
  console.log(`Video:   ${mp4Path}`);
  console.log(`Caption: ${captionPath}`);
  console.log(`Narration: ${narrationPath}`);
  console.log(`========================================\n`);
}

// Run if called directly
if (process.argv[1] && (process.argv[1].endsWith('render.js') || process.argv[1].includes('render'))) {
  main().catch((err) => {
    console.error('[FATAL]', err);
    process.exit(1);
  });
}
