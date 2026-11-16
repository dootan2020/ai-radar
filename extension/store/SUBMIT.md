# Hướng Dẫn Nộp Bản Cập Nhật Halcyon 0.1.2 Lên Chrome Web Store

Bản 0.1.1 đã được duyệt. Đây là các bước để anh Tuấn nộp bản **0.1.2** trên Chrome Web Store Developer Console của chính anh. Đăng nhập, tải gói lên và bấm nộp là việc của anh; console không script được nên anh tự dán từng ô theo bảng ở mục 0.

**Bản 0.1.2 đổi gì:** giao diện mới của đợt rà soát 16/11 (tin nổi bật, "Vừa đăng", lớp vỏ, thẻ Sự kiện luôn có "Xem tất cả", chấm carousel chạm nửa trái/phải); mọi liên kết người đọc bấm (logo, "Bản tin sáng", trang từng tin, "Sao chép liên kết", trang Nguồn, menu) mở trên `https://hco.news/` thay vì `radar-ai-vn.pages.dev`. **Không đổi quyền:** `permissions` và `host_permissions` giống hệt 0.1.1, vì một quyền máy chủ mới trong bản cập nhật làm Chrome tạm tắt tiện ích ở máy người đang dùng cho tới khi họ chấp nhận lại ([Permission warnings](https://developer.chrome.com/docs/extensions/develop/concepts/permission-warnings)).

---

## 0. Từng ô trên console: giữ, đổi hay dán lại

| Tab trên console | Ô | 0.1.2 | Lấy từ |
| --- | --- | --- | --- |
| Package | Upload New Package | **ĐỔI**: `extension-halcyon-0.1.2.zip` | mục 1.2 |
| Store listing | Name | giữ: `Halcyon` | — |
| Store listing | Summary | giữ (khối "Mô tả ngắn" trong `listing-vi.md`) | `listing-vi.md` |
| Store listing | Description | giữ (khối "Mô tả chi tiết" trong `listing-vi.md`) | `listing-vi.md` |
| Store listing | Category / Language | giữ: `News & Weather` / `Vietnamese` | — |
| Store listing | Store icon 128×128 | giữ: `brand/assets/store/extension-icon-128.png` | mục 1.4 |
| Store listing | Screenshots 1280×800 | **ĐỔI**: xoá hai ảnh cũ, tải hai ảnh mới chụp ngày 16/11 | mục 1.4 |
| Store listing | Small promo tile 440×280 | **ĐỔI** nếu console còn ảnh có mỏ chim trắng trên chữ "y": tải `extension/store/anh/small-promo-tile-440x280.png` | mục 1.4 |
| Store listing | Official URL / Homepage | giữ: `https://hco.news/` | — |
| Privacy practices | Single purpose | **DÁN LẠI** nguyên văn `single-purpose.txt` (chữ không đổi; ô này phải dán lại mỗi khi gói thay đổi) | mục 2, bước 3 |
| Privacy practices | `storage`, `alarms`, `search` | giữ (ba khối đầu trong `permissions.md`, chữ không đổi) | `permissions.md` |
| Privacy practices | Host permission `https://radar-ai-vn.pages.dev/*` | giữ (khối 4 trong `permissions.md`, chữ không đổi) | `permissions.md` |
| Privacy practices | Remote code | giữ: **No, I am not using remote code** | — |
| Privacy practices | Data usage: các ô loại dữ liệu | giữ: **không tích ô nào** | `data-disclosure.md` mục 1 |
| Privacy practices | Ô giải trình dữ liệu (nếu console có) | **ĐỔI**: dán lại khối code `data-disclosure.md` mục 1 (thêm dòng `hco.news`) | `data-disclosure.md` |
| Privacy practices | Ba cam kết | giữ: **tích cả ba** | — |
| Privacy practices | Privacy policy URL | giữ: `https://hco.news/chinh-sach-rieng-tu.html` | — |
| Distribution | Visibility / Regions / Pricing | giữ: Public / All regions / Free | — |

---

## 1. Chuẩn Bị Trước Khi Nộp

1. **Trang chính sách riêng tư** `https://hco.news/chinh-sach-rieng-tu.html` vẫn ghi "Cập nhật lần cuối: 11 tháng 11, 2026", có mục 6 (Cloudflare Web Analytics, ảnh từ nhà xuất bản) và khai `radar-ai-vn.pages.dev`. Bản 0.1.2 không đổi dữ liệu thu thập hay quyền, nên trang không cần sửa.
2. **Gói zip:** dựng từ `main` sau khi PR 0.1.2 đã merge. Từ thư mục gốc repo chạy `python extension/sync-site.py`, rồi `python extension/store/build-zip.py`. Tệp tải lên: `extension/store/extension-halcyon-0.1.2.zip` (bản sao ở thư mục gốc). Gói có `manifest.json` ở gốc, 83 tệp, không có `README.md`, `sync-site.py`, thư mục `store/` hay tệp `.py`.
3. **Manifest trong gói:** Manifest V3, tên `Halcyon`, phiên bản `0.1.2`, `permissions: ["storage", "alarms", "search"]`, `host_permissions: ["https://radar-ai-vn.pages.dev/*"]`, ghi đè trang tab mới bằng `newtab.html`. Quyền `search` để ô "Tìm trên web" tìm bằng công cụ tìm kiếm mặc định của người đọc qua `chrome.search.query` (Chrome Web Store yêu cầu tab mới có ô tìm kiếm phải tôn trọng lựa chọn này). Không xin `tabs` hay quyền đọc trang web. Mọi script nằm trong gói (không có remote code). Liên kết tới `hco.news` là thẻ `<a>` thường, không cần quyền.
4. **Ảnh cho trang Store:**
   - Store icon 128×128: `brand/assets/store/extension-icon-128.png` (không đổi).
   - Small promo tile 440×280: `extension/store/anh/small-promo-tile-440x280.png`, giống hệt `brand/assets/store/promo-small.png` (wordmark chỉ có chữ, từ `python brand/build-assets.py` rồi `python brand/export-png.py`).
   - Screenshots 1280×800: `extension/store/anh/screenshot-1-sang-1280x800.png` (sáng) và `extension/store/anh/screenshot-2-toi-1280x800.png` (tối), chụp 16/11 từ tab mới của chính gói 0.1.2 với dữ liệu thật.
   - Chụp lại ảnh khi giao diện đổi: `node brand/store-shots.js`. Lệnh cài chính thư mục `extension/` vào Chrome headless, chờ service worker của tiện ích lưu `radar-window.json` đang chạy trên mạng, báo lỗi nếu dữ liệu cũ hơn 3 giờ hoặc tab mới không có thẻ tin, rồi chụp tab mới của tiện ích ở hai giao diện.

---

## 2. Các Bước Trên Developer Console

### Bước 1: Tải gói mới
1. Mở [Chrome Web Store Developer Console](https://chrome.google.com/webstore/devconsole), chọn mục **Halcyon** (không bấm "New Item").
2. Tab **Package** → **Upload New Package** → chọn `extension/store/extension-halcyon-0.1.2.zip`.
3. Console đọc manifest: phiên bản `0.1.2`, quyền `storage`, `alarms`, `search`, host `https://radar-ai-vn.pages.dev/*`. Nếu console báo quyền mới thì dừng, chưa nộp, và chuyển nguyên văn cho Lucy: gói đúng không xin quyền mới.

### Bước 2: Store Listing
1. Name, Summary, Description, Category, Language, Official URL: giữ như 0.1.1 (bảng mục 0).
2. **Graphic assets:** xoá hai screenshot cũ, tải hai ảnh mới ở mục 1.4. Kiểm promo tile: nếu console còn ảnh có mỏ chim trắng trên chữ "y", thay bằng ảnh ở mục 1.4.

Nhấn **"Save draft"**.

### Bước 3: Privacy practices
1. **Single purpose description:** dán lại nguyên văn `single-purpose.txt`:
   ```text
   Halcyon replaces the browser's new tab page with a Vietnamese-language AI news reader: curated AI stories with links to their original publishers, a web search box that searches with the browser's default search engine, and the latest edition saved on the device so stories stay readable offline.
   ```
2. **Permission justifications:** bốn ô `storage`, `alarms`, `search` và host permission giữ nguyên chữ của 0.1.1 (bốn khối code trong `permissions.md`). Nếu console để trống ô nào thì dán khối tương ứng.
3. **Remote code:** "No, I am not using remote code".
4. **Data usage:** không tích loại dữ liệu nào. Nếu console có ô giải trình, dán lại khối code trong `data-disclosure.md` mục 1 (có thêm dòng `hco.news`). Tích cả ba cam kết.
5. **Privacy policy:** `https://hco.news/chinh-sach-rieng-tu.html`.

Nhấn **"Save draft"**.

### Bước 4: Distribution
- Giữ: Public, All regions, Free.

### Bước 5: Nộp duyệt
1. Kiểm tra không còn lỗi đỏ ở góc phải.
2. Nhấn **"Submit for review"**, rồi **"Submit"** trong hộp xác nhận. Người đang dùng 0.1.1 không thấy gì thay đổi cho tới khi bản mới được xuất bản ([Update your Chrome Web Store item](https://developer.chrome.com/docs/webstore/update)). Muốn tự chọn lúc lên, bỏ dấu ô xuất bản tự động trong hộp xác nhận; sau khi duyệt xong có 30 ngày để bấm xuất bản.

---

## 3. Đã Kiểm Theo Chính Sách Chrome Web Store (16/11/2026)

Nguồn: [Program Policies](https://developer.chrome.com/docs/webstore/program-policies/policies), [Supplying Images](https://developer.chrome.com/docs/webstore/images), [Update your item](https://developer.chrome.com/docs/webstore/update), [Permission warnings](https://developer.chrome.com/docs/extensions/develop/concepts/permission-warnings), mở ngày 16/11/2026.

| Điểm chính sách | Halcyon 0.1.2 |
| --- | --- |
| API Use: ghi đè tab mới phải qua URL Overrides API | `chrome_url_overrides.newtab = newtab.html` |
| Quality Guidelines: tab mới có ô tìm kiếm phải tôn trọng cài đặt tìm kiếm của người dùng | ô "Tìm trên web" gọi `chrome.search.query` (công cụ mặc định của người đọc), không đổi nhà cung cấp |
| Single purpose: một mục đích hẹp, dễ hiểu | trình đọc tin AI trên tab mới; ô tìm web, thời tiết, lịch là phần của trang tab mới, không thêm tính năng ngoài mục đích trong 0.1.2 |
| Use of Permissions: xin quyền hẹp nhất | `storage`, `alarms`, `search` và một host; 0.1.2 không thêm hay bớt quyền |
| Privacy Policy and Disclosure | chính sách 11/11 khai các máy chủ tiện ích liên hệ (test `test_privacy_policy_discloses_every_external_host_in_extension_sources`), có `hco.news` |
| Code Readability / MV3: không remote code, không làm rối mã | mọi script nằm trong gói, không minify che giấu, không `<script>` ngoài (`sync-site.py` chặn khi dựng) |
| Misleading or Unexpected Behavior: mô tả và ảnh khớp sản phẩm | ảnh chụp từ chính gói 0.1.2; listing không hứa tính năng đã bỏ |
| Ảnh: screenshot 1280×800, góc vuông, phủ kín; promo 440×280 | hai ảnh 1280×800 chụp toàn khung; promo 440×280 |

Một điểm chưa khớp hướng dẫn ảnh (không phải chính sách bắt buộc): trang Supplying Images khuyên promo tile tránh chữ, còn promo hiện có dòng "Những mẩu tin AI ngắn gọn". Anh quyết có bỏ dòng này ở bản sau hay không.

---

## 4. Sau Khi Nộp

- Bản cập nhật được duyệt như một mục mới; thời gian tùy mức thay đổi. Thư báo gửi về email của tài khoản nhà phát triển.
- Nếu Google hỏi lại hoặc từ chối: chuyển nguyên văn thư cho Lucy, không sửa gói trực tiếp trên console.
- Lần cập nhật sau: tăng `version` trong `extension/manifest.json`, chạy lại mục 1.2 và 1.4, tải gói mới lên tab Package của cùng mục, và dán lại ô Single purpose.
