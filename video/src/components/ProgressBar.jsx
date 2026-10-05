import React from 'react';
import { interpolate, useCurrentFrame } from 'remotion';
import { TOKENS } from '../tokens.js';

export const ProgressBar = ({ totalFrames, scenes }) => {
  const frame = useCurrentFrame();

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 50,
        left: 64,
        right: 64,
        display: 'flex',
        gap: 12,
        zIndex: 50,
      }}
    >
      {scenes.map((scene, idx) => {
        const isPast = frame >= scene.end;
        const isCurrent = frame >= scene.start && frame < scene.end;
        
        let progress = 0;
        if (isPast) {
          progress = 1;
        } else if (isCurrent) {
          progress = interpolate(
            frame,
            [scene.start, scene.end],
            [0, 1],
            { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
          );
        }

        return (
          <div
            key={idx}
            style={{
              flex: 1,
              height: 4,
              backgroundColor: 'rgba(255, 255, 255, 0.12)',
              borderRadius: TOKENS.radii.full,
              overflow: 'hidden',
              position: 'relative',
            }}
          >
            <div
              style={{
                width: `${progress * 100}%`,
                height: '100%',
                backgroundColor: isCurrent ? TOKENS.colors.accent : 'rgba(255, 255, 255, 0.7)',
                borderRadius: TOKENS.radii.full,
                transition: 'width 0.1s linear',
              }}
            />
          </div>
        );
      })}
    </div>
  );
};
