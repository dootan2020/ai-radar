# ai·radar new tab

Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select this `extension/` directory. Opening a new tab shows the last saved radar snapshot immediately. The worker refreshes it on installation and every 30 minutes. Search uses Chrome's configured default search engine; shortcuts come from the browser's top sites.

Run the focused tests from the repository root with `python -m unittest discover -s tests -p "test_extension_shell.py"`. Run the full suite with `python -m unittest discover -s tests -p "test_*.py"`. Tests use the saved offline fixture and need Node.js for the rendering checks.
