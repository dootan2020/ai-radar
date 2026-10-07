// Design tokens extracted from site/tokens.css for ai-radar Calm Editorial video

export const TOKENS = {
  colors: {
    canvas: '#141318',       // Deep serene dark canvas
    surface: '#1c1b22',      // Calm elevated card surface
    surfaceAlt: '#23222b',   // Inner card / panel
    inset: '#2a2835',        // Chips, indicators
    hair: '#363445',         // Subtle hairline separator
    hairFaint: 'rgba(255, 255, 255, 0.08)',
    ink: '#f6f6f8',          // Primary text (crisp off-white)
    inkSecondary: '#b8b7c6', // Secondary text
    inkMuted: '#7f7e91',     // Tertiary / metadata text
    accent: '#4378ff',       // ai-radar signature blue
    accentSoft: 'rgba(67, 120, 255, 0.14)',
    live: '#ff4d4f',         // Alert / live
    liveSoft: 'rgba(255, 77, 79, 0.14)',
    badgeBg: '#1f1e28',
    translatedBg: '#1a2845',
    translatedInk: '#8ab4f8',
  },
  fonts: {
    main: "'Be Vietnam Pro', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    mono: "ui-monospace, 'Cascadia Mono', Consolas, monospace",
  },
  radii: {
    sm: 12,
    md: 20,
    lg: 28,
    xl: 36,
    full: 9999,
    squircle: '28%',
  },
  shadows: {
    card: '0 24px 64px rgba(0, 0, 0, 0.45), 0 4px 16px rgba(0, 0, 0, 0.3)',
    lift: '0 12px 32px rgba(0, 0, 0, 0.35)',
    subtle: '0 2px 8px rgba(0, 0, 0, 0.2)',
  }
};
