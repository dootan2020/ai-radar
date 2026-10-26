# Kết quả sửa tiêu đề dịch

Ngày 26/10/2026. Bản kiểm tra offline trên snapshot `radar-ui-live.json` (1.754 stories); không gọi model API.

## Kết quả

Headline biên tập hợp lệ của S107 hiện đứng đầu ở danh sách, tra cứu, bản tin và trang đọc qua cùng hàm `site/editorial-headline.js`. Chỉ mục tra cứu và bản tin đều mang marker biên tập đã xác minh. Ảnh kiểm tra trình duyệt ở viewport CSS 375px và 1440px xác nhận kết quả tra cứu và trang chi tiết cùng hiển thị: “OpenAI cắt kết nối internet khi huấn luyện mô hình AI tiên phong sau loạt sự cố tấn công mạng”.

[Bảng trước/sau của đủ 17 mục](before-after.md) chạy hàm thật `site/titles.js` trên snapshot gốc và `site/editorial-headline.js` trên kết quả pipeline offline. “Sau” là tình huống không có model: cache sai bị loại, tiêu đề gốc tiếng Anh được hiển thị khi chưa có bản dịch hợp lệ. Các hàng S238, S251, S125 và S451 giữ nguyên headline vì lỗi audit nằm trong `summary_vi`; bản dịch summary sai của chúng bị loại. S103 bị loại cả `title_vi` và `summary_vi`.

## Nguyên nhân và cách sửa

`headlineShown` cũ ưu tiên `title_vi`/`headline_vi`, còn trang chi tiết tự chọn `editorial_headline_vi` khi summary đã được xác minh. Chỉ mục tra cứu trước đây bỏ trường biên tập nên cũng không thể chọn nó. Module mới thống nhất thứ tự ưu tiên; chỉ mục tra cứu mang headline và marker đã xác minh, không mang toàn bộ key points.

Pipeline cũ xác nhận tên, số, độ dài và dấu câu nhưng không kiểm nghĩa của thuật ngữ. Glossary không bao phủ các cụm audit nêu; cache Gemini, cache segment NLLB và `kept_published` có thể tái đưa bản sai vào snapshot. Guard mới so cụm nguồn với cách dịch đổi nghĩa trước khi glossary sửa chữ, xoá đúng entry Gemini/segment NLLB sai và từ chối bản đã xuất bản sai. Prompt và glossary bổ sung các thuật ngữ đã thấy; bản dịch mới phải qua validator hiện có. Khi provider không trả bản hợp lệ trong hạn mức cũ, UI dùng tiêu đề gốc.

## Bằng chứng giao diện

- [Trang chủ 375px](home-375.jpg), [danh sách S107 375px](s107-list-375.jpg), [chi tiết S107 375px](s107-detail-375.jpg).
- [Trang chủ 1440px](home-1440.jpg), [danh sách S107 1440px](s107-list-1440.jpg), [chi tiết S107 1440px](s107-detail-1440.jpg).

Trang chủ dùng snapshot copy trong `site/data/radar-ui.json`. Danh sách S107 được kiểm qua tra cứu vì mục này không nằm trên màn hình đầu trang của snapshot; chỉ mục tra cứu được tạo từ chính snapshot. Trang chi tiết tĩnh được tạo tạm từ S107 bằng `render_story_page`.

`git add` bị sandbox từ chối khi tạo `C:/Users/Admin/ai-radar/.git/worktrees/ai-radar-wt-tieu-de/index.lock`. Tree đã dọn sạch dữ liệu tạm nhưng chưa stage/commit; Lucy cần stage mã nguồn, test, báo cáo và screenshot (dùng `git add -f` cho `plans/`), rồi commit trên `fix/tieu-de-dich`.

## Test

Các test mới: `test_all_seventeen_wrong_senses_are_rejected_before_glossary`, `test_only_wrong_cache_entries_are_invalidated`, `test_offline_pipeline_drops_bad_cache_and_published_translations`, `test_glossary_repairs_audited_technical_senses`, `test_a_faithful_retranslation_can_enter_the_cache`, `test_search_projection_carries_only_verified_editorial_headline`, `test_verified_editorial_headline_is_shared_by_list_and_detail`, `test_verified_editorial_headline_survives_edition_projection`.

`python -m unittest discover -s tests` exit 0: `Ran 1325 tests in 154.929s`; `OK (skipped=8)`. `node tests/verify-feed-content.mjs` exit 0 (4 nhóm PASS). `node --check` cho các file JS đã sửa cũng exit 0.

## Giới hạn

Không có model call hoặc bản dịch mới thực tế trong kiểm tra này. Guard dùng các cặp nghĩa sai có bằng chứng trong 17 mục audit; lỗi nghĩa khác vẫn cần kiểm tra biên tập trên tin mới. Ảnh trang chi tiết offline có ảnh nguồn ngoài bị lỗi tải; headline và bố cục chữ vẫn kiểm được. Server port 8099 đã dừng; các file snapshot, chỉ mục tra cứu và trang S107 tạo tạm trong `site/` đã xoá.

## Bổ sung vòng 2: Chrome new tab

`extension/sync-site.py` đã copy thêm `editorial-headline.js`, khắc phục việc `feed.js` và `story.js` import module không có trong extension sau sync. Test extension hiện duyệt import/export ES module tương đối của toàn bộ `extension/*.js`, kiểm file đích tồn tại trong extension, và đối chiếu headline S107 của extension với site bằng module thật. Test này thất bại trước khi thêm file vào sync, sau đó qua. Sync không đổi `extension/manifest.json` hoặc live data URL.

Hai icon `favicon.ico` và `apple-touch-icon.png` thay đổi là kết quả đúng của sync sau khi site đổi thương hiệu sang Halcyon: site đã có icon mới còn extension giữ bản cũ. Hai bản extension hiện trùng byte với site và được giữ trong thay đổi.

Đã phục vụ repo tĩnh ở port 8099 và nhận HTTP 200 cho `extension/newtab.html`. Puppeteer không khởi chạy được Chrome hoặc Edge headless: GPU process thoát liên tục rồi báo `GPU process isn't usable` và launcher timeout. Vì vậy chưa thể xác nhận browser console hoặc chụp `ext-375.jpg`/`ext-1440.jpg` với snapshot; Lucy cần kiểm tra hai viewport trên browser chạy được. Server đã dừng và script browser tạm đã xoá; không tạo bản copy dữ liệu tạm.

Kiểm tra trên phiên bản cuối: `python -m unittest discover -s tests` exit 0, `Ran 1326 tests in 165.724s`, `OK (skipped=8)`. `python -m unittest discover -s tests -p test_extension_shell.py` exit 0 (12 test); `node tests/verify-feed-content.mjs` exit 0 (4 nhóm PASS); `node --check` cho toàn bộ `extension/*.js` và `git diff --check` exit 0. Chưa stage/commit; Lucy tiếp tục phần Git.
