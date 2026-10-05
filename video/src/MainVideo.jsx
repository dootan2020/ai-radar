import React from 'react';
import { Sequence } from 'remotion';
import { FONT_STYLES } from './fonts.js';
import { TOKENS } from './tokens.js';
import { IntroScene } from './components/IntroScene.jsx';
import { StoryScene } from './components/StoryScene.jsx';
import { OutroScene } from './components/OutroScene.jsx';
import { ProgressBar } from './components/ProgressBar.jsx';

export const MainVideo = ({
  stories = [],
  snapshotDate = 'Thứ Hai, 5 tháng 10, 2026',
  totalStoriesCount = 1306,
}) => {
  // Timeline setup (Total: 1080 frames = 36 seconds @ 30fps)
  const SCENES = [
    { start: 0, duration: 120, end: 120 },     // Intro: 4s
    { start: 120, duration: 285, end: 405 },   // Story 1: 9.5s
    { start: 405, duration: 285, end: 690 },   // Story 2: 9.5s
    { start: 690, duration: 270, end: 960 },   // Story 3: 9.0s
    { start: 960, duration: 120, end: 1080 },  // Outro: 4.0s
  ];

  return (
    <div
      style={{
        width: 1080,
        height: 1920,
        backgroundColor: TOKENS.colors.canvas,
        color: TOKENS.colors.ink,
        fontFamily: TOKENS.fonts.main,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Global Embedded Font Styles */}
      <style>{FONT_STYLES}</style>

      {/* Global Ambient Background Texture/Glow */}
      <div
        style={{
          position: 'absolute',
          top: -200,
          left: -100,
          width: 700,
          height: 700,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(67, 120, 255, 0.08) 0%, rgba(20, 19, 24, 0) 70%)',
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: 100,
          right: -100,
          width: 800,
          height: 800,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(67, 120, 255, 0.06) 0%, rgba(20, 19, 24, 0) 70%)',
          pointerEvents: 'none',
        }}
      />

      {/* Sequence 0: Intro Hook */}
      <Sequence from={SCENES[0].start} durationInFrames={SCENES[0].duration}>
        <IntroScene
          stories={stories}
          snapshotDate={snapshotDate}
          totalStoriesCount={totalStoriesCount}
        />
      </Sequence>

      {/* Sequence 1: Story 1 */}
      {stories[0] && (
        <Sequence from={SCENES[1].start} durationInFrames={SCENES[1].duration}>
          <StoryScene
            story={stories[0]}
            index={0}
            totalStories={stories.length}
            durationInFrames={SCENES[1].duration}
          />
        </Sequence>
      )}

      {/* Sequence 2: Story 2 */}
      {stories[1] && (
        <Sequence from={SCENES[2].start} durationInFrames={SCENES[2].duration}>
          <StoryScene
            story={stories[1]}
            index={1}
            totalStories={stories.length}
            durationInFrames={SCENES[2].duration}
          />
        </Sequence>
      )}

      {/* Sequence 3: Story 3 */}
      {stories[2] && (
        <Sequence from={SCENES[3].start} durationInFrames={SCENES[3].duration}>
          <StoryScene
            story={stories[2]}
            index={2}
            totalStories={stories.length}
            durationInFrames={SCENES[3].duration}
          />
        </Sequence>
      )}

      {/* Sequence 4: Outro */}
      <Sequence from={SCENES[4].start} durationInFrames={SCENES[4].duration}>
        <OutroScene />
      </Sequence>

      {/* Persistent Bottom Progress Bar */}
      <ProgressBar totalFrames={1080} scenes={SCENES} />
    </div>
  );
};
