# Giải Trình Quyền Của Extension (Permissions Justification)

*Sao chép từng đoạn tương ứng để dán vào các ô giải trình quyền trên Chrome Web Store Developer Dashboard (mục Privacy -> Permission justifications). Manifest xin `storage`, `alarms`, `search` và một host permission; ô "Tìm trên web" tìm bằng công cụ tìm kiếm mặc định của trình duyệt qua `chrome.search.query`, nên cần quyền `search`.*

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

### 3. `search`
```
The "search" permission is used only by the new tab's web search box. When the user submits a query, the page calls chrome.search.query with the typed text and disposition CURRENT_TAB, so Chrome runs the search with the user's own default search engine in the same tab. Halcyon does not choose, change, or redirect the search provider, and it does not read, log, store, or forward the query. An empty box does nothing.
```
*(Tiếng Việt: Quyền "search" chỉ dùng cho ô tìm kiếm web trên tab mới. Khi người dùng gửi từ khóa, trang gọi chrome.search.query với từ khóa đã gõ và disposition CURRENT_TAB, để Chrome tìm bằng công cụ tìm kiếm mặc định của chính người dùng ngay trong tab đó. Halcyon không chọn, không đổi, không chuyển hướng nhà cung cấp tìm kiếm, và không đọc, ghi, lưu hay chuyển tiếp từ khóa. Ô trống thì không làm gì.)*

---

### 4. Host Permission: `https://radar-ai-vn.pages.dev/*`
```
This is Halcyon's own static site on Cloudflare Pages. The service worker fetches the public news snapshot data/radar-window.json from it, and the new tab loads Halcyon's other public JSON files (radar-ui.json, arena.json, field-rankings.json, radar-search.json, feed-images.json, editor-picks.json) and its pictures. Like any web request, the server receives ordinary request data such as the IP address; Halcyon attaches no personal data or browsing history.
```
*(Tiếng Việt: Đây là site tĩnh của chính Halcyon trên Cloudflare Pages. Service worker tải bản tin công khai `data/radar-window.json`, tab mới tải các tệp JSON công khai khác và ảnh của Halcyon. Máy chủ nhận dữ liệu yêu cầu thông thường như địa chỉ IP; Halcyon không đính kèm dữ liệu cá nhân hay lịch sử duyệt web.)*

### Các dịch vụ ngoài khác được tiện ích liên hệ (không cần quyền)

Tab mới còn gửi yêu cầu tới: `hn.algolia.com` (tin Hacker News), `huggingface.co` (bài báo, mô hình, avatar), `github.com` (logo chủ repo), `avatars.githubusercontent.com` và `opengraph.githubassets.com` (ảnh GitHub), `cdn-thumbnails.huggingface.co` (ảnh Hugging Face), `i.ytimg.com` (ảnh video), `api.open-meteo.com` (thời tiết của thành phố người đọc chọn), `ssl.gstatic.com` (biểu tượng dịch vụ Google), và máy chủ ảnh của các nhà xuất bản (ảnh minh họa tin tải thẳng từ nguồn gốc). Từ khóa trong ô "Tìm trên web" do Chrome gửi tới công cụ tìm kiếm mặc định của người đọc, không qua Halcyon. Các liên kết `calendar.google.com`, các ứng dụng Google và `creativecommons.org` chỉ mở khi người đọc bấm. Mỗi dịch vụ nhận dữ liệu yêu cầu thông thường như địa chỉ IP. Khai báo đầy đủ nằm trong `data-disclosure.md` và trang chính sách riêng tư.
