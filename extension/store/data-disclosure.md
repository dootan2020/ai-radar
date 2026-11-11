# Khai Báo Dữ Liệu & Cam Kết Quyền Riêng Tư (Data Usage Disclosure & Certifications)

*Dùng để điền và tích chọn trong mục **Privacy** -> **Data usage** trên Chrome Web Store Developer Dashboard. Nội dung khớp trang https://hco.news/chinh-sach-rieng-tu.html (cập nhật 11/11/2026).*

---

## 1. Khai Báo Dữ Liệu Thu Thập (Data Collection)

### Câu hỏi: Extension có thu thập dữ liệu người dùng không?
- **Đề xuất:** không tích loại dữ liệu nào. Tiện ích không gửi dữ liệu của người đọc về Halcyon hay cho bên nào; mọi thứ nó lưu nằm trên máy.
- Danh sách loại dữ liệu (Personally identifiable information, Health, Financial, Authentication, Personal communications, Location, Web history, User activity, Website content): **không tích ô nào.**
- Điểm anh cần biết khi quyết: trình duyệt tự kết nối tới các dịch vụ ở mục 4 dưới đây (kể cả máy chủ ảnh của nhà xuất bản), nên các dịch vụ đó nhận địa chỉ IP như mọi lượt tải trang. Halcyon không nhận, không lưu và không gửi tiếp dữ liệu đó. Ô thời tiết chỉ gửi toạ độ cố định của thành phố người đọc chọn trong danh sách, không phải vị trí của họ.

### Văn bản giải trình dữ liệu (Data usage justification / explanation):
```
Halcyon does not collect, upload, sell, or share personal data, browsing history, or telemetry, and the new tab loads no analytics script. To show its news, the new tab's browser requests go directly to the services below; each receives the browser's ordinary request data, such as the IP address. Halcyon attaches no personal data to these requests and receives none of it.

1. No personal information: the extension does not collect names, email addresses, location, device identifiers, credentials, or browsing history.
2. Local storage only: the latest news snapshot and its refresh timestamp are kept in chrome.storage.local; theme, reading and saved-story state, cached Hugging Face avatar URLs, and the chosen weather city with a 30-minute forecast are kept in localStorage; the day's background picture is kept in Cache Storage. None of it is uploaded, and it is removed when the extension is uninstalled.
3. Search: the "Search Google" box opens Google's results page (www.google.com/search) in the same tab with the words typed. The query goes straight from the browser to Google; Halcyon does not log, store, or forward it.
4. External services and purpose:
   - radar-ai-vn.pages.dev (Halcyon's Cloudflare Pages site): public news data and pictures.
   - Publishers' image servers (for example platform.theverge.com, techcrunch.com, img.semafor.com): story pictures load directly from the original source.
   - hn.algolia.com (Algolia Hacker News API): live Hacker News stories.
   - huggingface.co, cdn-thumbnails.huggingface.co: daily papers, trending models, avatars, and thumbnails.
   - avatars.githubusercontent.com, opengraph.githubassets.com: GitHub avatars and article preview images.
   - i.ytimg.com: video thumbnails.
   - api.open-meteo.com: the weather forecast for the city the reader picks from a fixed list (only that city's coordinates are sent).
   - ssl.gstatic.com: icons on the Google service buttons and in the Google apps menu.
   - www.google.com, calendar.google.com, other Google apps, creativecommons.org: opened only when the reader clicks them.
```
*(Tiếng Việt: Halcyon không thu thập, tải lên, bán hay chia sẻ dữ liệu cá nhân, lịch sử duyệt web hay dữ liệu đo lường, và tab mới không tải công cụ thống kê nào. Trình duyệt kết nối thẳng tới các dịch vụ trên; mỗi dịch vụ nhận dữ liệu yêu cầu thông thường như địa chỉ IP. Dữ liệu bộ nhớ đệm và tùy chọn nằm trên máy người dùng.)*

---

## 2. Ba Cam Kết Bắt Buộc Của Nhà Phát Triển (The Three Certifications)

*Trên Developer Dashboard, tích chọn xác nhận cả 3 cam kết sau:*

### Cam kết 1: Không bán dữ liệu cho bên thứ ba (Not selling user data)
- **Tiêu chuẩn CWS:** "I certify that the item will not sell user data to third parties, outside of the approved use cases."
- **Thực tế Halcyon:** **ĐỒNG Ý (Tích chọn Yes).** Halcyon không thu thập và không bán dữ liệu người dùng cho bất kỳ bên thứ ba hay nhà môi giới dữ liệu nào.

### Cam kết 2: Không sử dụng dữ liệu ngoài mục đích cốt lõi (Not using data for unrelated purposes)
- **Tiêu chuẩn CWS:** "I certify that the item will not use or transfer user data for purposes that are unrelated to the item's core functionality."
- **Thực tế Halcyon:** **ĐỒNG Ý (Tích chọn Yes).** Mọi quyền và tài nguyên chỉ phục vụ việc hiển thị tin tức AI trên tab mới.

### Cam kết 3: Không dùng dữ liệu để chấm điểm tín dụng hoặc cho vay (Not using data for creditworthiness or lending)
- **Tiêu chuẩn CWS:** "I certify that the item will not use or transfer user data to determine creditworthiness or for lending purposes."
- **Thực tế Halcyon:** **ĐỒNG Ý (Tích chọn Yes).** Halcyon là một trình đọc tin tức công nghệ, không liên quan đến tài chính, tín dụng hay cho vay.

---

## 3. Đường Dẫn Chính Sách Quyền Riêng Tư (Privacy Policy URL)
```
https://hco.news/chinh-sach-rieng-tu.html
```
