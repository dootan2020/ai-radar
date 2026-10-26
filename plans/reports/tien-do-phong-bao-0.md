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

## Round 2: discovery nhiên liệu và cấu hình agy

- Đã kiểm tra bốn phát hiện của lượt live. Discovery trước đây chạy `trang-thai` không có `--do-gemini`; parser dò marker cạn ở mọi vị trí trong dòng nên trúng chữ `CẠN` trong lời nhắc ở dòng “chưa đo”. Ghi file `discover --output` không tạo thư mục cha. Profile agy thiếu model/output JSON. Canva chỉ dò qua `claude mcp list`, nên không thấy connector chỉ có trong Claude session.
- Discovery nay đo Gemini bằng `trang-thai --do-gemini` (timeout 90 giây). Registry chỉ loại boat khi verdict bắt đầu bằng một từ/cụm cạn hoặc dự trữ với ranh giới từ thật; dòng chưa đo chỉ có lời nhắc được ghi `fuel_status: unmeasured` và vẫn đủ điều kiện, vì chưa có bằng chứng hết nhiên liệu. Lựa chọn này giữ khả năng fallback checker nếu phép đo lỗi, còn trạng thái được thể hiện tường minh; discovery mặc định vẫn đo trước lượt chọn.
- Nếu phép đo trả lời yêu cầu đăng nhập, thanh toán, hoặc đổi account/model, discovery dừng bằng lỗi admission chung và không in chẩn đoán thô.
- `agy.toml` ghim `gemini-3.8-flash-high`, bật `--output-format json`, không thêm `--mode` chưa được xác nhận và không thêm workspace `--add-dir` vì desk chỉ nhận prompt, không sửa file. Runner bóc JSON envelope ở trường `response` trước khi xác thực `stories`.
- Discovery tạo thư mục cha của đường dẫn output. Nếu Canva MCP không thấy trong danh sách Claude, output nêu `state: session_only` và `required_context: Claude session`; không tuyên bố Canva được phát hiện và không ảnh hưởng phase 0.
- Fixture `fuel-lines.json` giữ nguyên hai dòng nhiên liệu live nêu trong brief. Regression tests kiểm tra verdict khô, chưa đo, đã đo, đối số discovery, trạng thái Canva, envelope JSON, thư mục output và chặn yêu cầu đổi account/thanh toán. Bộ test phòng báo hẹp trên code cuối: `Ran 14 tests in 0.270s`, `OK`.
- Không chạy boat hoặc model. Kiểm tra diff không thấy sửa trong `phong-bao/jobs/`; Lucy có thể tiếp tục live run sau khi nhận bàn giao.
- Kiểm chứng vòng 2 trên code cuối: `python -m unittest tests.test_phong_bao` cho `Ran 14 tests in 0.270s`, `OK`; `python -m unittest discover -s tests` cho `Ran 1380 tests in 346.048s`, `OK (skipped=8)`.

## Round 3: tách admission khỏi prompt và bài nguồn

- Nguyên nhân trong runner là regex quét chung `stderr` và `stdout` thất bại, nơi CLI có thể lặp prompt cùng đoạn trích bài; discovery áp dụng regex thô tương tự lên hai luồng phép đo nhiên liệu. Codex CLI không được cài trong worktree nên không thể tái hiện echo trực tiếp. Tài liệu Codex xác nhận `codex exec --json` xuất JSONL events; schema sự kiện định nghĩa lỗi ở `error`/`turn.failed` và token ở `turn.completed.usage` ([JSONL eval example](https://developers.openai.com/blog/eval-skills), [event schema](https://github.com/openai/codex/blob/main/sdk/typescript/src/events.ts), [message schema](https://github.com/openai/codex/blob/main/sdk/typescript/src/items.ts)).
- Profile Codex bật `--json`; runner chỉ tìm admission trong các lỗi JSON event, đọc assistant message từ `item.completed`, và yêu cầu usage thật để tính `tokens_per_story` (không dùng estimate ký tự cho Codex). Với agy, runner bỏ prompt đầy đủ bị echo trước khi kiểm tra stderr, và chỉ đọc `error.message` có cấu trúc từ stdout khi process lỗi; câu trả lời model không còn bị quét. Excerpt status giới hạn ở cụm admission khớp, không lưu cả dòng có thể chứa dữ liệu nhạy cảm.
- Discovery nhiên liệu/MCP không quét stdout, vốn là nội dung báo cáo/đo; chỉ xem stderr khi process lỗi và chỉ nhận dòng CLI có tiền tố error/fatal, rồi ghi excerpt admission an toàn. Fixture offline kiểm tra echo có “sign in”, “log in”, “subscribe” qua cả codex/agy mà vẫn qua; lỗi sign-in thật qua event/error dừng; kiểm tra riêng payment, usage limit, account mismatch và model mismatch; usage limit của phép đo fuel dừng. Kiểm tra integration xác nhận `status.json` ghi excerpt và không chứa bài nguồn.
- Không chạy boat/model. `codex` CLI không có trong môi trường; `agy --help` chỉ được dùng để kiểm tra option, không khởi chạy inference. Không sửa `phong-bao/jobs/`.
- Kiểm chứng vòng 3 trên code cuối: `python -m unittest tests.test_phong_bao` cho `Ran 18 tests in 0.481s`, `OK`; `python -m unittest discover -s tests` cho `Ran 1384 tests in 309.425s`, `OK (skipped=8)`.
