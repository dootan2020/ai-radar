import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {audioTimeline, createNarration, narrationForStory, normalizeSpeech, wavSpeechSegments, resolveOmniVoicePaths} from '../src/daily-audio.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function pcm(samples, sampleRate = 24_000) {
  const data = Buffer.alloc(samples.length * 2);
  samples.forEach((sample, index) => data.writeInt16LE(sample, index * 2));
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}

function silence(milliseconds) {
  return Array(24 * milliseconds).fill(0);
}

function speech(milliseconds, amplitude = 6000) {
  return Array(24 * milliseconds).fill(amplitude);
}

test('narration uses Vietnamese snapshot fields and only its first complete summary sentence', () => {
  const stories = [1, 2, 3].map((id) => ({
    id,
    title_vi: `Tiêu đề ${id}`,
    summary_vi: 'Câu đầu tiên. Câu thứ hai.',
  }));
  assert.equal(createNarration(stories),
    'Tiêu đề 1. Câu đầu tiên.\n\nTiêu đề 2. Câu đầu tiên.\n\nTiêu đề 3. Câu đầu tiên.\n');
  assert.throws(() => createNarration(stories.slice(0, 2)), /Expected 3 stories/);
});

test('WAV speech segments set scene starts and durations from measured audio', () => {
  const samples = [
    ...speech(1000), ...silence(1200), ...speech(800), ...silence(1200), ...speech(1100),
  ];
  const segments = wavSpeechSegments(pcm(samples));
  assert.equal(segments.length, 3);
  assert.deepEqual(segments.map(({duration}) => Math.round(duration * 10) / 10), [1, 0.8, 1.1]);

  const timeline = audioTimeline(segments);
  assert.equal(timeline.introFrames, 60);
  assert.equal(timeline.outroFrames, 90);
  assert.equal(timeline.storyDurations[0], Math.round(segments[1].start * 30));
  assert.equal(timeline.storyDurations[1], Math.round((segments[2].start - segments[1].start) * 30));
  assert.ok(timeline.totalFrames > timeline.introFrames + timeline.outroFrames);
});

test('speech segmentation rejects invalid WAV types and missing story breaks', () => {
  assert.throws(() => wavSpeechSegments(Buffer.from('not audio')), /RIFF\/WAVE/);
  assert.throws(() => wavSpeechSegments(pcm(speech(800))), /detected 1/);
});

test('speech normalization converts currency symbols and percentages for TTS', () => {
  // Exact case from coordinator findings:
  assert.equal(
    normalizeSpeech('Nvidia Shield TV 7 năm tuổi bây giờ là $ 100 đắt hơn do AI'),
    'Nvidia Shield TV 7 năm tuổi bây giờ là 100 đô la đắt hơn do AI'
  );
  assert.equal(normalizeSpeech('Amazon chi $1B để phát triển AI'), 'Amazon chi 1 tỷ đô la để phát triển AI');
  assert.equal(normalizeSpeech('Thỏa thuận trị giá $5.8B tiền mặt'), 'Thỏa thuận trị giá 5.8 tỷ đô la tiền mặt');
  assert.equal(normalizeSpeech('Huy động $100M trong vòng mới'), 'Huy động 100 triệu đô la trong vòng mới');
  assert.equal(normalizeSpeech('Chi phí $10k mỗi tháng'), 'Chi phí 10 nghìn đô la mỗi tháng');
  assert.equal(normalizeSpeech('Đạt $ 100 tỷ trong năm nay'), 'Đạt 100 tỷ đô la trong năm nay');
  assert.equal(normalizeSpeech('Giá chỉ $ 50 đô la'), 'Giá chỉ 50 đô la');
  assert.equal(normalizeSpeech('Giá chỉ $50 USD'), 'Giá chỉ 50 đô la');
  assert.equal(normalizeSpeech('Bán với giá 299$'), 'Bán với giá 299 đô la');
  assert.equal(normalizeSpeech('Tăng trưởng đạt 15% trong quý'), 'Tăng trưởng đạt 15 phần trăm trong quý');
  assert.equal(normalizeSpeech('Microsoft & OpenAI hợp tác'), 'Microsoft và OpenAI hợp tác');
});

test('narrationForStory normalizes symbols in title and summary for TTS', () => {
  const story = {
    id: 'nvidia-shield',
    title_vi: 'Nvidia Shield TV 7 năm tuổi bây giờ là $ 100 đắt hơn do AI',
    summary_vi: 'Amazon đầu tư $1B vào trung tâm dữ liệu với 15% tăng trưởng. Câu tiếp theo bị bỏ.',
  };
  const narration = narrationForStory(story);
  assert.equal(
    narration,
    'Nvidia Shield TV 7 năm tuổi bây giờ là 100 đô la đắt hơn do AI. Amazon đầu tư 1 tỷ đô la vào trung tâm dữ liệu với 15 phần trăm tăng trưởng.'
  );
});

test('committed reference voice audio and text exist in video/voice and are valid', () => {
  const wavPath = path.resolve(__dirname, '../voice/reference.wav');
  const txtPath = path.resolve(__dirname, '../voice/reference.txt');
  assert.ok(fs.existsSync(wavPath), 'voice/reference.wav must exist in the repo');
  assert.ok(fs.existsSync(txtPath), 'voice/reference.txt must exist in the repo');

  const wavBuffer = fs.readFileSync(wavPath);
  assert.ok(wavBuffer.length > 100_000, 'reference.wav should be roughly 0.5 MB');
  assert.ok(wavBuffer.toString('ascii', 0, 4) === 'RIFF');
  assert.ok(wavBuffer.toString('ascii', 8, 12) === 'WAVE');

  const txtContent = fs.readFileSync(txtPath, 'utf8').trim();
  assert.ok(txtContent.length > 20, 'reference.txt should contain reference transcript');
  assert.ok(txtContent.includes('Chào buổi sáng'), 'reference transcript should match approved voice sample');
});

test('resolves OmniVoice wrapper and fix-omnivoice post-processor without gitignored tham-chieu copies', () => {
  const paths = resolveOmniVoicePaths({});

  // 1. Wrapper resolution
  assert.ok(paths.wrapper, 'Wrapper script must be defined');
  assert.ok(fs.existsSync(paths.wrapper), `Wrapper script must exist on disk: ${paths.wrapper}`);
  assert.ok(paths.wrapper.endsWith(path.join('video', 'scripts', 'omnivoice_tts.py')) || paths.wrapper.endsWith('omnivoice_tts.py'));
  const normWrapper = paths.wrapper.replace(/\\/g, '/').toLowerCase();
  assert.ok(!normWrapper.includes('tham-chieu'), 'Resolved wrapper must not point to gitignored tham-chieu');
  assert.ok(!normWrapper.includes('/plans/'), 'Resolved wrapper must not point to gitignored plans directory');

  // 2. Post-processor resolution
  assert.ok(paths.fixOmnivoice, 'Fix OmniVoice script must be defined');
  assert.ok(fs.existsSync(paths.fixOmnivoice), `Fix OmniVoice script must exist on disk: ${paths.fixOmnivoice}`);
  assert.ok(paths.fixOmnivoice.endsWith(path.join('video', 'scripts', 'fix_omnivoice.py')) || paths.fixOmnivoice.endsWith('fix_omnivoice.py'));
  const normFix = paths.fixOmnivoice.replace(/\\/g, '/').toLowerCase();
  assert.ok(!normFix.includes('tham-chieu'), 'Resolved fix-omnivoice must not point to gitignored tham-chieu');
  assert.ok(!normFix.includes('/plans/'), 'Resolved fix-omnivoice must not point to gitignored plans directory');

  // 3. Audio & text reference resolution
  assert.ok(fs.existsSync(paths.referenceAudio), `Reference audio must exist: ${paths.referenceAudio}`);
  assert.ok(fs.existsSync(paths.referenceText), `Reference text must exist: ${paths.referenceText}`);
  const normRefAudio = paths.referenceAudio.replace(/\\/g, '/').toLowerCase();
  assert.ok(!normRefAudio.includes('tham-chieu'), 'Reference audio must not point to gitignored tham-chieu');
  assert.ok(!normRefAudio.includes('/plans/'), 'Reference audio must not point to gitignored plans directory');
});

test('resolves OmniVoice wrapper and fix script with custom environment overrides', () => {
  const customWrapper = path.resolve(__dirname, '../scripts/omnivoice_tts.py');
  const customFix = path.resolve(__dirname, '../scripts/fix_omnivoice.py');
  const paths = resolveOmniVoicePaths({
    OMNIVOICE_WRAPPER: customWrapper,
    FIX_OMNIVOICE_SCRIPT: customFix,
  });
  assert.equal(paths.wrapper, customWrapper);
  assert.equal(paths.fixOmnivoice, customFix);
});

