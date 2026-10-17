# Roadmap — ai-radar

Cập nhật: 2026-10-17 · Nguồn: quyết định của anh Tuấn (05/10, 07/10, 11/10/2026), trang `site/`, mã `radar/`, `build.py` và workflow cập nhật

## v1 — Đáng để quay lại mỗi sáng
Mục tiêu: Bạn đọc thấy bản tin AI có nguồn gốc rõ ràng và cập nhật đáng tin cậy; thuyền trưởng đo được người đọc quay lại trước khi quyết định thương mại hóa.

- [x] Bạn đọc thấy dòng tin dạng ảnh hoặc bìa dữ liệu, nhãn Translated trên tiêu đề được dịch và đường dẫn bài gốc — `site/index.html:48`, `site/feed.js:395`, `site/feed.js:629`, `site/feed.js:872`, `site/tokens.css:81`, `radar/assembly.py:117`, `.github/workflows/update.yml:144`
- [x] Bạn đọc bấm tiêu đề tin để mở modal; liên kết của tin trỏ đến trang tĩnh riêng khi mở trực tiếp — `site/feed.js:874`, `site/feed.js:2544`, `radar/story_pages.py:346`, `.github/workflows/update.yml:500`
- [x] Những bài cùng sự kiện khớp quy tắc gom cụm được hiển thị thành một câu chuyện có nhiều nguồn — `radar/assembly.py:117`, `radar/clustering.py:416`, `site/feed.js:861`, `.github/workflows/update.yml:144`
- [x] Dòng tin loại các mục tuyển dụng khớp bộ lọc và rút bốn nguồn báo Việt Nam đã ngừng dùng khỏi nội dung hiển thị — `radar/noise.py:29`, `radar/catalog.py:50`, `radar/assembly.py:103`, `radar/story_pages.py:327`, `.github/workflows/update.yml:144`
- [ ] Bạn đọc thấy bảng xếp hạng Arena có điểm và khoảng tin cậy khi dữ liệu nguồn cung cấp hai biên — giao diện và job đã nối (`site/arena.js:94`, `radar/arena.py:151`, `.github/workflows/update.yml:184`), nhưng worktree không có `site/data/arena.json`; trạng thái trên trang production chưa đo được
- [ ] Kịch bản video ngắn được tạo và kiểm duyệt CTA đã duyệt mỗi sáng — workflow có bước tạo (`.github/workflows/update.yml:311`), nhưng bước có thể bỏ qua hoặc từ chối (`radar/video_script.py:605`, `radar/video_script.py:771`); chưa có chứng cứ tạo thành công hằng ngày, và bộ kiểm tra chưa buộc đúng câu CTA
- [x] Trước lời gọi Gemini trả phí để dịch, tóm tắt hoặc viết kịch bản và lời gọi X API để lấy tin, mã dự trù và từ chối khi vượt trần ghi sổ tương ứng 20 USD và 30 USD mỗi tháng — `radar/gemini_paid_budget.py:28`, `radar/gemini_paid_budget.py:396`, `radar/x_paid_budget.py:17`, `radar/x_paid_budget.py:242`, `radar/translation_pipeline.py:213`, `radar/summary_pipeline.py:797`, `radar/video_script.py:717`, `radar/x_collector.py:273`, `.github/workflows/update.yml:32`
- [x] Bản tin cũ không bị ghi đè khi lần thu thập không qua cổng kiểm tra công bố — `build.py:40`, `build.py:48`, `radar/publication.py:174`, `.github/workflows/update.yml:144`
- [x] Bạn đọc nhận được bản tin mới đều đặn theo lịch workflow — workflow đặt lịch hai lần mỗi giờ (cron '7,37 * * * *', `.github/workflows/update.yml:6`); đo lường của Lucy ngày 17/10/2026 ~18:55 qua `gh run list` ghi nhận 8 lượt chạy gần nhất (09:20–11:40 UTC) đều hoàn thành thành công
- [ ] Nguồn tin lab lớn không mất tin âm thầm — chưa có cảnh báo theo từng nguồn khi nguồn không có tin qua các lượt thu thập liên tiếp; quyết định của anh Tuấn 07/10/2026
- [ ] Bạn đọc thấy tin từ lab lớn kịp thời sau khi nguồn đăng — chưa đo được độ trễ từ thời điểm nguồn công bố đến khi tin xuất hiện trên trang chủ
- [ ] Thuyền trưởng theo dõi được người đọc quay lại hằng ngày — trang chủ đã gắn Cloudflare Web Analytics (`site/index.html:54`), nhưng chưa có báo cáo retention được kiểm chứng
- [ ] Bản tin được giới thiệu đến các cộng đồng AI tại Việt Nam — **chờ anh**: duyệt bài giới thiệu và trực tiếp đăng lên cộng đồng theo quyết định của anh Tuấn 11/10/2026

## v1.1 — Phân phối đa kênh
Mục tiêu: Bạn đọc có thêm cách nhận bản tin và video; thuyền trưởng đo được các kênh nào đưa người đọc về trang.

- [ ] Bạn đọc xem video tóm tắt trên YouTube Shorts hoặc TikTok từ kịch bản đã kiểm duyệt — chưa có đường render và đăng video từ `video-script.json`
- [ ] Bạn đọc nhận tin qua Telegram và feed RSS đầu ra — chưa có bot Telegram và feed RSS riêng cho tin đã lọc
- [ ] Bạn đọc tra cứu được tin cũ ngoài cửa sổ lưu giữ hiện tại — trang tra cứu dùng `data/radar-search.json` (`site/tra-cuu.js:133`), chỉ lập chỉ mục các câu chuyện còn được lưu (`radar/search_index.py:111`, `radar/retention.py:9`); chưa có kho tìm kiếm đầy đủ cho tin cũ hơn

## v2 — Doanh thu từ tài trợ và affiliate
Mục tiêu: Thuyền trưởng thử tài trợ và affiliate khi có số liệu người đọc đủ để định giá và kiểm tra hiệu quả.

- [ ] Nhãn hàng có vị trí tài trợ được gắn nhãn rõ trên trang chủ và bản tin — chưa có vị trí và quy chế hiển thị được duyệt
- [ ] Thuyền trưởng theo dõi được doanh thu affiliate từ liên kết khoá học hoặc công cụ AI — chưa có liên kết và phép đo chuyển đổi
- [ ] Việc dịch tiêu đề dùng phương án có quyền sử dụng phù hợp khi bật kiếm tiền — pipeline còn fallback NLLB-200 (`radar/translation_pipeline.py:9`, `radar/translate.py:27`); cần xác minh giấy phép từ nguồn cấp phép và quyết định phương án thay thế nếu cần
- [ ] Kích hoạt tài khoản nhận tiền và chính sách giá tài trợ — **chờ anh**: chốt giá tài trợ và tài khoản nhận thanh toán

## Đề xuất cắt khỏi v1

- Tường thu phí và tài khoản người dùng: chưa phục vụ mục tiêu đo người đọc quay lại của v1; trang hiện là site tĩnh (`site/index.html`, `.github/workflows/update.yml:680`).
- Bảng điều khiển biên tập Google Sheet: quyết định chưa làm; ghim tin hiện dùng `site/editor-picks.json` (quyết định của anh Tuấn 05/10/2026).
- Podcast/Audio TTS: không nằm trong kết quả v1; kịch bản video đang có đường tạo riêng (`radar/video_script.py`, `.github/workflows/update.yml:311`).
- Proxy vượt chặn nguồn: quyết định không dùng với nguồn cố tình chặn; chỉ tìm đường truy cập được phép (quyết định của anh Tuấn 05/10/2026).
