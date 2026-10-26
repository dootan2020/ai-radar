# Tiến độ sửa tiêu đề dịch

## Session Intent

Đưa headline biên tập đã xác minh lên mọi bề mặt; chặn bản dịch đổi nghĩa, vô hiệu cache lỗi của 17 mục audit và kiểm tra offline cùng UI.

## Files Modified

Đã sửa `site/app.js`, `site/ban-tin.js`, `site/feed.js`, `site/story.js`, `site/tra-cuu.js`, thêm `site/editorial-headline.js`; sửa `radar/editions.py`, `radar/search_index.py`, `radar/translate.py`, `radar/translation_gemini.py`, `radar/translation_pipeline.py`, thêm `radar/translation_semantics.py`; thêm/sửa test và fixture trong `tests/`. Bảng trước/sau, báo cáo và sáu screenshot ở `plans/reports/tieu-de-dich-261026/`.

## Decisions Made

`site/editorial-headline.js` chọn headline chung sau khi xác minh bản biên tập. Giữ `site/titles.js` vì extension yêu cầu file này đồng bộ nguyên byte. Validation kiểm nghĩa nguồn/đích trước glossary; chỉ các entry cache sai bị xoá. Không gọi model API, không đổi budget hoặc request limits.

## Current State

Đã xác minh đủ 17 chỉ số S, tạo bảng trước/sau bằng hàm site thật, kiểm UI 375px/1440px và lưu sáu screenshot. Full suite `python -m unittest discover -s tests` exit 0: `Ran 1325 tests in 154.929s`, `OK (skipped=8)`; JS test exit 0. Server 8099 đã dừng và file site tạm đã xoá.

## Next Steps

`git add` bị sandbox từ chối vì không thể tạo `C:/Users/Admin/ai-radar/.git/worktrees/ai-radar-wt-tieu-de/index.lock`; giữ nguyên tree chưa stage/commit để Lucy stage (dùng `git add -f` cho `plans/`) và commit trên `fix/tieu-de-dich`. Không đưa snapshot 4 MB hoặc file `site/data/` tạm vào commit.

## Round 2: extension sync

Đã bổ sung `site/editorial-headline.js` vào danh sách copy của `extension/sync-site.py`, chạy sync và giữ lại các file extension được tạo. Test sẵn có trong `test_extension_shell.py` nay kiểm các import/export module tương đối, kiểm module mới đồng bộ nguyên byte với site, và xác nhận S107 ở extension có cùng headline với site. Trước khi sửa sync, test thất bại vì thiếu `extension/editorial-headline.js`; sau sửa, 12 test extension và `node tests/verify-feed-content.mjs` đều qua.

`favicon.ico` và `apple-touch-icon.png` được sync từ site là bản Halcyon mới, phù hợp việc đổi tên sản phẩm; hai file extension hiện trùng byte với site. Port 8099 đã phục vụ `extension/newtab.html` (HTTP 200) rồi được dừng. Puppeteer không khởi chạy được Chrome/Edge headless do GPU process crash, nên chưa có bằng chứng browser console hoặc ảnh `ext-*.jpg`; cần Lucy kiểm UI trên máy/browser hoạt động. Không có bản copy dữ liệu tạm trong `site/` hoặc script browser tạm để lại.

Full suite trên phiên bản cuối: `python -m unittest discover -s tests` exit 0, `Ran 1326 tests in 165.724s`, `OK (skipped=8)`. `node tests/verify-feed-content.mjs` exit 0 (4 nhóm PASS); `node --check` cho toàn bộ `extension/*.js` exit 0; `git diff --check` exit 0. Các thay đổi vòng 2 chưa stage/commit; Lucy tiếp tục xử lý phần Git.
