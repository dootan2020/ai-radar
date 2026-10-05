import React from 'react';
import { interpolate, useCurrentFrame, Easing } from 'remotion';
import { TOKENS } from '../tokens.js';

export const IntroScene = ({ stories, snapshotDate, totalStoriesCount = 1306 }) => {
  const frame = useCurrentFrame();

  // Easing curve: decelerate (water-like flow)
  const easeFlow = Easing.bezier(0.16, 1, 0.3, 1);

  // Entrance animations
  const headerOpacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const headerY = interpolate(frame, [0, 25], [30, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const titleOpacity = interpolate(frame, [10, 30], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const titleY = interpolate(frame, [10, 35], [40, 0], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const cardOpacity = interpolate(frame, [20, 45], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const cardScale = interpolate(frame, [20, 50], [0.96, 1], {
    easing: easeFlow,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Animated counter for total stories
  const countNumber = Math.round(
    interpolate(frame, [15, 60], [0, totalStoriesCount], {
      easing: easeFlow,
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    })
  );

  // Formatted date
  const dateFormatted = snapshotDate || 'Thứ Hai, 5 tháng 10, 2026';

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
      }}
    >
      {/* Top Header */}
      <div
        style={{
          opacity: headerOpacity,
          transform: `translateY(${headerY}px)`,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            backgroundColor: TOKENS.colors.surface,
            border: `1px solid ${TOKENS.colors.hairFaint}`,
            padding: '10px 22px',
            borderRadius: TOKENS.radii.full,
          }}
        >
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              backgroundColor: TOKENS.colors.accent,
              boxShadow: `0 0 12px ${TOKENS.colors.accent}`,
            }}
          />
          <span
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: '0.04em',
              color: TOKENS.colors.ink,
              textTransform: 'uppercase',
            }}
          >
            ai·radar · 3 TIN AI HÔM NAY
          </span>
        </div>

        <span
          style={{
            fontSize: 22,
            color: TOKENS.colors.inkMuted,
            fontWeight: 500,
          }}
        >
          {dateFormatted}
        </span>
      </div>

      {/* Hero Headline & Key Stat */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 36,
          marginTop: 20,
        }}
      >
        <div
          style={{
            opacity: titleOpacity,
            transform: `translateY(${titleY}px)`,
          }}
        >
          <div
            style={{
              fontSize: 24,
              color: TOKENS.colors.accent,
              fontWeight: 600,
              letterSpacing: '0.02em',
              marginBottom: 16,
              textTransform: 'uppercase',
            }}
          >
            Tổng hợp & Phân tích tự động
          </div>
          <h1
            style={{
              fontSize: 66,
              lineHeight: 1.18,
              fontWeight: 700,
              letterSpacing: '-0.03em',
              margin: 0,
              color: TOKENS.colors.ink,
            }}
          >
            3 câu chuyện công nghệ AI đáng chú ý nhất
          </h1>
        </div>

        {/* Bento Keynote Stat Card */}
        <div
          style={{
            opacity: cardOpacity,
            transform: `scale(${cardScale})`,
            backgroundColor: TOKENS.colors.surface,
            border: `1px solid ${TOKENS.colors.hairFaint}`,
            borderRadius: TOKENS.radii.xl,
            padding: '48px 52px',
            boxShadow: TOKENS.shadows.card,
            display: 'flex',
            alignItems: 'center',
            gap: 48,
          }}
        >
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div
              style={{
                fontSize: 96,
                fontWeight: 700,
                color: TOKENS.colors.ink,
                fontFamily: TOKENS.fonts.main,
                fontVariantNumeric: 'tabular-nums',
                letterSpacing: '-0.04em',
                lineHeight: 1,
              }}
            >
              {countNumber.toLocaleString('vi-VN')}
            </div>
            <div
              style={{
                fontSize: 22,
                color: TOKENS.colors.inkSecondary,
                marginTop: 10,
                fontWeight: 500,
              }}
            >
              tin AI được phân tích trong snapshot hôm nay
            </div>
          </div>

          <div
            style={{
              width: 1,
              height: 90,
              backgroundColor: 'rgba(255, 255, 255, 0.1)',
            }}
          />

          <div
            style={{
              flex: 1,
              fontSize: 22,
              lineHeight: 1.5,
              color: TOKENS.colors.inkMuted,
            }}
          >
            Lọc qua hàng trăm nguồn công nghệ độc lập. Chọn theo số nguồn cùng đưa tin và độ thảo luận thực tế.
          </div>
        </div>
      </div>

      {/* Preview of 3 topics */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        <div
          style={{
            fontSize: 20,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            color: TOKENS.colors.inkMuted,
            fontWeight: 600,
          }}
        >
          Mục lục tin hôm nay
        </div>

        {stories.slice(0, 3).map((st, i) => {
          const itemDelay = 40 + i * 15;
          const itemOpacity = interpolate(frame, [itemDelay, itemDelay + 20], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          const itemX = interpolate(frame, [itemDelay, itemDelay + 25], [30, 0], {
            easing: easeFlow,
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });

          const title = st.title_vi || st.title;

          return (
            <div
              key={st.id || i}
              style={{
                opacity: itemOpacity,
                transform: `translateX(${itemX}px)`,
                backgroundColor: TOKENS.colors.surfaceAlt,
                border: `1px solid ${TOKENS.colors.hairFaint}`,
                borderRadius: TOKENS.radii.lg,
                padding: '22px 28px',
                display: 'flex',
                alignItems: 'center',
                gap: 24,
              }}
            >
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: '50%',
                  backgroundColor: TOKENS.colors.accentSoft,
                  color: TOKENS.colors.accent,
                  fontSize: 20,
                  fontWeight: 700,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                0{i + 1}
              </div>

              <div
                style={{
                  flex: 1,
                  fontSize: 24,
                  fontWeight: 600,
                  color: TOKENS.colors.ink,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  lineHeight: 1.3,
                }}
              >
                {title}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
