/* The page projection and full fallback share schema v2. One check for the first load and for the
   3-minute poll, so a snapshot the page cannot render is refused in both places the same way.
   Pure (no DOM) so tests/test_app_streams.py can run it under Node. */
export function isSnapshotV2(j){
  return !!j && typeof j === 'object' && j.schema_version === 2 && typeof j.generated_at === 'string' && j.generated_at !== ''
    && Array.isArray(j.stories) && !!j.sections && typeof j.sections === 'object' && !Array.isArray(j.sections)
    && Array.isArray(j.sources);
}

const SNAPSHOT_TIMEOUT_MS = 10_000;

/* Include body consumption in the deadline: receiving headers does not mean
   the JSON has arrived. Abort releases the connection; the race also settles
   if a transport does not respond to cancellation. */
async function readSnapshot(url, options){
  const controller = new AbortController();
  let timer, cancel;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const error = Object.assign(new Error('Tải bản tin mất quá lâu. Vui lòng thử lại'), {vi: true});
      reject(error);
      controller.abort();
    }, SNAPSHOT_TIMEOUT_MS);
    cancel = () => {
      reject(options.signal.reason || new Error('Đã hủy tải bản tin'));
      controller.abort();
    };
    if (options?.signal?.aborted) cancel();
    else options?.signal?.addEventListener('abort', cancel, {once: true});
  });
  try {
    return await Promise.race([deadline, (async () => {
      const response = await fetch(url, {...options, signal: controller.signal});
      if (!response.ok) throw Object.assign(new Error(`Máy chủ trả mã HTTP ${response.status} khi tải ${url}`), {vi: true});
      const snapshot = await response.json();
      if (!isSnapshotV2(snapshot)) throw Object.assign(new Error('Tệp dữ liệu không đúng định dạng phiên bản 2'), {vi: true});
      return snapshot;
    })()]);
  } finally {
    clearTimeout(timer);
    options?.signal?.removeEventListener('abort', cancel);
  }
}

/* The compact projection contains every story. Older deployments and a failed
   optional projection write remain readable through the full snapshot. A
   maintainer's explicit ?data= fixture has no implicit fallback. */
export async function loadSnapshot(url, fallback = null, options){
  try {
    return await readSnapshot(url, options);
  } catch (error) {
    if (!fallback || options?.signal?.aborted) throw error;
    return loadSnapshot(fallback, null, options);
  }
}
