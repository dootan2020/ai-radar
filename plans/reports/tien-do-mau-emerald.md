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

