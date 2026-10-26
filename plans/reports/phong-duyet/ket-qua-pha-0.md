# Phòng báo pha 0: khung chạy tay và kiểm chứng offline

Đo lúc 26/10/2026 ICT. **Khung năm bàn đã chạy trọn trên fixture ba tin thật của pha A**, gồm một nguồn thay đã đọc được. Chưa có phép đo chất lượng 150 tin bằng boat thật: sandbox không chạy model hoặc mạng; Lucy thực hiện lượt đó sau khi nhận bàn giao. Mục tiêu cho lượt thật là rác lọt ≤2% và tin tốt giữ nhầm ≤10%.

## Kết quả giao

- `phong_bao/` cung cấp registry TOML, discovery, batch runner thay được, năm bàn, job có `status.json` từng bàn, `quyet-dinh.json` version 1, và evaluation. Input 150 story không nhãn ở `tests/fixtures/phong-bao/baseline-150.json` được trích từ snapshot pha A, khớp 150 ID của bộ nhãn.
- Chín file trong `phong-bao/cong-cu/` mô tả Codex CLI, agy, Claude Code, Gemini API, Remotion, ffmpeg, Canva MCP, HN Algolia và HTTP fetch. Vai khai năng lực; registry tự đọc file mới mỗi lượt. Công cụ không có file được báo `found_not_configured` và không được gọi.
- Bàn tiếp nhận dùng `radar.items.relevant` và `radar.press_relevance.press_subject_reason`; bàn phóng viên dùng `radar.summary_pipeline.fetch_article_result` với robots check, so nguồn trong coverage và corpus bằng `radar.clustering.titles_match`, rồi tìm HN Algolia. Bàn kiểm chứng dùng guard số của `radar.summary_validation`. Không đọc URL yêu cầu đăng nhập, không vượt paywall, và không suy 403 là paywall.
- Editor xuất các ID coverage cùng sự kiện và ID cần tách. Checker chạy thuyền khác editor cho từng tin. Tổng biên tập giữ tin thiếu nguồn/kiểm chứng, hạ top/notable khi sự kiện hoặc ngày gốc quá bảy ngày, và không cho top thiếu 4–8 key points đã qua checker.

## Bằng chứng offline

- Fixture gồm tin DeepSeek được đọc trực tiếp, case study Octave bị editor giữ, và tin METR được cứu bằng bài ArtificialWatch độc lập ghi trong chứng cứ pha A. Lượt chạy fixture hoàn thành cả năm bàn, reporter và editor dùng `codex`, checker dùng `agy`.
- `python -m phong_bao evaluate --decisions tests/fixtures/phong-bao/decisions.json --labels tests/fixtures/phong-bao/labels.json` trả **0/1 rác lọt, 0/2 tin tốt giữ nhầm**; editor giữ một tin và chief cho hai tin đi tiếp. Đây là phép thử hợp đồng ba tin, không phải ước lượng chất lượng 150 tin.
- Batch tối đa **8 tin** và 20.000 ký tự payload để vừa giới hạn lệnh Windows. Trên fixture, ước lượng theo ký tự là reporter 1.739/3 = **579,7 token/tin**, editor 2.292/3 = **764 token/tin**, checker 894/2 = **447 token/tin**. Đây **không phải usage model thật**. Runner ghi usage CLI nếu có; nếu CLI không trả usage, trường `source=character_estimate` giữ rõ tính ước lượng. Lucy cần báo số thật khi chạy live.
- Dry discovery fixture nhận `codex`, `agy`, `ffmpeg`, `python`, Canva MCP, Remotion qua file `node_modules/.bin/remotion.cmd` của VAS, và tên `GEMINI_API_KEY`; báo CapCut MCP và `NEW_VENDOR_API_KEY` là `found_not_configured`. Cần đối chiếu live vì đường dẫn Remotion có thể đổi. Không giá trị key nào được đọc.
- Test hẹp: `Ran 10 tests ... OK`. Test toàn repo trên code cuối: `Ran 1376 tests in 364.834s` và `OK (skipped=8)`. Một lượt trước đó lỗi ở test fixture vì fixture token được sửa lúc suite đang chạy; chạy lại sau khi đóng băng input đã qua.

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

## Giới hạn và quyết định cần anh xem

1. Gemini API có profile đúng trần **20 USD/tháng** nhưng runner cố ý disabled: quy tắc owner của phiên này chỉ cho model work trên subscription đã cấp. Muốn dùng paid API thật cần chủ sở hữu cho phép riêng và có adapter kiểm ngân sách trước mỗi request. Trần X **30 USD/tháng** không đổi.
2. Registry có thể nhận một plugin hoặc key mới chỉ bằng file profile, nhưng bàn ảnh/video và một paid adapter chưa thuộc pha 0. Công cụ mới được thấy mà chưa có profile sẽ không được gọi.
3. Thước đo ≤2%/≤10%, khả năng chạy CLI thật, usage token thật, và tình trạng Remotion/Canva lúc chạy chỉ có thể xác nhận bằng lượt live của Lucy. Vài trang redirect vẫn bị parser `radar` báo chưa đọc được; phóng viên sẽ tìm nguồn độc lập, không tự vượt redirect khi chưa kiểm robots ở đích.
4. `git add -f` bị sandbox từ chối khi tạo `index.lock` (`Permission denied`), nên mọi file vẫn unstaged. `.gitignore` đang bỏ qua `plans/`; Lucy cần force-add hai báo cáo theo đúng đường dẫn trong brief nếu muốn đưa vào commit.

## Nguồn quyết định

- [Plan phòng duyệt](plan.md), [kết quả pha A](ket-qua-pha-a.md), [nhãn và chứng cứ](../../../tests/fixtures/phong-duyet/), và các hàm `radar/` nêu trên.
- Đã đọc thiết kế profile TOML, job state và fallback của `D:\BACHDYON\VAS-v1.3\video-automator-skills-main` (README, AGENTS, `skills/kie-ai`, `skills/ausynclab-voice`). Chỉ học cấu trúc; không chép code PolyForm Noncommercial.

**Câu hỏi cuối:** Anh có muốn cho phép Gemini API trả phí trong phòng báo sau khi Lucy đo chất lượng bằng subscription không? Theo ranh giới hiện tại, phần đó tiếp tục tắt.
