import React from 'react';
import { Easing, interpolate, useCurrentFrame } from 'remotion';
import { TOKENS } from '../tokens.js';

export const IntroScene = ({
  snapshotDate = 'Thứ Hai, 5 tháng 10, 2026',
  totalStoriesCount = 3,
  windowHours = 72,
  hook = null,
  hint = null,
  durationInFrames = 260,
}) => {
  const frame = useCurrentFrame();
  const easeFlow = Easing.bezier(0.16, 1, 0.3, 1);

  const defaultHook = 'AI vừa khiến một chiếc TV box 7 năm tuổi đắt thêm 100 đô la. Và đó chưa phải tin lạ nhất hôm nay.';
  const defaultHint = 'Ba tin AI đáng chú ý nhất, trong 45 giây.';

  const fullHook = (hook && typeof hook === 'string' && hook.trim()) ? hook.trim() : defaultHook;
  const fullHint = (hint && typeof hint === 'string' && hint.trim()) ? hint.trim() : defaultHint;

  // Split hook into sentence 1 (core provocative claim) and sentence 2 (continuation / twist)
  const sentences = fullHook.split(/(?<=[.!?])\s+/u).filter(Boolean);
  const hookSentence1 = sentences[0] || fullHook;
  const hookSentence2 = sentences.slice(1).join(' ');

  // Phase 1: Opening Brand Announcement Card (frames 0 to 40)
  const brandOpacity = interpolate(frame, [0, 8, 34, 44], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const brandTitleY = interpolate(frame, [0, 14], [46, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const brandScale = interpolate(frame, [32, 44], [1, 1.05], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Phase 2: Hook Card (frames 38 onward)
  const hookOpacity = interpolate(frame, [38, 52], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const hookY = interpolate(frame, [38, 56], [40, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Phase 3: Secondary sentence & Hint Card reveal (frames 105 onward)
  const hintOpacity = interpolate(frame, [105, 125], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const hintY = interpolate(frame, [105, 130], [30, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Exit transition into Story 1
  const exitOpacity = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        backgroundColor: TOKENS.colors.canvas,
        color: TOKENS.colors.ink,
        fontFamily: TOKENS.fonts.main,
        overflow: 'hidden',
        opacity: exitOpacity,
      }}
    >
      {/* Background ambient radial glow */}
      <div
        style={{
          position: 'absolute',
          top: 200,
          left: -150,
          width: 900,
          height: 900,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(67, 120, 255, 0.12) 0%, rgba(20, 19, 24, 0) 70%)',
          pointerEvents: 'none',
        }}
      />

      {/* PHASE 1: Bold Brand Announcement Card (0s - 1.3s) */}
      {frame <= 45 && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            padding: '120px 76px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            backgroundColor: TOKENS.colors.accent,
            color: '#ffffff',
            opacity: brandOpacity,
            transform: `scale(${brandScale})`,
            zIndex: 10,
          }}
        >
          <div style={{ fontSize: 28, fontWeight: 700, letterSpacing: '0.12em' }}>AI·RADAR</div>
          <div style={{ transform: `translateY(${brandTitleY}px)` }}>
            <div style={{ fontSize: 42, fontWeight: 600, letterSpacing: '0.08em' }}>3 TIN AI</div>
            <div style={{ fontSize: 126, lineHeight: 0.98, fontWeight: 800, letterSpacing: '-0.04em' }}>
              HÔM NAY
            </div>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 25, fontWeight: 500 }}>
            <span>{snapshotDate}</span>
            <span>{totalStoriesCount.toLocaleString('vi-VN')} tin</span>
          </div>
        </div>
      )}

      {/* PHASE 2 & 3: Editorial Hook & Hint Panel (1.3s - 8.7s) */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '130px 68px 100px 68px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          opacity: hookOpacity,
          transform: `translateY(${hookY}px)`,
        }}
      >
        {/* Top Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 12,
              backgroundColor: 'rgba(255, 77, 79, 0.14)',
              border: '1px solid rgba(255, 77, 79, 0.35)',
              padding: '10px 22px',
              borderRadius: TOKENS.radii.full,
              fontSize: 20,
              fontWeight: 700,
              color: '#ff6163',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}
          >
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                backgroundColor: '#ff4d4f',
                boxShadow: '0 0 10px rgba(255, 77, 79, 0.8)',
              }}
            />
            ĐIỂM NÓNG HÔM NAY
          </div>

          <div
            style={{
              fontSize: 22,
              fontWeight: 600,
              color: TOKENS.colors.inkMuted,
              letterSpacing: '0.04em',
            }}
          >
            AI·RADAR
          </div>
        </div>

        {/* Center Hook Typography */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
          {/* Main Provocative Sentence (Watched muted at 2.0s) */}
          <h1
            style={{
              fontSize: 56,
              lineHeight: 1.26,
              fontWeight: 800,
              letterSpacing: '-0.035em',
              color: TOKENS.colors.ink,
              margin: 0,
            }}
          >
            {hookSentence1}
          </h1>

          {/* Continuation & Hint Reveal (Watched muted at 5.0s) */}
          <div
            style={{
              opacity: hintOpacity,
              transform: `translateY(${hintY}px)`,
              display: 'flex',
              flexDirection: 'column',
              gap: 28,
            }}
          >
            {hookSentence2 && (
              <div
                style={{
                  fontSize: 34,
                  lineHeight: 1.36,
                  fontWeight: 600,
                  color: TOKENS.colors.inkSecondary,
                  letterSpacing: '-0.015em',
                }}
              >
                {hookSentence2}
              </div>
            )}

            {/* 45-Second Hint Promise Bento Card */}
            <div
              style={{
                backgroundColor: TOKENS.colors.surfaceAlt,
                border: `1px solid rgba(67, 120, 255, 0.28)`,
                borderRadius: TOKENS.radii.xl,
                padding: '30px 36px',
                display: 'flex',
                alignItems: 'center',
                gap: 22,
                boxShadow: TOKENS.shadows.card,
              }}
            >
              <div
                style={{
                  width: 60,
                  height: 60,
                  borderRadius: 20,
                  backgroundColor: TOKENS.colors.accentSoft,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 30,
                  flexShrink: 0,
                }}
              >
                ⏱️
              </div>
              <div>
                <div
                  style={{
                    fontSize: 30,
                    fontWeight: 700,
                    color: TOKENS.colors.ink,
                    letterSpacing: '-0.02em',
                  }}
                >
                  {fullHint}
                </div>
                <div
                  style={{
                    fontSize: 22,
                    fontWeight: 500,
                    color: TOKENS.colors.accent,
                    marginTop: 4,
                  }}
                >
                  Bản tin tinh gọn mỗi sáng
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer info */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: 22,
            color: TOKENS.colors.inkMuted,
            paddingTop: 16,
            borderTop: `1px solid ${TOKENS.colors.hairFaint}`,
          }}
        >
          <span>{snapshotDate}</span>
          <span>{totalStoriesCount.toLocaleString('vi-VN')} tin trong {windowHours} giờ qua</span>
        </div>
      </div>
    </div>
  );
};
