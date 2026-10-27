# Giải Trình Quyền Của Extension (Permissions Justification)

*Sao chép từng đoạn tương ứng để dán vào các ô giải trình quyền trên Chrome Web Store Developer Dashboard (mục Privacy -> Permission justifications).*

---

### 1. `storage`
```
The "storage" permission is required to store the curated AI news snapshot (radarWindow), fetch timestamps, and reader theme preferences locally in chrome.storage.local. This ensures instant page rendering on every new tab and enables offline reading of the latest cached stories without network connectivity.
```
*(Tiếng Việt: Quyền "storage" dùng để lưu bản chụp tin tức AI (radarWindow), mốc thời gian cập nhật và tùy chọn giao diện sáng/tối cục bộ trong chrome.storage.local. Điều này giúp tab mới mở tức thì không bị giật và cho phép đọc ngoại tuyến khi không có mạng).*

---

### 2. `alarms`
```
The "alarms" permission is required to schedule a periodic background task every 30 minutes via chrome.alarms. This refreshes the local news cache with new editorial stories in the background without keeping the service worker running continuously, conserving battery and memory.
```
*(Tiếng Việt: Quyền "alarms" dùng để định kỳ đánh thức service worker mỗi 30 phút để tải bản tin AI mới nhất vào bộ nhớ đệm, tránh việc tiến trình nền phải chạy liên tục gây tốn RAM và pin của máy).*

---

### 3. `search`
```
The "search" permission is required to execute user-initiated web searches from the new tab search form using the Chrome Search API (chrome.search.query). This guarantees searches strictly utilize the user's configured default search engine in Chrome, without hijacking, modifying, or redirecting queries.
```
*(Tiếng Việt: Quyền "search" dùng để thực hiện truy vấn tìm kiếm từ ô tìm kiếm trên tab mới qua API chrome.search.query. Thao tác này đảm bảo tìm kiếm hoàn toàn thông qua công cụ mặc định do người dùng tự cài đặt trong Chrome, không can thiệp, không chuyển hướng và không thay đổi kết quả).*

---

### 4. Host Permission: `https://radar-ai-vn.pages.dev/*`
```
This host permission is required to fetch static JSON data feeds (radar-window.json, radar-ui.json, arena.json, editor-picks.json) and load news illustration images from the official Halcyon static site hosted on Cloudflare Pages. As with any web request, the service receives ordinary browser request data such as the IP address. Halcyon does not attach personal data or browsing telemetry.
```
*(Tiếng Việt: Quyền truy cập máy chủ này cần thiết để tải các tệp dữ liệu JSON tĩnh và hình ảnh minh họa bài viết từ máy chủ tĩnh chính thức của Halcyon trên Cloudflare Pages. Máy chủ nhận dữ liệu yêu cầu thông thường của trình duyệt như địa chỉ IP; Halcyon không đính kèm dữ liệu cá nhân hay lịch sử duyệt web).* 

### Các dịch vụ ngoài khác được tiện ích liên hệ

Ngoài host permission của Halcyon, tab mới tải dữ liệu Hacker News từ `hn.algolia.com`; dữ liệu bài báo, mô hình và avatar từ `huggingface.co`; ảnh avatar GitHub từ `avatars.githubusercontent.com`; ảnh xem trước GitHub từ `opengraph.githubassets.com`; ảnh thu nhỏ Hugging Face từ `cdn-thumbnails.huggingface.co`; ảnh video từ `i.ytimg.com`; và mở `calendar.google.com` khi người dùng chọn thêm sự kiện vào lịch. `creativecommons.org` được dùng làm liên kết giấy phép ghi công. Các dịch vụ nhận dữ liệu yêu cầu thông thường của trình duyệt, chẳng hạn địa chỉ IP. Mục đích và khai báo đầy đủ nằm trong `data-disclosure.md` và trang chính sách riêng tư.
