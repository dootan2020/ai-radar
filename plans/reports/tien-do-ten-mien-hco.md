# Progress: hco.news as the public address

## Session Intent
Halcyon answers at https://hco.news as its home address: every public address (canonical, og:url, sitemap, RSS, JSON-LD, share links, store listing website) says hco.news, and nothing that works today breaks. (Brief: plans/reports/su-kien/brief-ten-mien-hco.md in the coordinator worktree.)

## Files Modified
Changed to hco.news (public address):
- radar/site_config.py: `SITE_URL` (feeds seo.py sitemap/RSS, story_pages canonical/JSON-LD, health_probe, images UA, legacy_redirects, brand/build-assets.py).
- site/index.html, nguon.html, ban-tin.html, tra-cuu.html: canonical, og:url, og:image, twitter:image.
- site/tin/_sample/index.html: og:image.
- site/chinh-sach-rieng-tu.html lines 17, 20, 26, 27 (meta/canonical), 221, 239, 300, 318 (statements about the website itself), 244, 323 (contact link to home).
- video/render.js (caption link), video/src/components/OutroScene.jsx (outro text shown to viewers).
- brand/logo-work/hot-coral/build.py (address label in a logo mockup).
- README.md (published site link).
- extension/store/listing-en.md, listing-vi.md (website and privacy-policy URLs), SUBMIT.md (lines 22, 61, 117: website/privacy URLs), data-disclosure.md (line 55: privacy URL).
- Tests: tests/test_cloudflare_pages.py (SITE_URL now hco.news; Pages project name pinned as `radar-ai-vn`; video render/outro assert hco.news, daily-audio keeps the data host), tests/test_chrome_store.py (LIVE = hco.news; privacy page must contain hco.news and the pages.dev host permission).

Kept on radar-ai-vn.pages.dev (data endpoint the extension or another client fetches, or the extension host permission):
- extension/*.js, newtab.html, manifest.json (brief: extension unchanged), extension/sync-site.py (generates the extension from site, bakes the data host in).
- site/nen.js `LIVE` (used only when `extension` is true; website uses relative paths).
- phong_bao/cycle.py `SNAPSHOT_URL`, radar/shadow_collector.py `LIVE_FEED_URL`, video/src/daily-audio.js `liveUrl`, brand/store-shots.js request match.
- site/chinh-sach-rieng-tu.html lines 206, 212, 285, 291: they describe the extension's host permission and data host, still pages.dev.
- extension/store/SUBMIT.md lines 31, 92, 102, data-disclosure.md line 21, permissions.md line 23: host permission / contacted host.
- tests: capture-*.mjs, verify-nen.mjs, fixtures/phong-duyet/*, test_extension_shell.py, test_nen_trang.py, test_tab_moi.py (extension-side or data-host assertions).
- plans/ and old reports: history, untouched.

docs/ mentions (not edited; coordinator to update): docs/operations.md lines 181, 205, 208 (Web Analytics site name and live-check URL should become hco.news once DNS works); docs/hop-dong-ung-vien.md line 11 (snapshot URL, a data endpoint, can stay).

## Decisions Made
- Apex only, no www in the repo.
- www to apex 301: not built. `site/_redirects` (Cloudflare Pages) matches paths only, not hosts, so it cannot redirect www.hco.news. A Pages Function would run on every request. Recommend a Cloudflare Redirect Rule (www.hco.news to https://hco.news, preserving path).
- Legacy GitHub Pages redirect artifact follows SITE_URL, so old shared links now land on hco.news.
- Extension untouched; pages.dev keeps serving without redirect.

## Current State
Committed on feat/ten-mien-hco, not pushed. Targeted tests (cloudflare_pages, chrome_store, extension_shell, tab_moi, nen_trang, brand_meta, health_alert) 74 pass. Wider run: 36 test modules that touch site config, SEO, story pages, health probe, images or the domain ran 411 tests, all green. test_gemini_paid_budget and test_v2_pipeline hit a 60s timeout; neither mentions the domain, so unrelated (full `unittest discover` also hangs at near-zero CPU on this machine).
MERGE ORDER: health_probe checks SITE_URL live from CI, so do not merge until https://hco.news answers 200 (and serves /data/radar.json, /data/radar-ui.json and the assets), or the health alerts fire. Also the deploy must have happened before the probe runs on the new address.

## Next Steps
1. Coordinator: confirm hco.news DNS, then merge and deploy; check https://hco.news/ and a /tin/ page.
2. Add Cloudflare redirect rule for www.hco.news.
3. Update docs/operations.md; update the Web Analytics site name in Cloudflare.
4. Captain decides whether to later change the extension host permission (Store re-review).