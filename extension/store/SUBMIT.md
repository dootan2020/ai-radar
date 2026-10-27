# Hướng Dẫn Nộp Extension Halcyon Lên Chrome Web Store

Tài liệu hướng dẫn từng bước chi tiết dành cho Captain để đăng ký, cấu hình và nộp tiện ích **Halcyon** lên Chrome Web Store Developer Console để được duyệt ngay trong lần gửi đầu tiên.

---

## 1. Chuẩn Bị Trước Khi Nộp

1. **Tệp gói nén extension:**
   - Chạy lệnh: `python extension/store/build-zip.py`
   - Tệp tạo ra: `extension-halcyon-0.1.0.zip` (nằm ở thư mục gốc và trong `extension/store/`).
2. **Tài khoản Google Chrome Web Store Developer:**
   - Truy cập: [Chrome Web Store Developer Console](https://chrome.google.com/webstore/devconsole)
   - Đăng nhập tài khoản Google của bạn.
   - Thanh toán phí đăng ký nhà phát triển 5 USD (thanh toán một lần duy nhất qua thẻ Visa/Mastercard).
3. **Bộ ảnh Store Assets (trong thư mục `brand/assets/store/`):**
   - **Store Icon (128×128 px):** `brand/assets/store/extension-icon-128.png`
   - **Small Promo Tile (440×280 px):** `brand/assets/store/promo-small.png`
   - **Screenshots (1280×800 px):** `brand/assets/store/new-tab-light.png` và `brand/assets/store/new-tab-dark.png` (Lucy chạy lệnh `node brand/store-shots.js` để chụp).
4. **Trang Chính sách quyền riêng tư (Privacy Policy):**
   - Đã tạo tại `site/chinh-sach-rieng-tu.html` và deploy lên:
   - URL: `https://radar-ai-vn.pages.dev/chinh-sach-rieng-tu.html`

---

## 2. Các Bước Thực Hiện Trên Chrome Web Store Developer Console

### Bước 1: Tải tệp zip lên (Upload Package)
1. Trong Developer Console, nhấn nút **"New Item"** (Mục mới).
2. Kéo thả hoặc chọn tệp `extension-halcyon-0.1.0.zip`.
3. Chờ bảng điều khiển phân tích manifest (sẽ nhận diện Manifest V3, permissions: `storage`, `alarms`, `search`, host: `https://radar-ai-vn.pages.dev/*`).

---

### Bước 2: Điền thông tin Store Listing (Trang thông tin trên Cửa hàng)
Chuyển tới thẻ **Store Listing**:

1. **Product details (Chi tiết sản phẩm):**
   - **Language:** Chọn `Vietnamese` (Tiếng Việt) hoặc `English`.
   - **Name:** `Halcyon`
   - **Summary (Mô tả ngắn - tối đa 132 ký tự):**
     *Mở tệp `extension/store/listing-vi.md` và sao chép dòng sau:*
     ```text
     Những mẩu tin AI ngắn gọn trên tab mới, kèm tìm kiếm web và bản tin lưu đọc ngoại tuyến.
     ```
   - **Description (Mô tả chi tiết):**
     *Sao chép toàn bộ phần Mô tả chi tiết trong tệp `extension/store/listing-vi.md`.*

2. **Graphic assets (Hình ảnh đại diện):**
   - **Store Icon (128x128):** Tải lên tệp `brand/assets/store/extension-icon-128.png`.
   - **Screenshots (1280x800):** Tải lên 2 ảnh chụp màn hình:
     + `brand/assets/store/new-tab-light.png` (Giao diện sáng)
     + `brand/assets/store/new-tab-dark.png` (Giao diện tối)
   - **Small promo tile (440x280):** Tải lên tệp `brand/assets/store/promo-small.png`.

3. **Categorization (Phân loại):**
   - **Category (Danh mục chính):** `News & Weather` (Tin tức & Thời tiết)
   - **Additional Category (Danh mục phụ nếu có):** `Productivity` (Năng suất)

4. **Official URL (Trang web chính thức):**
   - Nhập: `https://radar-ai-vn.pages.dev/`

Nhấn **"Save draft"** (Lưu bản nháp).

---

### Bước 3: Điền thẻ Privacy (Quyền riêng tư & Giải trình kỹ thuật)
*Đây là bước quan trọng nhất quyết định việc duyệt ngay lần đầu.*

Chuyển tới thẻ **Privacy**:

1. **Single Purpose Description (Mô tả mục đích duy nhất):**
   *Sao chép nguyên văn từ tệp `extension/store/single-purpose.txt`:*
   ```text
   Halcyon provides a curated Vietnamese-language AI news feed on the browser's new tab page, offers convenient web search using the user's default search engine without hijacking or redirects, and stores the latest edition locally so stories remain readable offline.
   ```

2. **Permission Justifications (Giải trình từng quyền yêu cầu):**
   *Sao chép các đoạn tương ứng trong tệp `extension/store/permissions.md`:*
   - Ô **`storage`**:
     ```text
     The "storage" permission is required to store the curated AI news snapshot (radarWindow), fetch timestamps, and reader theme preferences locally in chrome.storage.local. This ensures instant page rendering on every new tab and enables offline reading of the latest cached stories without network connectivity.
     ```
   - Ô **`alarms`**:
     ```text
     The "alarms" permission is required to schedule a periodic background task every 30 minutes via chrome.alarms. This refreshes the local news cache with new editorial stories in the background without keeping the service worker running continuously, conserving battery and memory.
     ```
   - Ô **`search`**:
     ```text
     The "search" permission is required to execute user-initiated web searches from the new tab search form using the Chrome Search API (chrome.search.query). This guarantees searches strictly utilize the user's configured default search engine in Chrome, without hijacking, modifying, or redirecting queries.
     ```
   - Ô **Host permission `https://radar-ai-vn.pages.dev/*`**:
     ```text
     This host permission is required to fetch static JSON data feeds (radar-window.json, radar-ui.json, arena.json, editor-picks.json) and load news illustration images from the official Halcyon static site hosted on Cloudflare Pages. No user data or browsing telemetry is transmitted to this origin.
     ```

3. **Data Usage (Khai báo thu thập dữ liệu):**
   - Tại danh sách các loại dữ liệu người dùng: **KHÔNG TÍCH CHỌN BẤT KỲ Ô NÀO** (vì tiện ích không thu thập dữ liệu cá nhân hay lịch sử duyệt web).
   - Ô giải trình **Data usage explanation**:
     *Sao chép từ tệp `extension/store/data-disclosure.md`:*
     ```text
Halcyon does not collect, upload, sell, or share personal data, browsing history, or telemetry. To provide news data and article thumbnails, the extension contacts https://radar-ai-vn.pages.dev/, https://hn.algolia.com/, https://huggingface.co/, https://avatars.githubusercontent.com/, https://opengraph.githubassets.com/, https://cdn-thumbnails.huggingface.co/, and https://i.ytimg.com/. When you choose to add an event to your calendar, it opens https://calendar.google.com/. Those services receive ordinary browser request data such as your IP address. The extension keeps its news snapshot and refresh timestamp in chrome.storage.local and its theme, reading state, and cached Hugging Face avatar URLs in localStorage on your device. Search queries go directly through Chrome to your default search provider.

1. No Personal Information: The extension does not collect names, email addresses, location, device identifiers, credentials, or browsing history. Network providers may receive ordinary request data, including IP address, when the browser connects to them.
2. Local Storage Only: News snapshot and refresh timestamp are kept in chrome.storage.local. Theme preference, reading state, and cached Hugging Face avatar URLs are kept in localStorage on the device; this data is not uploaded.
     3. No Search Tracking: Web searches initiated from the new tab page are executed directly through the browser's default search engine via chrome.search.query, without interception, logging, or redirection.
4. External Services: Halcyon's site provides news data; Algolia provides Hacker News stories; Hugging Face provides papers, trending models, and avatars; GitHub avatar and Open Graph hosts, Hugging Face thumbnails, and YouTube provide article images; Google Calendar opens only when selected by the user. Ordinary browser request data such as IP address is sent to the contacted provider. No Halcyon account, browsing-history, or local reader data is attached. See the Privacy Policy for the complete host list and purposes.
     ```

4. **Certifications (3 cam kết bắt buộc):**
   *Tích chọn (Check) vào cả 3 ô vuông:*
   - [x] **I certify that the item will not sell user data to third parties, outside of the approved use cases.**
   - [x] **I certify that the item will not use or transfer user data for purposes that are unrelated to the item's core functionality.**
   - [x] **I certify that the item will not use or transfer user data to determine creditworthiness or for lending purposes.**

5. **Privacy Policy (Đường dẫn chính sách riêng tư):**
   - Nhập: `https://radar-ai-vn.pages.dev/chinh-sach-rieng-tu.html`

Nhấn **"Save draft"** (Lưu bản nháp).

---

### Bước 4: Phân phối (Distribution)
Chuyển tới thẻ **Distribution**:
1. **Visibility:** Chọn **Public** (Công khai).
2. **Regions:** Chọn **All regions** (Tất cả quốc gia/vùng lãnh thổ).
3. **Pricing:** Chọn **Free** (Miễn phí).

---

### Bước 5: Nộp Duyệt (Submit for Review)
1. Kiểm tra lại góc trên bên phải màn hình: Đảm bảo không còn thông báo lỗi màu đỏ nào.
2. Nhấn nút **"Submit for review"** màu xanh.
3. Một hộp thoại xác nhận hiện ra, nhấn **"Submit"**.

---

## 3. Thời Gian Duyệt & Lưu Ý
- Thời gian Google duyệt tiện ích mới thông thường: từ **24 đến 72 giờ** (1 - 3 ngày làm việc).
- Vì toàn bộ mã nguồn tuân thủ nghiêm ngặt Manifest V3, không dùng remote code, không inline script, quyền hạn tối thiểu và giải trình trung thực, tỷ lệ được duyệt ngay lần đầu là rất cao.
- Khi có thông báo từ Google gửi về email quản trị viên:
  - Nếu duyệt thành công: Extension sẽ tự động xuất hiện trên Chrome Web Store trong vòng vài giờ.
  - Nếu có bất kỳ câu hỏi phản hồi nào từ đội ngũ Google: Báo lại cho team kỹ thuật để hỗ trợ ngay lập tức.
