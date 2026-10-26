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

## Next Steps from Phase 1a (superseded)

Các hướng dẫn pha 1a bên dưới đã được pha 1b thay thế. Không push `decisions.json` lên `main`.

1. Lucy merge code vào checkout `main`, chạy cycle thật sau khi kiểm tra CLI vẫn đúng subscription/model. Trong checkout đó, lệnh chuyển quyết định là:

   ```powershell
   python -m phong_bao cycle
   git add -- phong-bao/decisions.json
   git commit -m "chore: publish newsroom decisions"
   git push origin main
   ```

2. Lucy xem `phong-bao/cong-cu/register-newsroom-cycle.ps1`, xác nhận checkout lâu dài và Python đúng; khi sẵn sàng mới chạy `powershell -File phong-bao/cong-cu/register-newsroom-cycle.ps1`. Script tự lấy đường dẫn repo tại nơi nó nằm.
3. Cần anh chốt: endpoint intake công khai có chấp nhận được không? Nếu không, cần một kênh snapshot riêng tư từ Actions tới máy này và phải mở rộng phạm vi workflow/quyền truy cập trước khi đăng ký lịch.

## Phase 1b: branch riêng và bản đọc tiếng Việt

- `cycle` gửi user agent tường minh, nhận `--snapshot-url`, và chỉ thử `/data/radar.json` nếu `/data/radar-intake.json` trả 404. Lần đầu chưa có intake vẫn đọc được snapshot live.
- `apply_decisions` chỉ bỏ story có quyết định hold và cap tier cho story publish được xét; ID chưa được xét giữ nguyên hành vi hiện tại. Không sửa `summary`, `summary_vi`, key points hoặc headline đã dịch. Bản intake vẫn đầy đủ. Bước fetch trong `update.yml` xóa seed ở checkout rồi lấy duy nhất `decisions.json` từ branch `newsroom-decisions` bằng raw media type (không vướng giới hạn 1 MB của base64 Contents API); branch/file 404 dùng hành vi cũ, lỗi khác làm step thất bại.
- `run-newsroom-cycle.ps1` dùng clone riêng, đồng bộ lịch sử branch về file local trước cycle (giữ quyết định local chưa push nếu nó là phần mở rộng của branch; dừng khi hai lịch sử phân kỳ), rồi commit/push duy nhất `decisions.json` lên `newsroom-decisions` bằng push thường. Nếu chưa có branch, nó tạo orphan branch. Nó không sửa `main`; registration gọi script này. Chưa chạy script, push hay đăng ký task trong phiên này.
- Kiểm tra các reader: translate và summarize đọc `radar.json` đã lọc, nên không tốn lượt cho hold. Trước sửa, cả hai ghi bản lọc đè `data/published-snapshot.json`, làm mất history đầy đủ; nay merge các trường mới của story còn hiển thị vào bản full trước khi ghi cache, giữ story hold, sections gốc và ranking tier gốc. Cache dịch và summary riêng vẫn là file riêng, không reset khi lọc. `edition_publish` và `video_script` chọn từ bản đọc đã lọc, đúng mục tiêu; nếu dưới ngưỡng chọn video, bước video trả `insufficient_stories`. `health_probe` chỉ xác thực schema và timestamp, không đòi số story tối thiểu. `build.py` ghi bản full vào published cache và baseline trước bước dịch, và intake full trước bộ lọc; với cache restored bình thường, hold không trở lại như story mới trong history. Khi cache published bị mất, fallback từ `site/data/radar.json` có thể thiếu history, nhưng quyết định theo ID vẫn giữ hold khỏi site khi branch còn mới.
- Tốc độ đo 110 story/24 giờ tương đương khoảng 550.000 token/ngày ở mức 5.000 token/story. Giữ lịch 06:00, 10:00, 14:00, 18:00, 20:00 Asia/Bangkok: ca 4 giờ khoảng 18–19 story (~92.000 token), ca đêm 10 giờ khoảng 46 story (~229.000 token). Cửa sổ quyết định 12 giờ đủ qua ca đêm nếu task hoàn tất. Lần đầu chưa có lịch sử sẽ thấy tối đa khoảng 1.821 ID cũ (~9,1 triệu token theo mức 1a), vượt xa ca thông thường và có thể chạm giới hạn task 2 giờ; Lucy cần chuẩn bị bootstrap trước khi kích hoạt lịch thật.
- Test HTTP/CLI cycle: `Ran 4 tests in 0.087s`, `OK`; quyết định: `Ran 2 tests in 0.175s`, `OK`; payload/build: `Ran 19 tests in 0.506s`, `OK`. Suite toàn repo trên code cuối: `Ran 1414 tests in 247.557s`, `OK (skipped=8)`. `py_compile`, `git diff --check` và cú pháp hai script PowerShell đều qua. Không đọc admission/observation, không chạy model, không chạm `.env`, secret, fixture hay `phong-bao/jobs/`.
- `git add` bị sandbox từ chối tại `C:/Users/Admin/ai-radar/.git/worktrees/ai-radar-wt-phong-bao/index.lock` (`Permission denied`). Worktree để nguyên cho Lucy stage và commit; report hiện là file đã tracked.

## Phase 1c: cửa sổ story gần đây và fallback khi fetch quyết định lỗi

- `python -m phong_bao cycle` chỉ chọn story có `published_at` hoặc `latest_coverage_at` mới hơn trong hai trường và nằm trong cửa sổ gần đây; mặc định 36 giờ, cấu hình bằng `--since-hours`. Story cũ không được gửi qua newsroom và vẫn giữ nguyên trong dữ liệu site.
- Cycle status ghi `considered_count` để CLI in số story nằm trong cửa sổ; `new_count` tiếp tục chỉ số story mới chưa có quyết định.
- Trong riêng step `Fetch newsroom decisions`, lỗi khác 404 giờ in GitHub Actions warning và tiếp tục với file quyết định đã xóa, tương tự fallback 404.
- Test mục tiêu: `Ran 5 tests in 0.124s`, `OK`. Toàn bộ suite: `Ran 1415 tests in 244.031s`, `OK (skipped=8)`.
- Không chạy model, push, register task; không sửa `.env`, secrets, fixtures hoặc `phong-bao/jobs/`.
