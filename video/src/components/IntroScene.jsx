import React from 'react';
import { Easing, interpolate, useCurrentFrame } from 'remotion';
import { TOKENS } from '../tokens.js';

export const IntroScene = ({snapshotDate, totalStoriesCount = 3}) => {
  const frame = useCurrentFrame();
  const titleY = interpolate(frame, [0, 14], [46, 0], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = interpolate(frame, [0, 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div style={{
      position: 'absolute', inset: 0, padding: '120px 76px',
      display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      backgroundColor: TOKENS.colors.accent, color: '#ffffff',
      fontFamily: TOKENS.fonts.main,
    }}>
      <div style={{opacity, fontSize: 28, fontWeight: 700, letterSpacing: '0.12em'}}>AI·RADAR</div>
      <div style={{opacity, transform: `translateY(${titleY}px)`}}>
        <div style={{fontSize: 42, fontWeight: 600, letterSpacing: '0.08em'}}>3 TIN AI</div>
        <div style={{fontSize: 126, lineHeight: 0.98, fontWeight: 800, letterSpacing: '-0.04em'}}>
          HÔM NAY
        </div>
      </div>
      <div style={{opacity, display: 'flex', justifyContent: 'space-between', fontSize: 25, fontWeight: 500}}>
        <span>{snapshotDate}</span>
        <span>{totalStoriesCount.toLocaleString('vi-VN')} tin</span>
      </div>
    </div>
  );
};
