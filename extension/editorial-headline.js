/* One headline choice for the reader surfaces. A verified editorial title wins;
   other cards keep their compact wording and reading views keep the full title. */
import { headlineShown as compactHeadline, shown } from './titles.js';

export function hasEditorialSummary(story) {
  return story.editorial_headline_verified === true || (story.key_points_prompt_version === 'summary-vi-5-full'
    && Array.isArray(story.key_points) && story.key_points.length >= 4
    && story.key_points.length <= 8 && story.key_points.every(p => typeof p === 'string' && p.trim())
    && Array.isArray(story.summary_sources) && story.summary_sources.some(s => /^https?:\/\//i.test(String(s?.url || ''))));
}

export function headlineShown(item, full = false) {
  if (hasEditorialSummary(item) && typeof item.editorial_headline_vi === 'string' && item.editorial_headline_vi.trim()) {
    return item.editorial_headline_vi.trim();
  }
  return full ? shown(item.title, item.title_vi) : compactHeadline(item);
}
