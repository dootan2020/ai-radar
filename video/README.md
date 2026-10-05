# ai-radar Video Template (Calm Editorial Direction)

Video template hàng ngày cho ai-radar: "3 tin AI hôm nay", định dạng dọc 1080x1920 (36 giây, 30fps) tối ưu cho TikTok, Facebook Reels và YouTube Shorts.

## Phong cách nghệ thuật (Art Direction)
- **Calm Editorial (Bento Keynote)**: Tối giản, điềm tĩnh, Apple-like decelerating easing (`cubic-bezier(0.16, 1, 0.3, 1)`), khoảng thở rộng rãi, một ý tưởng trên mỗi màn hình.
- **Thu hút trong 2 giây đầu**: Gây chú ý bằng sự rõ ràng và con số ấn tượng (số lượng tin được phân tích & xếp hạng trong ngày), không sử dụng hiệu ứng ồn ào hay giật gân.
- **Typography & Màu sắc**: Font **Be Vietnam Pro** (nhúng trực tiếp từ `site/fonts/`, không phụ thuộc Google Fonts lúc render), màu sắc trích xuất trực tiếp từ hệ thống token `site/tokens.css`.
- **Dữ liệu thật 100%**: Chỉ hiển thị sự thật từ snapshot dữ liệu; giữ nguyên danh từ riêng; dịch thuật tiêu đề tiếng Việt kèm nhãn `Translated` và tiêu đề gốc; xử lý ảnh remote linh hoạt (hiển thị ảnh sắc nét khi nạp thành công, fallback sang card đồ họa dữ liệu typography hoàn chỉnh nếu ảnh lỗi hoặc không tải được).

---

## Cấu trúc Video (36.0 giây = 1080 frames @ 30fps)
1. **Scene 0: Hook / Intro (0s - 4.0s / 120 frames)**
   - Badge thương hiệu `ai·radar · 3 TIN AI HÔM NAY`.
   - Ngày tháng phát hành snapshot.
   - Con số thống kê nổi bật: ví dụ `1.306` tin AI được quét và chấm điểm trong ngày.
   - Mục lục lướt qua 3 câu chuyện tiêu biểu.
2. **Scene 1: Tin 1 (4.0s - 13.5s / 285 frames)**
   - Lead story (tin có điểm `worth_score` cao nhất và nhiều nguồn tin nhất).
   - Card ảnh/đồ họa tỷ lệ lớn, bo tròn 36px, hiệu ứng trôi nhẹ (Ken Burns).
   - Tiêu đề tiếng Việt, tiêu đề gốc tiếng Anh, tóm tắt diễn biến chính và số nguồn độc lập cùng đưa tin.
3. **Scene 2: Tin 2 (13.5s - 23.0s / 285 frames)**
   - Câu chuyện công nghệ/phần cứng/mô hình nổi bật tiếp theo.
4. **Scene 3: Tin 3 (23.0s - 32.0s / 270 frames)**
   - Câu chuyện bảo mật/chính sách/agent AI tiêu biểu.
5. **Scene 4: Outro (32.0s - 36.0s / 120 frames)**
   - Logo squircle ai·radar.
   - Thông điệp thương hiệu: "Radar tin tức AI mỗi ngày".
   - Địa chỉ website: `dootan2020.github.io/ai-radar`.
   - Lời kêu gọi truy cập cập nhật 24/7.
- **Thanh tiến trình (Progress Bar)**: Thanh 5 phân đoạn mượt mà ở đáy màn hình theo dõi tiến độ xuyên suốt video.

---

## Lệnh Render

### 1. Render tự động từ snapshot
Chạy lệnh sau từ thư mục `video/`:
```bash
node render.js [đường-dẫn-snapshot.json]
```
Nếu không truyền đường dẫn snapshot, script sẽ mặc định tìm `sample/radar-ui.json` hoặc `../site/data/radar-ui.json`.

Ví dụ:
```bash
# Render snapshot mẫu hôm nay:
node render.js sample/radar-ui.json

# Hoặc từ thư mục gốc của repository:
node video/render.js video/sample/radar-ui.json
```

### 2. Kết quả đầu ra
Script sẽ tự động xuất 2 tệp vào thư mục `video/out/`:
- **`video/out/<YYYY-MM-DD>.mp4`**: Video dọc chuẩn 1080x1920, 30fps, H.264, không có audio track (để người đăng tự chọn âm thanh nền trên nền tảng).
- **`video/out/<YYYY-MM-DD>.txt`**: Caption soạn sẵn cho bài đăng mạng xã hội gồm:
  - Dòng mở đầu (hook).
  - 3 tiêu đề tin tức nổi bật.
  - Đường dẫn website `https://dootan2020.github.io/ai-radar`.
  - Hashtags thịnh hành (#airadar #ai #tintucai #congnghe #tech #shorts #reels #tiktok).

### 3. Xem trước trong Remotion Studio
Để mở giao diện chỉnh sửa và preview trực quan theo từng frame:
```bash
cd video
npm run studio
# hoặc: node node_modules/@remotion/cli/remotion-cli.js studio src/index.js
```
