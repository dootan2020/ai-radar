# Tiến độ: đưa dòng tin phẳng lên trang chủ

## Session Intent
Anh Tuấn duyệt (05/10 ~01:30): trang dòng tin phẳng (`site/feed.html`) thay trang chủ bento. Nhánh `pipeline-dang-doc`:
1. Merge `origin/main` (10 PR: tra cứu 7 ngày, link Bản tin sáng, dấu mới/đã xem/bỏ qua, nguồn tiếng Việt, gộp tin đa nguồn, giữ tin 7 ngày, dịch...);
2. Dòng tin phẳng trở thành trang gốc `site/index.html`, bento cũ giữ ở `site/bento.html` để quay lui khi cần, không liên kết từ điều hướng;
3. Mang toàn bộ tính năng người đọc của trang chủ main sang feed mà không làm mất diện mạo đã duyệt của dòng tin phẳng;
4. Hoàn tất kiểm thử tự động, kiểm tra hiển thị responsive (375px và 1440px), đối chiếu checklist thiết kế, lập báo cáo chi tiết.
Không push, không đụng `main`, không mở PR, không thêm phụ thuộc mới, không sửa `.github/workflows/**`.

## Files Modified
- `radar/assembly.py`, `radar/pipeline.py`: giải xung đột merge giữa retention 7 ngày (main) và chấm điểm worth + tìm ảnh + ảnh AI (nhánh).
- `site/index.html`: trang chủ dòng tin phẳng tại trang gốc, tích hợp đầy đủ CSP, SEO/OG meta, preload `radar-ui.json`, thanh tiêu đề dính gồm nhãn thương hiệu, bộ lọc danh mục, link Bản tin sáng (`ban-tin.html`), link Tra cứu (`tra-cuu.html`), nút đổi giao diện sáng/tối, khối thông báo tin mới `#moi`, lưới tin feed-grid, bảng nguồn và hộp phím tắt.
- `site/bento.html`: bản sao lưu toàn vẹn của trang chủ bento cũ, thêm thẻ `noindex` và thẻ canonical trỏ về trang gốc `./` để sẵn sàng quay lui tức thì khi cần.
- `site/feed.html`: trang chuyển hướng tĩnh tức thì về trang gốc `./`, đánh dấu `noindex`.
- `site/feed.js`: hỗ trợ đầy đủ khoá localStorage dùng chung của main (`air2:lastSeen`, `air2:read`, `air2:skipped`, `air2:saved`, `air2:theme`), logic đánh dấu tin mới/đã xem/bỏ qua, đồng bộ bộ lọc, điều hướng bàn phím (`?`, `j`, `k`, `o`, `s`, `c`), lưu bài viết, thông báo trực tiếp khi có cập nhật nền.
- `site/feed.css`: bổ sung kiểu cho thanh điều hướng responsive (hai dòng trên điện thoại, kích thước nút bấm tối thiểu 44px theo chuẩn chạm), khối fallback tĩnh không có JS, thẻ chỉ báo trạng thái tin mới/đã xem/bỏ qua.
- `radar/health_probe.py`: mở rộng bộ nhận diện trang chủ để chấp nhận cả cấu trúc feed (`feed-grid`, `feed.js`, `feed.css`) lẫn bento cũ (`board`, `app.js`, `styles.css`).
- `radar/site_payload.py`: cập nhật hàm `write_site_snapshot` để cập nhật thumbnail preload cho cả `index.html` và `bento.html`.
- `tests/test_health_probe.py`: bổ sung kiểm thử xác minh cả bố cục feed hiện tại và bento quay lui đều vượt qua health probe.
- `tests/test_initial_paint.py`: cập nhật kiểm thử preload ảnh đầu trang cho `bento.html` và preload `radar-ui.json` cho `index.html`.
- `tests/test_page_head.py`: điều chỉnh kiểm tra CSP, stylesheet và liên kết bento sang `bento.html`.
- `tests/test_reader_loading.py`: kiểm tra fallback tĩnh cho cả bento và feed khi mất JavaScript.
- `tests/test_trang_chu.py`: tạo mới bộ 8 bài test chuyên biệt kiểm tra toàn diện trang chủ feed (`site/index.html`): CSP bọc kín, SHA256 script inline đổi theme, preload, thẻ SEO/OG, sự hiện diện của các tính năng mang sang và cờ `noindex` của trang quay lui/chuyển hướng.

## Decisions Made
1. **Merge origin/main (commit `765def2`):**
   - Giữ nguyên cấu trúc pipeline của cả hai bên: retention của main chạy trước, kế thừa tin 7 ngày, sau đó pipeline chạy chấm điểm worth và tìm nạp ảnh/ảnh AI trên danh sách tin đã giữ.
   - Hàm `finish()` khi không truyền fetcher/transport sẽ không tự ý gọi mạng, tương thích hoàn toàn với test retention của main.
2. **Quản lý trang và đường dẫn quay lui:**
   - Trang gốc `site/index.html` là dòng tin phẳng được duyệt.
   - `site/bento.html` lưu trang bento cũ, gán `noindex`, canonical trỏ về `https://dootan2020.github.io/ai-radar/`. Nếu muốn quay lui, chỉ cần đổi tên tệp mà không ảnh hưởng SEO.
   - `site/feed.html` là trang chuyển hướng meta-refresh 0s về `./` có `noindex`, đảm bảo bạn đọc mở bookmark cũ vẫn tự động chuyển về trang chủ mới.
3. **Bố cục tính năng của main trên giao diện feed:**
   - Thanh trên dính (sticky header): Logo ai·radar bên trái dẫn về đầu trang; cụm nút bộ lọc danh mục ở giữa; cụm tiện ích bên phải gồm liên kết "Bản tin sáng" (`ban-tin.html`), liên kết "Tra cứu" (`tra-cuu.html`, tự thu gọn thành biểu tượng kính lúp trên mobile màn hình hẹp), và nút gạt theme Sáng/Tối.
   - Các nút tiện ích dùng phong cách pill/chip phẳng tối giản của feed (`color-surface-2`), không mang phong cách bento khung viền cũ.
   - Thẻ tin hiển thị dấu trạng thái đọc: chấm xanh tròn ở đầu hàng thông tin nguồn biểu thị tin mới (`.is-new`), làm mờ nhẹ với tin đã đọc (`.is-seen`), và viền nét đứt với tin đã bỏ qua (`.is-skipped`).
   - Khối thông báo tin mới `#moi`: hiển thị số tin mới trong 24 giờ qua với liên kết cuộn nhanh tới tin mới đầu tiên và nút "Đánh dấu đã xem".
   - Tương tác thẻ tin: tích hợp nút Đánh dấu lưu trữ (`data-act="save"`) và nút Sao chép liên kết (`data-act="copy"`).
4. **Bảo mật và SEO:**
   - CSP: giữ nguyên chính sách đóng chặt của main (`default-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `font-src 'self'`, `form-action 'none'`). Mở `img-src https:` để nạp ảnh đại diện từ các nguồn tin gốc đã duyệt. Script inline đổi theme được bảo vệ bằng giá trị sha256 hash chuẩn xác.
   - SEO: Đầy đủ thẻ canonical, OpenGraph (title, site_name, description, image, url), Twitter Card và sitemap trỏ chuẩn về root.

## Current State
- Toàn bộ 856 bài kiểm thử đơn vị (`python -m unittest discover -s tests`) vượt qua 100% (856 OK, 1 skip).
- Máy chủ cục bộ dựng thử tại `http://localhost:8790` chạy trơn tru, không có lỗi runtime.
- Kiểm tra hiển thị responsive tại viewport 375x667 và 1440x900 qua agent-browser cho kết quả 0px horizontal overflow (`overflow: false`).
- Các tính năng tương tác được kiểm thử trực tiếp trên trình duyệt thành công: chuyển đổi theme, lọc theo chuyên mục (từ 41 tin xuống 8 tin), phục hồi lọc, đánh dấu đã xem, lưu trữ tin vào `air2:saved`.
- Đã hoàn thành đối chiếu thiết kế theo `checklist-design` (`web-app-feed.md`).

## Next Steps
- Lập báo cáo tổng kết chi tiết `plans/reports/len-trang-chu-report.md` theo đầy đủ yêu cầu (giải quyết xung đột, chuyển đổi tệp, danh mục tính năng, kết quả kiểm thử, đối chiếu checklist thiết kế, lập luận thiết kế giao diện, kết thúc bằng `STATUS: DONE`).
- Dọn dẹp tệp thử nghiệm tạm (`scratch/`).
- Commit toàn bộ các thay đổi trên nhánh `pipeline-dang-doc`.
