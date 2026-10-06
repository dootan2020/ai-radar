import assert from 'node:assert/strict';
import test from 'node:test';
import {audioTimeline, createNarration, wavSpeechSegments} from '../src/daily-audio.js';

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
