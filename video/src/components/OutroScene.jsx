import React from 'react';
import { interpolate, useCurrentFrame, Easing } from 'remotion';
import { TOKENS } from '../tokens.js';

export const OutroScene = ({
  cta = null,
  durationInFrames = 193,
}) => {
  const frame = useCurrentFrame();
  const easeFlow = Easing.bezier(0.16, 1, 0.3, 1);

  const defaultCta = 'Mỗi sáng ai-radar chọn 3 tin AI đáng đọc nhất. Theo dõi kênh để cập nhật tin AI nóng nhất. Bạn quan tâm tin nào nhất? Bình luận cho mình biết nhé.';
  const fullCta = (cta && typeof cta === 'string' && cta.trim()) ? cta.trim() : defaultCta;

  // Extract question (ends with ?)
  const questionMatch = fullCta.match(/([^.!?]+\?)/u);
  const question = questionMatch ? questionMatch[1].trim() : 'Bạn quan tâm tin nào nhất?';

  // Check if follow prompt is in CTA
  const followMatch = fullCta.match(/([^.!?]*theo dõi[^.!?]*)/i);
  const followText = followMatch ? followMatch[1].trim() : 'Theo dõi kênh để cập nhật tin AI nóng nhất';

  // Animations
  const logoScale = interpolate(frame, [0, 30], [0.88, 1], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const logoOpacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const ctaY = interpolate(frame, [15, 45], [35, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const ctaOpacity = interpolate(frame, [15, 38], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const pillScale = interpolate(frame, [30, 58], [0.94, 1], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const pillOpacity = interpolate(frame, [30, 48], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '130px 64px 110px 64px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontFamily: TOKENS.fonts.main,
        color: TOKENS.colors.ink,
        textAlign: 'center',
      }}
    >
      {/* Background ambient radial glow */}
      <div
        style={{
          position: 'absolute',
          top: 300,
          width: 800,
          height: 800,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(67, 120, 255, 0.16) 0%, rgba(20, 19, 24, 0) 70%)',
          pointerEvents: 'none',
        }}
      />

      {/* Top Header: Brand Icon & Name */}
      <div
        style={{
          transform: `scale(${logoScale})`,
          opacity: logoOpacity,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 18,
        }}
      >
        <div
          style={{
            width: 110,
            height: 110,
            borderRadius: TOKENS.radii.squircle,
            backgroundColor: TOKENS.colors.surface,
            border: `1px solid ${TOKENS.colors.hairFaint}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: TOKENS.shadows.card,
            position: 'relative',
          }}
        >
          <div
            style={{
              fontSize: 40,
              fontWeight: 800,
              letterSpacing: '-0.04em',
              color: TOKENS.colors.ink,
            }}
          >
            ai<span style={{ color: TOKENS.colors.accent }}>·</span>r
          </div>
        </div>

        <h1
          style={{
            fontSize: 52,
            fontWeight: 700,
            letterSpacing: '-0.03em',
            margin: 0,
            color: TOKENS.colors.ink,
          }}
        >
          ai·radar
        </h1>
      </div>

      {/* Center Bento Call-To-Action Card (Watched muted at last 3s) */}
      <div
        style={{
          transform: `translateY(${ctaY}px)`,
          opacity: ctaOpacity,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 22,
          width: '100%',
          maxWidth: 820,
        }}
      >
        {/* Primary Action Button: Follow */}
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 16,
            backgroundColor: TOKENS.colors.accent,
            color: '#ffffff',
            padding: '20px 48px',
            borderRadius: TOKENS.radii.full,
            fontSize: 28,
            fontWeight: 700,
            letterSpacing: '0.01em',
            boxShadow: '0 10px 32px rgba(67, 120, 255, 0.42)',
          }}
        >
          <span style={{ fontSize: 28 }}>🔔</span>
          <span>{followText}</span>
        </div>

        <div
          style={{
            fontSize: 22,
            fontWeight: 500,
            color: TOKENS.colors.inkSecondary,
            letterSpacing: '0.01em',
          }}
        >
          Mỗi sáng chọn 3 tin AI đáng đọc nhất
        </div>

        {/* Interactive Community Question Card */}
        <div
          style={{
            backgroundColor: TOKENS.colors.surfaceAlt,
            border: `1px solid rgba(255, 255, 255, 0.1)`,
            borderRadius: TOKENS.radii.xl,
            padding: '28px 36px',
            display: 'flex',
            alignItems: 'center',
            gap: 20,
            width: '100%',
            boxShadow: TOKENS.shadows.card,
          }}
        >
          <div
            style={{
              width: 58,
              height: 58,
              borderRadius: '50%',
              backgroundColor: 'rgba(67, 120, 255, 0.16)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 28,
              flexShrink: 0,
            }}
          >
            💬
          </div>
          <div style={{ textAlign: 'left', flex: 1 }}>
            <div
              style={{
                fontSize: 26,
                fontWeight: 700,
                color: TOKENS.colors.ink,
                lineHeight: 1.32,
                letterSpacing: '-0.02em',
              }}
            >
              {question}
            </div>
            <div
              style={{
                fontSize: 20,
                color: TOKENS.colors.accent,
                fontWeight: 600,
                marginTop: 4,
              }}
            >
              Bình luận cho mình biết 👇
            </div>
          </div>
        </div>
      </div>

      {/* Website Address Pill */}
      <div
        style={{
          transform: `scale(${pillScale})`,
          opacity: pillOpacity,
          backgroundColor: TOKENS.colors.surface,
          border: `1px solid rgba(67, 120, 255, 0.35)`,
          borderRadius: TOKENS.radii.full,
          padding: '18px 44px',
          boxShadow: '0 8px 32px rgba(67, 120, 255, 0.18)',
          display: 'flex',
          alignItems: 'center',
          gap: 16,
        }}
      >
        <div
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            backgroundColor: TOKENS.colors.accent,
          }}
        />
        <span
          style={{
            fontSize: 28,
            fontWeight: 600,
            letterSpacing: '-0.02em',
            color: TOKENS.colors.ink,
            fontFamily: TOKENS.fonts.main,
          }}
        >
          radar-ai-vn.pages.dev
        </span>
      </div>
    </div>
  );
};
