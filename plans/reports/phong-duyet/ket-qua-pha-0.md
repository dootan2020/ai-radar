# Phòng báo pha 0: khung chạy tay và kiểm chứng offline

Khung năm bàn đã chạy trọn trên fixture pha A. Lượt live đầu có rác lọt **0/54** và tin tốt giữ nhầm **52/96**; lượt sau vòng 6 có **20/54 (37%)** và **1/96 (1%)**. Lượt sau vòng 7 có **2/54 rác lọt (3,7%)** và **22/96 tin tốt giữ nhầm (22,9%)**. Chưa lượt live nào đồng thời đạt ngưỡng rác lọt ≤2% và giữ nhầm ≤10%.

## Kết quả giao

- `phong_bao/` cung cấp registry TOML, discovery, batch runner thay được, năm bàn, job có `status.json` từng bàn, `quyet-dinh.json` version 1, và evaluation. Input 150 story không nhãn ở `tests/fixtures/phong-bao/baseline-150.json` được trích từ snapshot pha A, khớp 150 ID của bộ nhãn.
- Chín file trong `phong-bao/cong-cu/` mô tả Codex CLI, agy, Claude Code, Gemini API, Remotion, ffmpeg, Canva MCP, HN Algolia và HTTP fetch. Vai khai năng lực; registry tự đọc file mới mỗi lượt. Công cụ không có file được báo `found_not_configured` và không được gọi.
- Bàn tiếp nhận dùng `radar.press_relevance.press_subject_reason` (hàm này gọi `radar.items.relevant`); bàn phóng viên dùng `radar.summary_pipeline.fetch_article_result` với robots check, so nguồn trong coverage và corpus bằng `radar.clustering.titles_match`, rồi tìm HN Algolia. Bàn kiểm chứng dùng guard số của `radar.summary_validation`. Không đọc URL yêu cầu đăng nhập, không vượt paywall, và không suy 403 là paywall.
- Editor xuất các ID coverage cùng sự kiện và ID cần tách. Checker chạy thuyền khác editor cho từng tin. Tổng biên tập chỉ giữ tin bị intake loại hoặc editor xác định là rác; nguồn không đọc được, claim/title bị bác và tin cũ hơn bảy ngày được ghi là suy giảm trong quyết định.

## Bằng chứng offline

- Fixture gồm tin DeepSeek được đọc trực tiếp, case study Octave bị editor giữ, và tin METR được cứu bằng bài ArtificialWatch độc lập ghi trong chứng cứ pha A. Lượt chạy fixture hoàn thành cả năm bàn, reporter và editor dùng `codex`, checker dùng `agy`.
- `python -m phong_bao evaluate --decisions tests/fixtures/phong-bao/decisions.json --labels tests/fixtures/phong-bao/labels.json` trả **0/1 rác lọt, 0/2 tin tốt giữ nhầm**; editor giữ một tin và chief cho hai tin đi tiếp. Đây là phép thử hợp đồng ba tin, không phải ước lượng chất lượng 150 tin.
- Lượt fixture ban đầu dùng batch tối đa 8 tin và 20.000 ký tự. Ước lượng ký tự lúc đó là reporter 579,7, editor 764 và checker 447 token/tin; các số này **không phải usage model thật**. Số live thật và cấu hình mới ở phần dưới.
- Dry discovery fixture nhận `codex`, `agy`, `ffmpeg`, `python`, Canva MCP, Remotion qua file `node_modules/.bin/remotion.cmd` của VAS, và tên `GEMINI_API_KEY`; báo CapCut MCP và `NEW_VENDOR_API_KEY` là `found_not_configured`. Cần đối chiếu live vì đường dẫn Remotion có thể đổi. Không giá trị key nào được đọc.
- Lúc giao khung ban đầu, test hẹp chạy 10 case và suite toàn repo chạy 1.376 case (`OK (skipped=8)`). Kết quả kiểm chứng bản sửa live được ghi riêng bên dưới.

## Lượt live và sửa sau khi đo

`phong-bao/jobs/live-261026/danh-gia.json` ghi 150 quyết định: 54 rác, 96 tin tốt, **0 rác lọt** và **52 tin tốt giữ nhầm**. Trong 52 tin đó, intake giữ 1, reporter 25, editor 12, checker 14. Reporter giữ cả các trang NVIDIA, OpenAI và model card vì parser đọc quá ít hoặc không tìm được nguồn độc lập. Editor gọi những launch ngày 7, 8 và 13/10 là “stale resurfacing”, dù quy tắc là giữ launch có thật ở tầng standard sau bảy ngày. Checker giữ cả story vì một claim thiếu “tại Mỹ”, số không khớp, hoặc chữ “Europe” ở title thiếu chứng cứ.

`status.json` của lượt live ghi reporter **711.972 input / 11.477 output token qua 19 batch**, editor **686.469 / 44.948 qua 16 batch**, checker **209.791 / 152.405 qua 11 batch**. Tổng ba bàn là **1.817.062 token, khoảng 12.114 token/tin**. Một batch Codex chỉ có một story vẫn tốn khoảng 36.000 input token; đó là phần chi phí cố định cần chia cho batch lớn.

Sửa hợp đồng quyết định như sau:

- Editor vẫn phân loại story khi nguồn không đọc được, dựa trên title/teaser và trạng thái nguồn, và phải nêu `junk_kind` cụ thể cho verdict rác. Prompt hiệu chỉnh bằng nhãn pha A: trang Claude Opus 5.5 ngày 22/9 là nội dung cũ nổi lại; Cyber Mission ngày 8/10 và Qwen glasses ngày 13/10 là launch có thật dù cũ. Các loại rác `non_news_page`, `vendor_sales`, `customer_case_study`, `tutorial`, `incidental_ai`, `mis_merged_cluster`, `stale_content` vẫn bị giữ.
- Reporter không gọi boat khi không có bài ứng viên đọc được. Editor nhận URL gốc, loại card và tối đa 1.200 ký tự excerpt để vẫn nhận ra trang social/model card thiếu bài; checker nhận claim và một đoạn nguồn phù hợp cho title và mỗi claim, bỏ đoạn trùng, thay vì toàn bài. Checker trả danh sách claim được hỗ trợ và trạng thái title; guard số kiểm lại từng claim và title. Chief bỏ claim sai, bỏ summary khi còn dưới hai claim hoặc thiếu nguồn, dùng title gốc nếu title bị bác, và hạ top/notable khi thiếu chứng cứ hoặc sự kiện quá bảy ngày. `quyet-dinh.json` ghi `summary`, `tier_capped`, `degradation_reasons`, `use_original_title`, `key_points` và URL nguồn gốc khi chưa chọn được nguồn thay.
- Batch tối đa **32 story / 60.000 ký tự payload** với Codex qua stdin. Boat nhận prompt trong argv được chia ở **24.000 ký tự** để ở dưới giới hạn lệnh Windows; fallback tự chia batch lớn. Với khoảng **36.000 input token cố định mỗi lệnh Codex**, batch đủ 32 story chia còn **1.125 token cố định/tin**. Trần payload 60.000 ký tự tương đương khoảng 15.000 token, tức **tối đa khoảng 1.600 input token/tin** ở batch đầy, cộng output; batch nhỏ hơn sẽ có chi phí cố định/tin cao hơn. Nếu cả reporter và editor đều lấp đầy batch, giữ nguyên output cũ của hai bàn và toàn bộ usage checker cũ, phép tính cho **khoảng 6.000 token/tin** so với 12.114 đã đo. Đây là **ước lượng lập kế hoạch**, không phải usage mới; reporter còn bỏ các lệnh không có candidate, còn output checker có thể đổi đáng kể và phải đo lại.

Fixture `tests/fixtures/phong-bao/live-held-cases.json` sao chép card và excerpt tối thiểu của bảy case live: nguồn OpenAI không đọc được, launch Cyber Mission cũ, claim Claude Duet sai một địa điểm, claim NVIDIA sai số, title NVIDIA thiếu chứng cứ địa lý, case study Octave và bài Bluesky không có sự kiện. Reply fixture thể hiện verdict mong đợi theo hợp đồng mới, không phải câu trả lời model đã đo. Test offline xác nhận năm tin tốt được publish với suy giảm đúng, hai tin rác vẫn hold, từng `junk_kind` vẫn hold, và payload không mang bài toàn văn sang editor/checker. Chưa có số chất lượng mới trên 150 tin; không suy từ fixture thành ngưỡng live.

Kiểm chứng bản sửa: `python -m unittest tests.test_phong_bao` → `Ran 26 tests in 0.672s`, `OK`; `python -m unittest discover -s tests` → `Ran 1392 tests in 277.495s`, `OK (skipped=8)`. Cả hai exit 0. `git diff --check` exit 0.

Để Lucy tính lại trên job đã hoàn thành mà giữ intake/reporter cũ, chạy lệnh `run` với **`--from editor --through chief`** và cùng `--input`, `--corpus`, `--job` như trên. Quyết định cũ được giữ cho tới khi chief ghi quyết định mới hoàn chỉnh; nếu muốn đo luôn tiết kiệm của reporter, dùng `--from reporter`. Sau đó chạy lại `evaluate`. Không chạy boat/model trong worktree này.

## Lượt live sau vòng 6 và sửa hợp đồng editor

Lucy đo lại từ editor ngày 27/10, khoảng 01:1x–01:4x ICT: **20/54 rác lọt (37%, ngưỡng ≤2%)**, **1/96 tin tốt giữ nhầm (1%)**. Editor giữ **0** tin rác, chạy **46 batch**, ghi **28 row lỗi** và tiêu thụ **1.631.346 input token**. Phần lớn token đến từ retry từng story, khoảng **35.000 input token cố định** mỗi lệnh Codex. Raw reply đầu tiên được lưu ở `tests/fixtures/phong-bao/live-raw/editor-1.json`; điểm chấm ở `tests/fixtures/phong-bao/live-raw/danh-gia-vong6.json`.

Model trả `importance` là `high`, `low` hoặc `none` dù validator chỉ nhận `top`, `notable`, `standard`. Cả verdict `news:false` có `junk_kind` hợp lệ cũng bị validator coi là row lỗi vì thiếu metadata của tin; nhánh suy giảm vòng 6 đổi chúng thành publish standard. Bản sửa tách verdict khỏi metadata: mọi `news:false` được giữ và giữ nguyên `junk_kind`, kể cả giá trị chưa nhận diện. Tin `news:true` có 0 claim là hợp lệ và không có summary. Prompt dùng chung danh sách `junk_kind` với validator, nêu chính xác tier và số claim. Không tự ánh xạ `high` sang `notable`: ý nghĩa tier chưa đủ rõ để nâng hạng; row tin sai tier được retry, rồi hạ metadata về standard nếu vẫn sai. Retry row lỗi của từng bàn được gom theo batch, không gọi Codex riêng cho từng story.

Test offline đưa toàn bộ 28 row của raw reply đầu qua editor và chief: cả **5 verdict rác đều hold**; 3 row tin có tier `high` được retry cùng một batch. Chưa chạy boat/model và chưa có số đo chất lượng live cho bản sửa này.

Kiểm chứng bản sửa hiện tại: `python -m unittest tests.test_phong_bao` → `Ran 32 tests in 0.721s`, `OK`; `python -m unittest discover -s tests` → `Ran 1398 tests in 246.815s`, `OK (skipped=8)`. Cả hai exit 0.

## Lượt live sau vòng 7 và hiệu chỉnh ba loại nội dung

Lucy đo lại từ editor ngày 27/10 khoảng 02:1x ICT: **2/54 rác lọt (3,7%, ngưỡng ≤2%)** và **22/96 tin tốt giữ nhầm (22,9%, ngưỡng ≤10%)**. Editor giữ 21 trong 22 tin tốt; editor và checker mỗi bàn chạy 4 batch, dùng lần lượt khoảng **190.000** và **65.000 input token**. Hai rác lọt là model card trơ `InternScience/Sage-A1.5` và trang chào sản phẩm Vortex Code.

Nguyên nhân chính là prompt editor chỉ có hai ngả “news event” và “junk”. Phần lớn tin tốt bị giữ là phân tích, phỏng vấn, podcast, bình luận hoặc khảo sát về AI không có một sự kiện định ngày. Hợp đồng editor nay phân biệt `event_news`, `analysis` và `junk`; `analysis_kind` ghi kiểu bài. Chief publish phân tích ở standard ngay cả khi editor đề xuất hạng cao hơn. Launch có thật quá bảy ngày vẫn là `event_news` ở standard; `stale_content` chỉ dành cho cùng bài cũ đăng lại mà không có cập nhật. Prompt nêu rõ trang bán hàng hoặc Show HN chỉ là pitch, và model/dataset card trơ không có thông báo, là rác; một release có tài liệu thực chất vẫn có thể là tin dù nằm trên Hugging Face hoặc Show HN.

Test offline chọn tám case có thật từ bộ 150: ba bài phân tích/khảo sát, ba launch cũ được gắn nhãn tốt, và hai rác lọt. Một test thêm kiểm subtype phân tích vẫn được ghi sau retry lỗi. Test dùng nhãn để kiểm kỳ vọng và reply fixture để kiểm đường đi editor → chief; nó **không đo** hành vi model trên 150 story. Lucy cần chạy lại editor/checker/chief và evaluation để xác nhận hai ngưỡng live.

Kiểm chứng bản cuối: `python -m unittest tests.test_phong_bao` → `Ran 34 tests in 0.778s`, `OK`; `python -m unittest discover -s tests` → `Ran 1400 tests in 245.696s`, `OK (skipped=8)`. Cả hai exit 0.

## Sửa rò rỉ tiêu đề trong prompt

Prompt editor của vòng 7 và 8 đã đưa tiêu đề hoặc dấu hiệu nhận diện các story trong chính bộ 150 tin vào lời hướng dẫn. Vì thế điểm vòng 7 và 8 trên bộ này **bị thổi phồng một phần bởi rò rỉ đáp án**; các con số ghi trên là lịch sử chạy, không phải ước lượng độc lập đáng tin cậy. Vòng 8 chưa có lượt đo model mới sau khi đổi hợp đồng ba loại nội dung.

Prompt hiện tại chỉ nêu quy tắc phân loại tổng quát. Test hồi quy đối chiếu tất cả hằng prompt trong `phong_bao/newsroom.py` với tiêu đề của `baseline-150.json` và `nhan-tin-261026.json`, chặn cụm ba từ có nghĩa liên tiếp hoặc model ID trùng. Test này đã thất bại với prompt cũ trước khi sửa. Các case thật vẫn nằm trong test để kiểm hợp đồng editor/chief, không đưa vào prompt. Cần đánh giá lại bằng dữ liệu chưa từng lộ tiêu đề trong prompt để có số đo chất lượng công bằng.

Kiểm chứng sau sửa: `python -m unittest tests.test_phong_bao` → `Ran 35 tests in 0.915s`, `OK`; `python -m unittest discover -s tests` → `Ran 1401 tests in 258.178s`, `OK (skipped=8)`. Cả hai exit 0.

## Cập nhật vòng 10

Lượt holdout độc lập sau vòng 10 do Lucy đo trên 100 tin cho thấy **10/23 rác lọt (43%)** và **7/77 tin tốt giữ nhầm (9,1%)**. So với vòng 9, intake bỏ hold của bài gốc quá 30 ngày đã làm tăng rác lọt; mốc 7–30 ngày vẫn là publish ở standard. Đây là số đo trước sửa vòng 11; chưa có phép đo live sau sửa.

Vòng 10 runner chia batch lỗi làm hai nửa cho tới từng card, nhưng mỗi call có thể chờ đủ 600 giây trước khi bắt đầu chia. Vòng 11 thêm budget wall-clock độc lập cho mỗi desk, mặc định 1.200 giây, cấu hình qua `--desk-budget-seconds`. CLI nhận timeout theo thời gian còn lại; khi budget hết, các card chưa có phản hồi được ghi model failure và desk không gửi thêm. Editor model failure giữ card với `editor_model_failure`; checker model failure vẫn publish degraded không summary. Intake giữ bài có ngày xuất bản gốc trên 30 ngày nếu không có cập nhật được xác minh; bài 7–30 ngày tiếp tục qua intake và chief hạ về standard.

Test offline dùng fake runner, không gọi boat/model thật. Leak guard không đổi và không thêm dữ liệu từ holdout. Bản vòng 11 cần Lucy đo lại trên tập độc lập để xác nhận tỉ lệ rác lọt; phép thử hiện tại chưa phải số đo live.

Kiểm chứng code vòng 11: `python -m unittest tests.test_phong_bao` → `Ran 40 tests in 0.999s`, `OK`; `python -m unittest discover -s tests` → `Ran 1406 tests in 244.782s`, `OK (skipped=8)`. Không chạy boat/model trong phiên này.

## Lệnh Lucy chạy thật

Chạy từ gốc worktree. `discover` chỉ kiểm tra sự hiện diện và nhiên liệu; nó không bắn thử boat:

```powershell
python -m phong_bao discover --output phong-bao/jobs/live-261026/discovery.json
```

- **Tiếp nhận:** `python -m phong_bao run --input tests/fixtures/phong-bao/baseline-150.json --corpus tests/fixtures/phong-duyet/snapshot-261026.json.gz --job phong-bao/jobs/live-261026 --through intake`
- **Phóng viên:** `python -m phong_bao run --input tests/fixtures/phong-bao/baseline-150.json --corpus tests/fixtures/phong-duyet/snapshot-261026.json.gz --job phong-bao/jobs/live-261026 --through reporter`
- **Biên tập viên:** `python -m phong_bao run --input tests/fixtures/phong-bao/baseline-150.json --corpus tests/fixtures/phong-duyet/snapshot-261026.json.gz --job phong-bao/jobs/live-261026 --through editor`
- **Kiểm chứng:** `python -m phong_bao run --input tests/fixtures/phong-bao/baseline-150.json --corpus tests/fixtures/phong-duyet/snapshot-261026.json.gz --job phong-bao/jobs/live-261026 --through checker`
- **Tổng biên tập:** `python -m phong_bao run --input tests/fixtures/phong-bao/baseline-150.json --corpus tests/fixtures/phong-duyet/snapshot-261026.json.gz --job phong-bao/jobs/live-261026 --through chief`

Sau đó chấm đủ 150 ID:

```powershell
python -m phong_bao evaluate --decisions phong-bao/jobs/live-261026/quyet-dinh.json --labels tests/fixtures/phong-duyet/nhan-tin-261026.json
```

Script chấm lỗi nếu thiếu ID hoặc vượt một trong hai ngưỡng. `status.json` chỉ bàn đang lỗi; sửa nguyên nhân rồi chạy lại cùng lệnh, các bàn hoàn thành trước đó được giữ theo checksum input và corpus. Nếu CLI yêu cầu đăng nhập, trả phí hoặc báo đổi account/model, dừng và báo anh, không chọn boat khác để lách.

## Giới hạn và việc tiếp theo

1. Gemini API có profile đúng trần **20 USD/tháng** nhưng runner cố ý disabled: quy tắc owner của phiên này chỉ cho model work trên subscription đã cấp. Muốn dùng paid API thật cần chủ sở hữu cho phép riêng và có adapter kiểm ngân sách trước mỗi request. Trần X **30 USD/tháng** không đổi.
2. Registry có thể nhận một plugin hoặc key mới chỉ bằng file profile, nhưng bàn ảnh/video và một paid adapter chưa thuộc pha 0. Công cụ mới được thấy mà chưa có profile sẽ không được gọi.
3. Lượt live sau vòng 7 vượt cả hai ngưỡng. Lucy cần chạy lại editor/checker/chief và chấm đủ 150 tin trước khi kết luận bản hiệu chỉnh ba loại nội dung đạt ngưỡng; usage của bản mới chưa được đo. Vài trang redirect vẫn bị parser `radar` báo chưa đọc được; phóng viên tìm nguồn độc lập, không tự vượt redirect khi chưa kiểm robots ở đích.

## Nguồn quyết định

- [Plan phòng duyệt](plan.md), [kết quả pha A](ket-qua-pha-a.md), [nhãn và chứng cứ](../../../tests/fixtures/phong-duyet/), và các hàm `radar/` nêu trên.
- Đã đọc thiết kế profile TOML, job state và fallback của `D:\BACHDYON\VAS-v1.3\video-automator-skills-main` (README, AGENTS, `skills/kie-ai`, `skills/ausynclab-voice`). Chỉ học cấu trúc; không chép code PolyForm Noncommercial.
