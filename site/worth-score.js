/* Shared fallback scoring math; mirrors radar/worth.py for snapshots without pipeline scores. */
export const WORTH = {
  attention: 35, attentionFull: 60,
  breadth: 35, breadthFull: 4,
  freshness: 15, halfLifeH: 24,
  firstHand: 1.3,
  hotLabel: 20,
  picksMax: 5,
  sameEvent: 0.34,
};

export function fallbackWorth(st, generatedAt, hot, n, firstHand) {
  const coverageTimes = (st.coverage || []).map(c => Date.parse(c && c.published_at)).filter(Number.isFinite);
  const publishedAt = coverageTimes.length ? Math.max(...coverageTimes) : Date.parse(st.published_at);
  const ageH = Number.isFinite(publishedAt) ? Math.max(0, (generatedAt - publishedAt) / 36e5) : null;
  const recency = ageH == null ? 1 : Math.pow(0.5, ageH / WORTH.halfLifeH);
  const parts = {
    attention: WORTH.attention * Math.min(1, hot / WORTH.attentionFull) * recency,
    breadth: WORTH.breadth * Math.min(1, Math.max(0, n - 1) / (WORTH.breadthFull - 1)) * recency,
    freshness: ageH == null ? 0 : WORTH.freshness * recency,
  };
  if (!(st.hot_signals && st.hot_signals.measurement) || hot <= 0) delete parts.attention;
  if (n < 2) delete parts.breadth;
  if (ageH == null) delete parts.freshness;
  const base = WORTH.attention * Math.min(1, hot / WORTH.attentionFull)
    + WORTH.breadth * Math.min(1, Math.max(0, n - 1) / (WORTH.breadthFull - 1))
    + (ageH == null ? 0 : WORTH.freshness);
  return {
    score: base * recency * (firstHand ? WORTH.firstHand : 1),
    parts: Object.fromEntries(Object.entries(parts).map(([key, value]) => [key, Math.round(value * 100) / 100])),
  };
}
