# Official product updates

The v2 build adds `tool_updates` and `tool_updates_meta` alongside the existing
story and repository sections. They answer which official product entries changed
within the last seven days. Product releases remain separate from news clustering
and hot ranking. Existing snapshots without these optional fields stay valid.

## Source ownership

[The catalog](../radar/tool_sources.py) owns exact endpoints and product identities.

| Product | Official evidence | Scope |
| --- | --- | --- |
| Claude Code | Publisher-maintained Atom `feed.xml` and raw `CHANGELOG.md` | Feed dates plus version-matched changelog detail; repeated versions become one row. |
| Codex CLI | Official Codex changelog | The GitHub release is the primary link when the official changelog supplies it. |
| Codex desktop and general Codex | Official developer changelog, currently redirecting to ChatGPT Learn | Publisher `data-products` and `data-codex-topics` metadata identifies Codex entries. Unrelated ChatGPT entries are excluded. |

These are public, credential-free endpoints. The existing transport's honest
user agent, response-size limit, connection budget and shared build deadline
apply. Each endpoint has its own `sources` status and HTTP evidence. A failed
endpoint does not erase successful tool observations. Tool endpoints retain their
source diagnostics but do not participate in the news publication quorum; mirrors are evidence for one
product change, never extra independent corroboration in news ranking.

GitHub's generated releases Atom endpoints, Gemini CLI, Ollama, Cursor, GitHub
Copilot/VS Code and Antigravity are not configured here: their exact responses
still need captured parser evidence. The publisher-maintained Claude Atom and
official Codex HTML provide verified alternatives. Missing tools do not imply
no product changes; the inventory favors proven source coverage over breadth.

## Consumer contract

Each `tool_updates` row contains:

| Field | Meaning |
| --- | --- |
| `id` | Stable hash of product and version, or product and anchored official entry URL when no product version exists. |
| `product`, `product_name` | Stable product identity and display name. |
| `title`, `version` | Original entry title and nullable product version. A model version mentioned by a general announcement is not the product version. |
| `url` | Exact release entry or observed official changelog anchor. |
| `channel` | `stable` for selected entries. |
| `published_at` | Exact source publication timestamp with timezone, otherwise null. |
| `updated_at` | Exact Atom modification timestamp when supplied, otherwise null. |
| `published_date` | Source publication date, including date-only entries; null when only a modification time is known. |
| `time_precision` | `exact` or `date`; unknown dates cannot enter the selected window. |
| `time_basis` | `published` for selected releases; parsed modification evidence alone is never selected. |
| `sources` | All source IDs merged for this product/version. |
| `highlights` | Up to three original attributed excerpts, each with `text`, `source`, `source_name`, `url`, and `truncated`. |

An Atom entry containing only `updated` retains `published_at: null` and
`time_basis: "updated"` as collection evidence, but is excluded from selected
releases as `unknown_date`. Original publication evidence is required:
editing an old release does not make it a new release this week. A date-only entry
does not acquire midnight or a timezone. The partial date at the lower window
boundary is excluded because the whole day cannot be shown to fit the window.
Undated Claude Markdown sections never establish freshness alone; only a dated
observation with the same product and version can supply it.
Markdown evidence is admitted only for plain version headings whose GitHub-style
anchor is unique across headings of all levels. Complex headings, fenced-code,
setext-heading, HTML/comment, blockquote and nested-heading documents are conservatively excluded until
their rendered anchors can be verified. Publication validation also checks each
Markdown quote URL against its merged release version.

The source text remains original. HTML entities are decoded and whitespace is
normalized to rendered prose; Markdown inline formatting is retained. Excerpts
are exact prefixes of that text, at most 240 characters, cut at a word boundary.
`truncated` indicates omitted remainder without inserting fabricated punctuation
into the quote. A consumer should render them as text, never HTML, and label any
later translation separately. A quote from the official changelog links to that
entry even when the row's primary URL is the GitHub release.

## Selection and failure evidence

[Grouping and selection](../radar/tool_updates.py) merges all current observations
before selecting the rolling seven-day window. Stable entries with usable quotes
are ordered newest first. Within a release, security/breaking/deprecation text is
prioritized, followed by feature/support text and then other changes; source order
breaks ties. This is a transparent keyword heuristic, not a claim of measured
importance. No previous snapshot is reused as fresh evidence.

`tool_updates_meta` records `window_days`, `window_start`, `window_end`, the
selection identifier and explanation, date policy, and per-product `sources`,
`successful_sources`, `failed_sources`, and selected `count`. `excluded` counts
merged prerelease, unknown-date, outside-window and no-highlight entries. These
are collection counts; malformed-row filtering does not retroactively rewrite
source counts. Successful empty sources remain distinguishable from failures.
Malformed Codex entries are skipped individually; `dropped_entries` appears on
the source record and in metadata, alongside a readable source diagnostic. If no
Codex entry parses, the source fails explicitly. Metadata `ok` and `error` describe
grouping/selection health, separately from endpoint success. A grouping exception
produces empty tool rows plus `ok: false` and its error; news collection continues.

[Publication validation](../radar/tool_validation.py) checks identities, official
entry URLs, quote attribution, dates and precision. Malformed tool rows are
filtered and counted under `dropped_projection_rows.tool_updates` when the array
exists. Broken containers or metadata reject the candidate. The legacy five-key
drop-count object stays unchanged for snapshots without `tool_updates`. Existing
nonempty-story, two-thirds non-tool active-source quorum and freshness gates still apply.

## Verification boundary

Run `python -m unittest discover -s tests`. [Tool tests](../tests/test_tool_updates.py)
label constructed edge cases separately from authentic publisher captures.
[Fixture provenance](../tests/fixtures/tool_updates/) distinguishes browser DOM
fragments, original text exposed by GitHub's code view, and raw HTTP responses.
Browser captures prove parser structure, not the scheduled runner's transport.
Blocked raw feed requests must remain explicit in the final verification report;
synthetic Atom tests do not establish current endpoint health.
