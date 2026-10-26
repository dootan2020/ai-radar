# Phòng báo pha 0: khung chạy tay và kiểm chứng offline

Khung năm bàn đã chạy trọn trên fixture pha A. Lucy đo lượt live 150 tin từ 23:40 ngày 26/10 đến 00:20 ngày 27/10/2026 ICT: rác lọt **0/54 (0%)**, tin tốt giữ nhầm **52/96 (54,17%)**. Ngưỡng rác lọt ≤2% đạt, ngưỡng giữ nhầm ≤10% chưa đạt. Các thay đổi sau phép đo được kiểm chứng offline; Lucy sẽ chạy lại live.

## Kết quả giao

- `phong_bao/` cung cấp registry TOML, discovery, batch runner thay được, năm bàn, job có `status.json` từng bàn, `quyet-dinh.json` version 1, và evaluation. Input 150 story không nhãn ở `tests/fixtures/phong-bao/baseline-150.json` được trích từ snapshot pha A, khớp 150 ID của bộ nhãn.
- Chín file trong `phong-bao/cong-cu/` mô tả Codex CLI, agy, Claude Code, Gemini API, Remotion, ffmpeg, Canva MCP, HN Algolia và HTTP fetch. Vai khai năng lực; registry tự đọc file mới mỗi lượt. Công cụ không có file được báo `found_not_configured` và không được gọi.
- Bàn tiếp nhận dùng `radar.items.relevant` và `radar.press_relevance.press_subject_reason`; bàn phóng viên dùng `radar.summary_pipeline.fetch_article_result` với robots check, so nguồn trong coverage và corpus bằng `radar.clustering.titles_match`, rồi tìm HN Algolia. Bàn kiểm chứng dùng guard số của `radar.summary_validation`. Không đọc URL yêu cầu đăng nhập, không vượt paywall, và không suy 403 là paywall.
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

Để Lucy tính lại trên job đã hoàn thành mà giữ intake/reporter cũ, chạy lệnh `run` với **`--from editor --through chief`** và cùng `--input`, `--corpus`, `--job` như trên. Lệnh xóa quyết định cũ trước khi tính lại editor, checker và chief; nếu muốn đo luôn tiết kiệm của reporter, dùng `--from reporter`. Sau đó chạy lại `evaluate`. Không chạy boat/model trong worktree này.

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
3. Lượt live đầu đạt ngưỡng rác nhưng chưa đạt ngưỡng giữ nhầm. Lucy cần chạy lại editor/checker/chief và chấm đủ 150 tin trước khi kết luận bản sửa đạt ≤10%; usage mới cũng chưa được đo. Vài trang redirect vẫn bị parser `radar` báo chưa đọc được; phóng viên tìm nguồn độc lập, không tự vượt redirect khi chưa kiểm robots ở đích.

## Nguồn quyết định

- [Plan phòng duyệt](plan.md), [kết quả pha A](ket-qua-pha-a.md), [nhãn và chứng cứ](../../../tests/fixtures/phong-duyet/), và các hàm `radar/` nêu trên.
- Đã đọc thiết kế profile TOML, job state và fallback của `D:\BACHDYON\VAS-v1.3\video-automator-skills-main` (README, AGENTS, `skills/kie-ai`, `skills/ausynclab-voice`). Chỉ học cấu trúc; không chép code PolyForm Noncommercial.
