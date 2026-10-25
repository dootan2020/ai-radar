# Tiến độ màu emerald

## Session Intent

Đưa màu thao tác của LogosTab về cùng hệ emerald với chim bói cá, giảm các điểm nhấn không mang hành động, giữ chip Translated màu Google và xác minh contrast.

## Files Modified

Token và CSS site/extension, bốn SVG social/OG trong brand kit và bản public, hai PNG xuất từ SVG, `brand/build-assets.py`, sổ tay thương hiệu cùng bản phát hành đồng bộ. Danh sách và số đo ở [báo cáo](mau-emerald-261025/ket-qua.md).

## Decisions Made

- Chữ/link sáng dùng `#007A55`; `#007D56` gần sổ tay cũ hơn nhưng ít dư địa contrast hơn trên canvas. Tile logo giữ `#00B377`; dark dùng `#00D68F`.
- Trạng thái “ok” dùng mực trung tính trên nền fill. Dấu “Mới”, countdown, nhãn phân loại và eyebrow arena bớt dùng accent.
- Thang sáng tối và hue xám 265 không đổi; không đổi bố cục, spacing hay kiểu chữ. Google Translate giữ bốn token `--gt-blue-*`.

## Current State

Các token source/brand/public/extension giống byte; 1.317 unittest pass (8 skip), test brand và extension sau đồng bộ đều pass. Script contrast pass. Browser xem được site nhưng Chrome/Edge headless lỗi GPU, browser UI không áp dụng viewport yêu cầu, và giao thức `file:` cho extension bị chặn; chưa có ảnh 375/1440 hợp lệ.

## Next Steps

Lucy stage/commit trong checkout có quyền ghi Git index (`plans/` cần `git add -f`; không stage `.skills/`). Lucy chụp 16 trạng thái trên browser có viewport hoạt động và cho reviewer thứ hai xem cùng ảnh.


## Round 2 update

- Trả `--color-ok` về xanh lá hue 145, chroma thấp, khác emerald brand; thêm wash sáng/tối và ghi các phép đo mới vào bảng Round 2 của báo cáo kết quả.
- `.ed-link` là CTA emerald trên header home, với `--color-on-accent`; hover tối hơn. Focus giữ nguyên, selected tab vẫn đen, chip Translated không đổi.
- Chạy ba bước đồng bộ đều exit 0; bốn `tokens.css` giống byte. Contrast script exit 0; full unittest: 1.317 test, 6 skip, exit 0; `git diff --check` exit 0.
- Mở home và bản tin ở sáng/tối. Home hiển thị CTA emerald; bản tin local còn “Đang tải”. Browser capture không hỗ trợ kích thước 375/1440 hay ghi screenshot ra report; URL `javascript:` để đọc computed DOM bị browser policy chặn. Giá trị DOM cho `.lab.dung-ngay`, `.dot.ok`, `.ed-link` và ảnh `v2-*.png` còn thiếu.
- Giữ nguyên các thay đổi đã có từ trước trong `brand/assets/`, `site/brand/assets/`, `extension/arena.js`, `extension/feed.js`, `extension/newtab.html` và các file ngoài phạm vi. Lucy cần capture đúng viewport, lấy computed style từ DOM và review ảnh ở lượt sau.
