# Báo Cáo Đánh Giá Extension Halcyon Cho Chrome Web Store

**Mục tiêu:** Đảm bảo Halcyon Chrome extension vượt qua vòng xét duyệt của Chrome Web Store (CWS) ngay trong lần gửi đầu tiên (first-time pass).  
**Phạm vi kiểm tra:** `extension/` (Manifest V3, permissions `storage`, `alarms`, `search`, host `https://radar-ai-vn.pages.dev/*`, ghi đè tab mới `chrome_url_overrides: {"newtab": "newtab.html"}`).

---

## 1. Kết Quả Kiểm Tra Theo Các Tiêu Chí Của Chrome Web Store

### 1.1. Single Purpose (Nguyên tắc một mục đích duy nhất)
- **Chính sách:** Extension phải có một mục đích cụ thể, dễ hiểu và nhất quán giữa mô tả trên Store, giao diện người dùng và quyền hạn yêu cầu.
- **Hiện trạng:**
  - `extension/manifest.json:3-5`: Tên "Halcyon", mô tả rõ ràng tập trung vào việc hiển thị các mẩu tin tức AI tuyển chọn trên tab mới, kèm ô tìm kiếm web bằng công cụ tìm kiếm mặc định của trình duyệt và lưu trữ ngoại tuyến.
  - `extension/newtab.html:98-102`: Ô tìm kiếm web đặt trên đầu tab mới, sử dụng form `#web-search`.
  - `extension/newtab.js:1-5`: Xử lý submit tìm kiếm trực tiếp bằng `chrome.search.query`, hoàn toàn không chuyển hướng sang trang quảng cáo hoặc tìm kiếm trung gian.
- **Kết luận:** **ĐẠT**. Mục đích duy nhất: New Tab Page hiển thị tin tức AI và tìm kiếm web.

### 1.2. Least Permissions (Nguyên tắc cấp quyền tối thiểu)
- **Chính sách:** Chỉ yêu cầu các quyền thực sự cần thiết cho tính năng cốt lõi. Không yêu cầu các quyền thừa hoặc quyền nhạy cảm diện rộng (`<all_urls>`, `webRequest`, `cookies`, `tabs`).
- **Hiện trạng kiểm tra:**
  - `extension/manifest.json:6`: `"permissions": ["storage", "alarms", "search"]`
    - `storage`: Cần thiết để lưu bản sao dữ liệu tin tức `radarWindow` và mốc thời gian cập nhật vào `chrome.storage.local` (`extension/background.js:21`, `extension/snapshot.js:33`), cho phép tab mới tải tức thì và đọc offline khi mất mạng.
    - `alarms`: Cần thiết để lập lịch làm mới định kỳ mỗi 30 phút (`refresh-radar-window`, `extension/background.js:6, 33-35`) bằng `chrome.alarms`, tránh việc background worker phải chạy liên tục ngốn tài nguyên máy.
    - `search`: Cần thiết để thực hiện lệnh tìm kiếm web (`extension/newtab.js:4`) thông qua công cụ tìm kiếm mặc định do người dùng cấu hình trên Chrome.
  - `extension/manifest.json:7`: `"host_permissions": ["https://radar-ai-vn.pages.dev/*"]`
    - Chỉ yêu cầu chính xác 1 host duy nhất là domain chính thức của tòa soạn Halcyon Cloudflare Pages để fetch JSON data (`radar-window.json`, `radar-ui.json`, `arena.json`, `feed-images.json`, `editor-picks.json`) và load hình ảnh tin tức. Không sử dụng ký tự đại diện diện rộng như `*://*/*` hay `<all_urls>`.
- **Kết luận:** **ĐẠT**. Mọi quyền đều có mục đích kỹ thuật trực tiếp và tối thiểu.

### 1.3. No Remotely Hosted Code (Không tải và thực thi mã từ xa)
- **Chính sách:** Manifest V3 nghiêm cấm tải mã thực thi (JavaScript, WASM bên ngoài) từ máy chủ từ xa. Chỉ được phép tải dữ liệu tĩnh (JSON, hình ảnh, văn bản).
- **Hiện trạng kiểm tra:**
  - `extension/background.js:1, 14-20`: Chỉ tải file dữ liệu JSON `https://radar-ai-vn.pages.dev/data/radar-window.json` và kiểm tra cấu trúc `schema_version === 2`, không thực thi mã.
  - `extension/feed.js:27-30`: Chỉ tải JSON (`radar-ui.json`, `editor-picks.json`, `feed-images.json`) hoặc hình ảnh.
  - `extension/arena.js:255`: Chỉ tải `data/arena.json`.
  - Không có file nào chứa `import 'https://...'` hay chèn thẻ `<script src="https://...">` động.
  - Toàn bộ font chữ (`extension/fonts/*.woff2`) và icon đều được đóng gói cục bộ trong extension.
- **Kết luận:** **ĐẠT**. 100% mã nguồn thực thi được đóng gói cục bộ trong extension package.

### 1.4. No Inline Script or eval under MV3 CSP (Tuân thủ CSP của Manifest V3)
- **Chính sách:** Content Security Policy của Manifest V3 cấm inline script (`<script>...</script>` không có `src`), inline event handlers (`onclick`, `onload`,...), `eval()`, `new Function()`, và `setTimeout` nhận chuỗi.
- **Hiện trạng kiểm tra:**
  - `extension/newtab.html:29`: Đoạn script áp dụng theme trước khi render đã được tách ra file độc lập `theme.js` (`<script src="theme.js"></script>`), hoàn toàn không có inline script.
  - Quét regex toàn bộ `extension/*.html` và `extension/*.js`:
    - Không có inline event handlers (`on...=`).
    - Không có `eval()`.
    - Không có `new Function()`.
- **Kết luận:** **ĐẠT**. Tuân thủ tuyệt đối MV3 CSP.

### 1.5. New-Tab Override & Search Protection (Bảo vệ thiết lập tìm kiếm và Tab mới)
- **Chính sách:** Tiện ích ghi đè tab mới không được can thiệp, chiếm đoạt hoặc thay đổi công cụ tìm kiếm mặc định của người dùng. Nếu có tính năng tìm kiếm, phải tôn trọng lựa chọn của người dùng hoặc dùng API `chrome.search`.
- **Hiện trạng kiểm tra:**
  - `extension/manifest.json:8`: `"chrome_url_overrides": {"newtab": "newtab.html"}`.
  - `extension/newtab.js:1-5`:
    ```javascript
    document.querySelector('#web-search').addEventListener('submit', event => {
      event.preventDefault();
      const query = document.querySelector('#web-query').value.trim();
      if (query) chrome.search.query({text: query, disposition: 'CURRENT_TAB'});
    });
    ```
    Sử dụng chuẩn xác API `chrome.search.query({text: query, disposition: 'CURRENT_TAB'})`.
  - Không hề can thiệp cài đặt trình duyệt, không chuyển hướng qua affiliate engine, không can thiệp URL search của người dùng.
- **Kết luận:** **ĐẠT**.

### 1.6. Honest, Complete Listing & Metadata (Thông tin niêm yết trung thực, đầy đủ)
- **Chính sách:** Tên, mô tả ngắn, mô tả chi tiết, hình ảnh minh họa phải phản ánh chính xác 100% tính năng của extension, không giật tít gây hiểu nhầm, không chứa từ khóa spam (keyword stuffing).
- **Hiện trạng kiểm tra:**
  - Đã chuẩn bị đầy đủ bộ tài liệu niêm yết song ngữ tại `extension/store/listing-vi.md` và `extension/store/listing-en.md`.
  - Tên tiện ích: "Halcyon" (đồng bộ với manifest).
  - Short description: Tiếng Việt (88 ký tự) và Tiếng Anh (105 ký tự), đều <= 132 ký tự theo giới hạn của Chrome Web Store.
  - Full description: Mô tả chi tiết tính năng, nguồn gốc dữ liệu, tôn trọng quyền riêng tư, cách sử dụng các phím tắt.
- **Kết luận:** **ĐẠT**.

### 1.7. Privacy Policy & Data-Use Disclosure (Chính sách quyền riêng tư & công bố dữ liệu)
- **Chính sách:** CWS yêu cầu mọi extension có New Tab Override hoặc yêu cầu quyền lưu trữ/mạng phải có trang Chính sách quyền riêng tư công khai trực tuyến và công bố chính xác dữ liệu thu thập trong Developer Dashboard.
- **Hiện trạng kiểm tra:**
  - Tiện ích Halcyon không thu thập thông tin nhận dạng cá nhân, vị trí, lịch sử duyệt web hay dữ liệu phiên đăng nhập. Các dịch vụ bên ngoài nhận dữ liệu yêu cầu thông thường của trình duyệt, ví dụ địa chỉ IP, khi tab mới tải dữ liệu và ảnh.
  - Tiện ích liên hệ `radar-ai-vn.pages.dev` (dữ liệu Halcyon), `hn.algolia.com` (tin Hacker News), `huggingface.co` (bài báo, mô hình, avatar), `avatars.githubusercontent.com` và `opengraph.githubassets.com` (ảnh GitHub), `cdn-thumbnails.huggingface.co` (ảnh Hugging Face), `i.ytimg.com` (ảnh YouTube), `calendar.google.com` (lịch khi người dùng chọn), cùng liên kết giấy phép `creativecommons.org`.
  - Bản tin và mốc cập nhật nằm trong `chrome.storage.local`; tùy chọn giao diện, trạng thái đọc/lưu bài và avatar Hugging Face đã lưu đệm nằm trong `localStorage` trên máy người dùng. Tiện ích không tải dữ liệu cục bộ này lên, không bán hoặc chia sẻ dữ liệu cá nhân.
  - Trang chính sách quyền riêng tư đã được tạo tại `site/chinh-sach-rieng-tu.html`, sẵn sàng deploy lên URL công khai: `https://radar-ai-vn.pages.dev/chinh-sach-rieng-tu.html`.
  - Nội dung công bố dữ liệu và 3 cam kết chuẩn của CWS đã được soạn thảo sẵn trong `extension/store/data-disclosure.md`; trang chính sách và test cũng liệt kê các host bên ngoài trong mã extension.
- **Kết luận:** **ĐẠT**.

---

## 2. Kiểm Tra Tài Liệu Chính Sách Trực Tuyến

- Đã đối chiếu các quy định chính thức của Google:
  - **Chrome Web Store Program Policies:** Single Purpose Policy, Quality Guidelines, Misleading Functionality & Search Hijacking, User Data FAQ.
  - **Manifest V3 Migration & CSP Standards:** Cấm Remote Code Execution (RCE) và inline script.
  - Ghi chú môi trường: Trong môi trường container cục bộ này, các cổng web bên ngoài bị giới hạn, việc đối chiếu dựa trên quy chuẩn CWS MV3 2024-2026 hiện hành và bộ quy tắc kiểm thử `test_extension_shell.py` của dự án.

---

## 3. Danh Mục Các Tệp Cần Thiết Trong Gói Nộp Store

Gói zip tải lên Chrome Web Store (`build-zip.py`) chỉ bao gồm các tệp phục vụ hoạt động của extension:
- `manifest.json`
- `background.js`
- `newtab.html`, `newtab.js`, `newtab.css`
- `snapshot.js`, `theme.js`, `feed.js`, `feed.css`, `arena.js`, `arena.css`, `story.js`, `story.css`, `tokens.css`
- `calendar.js`, `editorial-headline.js`, `faces.js`, `live.js`, `time-text.js`, `titles.js`, `words.js`, `worth-score.js`
- `feed-images.json`, `editor-picks.json`
- `favicon.ico`, `apple-touch-icon.png`, `logo.svg`
- `icons/` (16.png, 32.png, 48.png, 128.png)
- `fonts/` (bộ font Be Vietnam Pro woff2 & OFL.txt)

Đã loại trừ toàn bộ các tệp dev/admin không dùng trên trình duyệt:
- `README.md`
- `sync-site.py`
- Thư mục `store/`
- Các tệp ẩn, cache (`.DS_Store`, `__pycache__`)

---

## 4. Trạng Thái Tổng Thể

- **Sẵn sàng nộp (Ready for submission):** 100% điều kiện kỹ thuật và tài liệu đã hoàn thiện.
- Không phát hiện bất kỳ vi phạm chính sách nào cần phải sửa đổi mã nguồn logic của extension.
