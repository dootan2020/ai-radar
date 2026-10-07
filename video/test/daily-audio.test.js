import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  audioTimeline,
  createNarration,
  formatDateSlug,
  formatVietnameseDate,
  generateFallbackScript,
  narrationForStory,
  normalizeSpeech,
  resolveOmniVoicePaths,
  resolveScript,
  validateScript,
  wavSpeechSegments,
} from '../src/daily-audio.js';

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

const mockSnapshot = {
  generated_at: '2026-10-05T19:00:45Z',
  stories: [
    {
      id: 'story-1',
      title_vi: 'Nvidia Shield TV tăng giá do AI',
      summary_vi: 'Nvidia Shield TV Pro tăng giá $100 vì nhu cầu AI. Câu tiếp theo.',
      worth_score: 8.5,
      coverage: [{ source: 'techcrunch', publisher: 'techcrunch' }, { source: 'the-verge', publisher: 'the-verge' }],
    },
    {
      id: 'story-2',
      title_vi: 'Apple thắt chặt quyền Full Disk Access',
      summary_vi: 'Apple cảnh báo agent AI có thể đọc trộm tin nhắn. Câu tiếp theo.',
      worth_score: 7.2,
      coverage: [{ source: 'techcrunch', publisher: 'techcrunch' }, { source: 'the-verge', publisher: 'the-verge' }],
    },
    {
      id: 'story-3',
      title_vi: 'Amazon đầu tư $1B vào trung tâm dữ liệu',
      summary_vi: 'Amazon chi $1B để xoa dịu phản ứng ô nhiễm. Câu tiếp theo.',
      worth_score: 6.9,
      coverage: [{ source: 'techcrunch', publisher: 'techcrunch' }, { source: 'the-verge', publisher: 'the-verge' }],
    },
  ],
};

test('narration uses Vietnamese snapshot fields and only its first complete summary sentence', () => {
  const stories = [1, 2, 3].map((id) => ({
    id: `story-${id}`,
    title_vi: `Tiêu đề ${id}`,
    summary_vi: 'Câu đầu tiên. Câu thứ hai.',
  }));
  assert.equal(
    createNarration(stories),
    'Tiêu đề 1. Câu đầu tiên.\n\nTiêu đề 2. Câu đầu tiên.\n\nTiêu đề 3. Câu đầu tiên.\n'
  );
  assert.throws(() => createNarration(stories.slice(0, 2)), /Expected 3 stories/);
});

test('Round 4 script validation validates contract structure, date, and story IDs', () => {
  const targetDate = formatDateSlug(mockSnapshot.generated_at);
  assert.equal(targetDate, '2026-10-06');

  const validScript = {
    date: targetDate,
    generated_at: '2026-10-06T19:00:00Z',
    prompt_version: 'v1.0',
    hook: 'AI vừa khiến một chiếc TV box 7 năm tuổi đắt thêm $100.',
    hint: 'Ba tin AI đáng chú ý nhất, trong 45 giây.',
    stories: [
      { id: 'story-1', line: 'Nvidia Shield TV Pro đắt thêm $100 vì AI.' },
      { id: 'story-2', line: 'Apple siết quyền truy cập toàn bộ ổ đĩa trên macOS.' },
      { id: 'story-3', line: 'Amazon chi $1B để xoa dịu phản ứng về trung tâm dữ liệu.' },
    ],
    cta: 'Mỗi sáng ai-radar chọn 3 tin AI đáng đọc nhất. Theo dõi kênh để cập nhật tin AI nóng nhất. Bạn quan tâm tin nào nhất? Bình luận cho mình biết nhé.',
  };

  const res1 = validateScript(validScript, mockSnapshot, targetDate);
  assert.equal(res1.valid, true);

  // Mismatched date
  const resWrongDate = validateScript({ ...validScript, date: '2026-10-05' }, mockSnapshot, targetDate);
  assert.equal(resWrongDate.valid, false);
  assert.ok(resWrongDate.reason.includes('does not match'));

  // Missing hook
  const resNoHook = validateScript({ ...validScript, hook: '' }, mockSnapshot, targetDate);
  assert.equal(resNoHook.valid, false);
  assert.ok(resNoHook.reason.includes('hook'));

  // Story ID not in snapshot
  const resBadId = validateScript(
    {
      ...validScript,
      stories: [
        { id: 'unknown-id', line: 'Line 1' },
        { id: 'story-2', line: 'Line 2' },
        { id: 'story-3', line: 'Line 3' },
      ],
    },
    mockSnapshot,
    targetDate
  );
  assert.equal(resBadId.valid, false);
  assert.ok(resBadId.reason.includes('unknown-id'));
});

test('generateFallbackScript creates honest script matching contract strictly from snapshot', () => {
  const targetDate = formatDateSlug(mockSnapshot.generated_at);
  const fallback = generateFallbackScript(mockSnapshot, mockSnapshot.stories, targetDate);

  assert.equal(fallback.date, targetDate);
  assert.ok(fallback.hook.includes('3 tin AI'));
  assert.ok(!fallback.hook.includes(mockSnapshot.stories[0].title_vi), 'Fallback hook must not stutter/repeat story 1');
  assert.ok(fallback.hint.includes('45 giây'));
  assert.equal(fallback.stories.length, 3);
  assert.equal(fallback.stories[0].id, 'story-1');
  assert.ok(fallback.cta.includes('Theo dõi kênh để cập nhật tin AI nóng nhất'));
  assert.ok(fallback.cta.includes('Bạn quan tâm tin nào nhất?'));

  // Validate that the generated fallback passes validation against the snapshot
  const validation = validateScript(fallback, mockSnapshot, targetDate);
  assert.equal(validation.valid, true);
});

test('resolveScript prioritizes valid script option, local file, and falls back to honest template', async () => {
  const targetDate = formatDateSlug(mockSnapshot.generated_at);
  const fixturePath = path.resolve(__dirname, '../fixtures/video-script.json');

  // When given the fixture path (which has real snapshot IDs)
  // Let's create a temporary snapshot containing the fixture's story IDs
  const realFixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const testSnapshot = {
    generated_at: '2026-10-05T19:00:45Z',
    stories: realFixture.stories.map((st) => ({
      id: st.id,
      title_vi: st.line,
      summary_vi: 'Tóm tắt câu một. Câu hai.',
      coverage: [{ source: 'techcrunch', publisher: 'techcrunch' }, { source: 'the-verge', publisher: 'the-verge' }],
    })),
  };

  const resolved = await resolveScript({
    snapshot: testSnapshot,
    scriptPathOption: fixturePath,
    targetDate: '2026-10-06',
    fetchLive: false,
  });
  assert.equal(resolved.fallback, false);
  assert.equal(resolved.source, fixturePath);
  assert.equal(resolved.script.date, '2026-10-06');
  assert.equal(resolved.script.stories.length, 3);

  // When script is missing or invalid: falls back to template and states reason
  const fallbackResolved = await resolveScript({
    snapshot: testSnapshot,
    scriptPathOption: 'non_existent_script.json',
    targetDate: '2026-10-06',
    fetchLive: false,
  });
  assert.equal(fallbackResolved.fallback, true);
  assert.equal(fallbackResolved.source, 'fallback template');
  assert.ok(fallbackResolved.reason.includes('not found') || fallbackResolved.reason.includes('missing'));
  assert.equal(fallbackResolved.script.stories.length, 3);
});

test('createNarration generates 5 paragraphs from script with symbol normalization', () => {
  const script = {
    date: '2026-10-06',
    hook: 'AI vừa khiến một chiếc TV box 7 năm tuổi đắt thêm $ 100.',
    hint: 'Ba tin AI đáng chú ý nhất, trong 45 giây.',
    stories: [
      { id: '1', line: 'Nvidia Shield TV Pro giờ bán $ 299, đắt hơn $100 vì AI.' },
      { id: '2', line: 'Apple siết quyền truy cập ổ đĩa với 15% người dùng.' },
      { id: '3', line: 'Amazon chi $1B để xoa dịu phản ứng & ô nhiễm.' },
    ],
    cta: 'Mỗi sáng ai-radar chọn 3 tin AI đáng đọc nhất. Theo dõi kênh để cập nhật tin AI nóng nhất. Bạn quan tâm tin nào nhất? Bình luận cho mình biết nhé.',
  };

  const narration = createNarration(script);
  const paragraphs = narration.trim().split('\n\n');
  assert.equal(paragraphs.length, 5);

  // Intro paragraph combines hook and hint
  assert.ok(paragraphs[0].includes('100 đô la'));
  assert.ok(paragraphs[0].includes('Ba tin AI đáng chú ý nhất, trong 45 giây'));

  // Story paragraphs normalized
  assert.ok(paragraphs[1].includes('299 đô la'));
  assert.ok(paragraphs[2].includes('15 phần trăm'));
  assert.ok(paragraphs[3].includes('1 tỷ đô la'));
  assert.ok(paragraphs[3].includes('và ô nhiễm'));

  // Outro CTA
  assert.ok(paragraphs[4].includes('Theo dõi kênh để cập nhật tin AI nóng nhất'));
});

test('WAV speech segments and audioTimeline handle Round 4 5-segment audio', () => {
  // 5 speech blocks: Intro, Story 1, Story 2, Story 3, Outro
  const samples = [
    ...speech(1500), ...silence(1200), // Intro (1.5s)
    ...speech(1000), ...silence(1200), // Story 1 (1.0s)
    ...speech(1200), ...silence(1200), // Story 2 (1.2s)
    ...speech(1100), ...silence(1200), // Story 3 (1.1s)
    ...speech(1300),                   // Outro (1.3s)
  ];
  const segments = wavSpeechSegments(pcm(samples));
  assert.equal(segments.length, 5);

  const timeline = audioTimeline(segments, { tailSeconds: 0.8 });
  assert.equal(timeline.hasVoiceIntro, true);
  assert.equal(timeline.hasVoiceOutro, true);

  // introFrames starts at 0 and extends until Story 1 starts
  assert.equal(timeline.introFrames, Math.round(segments[1].start * 30));
  // Story durations match intervals between segment starts
  assert.equal(timeline.storyDurations[0], Math.round((segments[2].start - segments[1].start) * 30));
  assert.equal(timeline.storyDurations[1], Math.round((segments[3].start - segments[2].start) * 30));
  assert.equal(timeline.storyDurations[2], Math.round((segments[4].start - segments[3].start) * 30));
  // Outro duration includes CTA speech + tail
  assert.equal(timeline.outroFrames, Math.round(segments[4].duration * 30) + Math.round(0.8 * 30));

  assert.equal(
    timeline.totalFrames,
    timeline.introFrames + timeline.storyDurations.reduce((a, b) => a + b, 0) + timeline.outroFrames
  );
});

test('Round 6 1s pauses: wavSpeechSegments handles ~1s section gaps while merging intra-story pauses', () => {
  // 5 speech blocks separated by 1000ms pauses, with an internal pause of 650ms in Story 2
  const samples = [
    ...speech(1500), ...silence(1000), // Intro (1.5s) + 1s pause
    ...speech(1000), ...silence(1000), // Story 1 (1.0s) + 1s pause
    ...speech(600), ...silence(650), ...speech(600), ...silence(1000), // Story 2 (with internal 650ms pause) + 1s pause
    ...speech(1100), ...silence(1000), // Story 3 (1.1s) + 1s pause
    ...speech(1300),                   // Outro (1.3s)
  ];
  const segments = wavSpeechSegments(pcm(samples));
  assert.equal(segments.length, 5);

  const timeline = audioTimeline(segments, { tailSeconds: 0.8 });
  assert.equal(timeline.hasVoiceIntro, true);
  assert.equal(timeline.hasVoiceOutro, true);
});

test('speech segmentation rejects invalid WAV types and invalid segment counts', () => {
  assert.throws(() => wavSpeechSegments(Buffer.from('not audio')), /RIFF\/WAVE/);
  assert.throws(() => wavSpeechSegments(pcm(speech(800))), /detected 1/);
});

test('speech normalization converts currency symbols and percentages for TTS', () => {
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

test('approved sample fixture video/fixtures/video-script.json exists and conforms to contract', () => {
  const fixturePath = path.resolve(__dirname, '../fixtures/video-script.json');
  assert.ok(fs.existsSync(fixturePath), 'video/fixtures/video-script.json must exist');
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));

  assert.equal(fixture.date, '2026-10-06');
  assert.equal(fixture.prompt_version, 'v1.0');
  assert.ok(fixture.hook.includes('AI vừa khiến một chiếc TV box 7 năm tuổi'));
  assert.ok(fixture.hint.includes('Ba tin AI đáng chú ý nhất'));
  assert.equal(fixture.stories.length, 3);
  assert.equal(fixture.stories[0].id, 'a08a24d3f61d4df508c8'); // Nvidia Shield TV (most surprising first)
  assert.equal(fixture.stories[1].id, '5432f5b94c34f514ec03'); // Apple macOS
  assert.equal(fixture.stories[2].id, '90c6c9903271281ae042'); // Amazon $1B plan
  assert.ok(fixture.cta.includes('Mỗi sáng ai-radar chọn 3 tin AI'));
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
  assert.ok(
    paths.wrapper.endsWith(path.join('video', 'scripts', 'omnivoice_tts.py')) ||
      paths.wrapper.endsWith('omnivoice_tts.py')
  );
  const normWrapper = paths.wrapper.replace(/\\/g, '/').toLowerCase();
  assert.ok(!normWrapper.includes('tham-chieu'), 'Resolved wrapper must not point to gitignored tham-chieu');
  assert.ok(!normWrapper.includes('/plans/'), 'Resolved wrapper must not point to gitignored plans directory');

  // 2. Post-processor resolution
  assert.ok(paths.fixOmnivoice, 'Fix OmniVoice script must be defined');
  assert.ok(fs.existsSync(paths.fixOmnivoice), `Fix OmniVoice script must exist on disk: ${paths.fixOmnivoice}`);
  assert.ok(
    paths.fixOmnivoice.endsWith(path.join('video', 'scripts', 'fix_omnivoice.py')) ||
      paths.fixOmnivoice.endsWith('fix_omnivoice.py')
  );
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

test('Round 5 muted viewer contract: script and fallback deliver hook, hint, 3 story lines, and cta', () => {
  const fallback = generateFallbackScript(mockSnapshot, mockSnapshot.stories, '2026-10-05');
  assert.ok(fallback.hook && fallback.hook.length > 10, 'Fallback must supply non-empty hook');
  assert.ok(fallback.hint && fallback.hint.length > 5, 'Fallback must supply non-empty hint');
  assert.ok(fallback.cta && fallback.cta.includes('Theo dõi kênh để cập nhật tin AI nóng nhất'), 'Fallback must supply actionable cta');
  assert.equal(fallback.stories.length, 3, 'Fallback must provide 3 stories');
  fallback.stories.forEach((st, i) => {
    assert.ok(st.id, `Fallback story ${i} missing id`);
    assert.ok(st.line && st.line.length > 10, `Fallback story ${i} missing line for audio and visual card`);
    assert.ok(st.line.includes(normalizeSpeech(mockSnapshot.stories[i].title_vi)), `Fallback story ${i} must include Vietnamese title`);
    assert.ok(!st.line.includes('Câu tiếp theo'), `Fallback story ${i} must not include raw summary sentences`);
  });

  const fixturePath = path.resolve(__dirname, '../fixtures/video-script.json');
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const fixtureSnapshot = {
    generated_at: '2026-10-06T19:00:00Z',
    stories: fixture.stories.map(st => ({ id: st.id, title_vi: st.line })),
  };
  const check = validateScript(fixture, fixtureSnapshot, '2026-10-06');
  assert.equal(check.valid, true);
  assert.ok(fixture.hook.includes('TV box 7 năm tuổi'), 'Approved sample hook covers opening visual');
  assert.ok(fixture.hint.includes('45 giây'), 'Approved sample hint promises 45-second duration');
  assert.ok(fixture.cta.includes('Theo dõi kênh để cập nhật tin AI nóng nhất'), 'Approved sample CTA includes follow prompt');
  assert.ok(fixture.cta.includes('Bình luận'), 'Approved sample CTA includes comment prompt');
});

