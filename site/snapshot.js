/* The data contract the page renders (data/radar.json, schema v2). One check for the first load and for the
   3-minute poll, so a snapshot the page cannot render is refused in both places the same way.
   Pure (no DOM) so tests/test_app_streams.py can run it under Node. */
export function isSnapshotV2(j){
  return !!j && typeof j === 'object' && j.schema_version === 2 && typeof j.generated_at === 'string' && j.generated_at !== ''
    && Array.isArray(j.stories) && !!j.sections && typeof j.sections === 'object' && !Array.isArray(j.sections)
    && Array.isArray(j.sources);
}
