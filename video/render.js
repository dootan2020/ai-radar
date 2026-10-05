import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execFileSync } from 'child_process';
import { selectThreeStories } from './src/pick-stories.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Helper to format Vietnamese date
function formatVietnameseDate(isoString) {
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return '5 tháng 10, 2026';
    const days = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
    const dayName = days[d.getDay()];
    return `${dayName}, ${d.getDate()} tháng ${d.getMonth() + 1}, ${d.getFullYear()}`;
  } catch {
    return '5 tháng 10, 2026';
  }
}

// Helper to format date slug (YYYY-MM-DD)
function formatDateSlug(isoString) {
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return '2026-10-05';
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  } catch {
    return '2026-10-05';
  }
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

  // 2. Select top 3 stories
  const pickedStories = selectThreeStories(snapshot);
  if (!pickedStories || pickedStories.length === 0) {
    console.error('[ERROR] No stories could be selected from snapshot.');
    process.exit(1);
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
  if (!fs.existsSync(outDir)) {
    fs.mkdirSync(outDir, { recursive: true });
  }

  const mp4Path = path.join(outDir, `${dateSlug}.mp4`);
  const captionPath = path.join(outDir, `${dateSlug}.txt`);
  const propsJsonPath = path.join(outDir, `props-${dateSlug}.json`);

  // 5. Generate social caption file (.txt)
  const captionLines = [
    `3 tin AI đáng chú ý hôm nay (${dateSlug}):`,
    '',
    ...preparedStories.map((st, i) => `${i + 1}. ${st.title_vi || st.title}`),
    '',
    'Cập nhật radar tin tức công nghệ AI liên tục tại:',
    'https://dootan2020.github.io/ai-radar',
    '',
    '#airadar #ai #tintucai #congnghe #tech #shorts #reels #tiktok',
  ];
  fs.writeFileSync(captionPath, captionLines.join('\n'), 'utf8');
  console.log(`[INFO] Caption saved: ${captionPath}`);

  // 6. Write input props file for Remotion
  const inputProps = {
    stories: preparedStories,
    snapshotDate: formattedDate,
    totalStoriesCount: snapshot.stories ? snapshot.stories.length : 1306,
  };
  fs.writeFileSync(propsJsonPath, JSON.stringify(inputProps, null, 2), 'utf8');

  // 7. Render video with Remotion CLI
  console.log(`[INFO] Rendering video to: ${mp4Path}...`);
  const cliPath = path.resolve(__dirname, 'node_modules/@remotion/cli/remotion-cli.js');
  const entryPoint = path.resolve(__dirname, 'src/index.js');

  const args = [
    cliPath,
    'render',
    entryPoint,
    'AiRadarDailyVideo',
    mp4Path,
    `--props=${propsJsonPath}`,
    '--muted',
  ];

  try {
    execFileSync('node', args, {
      cwd: __dirname,
      stdio: 'inherit',
    });
  } catch (err) {
    console.error('[ERROR] Remotion render failed:', err.message);
    process.exit(1);
  }

  // Clean up temporary props file
  try {
    fs.unlinkSync(propsJsonPath);
  } catch {}

  const durationSec = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`\n========================================`);
  console.log(`[SUCCESS] Video render completed in ${durationSec}s`);
  console.log(`Video:   ${mp4Path}`);
  console.log(`Caption: ${captionPath}`);
  console.log(`========================================\n`);
}

// Run if called directly
if (process.argv[1] && (process.argv[1].endsWith('render.js') || process.argv[1].includes('render'))) {
  main().catch((err) => {
    console.error('[FATAL]', err);
    process.exit(1);
  });
}
