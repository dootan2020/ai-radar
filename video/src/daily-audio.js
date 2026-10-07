import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { selectThreeStories } from './pick-stories.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function formatDateSlug(isoString, timeZone = 'Asia/Ho_Chi_Minh') {
  const d = new Date(isoString);
  if (isNaN(d.getTime())) throw new Error(`Invalid snapshot generated_at: ${isoString}`);
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
  return formatter.format(d);
}

export function formatVietnameseDate(isoString, timeZone = 'Asia/Ho_Chi_Minh') {
  const d = new Date(isoString);
  if (isNaN(d.getTime())) throw new Error(`Invalid snapshot generated_at: ${isoString}`);
  const weekdayFormatter = new Intl.DateTimeFormat('vi-VN', { timeZone, weekday: 'long' });
  const dayFormatter = new Intl.DateTimeFormat('vi-VN', { timeZone, day: 'numeric' });
  const monthFormatter = new Intl.DateTimeFormat('vi-VN', { timeZone, month: 'numeric' });
  const yearFormatter = new Intl.DateTimeFormat('vi-VN', { timeZone, year: 'numeric' });

  let weekday = weekdayFormatter.format(d);
  weekday = weekday.charAt(0).toUpperCase() + weekday.slice(1);
  return `${weekday}, ${dayFormatter.format(d)} tháng ${monthFormatter.format(d)}, ${yearFormatter.format(d)}`;
}

export function normalizeSpeech(text) {
  if (!text || typeof text !== 'string') return '';
  let s = text;

  // 1. $ with number and scale abbreviation: $1B, $1.5B, $100M, $10k
  s = s.replace(/\$\s*(\d+(?:[.,]\d+)?)\s*(?:[bB]|(?:[bB]illion))(?!\p{L})/gu, '$1 tỷ đô la');
  s = s.replace(/\$\s*(\d+(?:[.,]\d+)?)\s*(?:[mM]|(?:[mM]illion))(?!\p{L})/gu, '$1 triệu đô la');
  s = s.replace(/\$\s*(\d+(?:[.,]\d+)?)\s*(?:[kK])(?!\p{L})/gu, '$1 nghìn đô la');

  // 2. $ with Vietnamese scale words: $ 100 tỷ, $100 triệu, $100 nghìn
  s = s.replace(/\$\s*(\d+(?:[.,]\d+)?)\s*(tỷ|tỉ|triệu|nghìn|ngàn)\s+(?:đô\s*la|USD|usd)(?!\p{L})/giu, '$1 $2 đô la');
  s = s.replace(/\$\s*(\d+(?:[.,]\d+)?)\s*(tỷ|tỉ|triệu|nghìn|ngàn)(?!\p{L})/giu, '$1 $2 đô la');

  // 3. $ with existing đô la/USD: $ 100 đô la, $100 USD -> 100 đô la
  s = s.replace(/\$\s*(\d+(?:[.,]\d+)?)\s*(?:đô\s*la|USD|usd)(?!\p{L})/giu, '$1 đô la');

  // 4. Standard $ with number: $ 100, $100 -> 100 đô la
  s = s.replace(/\$\s*(\d+(?:[.,]\d+)?)(?!\p{L})/gu, '$1 đô la');

  // 5. Number followed by $: 100$, 100 $ -> 100 đô la
  s = s.replace(/(\d+(?:[.,]\d+)?)\s*\$\s*(?:đô\s*la|USD|usd)?(?!\p{L})/giu, '$1 đô la');

  // 6. Other currency symbols: EUR, GBP, JPY
  s = s.replace(/€\s*(\d+(?:[.,]\d+)?)(?!\p{L})/gu, '$1 euro');
  s = s.replace(/(\d+(?:[.,]\d+)?)\s*€(?!\p{L})/gu, '$1 euro');
  s = s.replace(/£\s*(\d+(?:[.,]\d+)?)(?!\p{L})/gu, '$1 bảng Anh');
  s = s.replace(/(\d+(?:[.,]\d+)?)\s*£(?!\p{L})/gu, '$1 bảng Anh');
  s = s.replace(/¥\s*(\d+(?:[.,]\d+)?)(?!\p{L})/gu, '$1 yên');
  s = s.replace(/(\d+(?:[.,]\d+)?)\s*¥(?!\p{L})/gu, '$1 yên');

  // 7. Percentages: 15%, 15 % -> 15 phần trăm
  s = s.replace(/(\d+(?:[.,]\d+)?)\s*%/g, '$1 phần trăm');

  // 8. Isolated ampersand between words
  s = s.replace(/\s+&\s+/g, ' và ');

  // 9. Any leftover bare $
  s = s.replace(/\$/g, 'đô la');

  // 10. Normalize multiple spaces
  s = s.replace(/[ \t]{2,}/g, ' ').trim();

  return s;
}

export function narrationForStory(story) {
  const rawTitle = String(story.title_vi || '').trim();
  const rawSummary = String(story.summary_vi || story.description_vi || '').trim();
  if (!rawTitle) throw new Error(`Story ${story.id || '(unknown)'} has no title.`);
  const title = normalizeSpeech(rawTitle);
  const sentence = normalizeSpeech(firstSentence(rawSummary));
  return sentence ? `${title}${/[.!?]$/u.test(title) ? ' ' : '. '}${sentence}` : title;
}

function firstSentence(text) {
  if (!text) return '';
  const sentences = new Intl.Segmenter('vi', {granularity: 'sentence'}).segment(text);
  return [...sentences][0]?.segment.trim() || text;
}

export function validateScript(script, snapshot, targetDate) {
  if (!script || typeof script !== 'object') {
    return { valid: false, reason: 'Script must be a non-null object' };
  }
  if (targetDate && script.date !== targetDate) {
    return {
      valid: false,
      reason: `Script date '${script.date}' does not match snapshot date '${targetDate}'`,
    };
  }
  if (!script.hook || typeof script.hook !== 'string' || !script.hook.trim()) {
    return { valid: false, reason: 'Script is missing non-empty hook' };
  }
  if (!script.hint || typeof script.hint !== 'string' || !script.hint.trim()) {
    return { valid: false, reason: 'Script is missing non-empty hint' };
  }
  if (!script.cta || typeof script.cta !== 'string' || !script.cta.trim()) {
    return { valid: false, reason: 'Script is missing non-empty cta' };
  }
  if (!Array.isArray(script.stories) || script.stories.length !== 3) {
    return {
      valid: false,
      reason: `Script must include exactly 3 stories, got ${Array.isArray(script.stories) ? script.stories.length : typeof script.stories}`,
    };
  }
  const snapshotStories = Array.isArray(snapshot?.stories) ? snapshot.stories : [];
  for (let i = 0; i < script.stories.length; i++) {
    const item = script.stories[i];
    if (!item || typeof item !== 'object' || !item.id || !item.line) {
      return { valid: false, reason: `Story item at index ${i} is missing id or line` };
    }
    const found = snapshotStories.find(s => s.id === item.id);
    if (!found) {
      return { valid: false, reason: `Story '${item.id}' from script is not found in snapshot` };
    }
    if (!found.title_vi || typeof found.title_vi !== 'string' || !found.title_vi.trim()) {
      return { valid: false, reason: `Story '${item.id}' from script lacks a Vietnamese title in snapshot` };
    }
  }
  return { valid: true };
}

const FALLBACK_PHRASINGS = [
  (count) => count >= 2 ? `Được ${count} nguồn công nghệ cùng đưa tin.` : 'Được ghi nhận từ nguồn tin công nghệ.',
  (count) => count >= 2 ? `Ghi nhận từ ${count} nguồn tin cùng đăng tải.` : 'Ghi nhận từ nguồn tin công nghệ.',
  (count) => count >= 2 ? `Được ${count} nguồn tin độc lập cùng xác nhận.` : 'Được nguồn tin độc lập xác nhận.',
];

export function fallbackStoryLine(story, index = 0) {
  const rawTitle = String(story.title_vi || story.title || '').trim();
  if (!rawTitle) throw new Error(`Story ${story.id || '(unknown)'} has no title.`);
  const title = normalizeSpeech(rawTitle);
  const titleWithPeriod = /[.!?]$/u.test(title) ? title : `${title}.`;
  const count = story.source_count || (Array.isArray(story.coverage) ? story.coverage.length : 1);
  const phrasingFn = FALLBACK_PHRASINGS[index % FALLBACK_PHRASINGS.length];
  return `${titleWithPeriod} ${phrasingFn(count)}`;
}

export function generateFallbackScript(snapshot, pickedStories, targetDate) {
  const date = targetDate || formatDateSlug(snapshot.generated_at);
  const stories = pickedStories && pickedStories.length === 3
    ? pickedStories
    : selectThreeStories(snapshot);

  if (!stories || stories.length < 3 || stories.some(s => !s.title_vi || typeof s.title_vi !== 'string' || !s.title_vi.trim())) {
    return null;
  }

  const storyCount = Array.isArray(snapshot?.stories) ? snapshot.stories.length : 3;

  return {
    date,
    generated_at: snapshot.generated_at || new Date().toISOString(),
    prompt_version: 'fallback-template-v2',
    hook: `Hôm nay ai-radar theo dõi ${storyCount} tin AI từ các nguồn công nghệ.`,
    hint: 'Ba tin AI đáng chú ý nhất, trong 45 giây.',
    stories: stories.map((st, i) => ({
      id: st.id,
      line: fallbackStoryLine(st, i),
    })),
    cta: 'Mỗi sáng ai-radar chọn 3 tin AI đáng đọc nhất. Theo dõi kênh để cập nhật tin AI nóng nhất. Bạn quan tâm tin nào nhất? Bình luận cho mình biết nhé.',
  };
}

export async function resolveScript({
  snapshot,
  snapshotPath,
  scriptPathOption,
  targetDate,
  pickedStories,
  liveUrl = 'https://dootan2020.github.io/ai-radar/data/video-script.json',
  fetchLive = true,
} = {}) {
  const expectedDate = targetDate || formatDateSlug(snapshot.generated_at);
  let lastReason = null;

  // 1. Explicit script path option (CLI --script or argument)
  if (scriptPathOption) {
    const candidatePath = path.isAbsolute(scriptPathOption)
      ? scriptPathOption
      : path.resolve(process.cwd(), scriptPathOption);
    if (fs.existsSync(candidatePath)) {
      try {
        const raw = fs.readFileSync(candidatePath, 'utf8');
        const parsed = JSON.parse(raw);
        const check = validateScript(parsed, snapshot, expectedDate);
        if (check.valid) {
          return { script: parsed, source: candidatePath, fallback: false };
        }
        lastReason = `explicit script invalid: ${check.reason}`;
      } catch (err) {
        lastReason = `explicit script read error: ${err.message}`;
      }
    } else {
      lastReason = `explicit script not found at ${candidatePath}`;
    }
  }

  // 2. Local candidate files
  const localCandidates = [];
  if (snapshotPath) {
    localCandidates.push(path.resolve(path.dirname(snapshotPath), 'video-script.json'));
  }
  localCandidates.push(path.resolve(process.cwd(), 'site/data/video-script.json'));
  localCandidates.push(path.resolve(__dirname, '../../site/data/video-script.json'));

  const seenCandidates = new Set();
  for (const candidate of localCandidates) {
    if (seenCandidates.has(candidate)) continue;
    seenCandidates.add(candidate);
    if (fs.existsSync(candidate)) {
      try {
        const raw = fs.readFileSync(candidate, 'utf8');
        const parsed = JSON.parse(raw);
        const check = validateScript(parsed, snapshot, expectedDate);
        if (check.valid) {
          return { script: parsed, source: candidate, fallback: false };
        }
        lastReason = `local file invalid (${candidate}): ${check.reason}`;
      } catch (err) {
        lastReason = `local file parse error (${candidate}): ${err.message}`;
      }
    }
  }

  // 3. Live URL
  if (fetchLive && liveUrl) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2500);
      const res = await fetch(liveUrl, {
        signal: controller.signal,
        headers: { 'User-Agent': 'ai-radar-video/1.0' },
      });
      clearTimeout(timer);
      if (res.ok) {
        const parsed = await res.json();
        const check = validateScript(parsed, snapshot, expectedDate);
        if (check.valid) {
          return { script: parsed, source: liveUrl, fallback: false };
        }
        lastReason = `live script invalid: ${check.reason}`;
      } else {
        lastReason = `live script HTTP ${res.status}`;
      }
    } catch (err) {
      lastReason = `live script fetch failed: ${err.message}`;
    }
  }

  // 4. Fallback template built from snapshot fields
  const fallbackScript = generateFallbackScript(snapshot, pickedStories, expectedDate);
  if (!fallbackScript) {
    return {
      script: null,
      source: 'fallback template',
      reason: lastReason || 'fewer than 3 translated stories qualify',
      fallback: true,
    };
  }
  return {
    script: fallbackScript,
    source: 'fallback template',
    reason: lastReason || 'script file missing or not for today',
    fallback: true,
  };
}

export function createNarration(input) {
  // Support legacy array of 3 stories
  if (Array.isArray(input)) {
    if (input.length !== 3) throw new Error(`Expected 3 stories, received ${input.length}.`);
    return input.map(narrationForStory).join('\n\n') + '\n';
  }

  // Script object
  const script = input;
  if (!script || typeof script !== 'object') {
    throw new Error('Expected script object or array of 3 stories.');
  }
  if (!script.hook || !script.hint || !Array.isArray(script.stories) || script.stories.length !== 3 || !script.cta) {
    throw new Error('Script object missing hook, hint, 3 stories, or cta.');
  }

  const hook = normalizeSpeech(script.hook);
  const hint = normalizeSpeech(script.hint);
  const introParagraph = `${hook}${/[.!?]$/u.test(hook) ? ' ' : '. '}${hint}`;

  const paragraphs = [
    introParagraph,
    normalizeSpeech(script.stories[0].line),
    normalizeSpeech(script.stories[1].line),
    normalizeSpeech(script.stories[2].line),
    normalizeSpeech(script.cta),
  ];

  return paragraphs.join('\n\n') + '\n';
}

export function wavSpeechSegments(buffer, {thresholdDb = -48, frameMs = 10, separatorMs = 800} = {}) {
  const {dataOffset, dataSize, sampleRate, channels, bitsPerSample, format} = readWav(buffer);
  if (format !== 1 || bitsPerSample !== 16) throw new Error('Expected 16-bit PCM WAV audio.');

  const bytesPerFrame = channels * 2;
  const frameSamples = Math.max(1, Math.round(sampleRate * frameMs / 1000));
  const sampleCount = Math.floor(dataSize / bytesPerFrame);
  const active = [];
  const threshold = 10 ** (thresholdDb / 20);

  for (let start = 0; start < sampleCount; start += frameSamples) {
    const end = Math.min(sampleCount, start + frameSamples);
    let energy = 0;
    for (let sample = start; sample < end; sample++) {
      for (let channel = 0; channel < channels; channel++) {
        const value = buffer.readInt16LE(dataOffset + (sample * channels + channel) * 2) / 32768;
        energy += value * value;
      }
    }
    const rms = Math.sqrt(energy / ((end - start) * channels));
    active.push(rms >= threshold);
  }

  const spans = [];
  let startFrame = -1;
  for (let i = 0; i <= active.length; i++) {
    if (i < active.length && active[i]) {
      if (startFrame < 0) startFrame = i;
      continue;
    }
    if (startFrame >= 0) {
      spans.push({start: startFrame * frameMs / 1000, end: i * frameMs / 1000});
      startFrame = -1;
    }
  }

  const segments = [];
  for (const span of spans) {
    const previous = segments.at(-1);
    if (previous && (span.start - previous.end) * 1000 < separatorMs) {
      previous.end = span.end;
    } else {
      segments.push({...span});
    }
  }
  if (segments.length !== 5 && segments.length !== 3) {
    throw new Error(`Expected 5 (or 3) narration audio segments; detected ${segments.length}.`);
  }
  return segments.map(({start, end}) => ({
    start,
    end,
    duration: end - start,
    startFrame: Math.round(start * 30),
    durationFrames: Math.round((end - start) * 30),
  }));
}

function readWav(buffer) {
  if (buffer.toString('ascii', 0, 4) !== 'RIFF' || buffer.toString('ascii', 8, 12) !== 'WAVE') {
    throw new Error('Expected a RIFF/WAVE audio file.');
  }
  let format;
  let channels;
  let sampleRate;
  let bitsPerSample;
  let dataOffset;
  let dataSize;
  for (let offset = 12; offset + 8 <= buffer.length;) {
    const id = buffer.toString('ascii', offset, offset + 4);
    const size = buffer.readUInt32LE(offset + 4);
    const content = offset + 8;
    if (id === 'fmt ') {
      format = buffer.readUInt16LE(content);
      channels = buffer.readUInt16LE(content + 2);
      sampleRate = buffer.readUInt32LE(content + 4);
      bitsPerSample = buffer.readUInt16LE(content + 14);
    } else if (id === 'data') {
      dataOffset = content;
      dataSize = size;
      break;
    }
    offset = content + size + (size % 2);
  }
  if (!channels || !sampleRate || dataOffset === undefined || dataOffset + dataSize > buffer.length) {
    throw new Error('WAV is missing a valid format or data chunk.');
  }
  return {format, channels, sampleRate, bitsPerSample, dataOffset, dataSize};
}

export function audioTimeline(segments, {introSeconds = 2, outroSeconds = 3, tailSeconds = 0.8} = {}) {
  if (segments.length !== 5 && segments.length !== 3) {
    throw new Error(`Expected 5 or 3 audio segments, received ${segments.length}.`);
  }

  if (segments.length === 5) {
    // Round 4: Voice starts over opening visual (Intro = segment 0, Story 1 = segment 1, Story 2 = segment 2, Story 3 = segment 3, Outro = segment 4)
    const introFrames = Math.round(segments[1].start * 30);
    const storyDurations = [
      Math.round((segments[2].start - segments[1].start) * 30),
      Math.round((segments[3].start - segments[2].start) * 30),
      Math.round((segments[4].start - segments[3].start) * 30),
    ];
    const outroFrames = Math.round(segments[4].duration * 30) + Math.round(tailSeconds * 30);
    return {
      introFrames,
      outroFrames,
      storyDurations,
      totalFrames: introFrames + storyDurations.reduce((sum, value) => sum + value, 0) + outroFrames,
      hasVoiceIntro: true,
      hasVoiceOutro: true,
    };
  }

  // Legacy 3 segments
  const introFrames = Math.round(introSeconds * 30);
  const outroFrames = Math.round(outroSeconds * 30);
  const storyDurations = segments.map((segment, index) => index < 2
    ? Math.round((segments[index + 1].start - segment.start) * 30)
    : Math.round(segment.duration * 30) + Math.round(tailSeconds * 30));
  return {
    introFrames,
    outroFrames,
    storyDurations,
    totalFrames: introFrames + storyDurations.reduce((sum, value) => sum + value, 0) + outroFrames,
    hasVoiceIntro: false,
    hasVoiceOutro: false,
  };
}

export function resolveOmniVoicePaths(env = process.env, options = {}) {
  const baseDir = options.baseDir || path.resolve(__dirname, '..');
  const codex = env.CODEX_HOME || path.join(os.homedir(), '.codex');

  const pythonCandidates = [
    env.OMNIVOICE_PYTHON,
    path.join(codex, '.cache', 'omnivoice-tts', 'venv', 'Scripts', 'python.exe'),
    path.join(codex, '.cache', 'omnivoice-tts', 'venv', 'bin', 'python'),
  ];
  const python = pythonCandidates.find(candidate => candidate && fs.existsSync(candidate))
    || env.OMNIVOICE_PYTHON
    || path.join(codex, '.cache', 'omnivoice-tts', 'venv', 'Scripts', 'python.exe');

  const cache = env.OMNIVOICE_CACHE_DIR
    || path.join(codex, '.cache', 'omnivoice-tts', 'huggingface');

  const wrapperCandidates = [
    env.OMNIVOICE_WRAPPER,
    env.OMNIVOICE_SCRIPT,
    path.resolve(baseDir, 'scripts/omnivoice_tts.py'),
    path.join(codex, 'skills-parked-vas', 'omnivoice-tts', 'scripts', 'omnivoice_tts.py'),
    path.resolve(baseDir, '../plans/reports/tham-chieu/skills/omnivoice-tts/scripts/omnivoice_tts.py'),
  ];
  const wrapper = wrapperCandidates.find(candidate => candidate && fs.existsSync(candidate))
    || path.resolve(baseDir, 'scripts/omnivoice_tts.py');

  const fixOmnivoiceCandidates = [
    env.FIX_OMNIVOICE_SCRIPT,
    path.resolve(path.dirname(wrapper), 'fix_omnivoice.py'),
    path.resolve(baseDir, 'scripts/fix_omnivoice.py'),
    path.join(codex, 'skills-parked-vas', 'fix-omnivoice', 'scripts', 'fix_omnivoice.py'),
    path.join(codex, 'skills', 'fix-omnivoice', 'scripts', 'fix_omnivoice.py'),
    path.resolve(baseDir, '../plans/reports/tham-chieu/skills/fix-omnivoice/scripts/fix_omnivoice.py'),
  ];
  const fixOmnivoice = fixOmnivoiceCandidates.find(candidate => candidate && fs.existsSync(candidate))
    || path.resolve(baseDir, 'scripts/fix_omnivoice.py');

  const referenceAudioCandidates = [
    env.OMNIVOICE_REF_AUDIO,
    path.resolve(baseDir, 'voice/reference.wav'),
    path.resolve(baseDir, 'voice/giong-2-trung-nien-tram.wav'),
    path.resolve(baseDir, '../plans/reports/tham-chieu/giong/giong-2-trung-nien-tram.wav'),
  ];
  const referenceAudio = referenceAudioCandidates.find(candidate => candidate && fs.existsSync(candidate))
    || path.resolve(baseDir, 'voice/reference.wav');

  const referenceTextCandidates = [
    env.OMNIVOICE_REF_TEXT,
    path.resolve(baseDir, 'voice/reference.txt'),
    path.resolve(baseDir, 'voice/giong-2.txt'),
    path.resolve(baseDir, '../plans/reports/tham-chieu/giong/giong-2.txt'),
  ];
  const referenceText = referenceTextCandidates.find(candidate => candidate && fs.existsSync(candidate))
    || path.resolve(baseDir, 'voice/reference.txt');

  return {
    python,
    cache,
    wrapper,
    fixOmnivoice,
    referenceAudio,
    referenceText,
  };
}
