# Hướng Dẫn Nộp Extension Halcyon Lên Chrome Web Store

Hướng dẫn từng bước để anh Tuấn nộp tiện ích **Halcyon** trên Chrome Web Store Developer Console của chính anh. Đăng nhập, phí đăng ký, tải gói lên và bấm nộp là việc của anh; Lucy cùng anh điền form.

---

## 0. Việc anh tự nhập hoặc tự tích (bản tóm tắt)

| Ô trên Developer Console | Giá trị đề xuất | Lấy từ |
| --- | --- | --- |
| Category | `News & Weather` | mục 2, bước 2 |
| Language | `Vietnamese` | `listing-vi.md` |
| Single purpose | đoạn tiếng Anh trong `single-purpose.txt` | mục 2, bước 3 |
| Permission justification: `storage`, `alarms`, `search`, host `https://radar-ai-vn.pages.dev/*` | bốn đoạn trong `permissions.md` | mục 2, bước 3 |
| Remote code | **No, I am not using remote code** | mục 2, bước 3 |
| Data usage: các ô loại dữ liệu | **không tích ô nào** (anh quyết, xem lý do trong `data-disclosure.md` mục 1) | mục 2, bước 3 |
| Ba cam kết (không bán, không dùng ngoài mục đích, không dùng cho tín dụng) | **tích cả ba** | mục 2, bước 3 |
| Privacy policy URL | `https://hco.news/chinh-sach-rieng-tu.html` | mục 2, bước 3 |
| Visibility / Regions / Pricing | Public / All regions / Free | mục 2, bước 4 |

---

## 1. Chuẩn Bị Trước Khi Nộp

1. **Trang chính sách riêng tư phải là bản mới trên mạng.** Mở `https://hco.news/chinh-sach-rieng-tu.html` và xác nhận dòng "Cập nhật lần cuối: 11 tháng 11, 2026" cùng mục 6 (Cloudflare Web Analytics, ảnh từ nhà xuất bản). Bản cũ ngày 10/11 còn hứa "không theo dõi" mà chưa nêu hai điều này; đừng nộp khi URL còn trả bản cũ. Trang lên mạng khi nhánh có thay đổi được merge vào `main` và lượt **Update AI Radar** kế tiếp deploy xong.
2. **Gói zip:** từ thư mục gốc repo chạy `python extension/sync-site.py` (tab mới khớp trang chủ trên `main`), rồi `python extension/store/build-zip.py`. Tệp tải lên: `extension/store/extension-halcyon-0.1.0.zip` (bản sao ở thư mục gốc). Gói có `manifest.json` ở gốc, 83 tệp, không có `README.md`, `sync-site.py`, thư mục `store/` hay tệp `.py`.
3. **Manifest trong gói:** Manifest V3, tên `Halcyon`, phiên bản `0.1.0`, `permissions: ["storage", "alarms", "search"]`, `host_permissions: ["https://radar-ai-vn.pages.dev/*"]`, ghi đè trang tab mới bằng `newtab.html`. Quyền `search` để ô "Tìm trên web" tìm bằng công cụ tìm kiếm mặc định của người đọc qua `chrome.search.query` (Chrome Web Store yêu cầu tab mới có ô tìm kiếm phải tôn trọng lựa chọn này). Không xin `tabs` hay quyền đọc trang web. Mọi script nằm trong gói (không có remote code).
4. **Ảnh cho trang Store:**
   - Store icon 128×128: `brand/assets/store/extension-icon-128.png`
   - Small promo tile 440×280: `brand/assets/store/promo-small.png`
   - Screenshots 1280×800: `extension/store/anh/screenshot-1-sang-1280x800.png` (sáng) và `extension/store/anh/screenshot-2-toi-1280x800.png` (tối).
   - Chụp lại ảnh khi giao diện đổi: `node brand/store-shots.js`. Lệnh cài chính thư mục `extension/` vào Chrome headless, chờ service worker của tiện ích lưu `radar-window.json` đang chạy trên mạng, báo lỗi nếu dữ liệu cũ hơn 3 giờ hoặc tab mới không có thẻ tin, rồi chụp tab mới của tiện ích ở hai giao diện.
5. **Tài khoản nhà phát triển:** [Chrome Web Store Developer Console](https://chrome.google.com/webstore/devconsole), tài khoản Google của anh. Phí đăng ký một lần 5 USD là quyết định chi tiền của anh.

---

## 2. Các Bước Trên Developer Console

### Bước 1: Tải gói lên (Upload Package)
1. Nhấn **"New Item"**.
2. Chọn `extension/store/extension-halcyon-0.1.0.zip`.
3. Console đọc manifest: Manifest V3, quyền `storage`, `alarms`, `search`, host `https://radar-ai-vn.pages.dev/*`.

### Bước 2: Store Listing
1. **Product details:**
   - **Language:** `Vietnamese`.
   - **Name:** `Halcyon`
   - **Summary (tối đa 132 ký tự):** dòng trong `listing-vi.md`:
     ```text
     Những mẩu tin AI ngắn gọn trên tab mới, kèm tìm kiếm web và bản tin lưu đọc ngoại tuyến.
     ```
   - **Description:** toàn bộ khối "Mô tả chi tiết" trong `listing-vi.md` (bản tiếng Anh trong `listing-en.md` nếu anh thêm ngôn ngữ thứ hai).
2. **Graphic assets:** icon, hai screenshots và promo tile ở mục 1.4.
3. **Category:** `News & Weather`.
4. **Official URL / Homepage:** `https://hco.news/`

Nhấn **"Save draft"**.

### Bước 3: Privacy
1. **Single purpose description:** dán nguyên văn `single-purpose.txt`:
   ```text
   Halcyon replaces the browser's new tab page with a Vietnamese-language AI news reader: curated AI stories with links to their original publishers, a web search box that searches with the browser's default search engine, and the latest edition saved on the device so stories stay readable offline.
   ```
2. **Permission justifications:** dán từng đoạn trong khối code của `permissions.md` vào ô `storage`, `alarms`, `search` và ô host permission.
3. **Remote code:** chọn "No, I am not using remote code". Mọi tệp JS nằm trong gói; trang tab mới chỉ tải dữ liệu JSON và ảnh.
4. **Data usage:** không tích loại dữ liệu nào (đề xuất; anh quyết). Nếu console có ô giải trình, dán khối code trong `data-disclosure.md` mục 1. Tích cả ba cam kết.
5. **Privacy policy:** `https://hco.news/chinh-sach-rieng-tu.html` (đã kiểm ở mục 1.1).

Nhấn **"Save draft"**.

### Bước 4: Distribution
- **Visibility:** Public. **Regions:** All regions. **Pricing:** Free.

### Bước 5: Nộp duyệt
1. Kiểm tra không còn lỗi đỏ ở góc phải.
2. Nhấn **"Submit for review"**, rồi **"Submit"** trong hộp xác nhận.

---

## 3. Sau Khi Nộp

- Google duyệt tiện ích mới thường mất vài ngày; thư báo gửi về email của tài khoản nhà phát triển.
- Nếu Google hỏi lại hoặc từ chối: chuyển nguyên văn thư cho Lucy, không sửa gói trực tiếp trên console.
- Lần cập nhật sau: tăng `version` trong `extension/manifest.json`, chạy lại mục 1.2 và 1.4, tải gói mới lên cùng mục.
