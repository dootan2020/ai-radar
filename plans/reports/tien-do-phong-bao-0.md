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

## Round 4: không bỏ số đo khi lane chạm dự trữ

- Nguyên nhân: `hai-thuyen.py` trả exit 3 khi có lane còn nhiên liệu nhưng chưa được giao việc, đồng thời vẫn in các dòng đo; discovery chỉ giữ stdout khi exit 0 nên bỏ cả số đo Claude chạm dự trữ. Registry trước đó cho phép Claude chưa đo được chọn tự động.
- Discovery nay giữ các dòng nhiên liệu trên exit 0 và exit 3; lỗi khác, crash hoặc timeout vẫn là `unavailable`. Parser nhận `CHẠM DỰ TRỮ` trong dòng có phần trăm sử dụng, đồng thời vẫn chỉ nhận `CẠN` ở đầu verdict để tránh nhầm lời nhắc “chưa đo”. Claude chỉ được chọn khi đo rõ còn dưới ngưỡng. Codex/Gemini chưa đo vẫn có thể được dùng vì quota tách biệt với coordinator; chỉ Claude dùng chung pool cần fail closed.
- Fixture exit 3 chứa Codex và Gemini còn nhiên liệu cùng Claude tuần 84% chạm ngưỡng 80%; test xác nhận chọn Codex và agy, loại claude-code. Fixture không có dòng đo cũng không chọn Claude. Không chạy boat/model và không chỉnh `phong-bao/jobs/`.
- Kiểm chứng vòng 4: `python -m unittest tests.test_phong_bao` cho `Ran 20 tests in 0.913s`, `OK`; `python -m unittest discover -s tests` cho `Ran 1386 tests in 407.512s`, `OK (skipped=8)`.

## Round 5: chỉ giữ rác, hạ cấp tin thiếu chứng cứ

- Lượt live của Lucy: 0/54 rác lọt, 52/96 tin tốt giữ nhầm; reporter 25, editor 12, checker 14, intake 1. Ba bàn dùng tổng 1.817.062 token, khoảng 12.114/tin.
- Chief chỉ hold khi intake loại hoặc editor xác định một loại rác. Tin không đọc được vẫn qua editor để phân loại từ metadata, sau đó lên standard với title gốc/link, không summary. Checker trả claim được hỗ trợ và cờ title; chief bỏ claim sai hoặc summary, hạ tier theo ngày và chứng cứ. Quyết định ghi `summary`, `tier_capped`, lý do suy giảm và cờ dùng title gốc.
- Batch tối đa 32 story/60.000 ký tự qua stdin Codex; agy dùng argv được chia ở 24.000 ký tự. Reporter bỏ gọi boat khi không có candidate, chỉ gửi excerpt 900 ký tự; editor nhận excerpt 1.200 ký tự; checker nhận claim và các đoạn nguồn liên quan.
- `run --from editor --through chief` cho phép Lucy tính lại job cũ, bỏ quyết định cũ trước khi tính. Fixture bảy case thật từ live và các test bảo vệ mọi loại rác đã được thêm. Chưa chạy boat/model hoặc sửa `phong-bao/jobs/`; lượt chấm 150 tin mới thuộc Lucy.
- Kiểm chứng bản cuối: `python -m unittest tests.test_phong_bao` cho `Ran 26 tests in 0.672s`, `OK`; `python -m unittest discover -s tests` cho `Ran 1392 tests in 277.495s`, `OK (skipped=8)`. Cả hai exit 0; `git diff --check` exit 0.

## Round 6: cô lập row lỗi, giữ raw reply và quyết định cũ

- Nguyên nhân: `_editor` ném lỗi khi một row JSON hợp lệ thiếu trường bắt buộc, khiến toàn desk batch bị mất. Prompt đã nêu các trường round 5, nhưng chưa nói rõ giới hạn tối đa tám claims và 520 ký tự/claim như validator yêu cầu.
- Reporter, editor và checker ghi các row JSON đã parse vào `raw/<desk>-<n>.json`. Row sai schema được thử lại riêng một lần; nếu vẫn sai, desk ghi `invalid_rows`, reporter/checker hạ chứng cứ, còn editor đặt `editor_invalid` và đưa tin qua nhánh publish standard không summary. Lỗi batch/ID và admission stop vẫn dừng desk.
- Prompt editor nay nêu rõ tối đa tám claims, mỗi claim 1–520 ký tự. `--from` không xóa `quyet-dinh.json`; file cũ chỉ bị thay khi lượt chief mới ghi quyết định hoàn chỉnh.
- Không chạy boat/model, không sửa `phong-bao/jobs/`. Có regression tests cho retry row riêng, raw files, suy giảm sau lần retry lỗi và giữ quyết định qua rerun thất bại.
- Kiểm chứng bản cuối: `python -m unittest tests.test_phong_bao` cho `Ran 28 tests in 1.386s`, `OK`; `python -m unittest discover -s tests` cho `Ran 1394 tests in 354.396s`, `OK (skipped=8)`. `git diff --check` exit 0.

## Round 7: giữ verdict rác và gom retry

- Lucy đo live sau vòng 6: rác lọt 20/54 (37%), tin tốt giữ nhầm 1/96 (1%); editor giữ 0 rác, có 46 batch, 28 row lỗi và 1.631.346 input token. Raw reply đầu và kết quả chấm được đưa vào `tests/fixtures/phong-bao/live-raw/`.
- Nguyên nhân: validator bắt mọi row editor có metadata của tin, nên `news:false` với `importance:none` bị coi là sai; nhánh `editor_invalid` đổi nó thành publish. Retry từng row làm phát sinh lệnh Codex riêng.
- Editor nay giữ mọi `news:false`, kể cả kind chưa nhận diện và giữ nguyên giá trị kind. Row tin sai metadata được retry; tier không hợp lệ bị hạ về standard nhưng claims hợp lệ vẫn được giữ. Row thiếu verdict chỉ publish standard khi không có dấu hiệu rác. Prompt và validator dùng cùng danh sách kind và tier; không ánh xạ `high` sang `notable` vì có thể nâng tier sai. Tin 0 claim vẫn là tin hợp lệ và không có summary.
- Retry row lỗi được gom theo batch ở reporter, editor và checker. Test offline chạy toàn bộ raw reply editor đầu, xác nhận cả năm verdict rác đều hold; test riêng kiểm retry theo batch, kind lạ và verdict thiếu.
- Không chạy boat/model hoặc sửa `phong-bao/jobs/`.
- Kiểm chứng bản cuối: `python -m unittest tests.test_phong_bao` cho `Ran 32 tests in 0.721s`, `OK`; `python -m unittest discover -s tests` cho `Ran 1398 tests in 246.815s`, `OK (skipped=8)`. Cả hai exit 0.

## Round 8: phân biệt phân tích với rác

- Lucy đo lượt live sau vòng 7: rác lọt **2/54 (3,7%)**, tin tốt giữ nhầm **22/96 (22,9%)**; editor giữ 21 tin tốt. Editor dùng 4 batch và khoảng 190.000 input token, checker 4 batch và khoảng 65.000. Hai rác lọt là model card `InternScience/Sage-A1.5` và pitch Vortex Code.
- Prompt editor trước đó chỉ có hai ngả tin sự kiện hoặc rác, nên coi nhiều phân tích, phỏng vấn, podcast và khảo sát về AI không có sự kiện định ngày là `non_news_page`. Hợp đồng mới ghi `content_kind` ba giá trị `event_news`, `analysis`, `junk`, và `analysis_kind`; chief luôn hạ phân tích về standard. Launch thật cũ hơn bảy ngày vẫn publish standard; chỉ cùng bài cũ nổi lại không có cập nhật mới là `stale_content`.
- Prompt phân biệt pitch Show HN/trang bán hàng với release có nội dung thực chất và phân biệt model card trơ với thông báo model. Test offline dùng tám case thật trong baseline và nhãn pha A để kiểm đường đi editor/chief; chưa chạy boat/model hay sửa `phong-bao/jobs/`.
- Nếu reply phân tích vẫn thiếu subtype sau một lần retry, editor ghi subtype chung `analysis` để quyết định không mất kind. Kiểm chứng bản cuối: `python -m unittest tests.test_phong_bao` cho `Ran 34 tests in 0.778s`, `OK`; `python -m unittest discover -s tests` cho `Ran 1400 tests in 245.696s`, `OK (skipped=8)`. Cả hai exit 0.

## Round 9: bỏ tiêu đề fixture khỏi prompt

- Prompt các vòng 7 và 8 chứa tiêu đề hoặc dấu hiệu nhận diện story trong bộ 150 tin. Vì vậy điểm chấm vòng 7 và mọi điểm chấm vòng 8 trên bộ này bị thổi phồng một phần bởi rò rỉ đáp án; không thể coi là phép đo độc lập về khả năng phân loại. Test mới đối chiếu prompt với cả hai fixture theo cụm ba từ có nghĩa và model ID, đã đỏ trên prompt vòng 8 trước khi sửa.
- Editor prompt nay diễn đạt quy tắc chung cho phân tích, launch cũ, bài đăng lại, pitch bán hàng, model card trơ và AI chỉ xuất hiện thoáng qua. Không gọi boat/model hoặc sửa `phong-bao/jobs/`. Cần đo lại trên bộ đánh giá sạch trước khi kết luận chất lượng thực tế.
- Kiểm chứng: `python -m unittest tests.test_phong_bao` → `Ran 35 tests in 0.915s`, `OK`; `python -m unittest discover -s tests` → `Ran 1401 tests in 258.178s`, `OK (skipped=8)`. Cả hai exit 0.
