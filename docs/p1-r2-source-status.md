# Failed-source decisions, 2026-10-02

The supplied hosted-runner evidence is run **36992692119**. It reported three
Substack HTTP 403 responses, one HTTP 200 invalid XML response, and one HTTP 404.
Those observations establish endpoint failures, not their server-side causes.
In particular, the DeepMind body was not captured here: compression, encoding,
and challenge-page explanations are unproven.

## Inventory decisions

| Source ID | Original endpoint | Decision and evidence |
| --- | --- | --- |
| `vnexpress-tech` | `https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss` | Replace with `https://vnexpress.net/rss/tin-moi-nhat.rss`, the **Tin mới nhất RSS** link in the [publisher's RSS directory](https://vnexpress.net/rss). Coordinator opened the directory and resolved this link on 2026-10-02. The latest-news feed is broader than the technology category, so retain `filter_ai=True`, Vietnamese group and VnExpress publisher identity; name now states “VnExpress AI from latest news”. The category directory still advertises the original endpoint; do not claim it moved. |
| `dwarkesh-podcast` | `https://api.substack.com/feed/podcast/69345.rss` | Disable after runner HTTP 403. [Official about page](https://www.dwarkesh.com/about) links the creator's [YouTube channel](https://www.youtube.com/c/DwarkeshPatel). Existing `dwarkesh-video` remains enabled separately; this does not restore the audio feed or justify duplicate observations. No new feed address guessed. |
| `latent-space` | `https://api.substack.com/feed/podcast/1084089.rss` | Disable after runner HTTP 403. [Official about page](https://www.latent.space/about) advertises video/audio and links a [podcast playlist](https://www.youtube.com/playlist?list=PLWEAb1SXhjlfkEF_PxzYHonU_v5LPMI8L) plus [LatentSpaceTV](https://www.youtube.com/@LatentSpaceTV). Its channel metadata/feed was not verified, so no guessed channel-ID RSS is configured. |
| `import-ai` | `https://importai.substack.com/feed` | Disable after runner HTTP 403. [Official about page](https://importai.substack.com/about) identifies Jack Clark; his [Import AI website](https://jack-clark.net/) still publishes current content, including Import AI 473 dated September 21, 2026. `https://jack-clark.net/feed/` is a research candidate, not a verified replacement: exact RSS discovery/response was unavailable here. |
| `google-deepmind` | `https://deepmind.google/blog/rss.xml` | Disable after runner HTTP 200 and `ParseError: not well-formed (invalid token): line 1, column 0`. The [official news page](https://deepmind.google/blog/) is accessible through web research, but that does not prove its RSS body is valid. Existing Google AI RSS and DeepMind YouTube collection remain separate; neither is claimed to reproduce the disabled blog feed. |

## Explicit disabled-source contract

Disabled endpoints remain in the source inventory and every generated snapshot.
Their record includes `disabled: true`, a nonempty `disabled_reason`, `ok: false`,
`count: 0`, and `error: "Disabled: " + disabled_reason`. The inventory and V2
records retain the original URL and publisher attribution. V2 adds `http_status: null` and
`http_requests: []`; `checked_at` is the snapshot's policy-evaluation time, not a
claim that the remote endpoint was contacted. Historical failure status is in
the reason and this report, never fabricated as a new HTTP observation.

The pipeline records these sources before it schedules active requests. It does
not fetch, parse, retry, or convert them into successful empty feeds. This also
applies to the legacy build and to expired collection deadlines. Cache-quality
calculations may exclude only explicit `disabled: true` records from the active
remote-source denominator. Ordinary failed sources still count against quality.

Re-enable only after a legitimate same-publisher endpoint is established and
the collector has produced actual parse/HTTP evidence on the hosted runner.
Retain this report as the dated decision history; update the inventory reason
when the evidence changes.

## Evidence boundaries and verification

- **Live web research:** official pages above were opened on 2026-10-02. The
  VnExpress alternate is advertised by the publisher. This proves provenance,
  not successful collector access or complete AI coverage; a broad latest-news
  feed may omit older AI stories sooner than a dedicated category feed.
- **Local direct network:** `radar.transport.read_url` attempts for DeepMind,
  VnExpress's directory, and podcast about pages failed before receiving HTTP
  with `URLError` / `[WinError 10013]`. No bypass, changed User-Agent, cookies,
  or browser impersonation was used. No live feed capture was fabricated.
- **Offline tests:** `tests/test_source_replacements.py` contains explicitly
  synthetic RSS. It proves filtering, timezone handling, source identity,
  disabled request suppression, and truthful snapshot metadata. It does not
  establish current publisher content or hosted-runner availability.
  All five tests pass; disabling the scheduling guard in memory produces three
  expected failures/errors, detecting requests to all four disabled endpoints.
  The full current suite passes: 181 tests in 2.179s.
- **Runner follow-up:** coordinator must inspect the branch build artifact:
  `vnexpress-tech` must show the alternate URL and genuine HTTP/parse results;
  all four disabled IDs must remain visible, failed, and have no HTTP requests.
  No full network build, production deploy, or push was performed in this slice.

Docs impact: minor; source inventory behavior and the disabled-source contract
are documented here. No unresolved owner decision. Hosted-runner verification
remains outstanding.
