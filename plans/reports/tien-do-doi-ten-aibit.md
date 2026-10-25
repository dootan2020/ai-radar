# Tiến độ đổi tên AIBit News

## Mục tiêu và quyết định

Đổi tên sản phẩm từ LogosTab sang **AIBit News**, tagline **Những mẩu tin AI ngắn gọn** theo quyết định của anh Tuấn ngày 26/10. Giữ logo chim bói cá, màu emerald, tokens, layout, spacing, canonical URL, Pages project, workflow, secrets và tên tệp dữ liệu. `aibitnews.com` chỉ được nêu trong brandbook là tên miền dự kiến.

Round 1 đã đổi các bề mặt trong `site/`, `extension/`, `brand/`, `tests/` và `README.md`. Round 2 được mở rộng sang các chuỗi reader-facing do `radar/` tạo ra: trang tin, metadata, redirect, health probe và prompt video. Không sửa `.github/workflows/`.

## Công việc đã làm

- Đổi 103 tệp ban đầu chứa LogosTab ở các bề mặt round 1; chuyển brandbook nguồn sang `brand/aibit-news/`, xuất lại SVG, PNG, kit và đồng bộ extension.
- Đổi tên trong `radar/story_page_template.html`, `radar/story_pages.py`, `radar/legacy_redirects.py`, `radar/health_probe.py`, `radar/video_script.py` và `radar/summary-system-prompt.txt`. Cập nhật assertion số byte của request video sau khi prompt đổi tên.
- Chỉnh `brand/store-shots.js` để đọc `site/data/radar-window.json` và dựng new tab từ snapshot local. Snapshot thật trong `tests/fixtures/radar-window-sample.json` được sao chép tạm vào `site/data/` để thử, rồi dọn khỏi worktree.
- Các script `brand/logo/build-logo.py`, `brand/build-assets.py --site`, `brand/publish_kit.py`, `extension/sync-site.py` và `brand/export-png.py` đều exit 0. Ảnh Store icon và promo được tạo lại; các comparison sheet tạm của script logo đã được dọn, kit có 58 file publishable như trước.

## Bằng chứng

- `git grep -n -i -E "LogosTab|AI Radar" -- radar/ site/ extension/ brand/ tests/ README.md`: 32 dòng trước round 2, 15 dòng sau. `LogosTab`: 0 dòng. Cả 15 dòng còn lại là tên workflow `Update AI Radar`, thông báo lỗi nội bộ, mô tả/scorecard nội bộ hoặc fixture/test; không có chuỗi reader-facing. Host `radar-ai-vn.pages.dev`, đường dẫn dữ liệu, khóa lưu theme và định danh lịch giữ nguyên.
- `python -m unittest discover -s tests`: **Ran 1317 tests in 156.936s; OK (skipped=8)**. Trước đó test budget video được cập nhật theo prompt mới; một lần full suite khác lỗi do tệp preview tạm, đã dọn và chạy lại xanh.
- `node --check brand/store-shots.js`, `python -m py_compile` các module sửa và `git diff --check`: exit 0.
- Trình duyệt đã mở `/`, `/tin/_sample/` và `extension/newtab.html` ở 375px và 1440px. Wordmark nằm một dòng trong header tại 375px; không có tràn ngang. Ảnh chụp trong trình duyệt không xuất được vào report.

## Còn vướng

- Hai ảnh `brand/assets/store/new-tab-light.png` và `new-tab-dark.png` vẫn chưa tạo lại. Puppeteer timeout khi khởi động Chrome và Edge headless, kể cả với snapshot local. Ảnh cũ chứa tên cũ tiếp tục được gỡ để tránh phát hành nhầm. Cần chạy `node brand/store-shots.js` trong môi trường có headless browser hoạt động và `site/data/radar-window.json` đã được tạo.
- Port 8098 đang thuộc một tiến trình khác, nên phiên này dùng 8099 cho site và 8100 cho extension. Chỉ dừng các server do phiên này mở.
- `git add -- README.md brand extension radar site tests` bị sandbox từ chối tạo `.git/worktrees/ai-radar-wt-aibit/index.lock` (exit 128). Chưa stage/commit; tree đã sẵn để Lucy thực hiện, không stage `.skills/` và cần `git add -f` cho hai report trong `plans/`.

Chi tiết của round 1 và round 2: [kiểm tra đổi tên](doi-ten-aibit-261026/kiem-tra-doi-ten.md).
