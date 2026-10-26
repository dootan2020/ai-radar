# Kiểm tra đổi tên Halcyon

## Kết quả

- `git grep -l "AIBit" -- radar site extension brand tests README.md`: **109 file trước, 0 file sau**. Trong các thư mục sản phẩm, không còn `LogosTab`; `AI Radar` chỉ còn trong định danh vận hành và test nội bộ liệt kê bên dưới.
- Site, trang tin mẫu, bản tin, new tab extension, manifest, metadata, brandbook, lockup/wordmark SVG và PNG đều dùng **Halcyon**. Tagline vẫn là **Những mẩu tin AI ngắn gọn**. Brandbook gọi `halcyonnews.com` là **tên miền dự kiến**; canonical và Pages host vẫn là `radar-ai-vn.pages.dev`.
- So sánh SVG mark/glyph sau khi bỏ nhãn tên cho thấy hình chim bói cá không đổi. Không sửa token, CSS, bố cục hoặc spacing.

## Thiết kế được giữ

Register: Brand. Scene: đọc tin AI nhanh trên điện thoại và desktop. Direction: gọn, bình tĩnh vì nội dung là các mẩu tin ngắn. Color: Committed; nền `oklch(0.962 0.004 265)`, chữ `oklch(0.210 0.009 265)`, accent `#007A55` theo token hiện có. Type: Be Vietnam Pro. Signature: chim bói cá ngọc lục bảo. Dials: giữ nguyên variance, motion và density hiện có.

## Kiểm chứng

| Lệnh | Kết quả |
| --- | --- |
| `python brand/logo/build-logo.py` | Exit 0; SVG/PNG lockup tạo lại. |
| `python brand/build-assets.py --site` | Exit 0; SVG tạo lại, publish kit. |
| `python brand/publish_kit.py` | Exit 0; 58 file đồng bộ sang `site/brand/`. |
| `python extension/sync-site.py` | Exit 0; new tab đồng bộ từ site. |
| Export PNG bằng các job trong `brand/export-png.py` | Exit 0; ImageMagick render các PNG site/Store và icon extension. Bỏ qua ảnh chụp Store theo brief. |
| `python -m unittest discover -s tests` | **Ran 1317 tests in 147.015s; OK (skipped=8)**. |
| `node --check` trên 14 file JS đã sửa; `python -m py_compile` trên các generator/script Python đã sửa | Đều exit 0. |
| `git diff --check` | Exit 0. |
| `git add -- README.md radar site extension brand tests` | Exit 1; sandbox từ chối tạo `.git/worktrees/ai-radar-wt-halcyon/index.lock`. Chưa stage hoặc commit. |

Lần chạy full đầu có một fail ở test đo kích thước request video: prompt ngắn hơn 6 byte sau khi đổi tên. Đã cập nhật mức byte kỳ vọng từ 8.313 sang 8.307, chạy test riêng exit 0 rồi chạy lại full suite exit 0.

Đã mở `/`, `/tin/_sample/`, `/ban-tin.html` và `extension/newtab.html` trong Chrome ở **375px** và **1440px**. Cả bốn trang hiển thị tên Halcyon, không tràn ngang; ở 375px, wordmark nằm **một dòng cạnh chim bói cá**. New tab khi chạy như trang tĩnh không có `chrome.storage`, nên vùng dữ liệu hiện trạng thái lỗi; phần shell, tên và bố cục đã kiểm tra. Brandbook trên `/brand/` hiển thị đúng câu nguồn gốc tên và domain dự kiến.

Port **8098** đang do Python server khác phục vụ trang `LogosTab` chiếm và không thể xác định chủ sở hữu từ command line, nên phiên này dùng **8099** cho site và **8100** cho extension; hai server này đã được dừng. Browser tương tác chụp được ảnh để xem, nhưng không có đường ghi ảnh vào report. `render-check.mjs` với Chrome rồi Edge đều exit 0 mà không tạo report hay screenshot; không có file ảnh 375/1440 để bàn giao. Lucy cần chụp và mang ảnh về cho anh Tuấn.

## Định danh nội bộ giữ nguyên

- `radar-ai-vn.pages.dev`, Pages project `radar-ai-vn`, các URL canonical, tên file `radar-*.json`, `air2:theme` và `ai-radar` trong UID/PRODID lịch: giữ đường dẫn, dữ liệu lưu và nhận dạng sự kiện ổn định.
- Tên workflow `Update AI Radar` trong README, alert matcher và test; tiêu đề cảnh báo vận hành `AI Radar` và source scorecard nội bộ: giữ khớp workflow và báo cáo vận hành, không hiển thị trên site/extension/Store.
- Chuỗi `AI radar` trong fixture kiểm tra tìm kiếm chỉ là truy vấn thử. `.github/workflows/` không thay đổi.

Lucy cần stage các file sản phẩm và test, dùng `git add -f` cho hai report trong `plans/reports/`, không stage `.skills/`, rồi commit trên `feat/rename-halcyon`.
