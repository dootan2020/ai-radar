/* The page projection and full fallback share schema v2. One check for the first load and for the
   3-minute poll, so a snapshot the page cannot render is refused in both places the same way.
   Pure (no DOM) so tests/test_app_streams.py can run it under Node. */
export function isSnapshotV2(j){
  return !!j && typeof j === 'object' && j.schema_version === 2 && typeof j.generated_at === 'string' && j.generated_at !== ''
    && Array.isArray(j.stories) && !!j.sections && typeof j.sections === 'object' && !Array.isArray(j.sections)
    && Array.isArray(j.sources);
}

/* The compact projection contains every story. Older deployments and a failed
   optional projection write remain readable through the full snapshot. A
   maintainer's explicit ?data= fixture has no implicit fallback. */
export async function loadSnapshot(url, fallback = null, options){
  try {
    const response = await fetch(url, options);
    if (!response.ok) throw Object.assign(new Error(`Máy chủ trả mã HTTP ${response.status} khi tải ${url}`), {vi: true});
    const snapshot = await response.json();
    if (!isSnapshotV2(snapshot)) throw Object.assign(new Error('Tệp dữ liệu không đúng định dạng phiên bản 2'), {vi: true});
    return snapshot;
  } catch (error) {
    if (!fallback) throw error;
    return loadSnapshot(fallback, null, options);
  }
}
