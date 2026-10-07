import React, { useState } from 'react';
import { interpolate, useCurrentFrame, Easing, Img } from 'remotion';
import { TOKENS } from '../tokens.js';

export const StoryScene = ({ story, index, totalStories = 3, durationInFrames }) => {
  const frame = useCurrentFrame();
  const easeFlow = Easing.bezier(0.16, 1, 0.3, 1);

  // Entrance animations
  /*
  const sceneOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  */

  const headerY = interpolate(frame, [0, 20], [25, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const visualY = interpolate(frame, [5, 28], [35, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const textY = interpolate(frame, [12, 35], [40, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Slow subtle drift for image
  const imgScale = interpolate(frame, [0, durationInFrames], [1, 1.05], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Exit transition
  const exitOpacity = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  // Data extraction
  const titleVi = story.title_vi || '';
  const titleEn = story.title !== titleVi ? story.title : null;
  const summary = story.scriptLine || story.line || story.summary_vi || story.description_vi || '';
  
  // Sources
  const coverage = story.coverage || [];
  const sourceNames = [...new Set(coverage.map(c => c.publisher || c.source).filter(Boolean))];
  const sourceText = sourceNames.slice(0, 3).join(' · ') || 'Tin quốc tế';
  const sourceCount = sourceNames.length || 1;

  // Image URL
  const imageUrl = story.imageUrl || (story.image && story.image.src) || null;

  // Monogram / initial for fallback
  const firstLetter = (titleVi || 'A').charAt(0).toUpperCase();

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '120px 64px 100px 64px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        fontFamily: TOKENS.fonts.main,
        color: TOKENS.colors.ink,
        opacity: exitOpacity,
      }}
    >
      {/* Top Header / Meta bar */}
      <div
        style={{
          transform: `translateY(${headerY}px)`,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {/* Index pill */}
          <div
            style={{
              backgroundColor: TOKENS.colors.accent,
              color: '#ffffff',
              fontSize: 20,
              fontWeight: 700,
              padding: '8px 20px',
              borderRadius: TOKENS.radii.full,
              letterSpacing: '0.04em',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            0{index + 1} / 0{totalStories}
          </div>

          {/* Sources badge */}
          <div
            style={{
              backgroundColor: TOKENS.colors.surface,
              border: `1px solid ${TOKENS.colors.hairFaint}`,
              padding: '8px 18px',
              borderRadius: TOKENS.radii.full,
              fontSize: 20,
              fontWeight: 500,
              color: TOKENS.colors.inkSecondary,
            }}
          >
            {sourceCount >= 2 ? `${sourceCount} nguồn cùng đưa tin` : sourceText}
          </div>
        </div>

      </div>

      {/* Hero Visual Area (Photo or Typographic Card) */}
      <div
        style={{
          transform: `translateY(${visualY}px)`,
          width: '100%',
          height: 600,
          borderRadius: TOKENS.radii.xl,
          overflow: 'hidden',
          position: 'relative',
          backgroundColor: TOKENS.colors.surface,
          border: `1px solid ${TOKENS.colors.hairFaint}`,
          boxShadow: TOKENS.shadows.card,
        }}
      >
        {imageUrl ? (
          <div
            style={{
              width: '100%',
              height: '100%',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            <Img
              src={imageUrl}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                transform: `scale(${imgScale})`,
              }}
            />
            {/* Subtle editorial gradient overlay */}
            <div
              style={{
                position: 'absolute',
                inset: 0,
                background: 'linear-gradient(180deg, rgba(20,19,24,0) 60%, rgba(20,19,24,0.7) 100%)',
              }}
            />
          </div>
        ) : (
          /* Editorial Fallback Graphic */
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              alignItems: 'center',
              padding: 48,
              background: 'radial-gradient(circle at 50% 30%, rgba(67, 120, 255, 0.12) 0%, rgba(28, 27, 34, 0.95) 70%)',
            }}
          >
            <div
              style={{
                width: 120,
                height: 120,
                borderRadius: '28%',
                backgroundColor: TOKENS.colors.accentSoft,
                border: `1px solid ${TOKENS.colors.hairFaint}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 54,
                fontWeight: 700,
                color: TOKENS.colors.accent,
                marginBottom: 28,
              }}
            >
              {firstLetter}
            </div>

            <div
              style={{
                fontSize: 24,
                color: TOKENS.colors.inkSecondary,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                marginBottom: 12,
              }}
            >
              {sourceText}
            </div>

            <div
              style={{
                fontSize: 20,
                color: TOKENS.colors.inkMuted,
              }}
            >
              Bản ghi dữ liệu từ hệ thống radar tin tức
            </div>
          </div>
        )}
      </div>

      {/* Main Editorial Text Area */}
      <div
        style={{
          transform: `translateY(${textY}px)`,
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}
      >
        {/* Vietnamese Headline */}
        <h2
          style={{
            fontSize: 48,
            lineHeight: 1.26,
            fontWeight: 700,
            letterSpacing: '-0.025em',
            margin: 0,
            color: TOKENS.colors.ink,
          }}
        >
          {titleVi}
        </h2>

        {/* English Original Subtitle with Translated Badge */}
        {titleEn && (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 12,
            }}
          >
            <span
              style={{
                backgroundColor: TOKENS.colors.translatedBg,
                color: TOKENS.colors.translatedInk,
                fontSize: 16,
                fontWeight: 600,
                padding: '4px 10px',
                borderRadius: TOKENS.radii.sm,
                letterSpacing: '0.02em',
                flexShrink: 0,
                marginTop: 4,
              }}
            >
              Translated
            </span>
            <span
              style={{
                fontSize: 22,
                lineHeight: 1.4,
                color: TOKENS.colors.inkMuted,
                fontWeight: 400,
              }}
            >
              {titleEn}
            </span>
          </div>
        )}

        {/* Factual Summary */}
        {summary && (
          <div
            style={{
              backgroundColor: TOKENS.colors.surfaceAlt,
              border: `1px solid ${TOKENS.colors.hairFaint}`,
              borderRadius: TOKENS.radii.lg,
              padding: '24px 28px',
              fontSize: 26,
              lineHeight: 1.5,
              color: TOKENS.colors.inkSecondary,
              fontWeight: 400,
            }}
          >
            {summary}
          </div>
        )}
      </div>

      {/* Source Citation Footer */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: 20,
          color: TOKENS.colors.inkMuted,
          paddingTop: 8,
          borderTop: `1px solid ${TOKENS.colors.hairFaint}`,
        }}
      >
        <div>
          <span>Nguồn: </span>
          <span style={{ color: TOKENS.colors.inkSecondary, fontWeight: 500 }}>{sourceText}</span>
        </div>
        <div>ai-radar</div>
      </div>
    </div>
  );
};
