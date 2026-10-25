# ai·radar new tab

Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select this `extension/` directory. Open a new tab to see the ai·radar homepage and the **Tìm trên web** field. The field uses Chrome's configured default search engine.

The background worker saves `data/radar-window.json` in `chrome.storage.local` on install, startup, and every 30 minutes. The page draws that saved snapshot first. When online, it loads `data/radar-ui.json` after the first paint; when offline, the saved stories remain readable. On a first install without a saved snapshot, the homepage's empty state appears until the first worker refresh completes. Reader preferences are stored under the extension origin and start empty.

The homepage files under `site/` are the source. After a site UI change, run `python extension/sync-site.py` from the repository root. The script copies the homepage's CSS, modules, fonts, image manifest, and editor picks, then generates `extension/newtab.html` and `extension/feed.js` with the MV3 data and link adaptations. Review the generated diff and run the tests; the extension-specific search and cache files remain separate. The script fails if an expected source anchor changes, so a site change cannot silently skip an adaptation.

Run focused tests with `python -m unittest discover -s tests -p "test_extension_shell.py"` and the full suite with `python -m unittest discover -s tests -p "test_*.py"`. The visual walk uses `node tests/fixtures/extension-walk.js`; it requires Puppeteer and local Chrome.
