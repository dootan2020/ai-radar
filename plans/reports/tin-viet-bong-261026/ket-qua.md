# Kết quả thử tin Việt bóng — 26/10/2026

Shadow collector đã thu thập và gắn nhãn hai RSS tiếng Việt, không thay đổi nguồn live hay trang đọc. Đây là số liệu mở đầu từ **một lần quét**, chưa phải kết luận của thử nghiệm bảy ngày.

## Nguồn

| Tổ chức | Kết quả kiểm tra ngày 26/10 | Quyết định |
| --- | --- | --- |
| [VnExpress Khoa học công nghệ](https://vnexpress.net/rss/khoa-hoc-cong-nghe.rss) | RSS HTTP 200, robots cho phép, parse được 30 mục. [Trang RSS chính thức](https://vnexpress.net/rss). | Thêm `vnexpress-khoa-hoc-cong-nghe`. |
| [Bộ KH&CN](https://mst.gov.vn/rss/tin-tuc-su-kien.rss) | RSS HTTP 200, robots cho phép, parse được 30 mục. [Danh mục RSS chính thức](https://mst.gov.vn/index.rss) liệt kê URL này. Domain cũ `most.gov.vn` có lỗi hostname certificate tại máy thử. | Thêm `mst-tin-tuc-su-kien` trên cổng hiện tại. |
| [FPT](https://fpt.com/vi/tin-tuc) | Trang tin chính thức có nội dung mới, nhưng `/vi/tin-tuc/rss` và `/feed` trả HTTP 404. | Bỏ qua vì chưa tìm được RSS/Atom hợp lệ. |
| [Viettel](https://www.viettel.vn/en) | `/feed` trên `www.viettel.vn` trả HTTP 404; `/rss` trên `viettel.com.vn` không đọc được robots do khai báo encoding lỗi. | Bỏ qua; không đoán quyền truy cập hay dùng HTML. |
| [VNG/Zalo](https://vng.com.vn/news/list.1.html) | Trang tin có bài AI, nhưng `/rss` và `/feed` trả HTTP 404. | Bỏ qua vì chưa tìm được RSS/Atom hợp lệ. |
| [VinAI](https://www.vinai.io/news/) | `/feed`, `/feed/`, `/feed.xml` và `/news/feed/` trả HTTP 404. Trang tin hiện thấy bài mới nhất từ 2025; không suy diễn feed của Qualcomm là nguồn kế nhiệm cho tin Việt. | Bỏ qua vì chưa tìm được RSS/Atom hợp lệ. |

Không dùng HTML scraping, endpoint trả phí, tài khoản hay model API. Workflow hiện có chạy phút 17 mỗi giờ, upload `shadow-records.json` và JSONL, giữ artifact 14 ngày. Không sửa workflow.

## Quy tắc gắn nhãn

Mỗi mục từ candidate có `origin_trial: true` giữ tiêu đề và mô tả RSS. `radar/vn_origin.py` đánh dấu `is_ai` bằng `radar.items.relevant`; `has_vn_entity` bằng danh sách từ khóa có ranh giới từ cho tổ chức, địa danh, chính sách Việt Nam và mẫu tên người Việt có họ phổ biến. Tên publisher tự nó không tạo nhãn nguồn gốc. `vn_origin_ai` đúng khi cả hai nhãn đúng.

Collector tải một lần snapshot live `radar-ui.json` (sau kiểm tra robots), dùng URL chuẩn hóa hoặc `radar.clustering.titles_match` với các story/coverage hiện có. `likely_foreign_republish` đúng khi không có thực thể Việt Nam **hoặc** có match live. Nhãn này là tín hiệu cần đọc lại, không phải bằng chứng sao chép. Nếu live snapshot lỗi, `live_match_checked=false`; script review báo thiếu và trả mã lỗi để không đưa ra tỷ lệ có vẻ hoàn chỉnh.

Quy tắc thực thể là danh sách cố định nên có thể bỏ sót tên người, địa phương hoặc doanh nghiệp chưa liệt kê. Mục tiếng Việt thiếu tên Việt có thể bị gắn cờ tin ngoại dù là tin nội địa. So khớp tiêu đề giữa hai ngôn ngữ cũng có thể bỏ sót cùng một sự kiện. Vì vậy các tỷ lệ này cần được đối chiếu bằng URL trước quyết định live.

Script `scripts/review-vn-origin.py` dùng `gh run list` và `gh run download` để lấy artifact theo ngày chạy, sau đó gộp các lần quét theo canonical URL. Tin được xếp theo ngày đăng tại Việt Nam, không tính mục thiếu ngày, và lấy mẫu ngẫu nhiên tối đa 20 URL với seed cố định. Khi thiếu artifact, source lỗi, thiếu ngày hoặc so khớp live chưa hoàn tất, script báo và trả mã lỗi. Mẫu cần anh đọc để xác định số tin **đáng đọc**; nhãn tự động không đo thay tiêu chí biên tập này.

```sh
python scripts/review-vn-origin.py --start YYYY-MM-DD
python scripts/review-vn-origin.py --start 2026-10-20 --input PATH_TO_LOCAL_SHADOW_RECORDS.json
```

## Lần quét đầu

| Nguồn | Mục | Có AI | AI có thực thể Việt Nam | Dấu hiệu chuyển tiếp tin ngoại |
| --- | ---: | ---: | ---: | ---: |
| VnExpress | 30 | 8 | 0 | 25 |
| Bộ KH&CN | 30 | 1 | 1 | 16 |
| Tổng | 60 | 9 | 1 | 41 |

Tất cả 60 mục đã được so với snapshot live; không có URL hay tiêu đề nào match. Trong cửa sổ **ngày đăng** 20–26/10, script in lần lượt 0, 0, 0, 0, 1, 0, 0 tin AI có thực thể Việt Nam; tổng 1/60, bình quân 0,14/ngày; 41/60 mục (68,3%) bị đánh dấu chuyển tiếp tin ngoại. Đây là dữ liệu ban đầu, gồm bài cũ có sẵn trong feed, không được xem như một tuần chạy shadow thật. Snapshot dùng để thử script được xóa sau khi ghi số liệu vì chứa bản sao tiêu đề và mô tả của bên thứ ba.

Kiểm thử: `python -m unittest discover -s tests` hoàn tất `Ran 1329 tests in 281.426s`, `OK (skipped=8)`; năm test tập trung chạy lại sau chỉnh sửa cuối đều đạt. Chế độ script tải artifact từ GitHub chưa được thử trên máy này vì `gh` không đọc được file cấu hình trong sandbox (`Access is denied`); chế độ đọc snapshot local đã chạy thành công.

Không tạo được commit: `git add` bị sandbox từ chối khi tạo `.git/worktrees/ai-radar-wt-tin-viet/index.lock` (`Permission denied`). Cây làm việc được giữ nguyên để Lucy stage, kể cả `git add -f plans/`, rồi commit; không push.

## Bước tiếp theo

Sau bảy ngày workflow chạy trên branch mặc định, chạy script với ngày bắt đầu thử nghiệm và đọc mẫu URL. Chỉ đề xuất live nếu bình quân **ít nhất 2 tin Việt Nam về AI đáng đọc mỗi ngày** và **không quá 30% mục tiếng Việt là tin ngoại chuyển tiếp** theo đánh giá của anh. Nếu feed lỗi hoặc nhãn gây nghi ngờ, đọc lại URL trước khi quyết định.

## Câu hỏi chưa giải quyết

- FPT, Viettel, VNG/Zalo và VinAI có RSS/Atom chính thức khác chưa được công bố công khai hay không? Vòng này không thêm nguồn chưa mở và parse được.
- Khi đọc mẫu sau bảy ngày, anh có muốn tính mọi mục không nêu thực thể Việt Nam vào tỷ lệ tin ngoại, hay chỉ những mục thực sự viết lại một tin nước ngoài? Script hiện chọn quy tắc bảo thủ theo brief; đây là giả định cần đối chiếu trước quyết định live.

## Vòng 2: sửa phép đếm và mở rộng shadow

Quy tắc cũ bỏ sót địa danh, chức danh và chữ “Việt” dùng như tính từ. Quy tắc mới nhận đủ 34 tỉnh, thành hiện hành sau sáp nhập 2025 cùng tên tỉnh cũ thường gặp; thêm tổ chức, chức danh, doanh nghiệp, sự kiện và tiền đồng. Tiêu đề xác định chủ thể chính: một bài về nhân vật Trung Quốc không thành tin Việt chỉ vì mô tả nhắc đồng sáng lập gốc Việt. Em thử hướng mặc định tin tiếng Việt là nội địa, nhưng scan đẩy nhiều bài nghiên cứu, sự cố và sản phẩm nước ngoài vào nhãn Việt. Vì vậy phép đếm dùng bằng chứng nội địa trong tiêu đề hoặc mô tả, không lấy quốc tịch publisher làm bằng chứng. Mục chưa đủ bằng chứng được gắn cờ đọc lại; nhãn `likely_foreign_republish` vẫn là tín hiệu, không phải kết luận sao chép.

Tuổi Trẻ phát ngày theo dạng `10/23/2026 6:31:00 PM` không có múi giờ. Shadow parser nay truyền múi giờ `+07:00` đã khai báo trong candidate vào parser RSS; trước sửa cả 30 mục Tuổi Trẻ thiếu ngày và bị script loại. Live pipeline không đổi.

### Fixture gắn nhãn

[`tests/fixtures/vn-origin-titles.json`](../../../tests/fixtures/vn-origin-titles.json) lưu 49 tiêu đề thật lấy từ sáu RSS đang cập nhật ngày 26/10, mỗi dòng có nguồn, nhãn do em đọc và lý do; một dòng giữ mô tả RSS để xác định cảnh báo của Công an Hà Nội. Chạy `python scripts/evaluate-vn-origin-fixture.py` cho kết quả:

| Nhãn | TP | FP | FN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Việt Nam | 26 | 0 | 0 | 100,0% | 100,0% |
| Nước ngoài | 23 | 0 | 0 | 100,0% | 100,0% |

Đây là fixture có chọn tiêu đề đủ ngữ cảnh và dùng để kiểm hồi quy, không phải ước lượng chất lượng trên toàn bộ bài bảy ngày. Lớp “Nước ngoài” là lớp đối của nguồn gốc Việt trên fixture, tương ứng cờ chuyển tiếp khi không có live match; nó không chứng minh bài đã được đăng lại. Các tiêu đề mơ hồ vẫn cần đọc tay. Test riêng xác nhận năm ví dụ Lucy nêu được nhận là nội địa, còn “Chính phủ Canada” và bài nhân vật Trung Quốc có nhắc người Việt trong mô tả không bị nhận nhầm.

### Nguồn và lần quét local sau sửa

Bốn URL `vnexpress-tech`, `genk-ai`, `tuoitre-so`, `thanhnien-cong-nghe` lấy từ `radar/catalog.py` đều trả RSS HTTP 200 và parse được. Chúng chỉ được thêm vào shadow candidates; cả bốn vẫn thuộc `RETIRED` của live. RSS [VietnamNet Công nghệ](https://vietnamnet.vn/cong-nghe.rss) cũng trả 200 và parse được, nên được thêm để quan sát; mục mới nhất là **06/05/2025**, không đóng góp tin hiện thời. RSS ICTnews thử mở chuyển về trang HTML, không parse được. Hai nguồn vòng 1 được giữ nguyên.

| Nguồn shadow | Mục | AI | AI gốc Việt | Có dấu hiệu chuyển tiếp tin ngoại | Mới nhất (UTC) |
| --- | ---: | ---: | ---: | ---: | --- |
| VnExpress Khoa học công nghệ | 30 | 8 | 1 | 20 | 26/10/2026 |
| Bộ KH&CN | 30 | 1 | 1 | 9 | 25/10/2026 |
| VnExpress International Tech | 30 | 10 | 1 | 26 | 26/10/2026 |
| GenK AI | 30 | 30 | 4 | 26 | 26/10/2026 |
| Tuổi Trẻ Nhịp sống số | 30 | 15 | 1 | 23 | 23/10/2026 |
| Thanh Niên Công nghệ | 30 | 1 | 0 | 27 | 26/10/2026 |
| VietnamNet Công nghệ | 30 | 3 | 3 | 2 | 06/05/2025 |
| **Tổng một lần quét** | **210** | **68** | **11** | **133** | |

Một snapshot local được quét với robots check và so với snapshot live; không có URL hay tiêu đề nào match live trong lần này. Chạy `python scripts/review-vn-origin.py --start 2026-10-20 --input <snapshot>` trả mã **0**: 137 URL có ngày đăng trong 20–26/10, **5** AI gốc Việt (0,71/ngày), **96** mục có dấu hiệu chuyển tiếp (70,1%); 0 mục thiếu ngày, 0 source-day lỗi, 0 mục thiếu so khớp live. Đây là bài đã nằm sẵn trong RSS của **một lần quét**, chưa phải bảy ngày thu thập thực tế hay đánh giá bài đáng đọc. Snapshot ở thư mục tạm đã được xóa sau khi ghi số liệu.

Kiểm thử sau chỉnh sửa cuối: `python -m unittest discover -s tests` trả mã 0, `Ran 1336 tests in 205.678s`, `OK (skipped=8)`. Test tập trung `test_vn_origin.py` đạt 10/10; `git diff --check` không có lỗi whitespace.

`git add -f` vẫn bị sandbox từ chối khi tạo `.git/worktrees/ai-radar-wt-tin-viet/index.lock` (`Permission denied`). Các file được để nguyên để Lucy stage và commit; không push.
