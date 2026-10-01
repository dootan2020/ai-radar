# Radar AI · Bản tin sáng

Mở mỗi sáng để xem các phòng lab AI vừa có gì mới, buổi phát trực tiếp nào đáng theo dõi và dự án nào đang nổi. Mỗi tin dẫn về nguồn gốc để đọc tiếp.

## Chạy trên máy

Cần **Python 3.11+**, chỉ dùng thư viện chuẩn, không phải cài thêm package hay cung cấp API key. Chạy trong thư mục dự án:

```sh
python -m unittest discover -s tests
python build.py
python serve.py
```

Mở **http://localhost:8790**. Test chạy offline; build cần Internet để lấy dữ liệu thật và ghi vào [site/data/radar.json](site/data/radar.json). Chạy lại `python build.py`, rồi tải lại trang khi muốn cập nhật. Dừng server bằng `Ctrl+C`; nếu cổng 8790 đang bận, server báo lỗi và không tự đổi cổng.

## Đọc bản tin

| Mục | Nội dung và nguồn |
| --- | --- |
| Đáng chú ý nhất | Tin được chọn từ feed; chỉ hiện khi có tin phù hợp. Nhãn “Mới” và nút “Đánh dấu đã xem hết” giúp theo dõi lần đọc. |
| Tin từ các phòng lab | Tin và nghiên cứu, lọc theo lab. RSS chính thức của OpenAI, Google AI, DeepMind, Hugging Face; feed cộng đồng cho Anthropic, xAI, Meta và Mistral. [Danh mục feed](radar/feeds.py). |
| Phát trực tiếp | Đang live, sắp bắt đầu và vừa kết thúc trong 7 ngày từ YouTube OpenAI, Anthropic, Google, DeepMind; trạng thái kiểm tra bằng metadata video. [Kênh và collector](radar/youtube.py). |
| Đang nổi | GitHub Trending hôm nay và Hugging Face Trending. GitHub là xu hướng chung, không chỉ AI. [GitHub](radar/github.py) · [Hugging Face](radar/huggingface.py). |
| Mô hình mở mới trên Hugging Face | Repository model mới từ các tổ chức OpenAI, Google, DeepSeek, Meta, Mistral, Qwen và xAI. [Danh mục tổ chức](radar/huggingface.py). |
| Nguồn của bản tin này | Thời điểm build, số mục đọc được và nguồn gặp lỗi; nguồn lỗi không làm mất dữ liệu từ nguồn thành công. |

## Giới hạn cần biết

- Nhãn `kind` (mô hình, sản phẩm, nghiên cứu…) dựa trên tiêu đề và mô tả trong feed, không đọc toàn bài. Có thể bỏ sót thông báo ra mắt hoặc phân loại sai; nhãn không phải xác nhận độc lập.
- Feed cộng đồng có thể chậm hoặc thiếu tin. Đọc được nguồn không đồng nghĩa nguồn còn mới hay bao phủ đầy đủ; ngày đăng gốc được giữ nguyên.
- **Chưa xác minh được kênh YouTube chính thức của xAI**; `@xai` là tài khoản không liên quan nên không nằm trong nguồn thu thập. xAI vẫn có tin từ feed cộng đồng và model từ `xai-org` trên Hugging Face.
- Hugging Face `created_at` là ngày tạo repository, **không phải ngày ra mắt model**. Tên mục “Mô hình mở” không xác nhận giấy phép mở; cần kiểm tra model card và license ở nguồn.
- YouTube và các trang công khai có thể đổi cấu trúc hoặc tạm lỗi; lượt quét có giới hạn nên không bảo đảm tìm đủ mọi buổi phát. Trang hiển thị snapshot từ lần build gần nhất, không phải theo dõi thời gian thực.

## Xuất bản sau

**Chưa xuất bản.** Khi được duyệt, dùng workflow có sẵn [Update AI Radar](.github/workflows/update.yml): vào repository **Settings → Pages → Source → GitHub Actions**, rồi chạy workflow trong tab **Actions**. Workflow chạy test, build và deploy thư mục `site/`; lịch cập nhật ở phút 07 và 37 mỗi giờ, có thể bị GitHub trì hoãn.
