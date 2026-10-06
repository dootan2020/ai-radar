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

export function createNarration(stories) {
  if (stories.length !== 3) throw new Error(`Expected 3 stories, received ${stories.length}.`);
  return stories.map(narrationForStory).join('\n\n') + '\n';
}

export function wavSpeechSegments(buffer, {thresholdDb = -48, frameMs = 10, separatorMs = 1050} = {}) {
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
  if (segments.length !== 3) {
    throw new Error(`Expected 3 narration audio segments; detected ${segments.length}.`);
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
  if (segments.length !== 3) throw new Error(`Expected 3 audio segments, received ${segments.length}.`);
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
  };
}
