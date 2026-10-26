# Tiến độ phòng báo pha 0

## Session Intent

Dựng registry năng lực, bước dò công cụ, năm bàn duyệt tin chạy tay trên 150 story, và phép chấm với bộ nhãn pha A. Không chạy boat hoặc mạng trong sandbox.

## Files Modified

- `phong_bao/`: registry, discovery, batch runner, newsroom, CLI, evaluation.
- `phong-bao/cong-cu/`: chín profile công cụ có sẵn.
- `tests/fixtures/phong-bao/`: input 150 story không chứa nhãn và fixture offline ba story.
- `tests/test_phong_bao.py`: kiểm registry, job, thuyền độc lập, fail closed và evaluation.
- `plans/reports/phong-duyet/ket-qua-pha-0.md`: báo cáo cuối phiên, đang hoàn thiện.

## Decisions Made

- Boat agent xử lý tối đa tám story và 20.000 ký tự payload mỗi batch. Bài nguồn được giới hạn 3.200 ký tự trong prompt; fixture chỉ ước lượng token theo ký tự, còn CLI có usage thì runner ghi số thật.
- Gemini API chỉ được mô tả, chưa được gọi: chủ sở hữu giới hạn model work ở subscription; chưa có adapter ngân sách được duyệt.
- Checker phải dùng thuyền khác editor. Thiếu thuyền thứ hai thì job dừng và không tạo quyết định xuất bản.
- Bài top/notable cần ngày gốc và ngày sự kiện không quá bảy ngày; tin cũ hơn được hạ về standard.

## Current State

Mười test mới chạy thành công. Fixture ba story chạy qua cả năm bàn và evaluation đạt 0 rác lọt, 0 tin tốt giữ nhầm chỉ trên fixture; chưa phải số đo 150 story. Suite toàn repo trên code cuối: `Ran 1376 tests in 364.834s`, `OK (skipped=8)`. Một lượt đang chạy khi fixture được sửa đã lỗi đúng ở kỳ vọng usage; lượt cuối đã qua.
`git add -f` bị sandbox từ chối tại `index.lock` (`Permission denied`); worktree để nguyên cho Lucy stage và commit. Hai report trong `plans/` bị `.gitignore` ẩn nên cần force-add.

## Next Steps

Lucy chạy discovery live, năm lệnh bàn duyệt trên 150 story, rồi evaluation theo các lệnh trong `plans/reports/phong-duyet/ket-qua-pha-0.md`; báo usage thật và các ngưỡng chất lượng cho anh.
