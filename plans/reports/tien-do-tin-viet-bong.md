# Tiến độ tin Việt bóng

## Session Intent

Thử thu thập tin AI có nguồn gốc Việt Nam trong shadow collector bảy ngày, không đưa lên site, và chuẩn bị phép đếm có thể kiểm tra lại.

## Files Modified

Đã sửa `data/shadow-candidates.json`, `radar/shadow_collector.py`; thêm `radar/vn_origin.py`, `scripts/review-vn-origin.py`, `tests/test_vn_origin.py`, và `plans/reports/tin-viet-bong-261026/ket-qua.md`. Snapshot local chỉ dùng để kiểm thử rồi xóa.

## Decisions Made

- Chỉ thêm RSS đã mở và parse được: VnExpress và Bộ KH&CN tại `mst.gov.vn`. FPT, Viettel, VNG/Zalo và VinAI chưa có feed hợp lệ trong các URL đã thử.
- Dùng quy tắc xác định, giữ dấu vết kết quả so khớp với feed live; mẫu đọc tay vẫn quyết định tin có đáng đọc. Script trả mã lỗi nếu thiếu artifact, source lỗi, thiếu ngày hoặc chưa so được live.

## Current State

Đã xác nhận workflow chạy mỗi giờ, collector chỉ ghi artifact giữ 14 ngày. Lần quét cuối trên code hiện tại thu 30 mục VnExpress và 30 mục Bộ KH&CN; 1 mục AI có thực thể Việt Nam, 41 mục có dấu hiệu chuyển tiếp. Toàn bộ 1329 unittest đạt, 8 skipped. `gh` không đọc được cấu hình trong sandbox, nên chưa thử tải artifact từ Actions; script đọc snapshot local đã đạt. `git add` bị từ chối khi tạo index.lock trong `.git` (`Permission denied`), nên chưa stage hay commit.

## Next Steps

Lucy cần stage các file và `git add -f plans/`, rồi commit trong branch này; không push từ phiên làm việc này. Sau bảy ngày workflow chạy trên branch mặc định, thử `gh run download` trong môi trường có quyền đọc cấu hình, đọc mẫu URL và quyết định theo ngưỡng chủ sở hữu đã duyệt.

## Vòng 2 — 26/10/2026

Đã mở rộng shadow từ hai lên bảy RSS, gồm bốn nguồn `RETIRED` vẫn không đổi ở live và VietnamNet có RSS parse được nhưng bài mới nhất từ 06/05/2025. Đã sửa nhãn nguồn gốc Việt theo chủ thể tiêu đề, địa danh sau sáp nhập và tên cũ, chức danh, tổ chức, doanh nghiệp, sự kiện; sửa múi giờ Tuổi Trẻ để 30/30 mục có ngày. Fixture 49 tiêu đề có lý do gắn nhãn đạt precision/recall 100% cho hai lớp trên chính fixture.

Scan local cuối: 210 mục, 68 AI, 11 AI gốc Việt, 133 dấu hiệu chuyển tiếp. Review theo ngày đăng 20–26/10 trả mã 0: 137 URL, 5 AI gốc Việt, 96 dấu hiệu chuyển tiếp, 0 thiếu ngày hoặc live comparison. Chi tiết tại `plans/reports/tin-viet-bong-261026/ket-qua.md`. Đây vẫn chỉ là một snapshot; cần đọc mẫu và đủ bảy ngày chạy shadow trước quyết định live. Chưa commit hoặc push.

Kiểm thử cuối: `python -m unittest discover -s tests` đạt 1336 test, 8 skipped (`Ran 1336 tests in 205.678s`, `OK (skipped=8)`).

`git add -f` lại bị sandbox từ chối khi tạo worktree `index.lock`; Lucy cần stage cả các file trong `plans/` rồi commit. Không push.
