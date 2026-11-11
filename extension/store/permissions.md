# Giải Trình Quyền Của Extension (Permissions Justification)

*Sao chép từng đoạn tương ứng để dán vào các ô giải trình quyền trên Chrome Web Store Developer Dashboard (mục Privacy -> Permission justifications). Manifest chỉ xin `storage`, `alarms` và một host permission; ô tìm kiếm mở thẳng trang kết quả của Google nên không cần quyền `search`.*

---

### 1. `storage`
```
The "storage" permission is used to keep the latest curated AI news snapshot (radarWindow) and its refresh timestamp in chrome.storage.local. The new tab draws this saved edition immediately, without waiting for the network, and the stories stay readable offline. Nothing in this storage is uploaded.
```
*(Tiếng Việt: Quyền "storage" dùng để lưu bản tin AI gần nhất (radarWindow) và mốc thời gian cập nhật trong chrome.storage.local, để tab mới hiện ngay và vẫn đọc được khi mất mạng. Không dữ liệu nào trong bộ nhớ này được tải lên.)*

---

### 2. `alarms`
```
The "alarms" permission schedules one chrome.alarms task every 30 minutes that wakes the service worker to refresh the saved news snapshot, so the worker does not have to keep running in the background.
```
*(Tiếng Việt: Quyền "alarms" đặt một lịch mỗi 30 phút đánh thức service worker để làm mới bản tin đã lưu, nên tiến trình nền không phải chạy liên tục.)*

---

### 3. Host Permission: `https://radar-ai-vn.pages.dev/*`
```
This is Halcyon's own static site on Cloudflare Pages. The service worker fetches the public news snapshot data/radar-window.json from it, and the new tab loads Halcyon's other public JSON files (radar-ui.json, arena.json, field-rankings.json, radar-search.json, feed-images.json, editor-picks.json) and its pictures. Like any web request, the server receives ordinary request data such as the IP address; Halcyon attaches no personal data or browsing history.
```
*(Tiếng Việt: Đây là site tĩnh của chính Halcyon trên Cloudflare Pages. Service worker tải bản tin công khai `data/radar-window.json`, tab mới tải các tệp JSON công khai khác và ảnh của Halcyon. Máy chủ nhận dữ liệu yêu cầu thông thường như địa chỉ IP; Halcyon không đính kèm dữ liệu cá nhân hay lịch sử duyệt web.)*

### Các dịch vụ ngoài khác được tiện ích liên hệ (không cần quyền)

Tab mới còn gửi yêu cầu tới: `hn.algolia.com` (tin Hacker News), `huggingface.co` (bài báo, mô hình, avatar), `avatars.githubusercontent.com` và `opengraph.githubassets.com` (ảnh GitHub), `cdn-thumbnails.huggingface.co` (ảnh Hugging Face), `i.ytimg.com` (ảnh video), `api.open-meteo.com` (thời tiết của thành phố người đọc chọn), `ssl.gstatic.com` (biểu tượng dịch vụ Google), và máy chủ ảnh của các nhà xuất bản (ảnh minh họa tin tải thẳng từ nguồn gốc). Các liên kết `www.google.com/search`, `calendar.google.com`, các ứng dụng Google và `creativecommons.org` chỉ mở khi người đọc bấm. Mỗi dịch vụ nhận dữ liệu yêu cầu thông thường như địa chỉ IP. Khai báo đầy đủ nằm trong `data-disclosure.md` và trang chính sách riêng tư.
