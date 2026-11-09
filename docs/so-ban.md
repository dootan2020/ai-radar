# Sổ bàn newsroom

Lệnh này đọc các cycle đã lưu, không chạy lại desk và không sửa dữ liệu nguồn.

```sh
python -m phong_bao so-ban --cycles phong-bao/cycles --out phong-bao/so-ban
python -m phong_bao so-ban --cycles phong-bao/cycles --out phong-bao/so-ban --month 2026-11 --labels labels.json
```

`so-ban.jsonl` có hai loại hàng: `story` ghi verdict, giá trị gốc, lý do, provider, boat và các cờ của từng desk cho từng tin; `desk` ghi trạng thái, thời lượng, token theo provider, số hàng lỗi, lỗi model và budget của một cycle. Ledger bao gồm mọi cycle có thư mục mang dấu thời gian hợp lệ. `so-ban-domains.csv` chứa đầy đủ tổng publish và hold theo domain của tháng được chọn. Báo cáo `bao-cao-YYYY-MM.md` chỉ tính tháng được chọn theo lịch Asia/Bangkok; mặc định là tháng địa phương của cycle mới nhất. Giờ lịch trong báo cáo dùng múi giờ +07:00, còn dấu thời gian trong ledger là UTC.

Đọc phần lịch để thấy số cycle có mặt, hoàn tất và bị ngắt; các khung kỳ vọng bắt đầu lúc 02:00 ngày đầu tháng và kết thúc ở khung gần nhất trước thời điểm chạy hoặc trước khi hết tháng. Bảng domain trong báo cáo chỉ hiển thị 15 domain có nhiều tin nhất và một dòng tổng phần còn lại; CSV giữ đầy đủ dữ liệu. Các bảng desk cho biết kết quả, lý do phổ biến, token và p50/p95 thời gian. Thời gian chỉ được gán cho provider khi toàn bộ desk trong cycle dùng một provider có batch được ghi; với nhiều provider hoặc cycle cũ thiếu `seconds`, báo cáo nói không có dữ liệu. Tỷ lệ writer loại các hàng không đủ điều kiện viết; tỷ lệ checker chỉ tính hàng có `rejected_claims`. Phần cuối liệt kê file hoặc trường không đọc được. Tin hold trong lịch sử có thể thiếu tiêu đề tiếng Việt; mẫu tin ghi rõ điều đó thay vì tự tạo tiêu đề.

Khi có `--labels`, lệnh lấy quyết định mới nhất cho từng ID được gán nhãn trong lịch sử rồi gọi `phong_bao.evaluation.evaluate()`. Nhãn thiếu quyết định hoặc sai schema được ghi ở phần dữ liệu không đọc được.
