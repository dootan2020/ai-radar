/* One headline choice for the reader surfaces. A verified editorial title wins;
   other cards keep their compact wording and reading views keep the full title. */
import { headlineShown as compactHeadline, shown } from './titles.js';

/* The newsroom's writer desk ("Người viết") publishes 3-4 short paragraphs under its own contract. */
export function isDeskProse(story) {
  return story?.key_points_source === 'nguoi-viet' && story.key_points_prompt_version === 'summary-vi-6-prose';
}

export function hasEditorialSummary(story) {
  const [min, max] = isDeskProse(story) ? [3, 4] : [4, 8];
  return story.editorial_headline_verified === true
    || ((story.key_points_prompt_version === 'summary-vi-5-full' || isDeskProse(story))
    && Array.isArray(story.key_points) && story.key_points.length >= min
    && story.key_points.length <= max && story.key_points.every(p => typeof p === 'string' && p.trim())
    && Array.isArray(story.summary_sources) && story.summary_sources.some(s => /^https?:\/\//i.test(String(s?.url || ''))));
}

/* The publisher's own description (the RSS dek, usually machine-translated) read as Halcyon's summary (owner,
   04/11). The label follows the text, not the story: every surface that shows the dek opens it with this mark,
   desk-written stories included; the desk's own paragraphs are never labelled. */
export const SOURCE_DESCRIPTION_LABEL = 'Mô tả từ nguồn';

export function sourceDescriptionMark(cls = 'src-desc') {
  return `<span class="${cls}">${SOURCE_DESCRIPTION_LABEL}</span> `;
}

export function headlineShown(item, full = false) {
  if (hasEditorialSummary(item) && typeof item.editorial_headline_vi === 'string' && item.editorial_headline_vi.trim()) {
    return item.editorial_headline_vi.trim();
  }
  return full ? shown(item.title, item.title_vi) : compactHeadline(item);
}
