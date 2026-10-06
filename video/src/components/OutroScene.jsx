import React from 'react';
import { interpolate, useCurrentFrame, Easing } from 'remotion';
import { TOKENS } from '../tokens.js';

export const OutroScene = () => {
  const frame = useCurrentFrame();
  const easeFlow = Easing.bezier(0.16, 1, 0.3, 1);

  // Animations
  const logoScale = interpolate(frame, [0, 35], [0.88, 1], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const logoOpacity = interpolate(frame, [0, 25], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const contentY = interpolate(frame, [15, 45], [30, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const contentOpacity = interpolate(frame, [15, 40], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const pillScale = interpolate(frame, [30, 60], [0.94, 1], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const pillOpacity = interpolate(frame, [30, 50], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '120px 64px 100px 64px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
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
          width: 800,
          height: 800,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(67, 120, 255, 0.15) 0%, rgba(20, 19, 24, 0) 70%)',
          pointerEvents: 'none',
        }}
      />

      {/* Brand Icon (Squircle Apple-like) */}
      <div
        style={{
          transform: `scale(${logoScale})`,
          opacity: logoOpacity,
          width: 140,
          height: 140,
          borderRadius: TOKENS.radii.squircle,
          backgroundColor: TOKENS.colors.surface,
          border: `1px solid ${TOKENS.colors.hairFaint}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: TOKENS.shadows.card,
          marginBottom: 44,
          position: 'relative',
        }}
      >
        <div
          style={{
            fontSize: 48,
            fontWeight: 800,
            letterSpacing: '-0.04em',
            color: TOKENS.colors.ink,
          }}
        >
          ai<span style={{ color: TOKENS.colors.accent }}>·</span>r
        </div>
      </div>

      {/* Main Content */}
      <div
        style={{
          transform: `translateY(${contentY}px)`,
          opacity: contentOpacity,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 16,
          maxWidth: 820,
        }}
      >
        <h1
          style={{
            fontSize: 72,
            fontWeight: 700,
            letterSpacing: '-0.03em',
            margin: 0,
            color: TOKENS.colors.ink,
          }}
        >
          ai·radar
        </h1>

      </div>

      {/* Website Address Pill */}
      <div
        style={{
          transform: `scale(${pillScale})`,
          opacity: pillOpacity,
          backgroundColor: TOKENS.colors.surface,
          border: `1px solid rgba(67, 120, 255, 0.4)`,
          borderRadius: TOKENS.radii.full,
          padding: '20px 48px',
          boxShadow: '0 8px 32px rgba(67, 120, 255, 0.2)',
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
            fontSize: 32,
            fontWeight: 600,
            letterSpacing: '-0.02em',
            color: TOKENS.colors.ink,
            fontFamily: TOKENS.fonts.main,
          }}
        >
          dootan2020.github.io/ai-radar
        </span>
      </div>
    </div>
  );
};
