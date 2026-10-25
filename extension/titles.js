/* Machine-translated headlines and de-duplicated coverage, kept free of the DOM so Node can test them.
   The snapshot carries title_vi / description_vi next to the original; a missing or empty translation
   means the original is shown alone, exactly as before translation existed. */

const viOf = (orig, vi) => (typeof vi === 'string' && vi.trim() && vi.trim() !== String(orig).trim()) ? vi.trim() : null;

/* The line a reader reads first: the Vietnamese when there is one, otherwise the original. */
export const shown = (orig, vi) => viOf(orig, vi) || String(orig == null ? '' : orig);

/* Compact listing text follows the full title's language eligibility. Attribution and
   opened stories still use the full fields, never a shortened translation as evidence. */
export function headlineShown(item) {
  const translated = viOf(item.title, item.title_vi);
  const headline = translated ? item.headline_vi : item.headline;
  return (typeof headline === 'string' && headline.trim()) || translated || String(item.title || '');
}

/* The small line under a translated title: the original, labelled as a machine translation. Empty when untranslated.
   The chip reads "Translated", in Google Translate's colours (owner, 03/10 17:49); a screen reader hears the
   Vietnamese sentence beside it instead. */
export function origLine(orig, vi, esc, cls = 'orig'){
  if (!viOf(orig, vi)) return '';
  return `<span class="${cls}" lang="en"><span class="mt" aria-hidden="true" title="Bản dịch máy; dòng này là tiêu đề gốc">Translated</span><span class="sr" lang="vi">Bản dịch máy. Tiêu đề gốc: </span>${esc(String(orig))}</span>`;
}

/* One entry per publisher: two feeds of the same site (Hacker News front page and its AI search) report the
   same discussion, and a list that names a source twice reads as two sources. The entry with the most
   measured numbers wins; ties keep the earlier one. */
export function uniqCoverage(coverage, nameOf){
  const best = new Map();
  (coverage || []).forEach((c, i) => {
    if (!c) return;
    const key = String(c.publisher || nameOf(c.source) || c.source || i).toLowerCase();
    const score = c.metrics ? Object.values(c.metrics).filter(v => typeof v === 'number' && Number.isFinite(v)).length : 0;
    const prev = best.get(key);
    if (!prev || score > prev.score) best.set(key, {c, i: prev ? prev.i : i, score});
  });
  return [...best.values()].sort((a, b) => a.i - b.i).map(x => x.c);
}
