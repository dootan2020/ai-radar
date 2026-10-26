# Tiến độ phòng báo pha 1a

## Session Intent

Cho phòng báo chạy `python -m phong_bao cycle` theo lịch trên máy này, chỉ duyệt story ID mới, giữ quyết định cũ, và cho nhà in áp dụng quyết định còn mới trong giới hạn 12 giờ. Không chạy model, push hay đăng ký Scheduled Task trong phiên này.

## Files Modified

- `phong_bao/cycle.py`, `phong_bao/__main__.py`: cycle, khóa chồng lượt, lấy snapshot, kiểm tra lane và gọi năm desk.
- `radar/newsroom_decisions.py`, `radar/site_payload.py`: kiểm tra tuổi quyết định, lọc payload đọc, lưu bản intake đầy đủ.
- `phong-bao/cong-cu/register-newsroom-cycle.ps1`: định nghĩa lịch Windows.
- `phong-bao/decisions.json`: trạng thái rỗng chưa có cycle; `generated_at: null` khiến nhà in dùng hành vi cũ.
- `phong-bao/cycles/.gitignore`: giữ log/job local ngoài commit quyết định.
- `tests/test_phong_bao_cycle.py`, `tests/test_newsroom_decisions.py`: fake runner, khóa, lane cạn, đường có và không có quyết định.

## Decisions Made

- Nguồn đang xuất bản trước pha này là `/data/radar.json`. Sau khi quyết định lọc `radar.json`, nhà in ghi thêm `/data/radar-intake.json` chứa collection đầy đủ để cycle sau vẫn thấy story mới; `radar.json` và các companion đọc chỉ chứa story được duyệt khi file quyết định còn mới. Tệp intake là dữ liệu công khai bằng URL; giao diện không dùng nó. Đây là điểm cần anh chốt nếu “chỉ xuất bản tin được duyệt” cũng cấm công khai dữ liệu nguồn qua endpoint.
- Cách chuyển được chọn: `phong-bao/decisions.json` là lịch sử quyết định tích lũy, gồm cả hold. Lucy commit và push file này lên `main`; checkout của Actions đọc trực tiếp, không sửa workflow và không cần secret mới. Đổi lại, cần Lucy push sau mỗi cycle muốn có hiệu lực và file tăng dần theo thời gian.
- Phương án còn lại: branch riêng cho decisions rồi Actions fetch branch đó trước build. Nó tách dữ liệu khỏi code và có thể cập nhật độc lập, nhưng cần sửa `.github/workflows/update.yml`, đang ngoài phạm vi brief, và thêm logic fetch/failure.
- Lịch đề xuất: 06:00, 10:00, 14:00, 18:00, 20:00 giờ Asia/Bangkok; nghỉ 22:00–06:00. Lượt 100 story trước dùng khoảng 18 phút, 495k tokens; chỉ story mới đi qua model nên mỗi lượt thông thường ít hơn. Task giới hạn hai giờ để lượt cuối dừng trước 22:00, bỏ lượt trùng; process giữ khóa OS và ghi `dry_lane` khi không đủ hai boat khác nhau. Task chạy dưới user đăng nhập để dùng subscription CLI và mạng; Lucy có thể điều chỉnh sau khi kiểm tra điều kiện máy.
- Khi file quyết định thiếu, sai hoặc quá 12 giờ, payload từ build giữ nguyên hành vi hiện tại. `RADAR_NEWSROOM_MAX_AGE_HOURS` đổi giới hạn. Khi còn mới, story chưa có quyết định cũng không lên payload đọc; analysis và mọi quyết định bị cap xuống standard. Chỉ key points đã kiểm chứng mới thay summary; bản dịch summary cũ bị bỏ để không hiển thị nội dung khác.

## Current State

- Test hẹp: `python -m unittest discover -s tests -p 'test_phong_bao*.py'` → `Ran 42 tests in 1.030s`, `OK`; `test_site_payload.py` → `Ran 17 tests in 0.425s`, `OK`.
- Suite toàn repo trên code cuối: `Ran 1410 tests in 245.963s`, `OK (skipped=8)`. PowerShell registration script đã qua kiểm tra cú pháp; chưa được chạy.
- Không gọi model, không push, không đăng ký Scheduled Task và không sửa `phong-bao/jobs/`.
- `git add` các file trong scope bị sandbox từ chối tại `.git/worktrees/ai-radar-wt-phong-bao/index.lock` (`Permission denied`). Worktree để nguyên cho Lucy stage; report này bị `plans/` ignore nên Lucy cần `git add -f -- plans/reports/tien-do-phong-bao-1.md`.

## Next Steps

1. Lucy merge code vào checkout `main`, chạy cycle thật sau khi kiểm tra CLI vẫn đúng subscription/model. Trong checkout đó, lệnh chuyển quyết định là:

   ```powershell
   python -m phong_bao cycle
   git add -- phong-bao/decisions.json
   git commit -m "chore: publish newsroom decisions"
   git push origin main
   ```

2. Lucy xem `phong-bao/cong-cu/register-newsroom-cycle.ps1`, xác nhận checkout lâu dài và Python đúng; khi sẵn sàng mới chạy `powershell -File phong-bao/cong-cu/register-newsroom-cycle.ps1`. Script tự lấy đường dẫn repo tại nơi nó nằm.
3. Cần anh chốt: endpoint intake công khai có chấp nhận được không? Nếu không, cần một kênh snapshot riêng tư từ Actions tới máy này và phải mở rộng phạm vi workflow/quyền truy cập trước khi đăng ký lịch.
