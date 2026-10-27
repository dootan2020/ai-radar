# Khai Báo Dữ Liệu & Cam Kết Quyền Riêng Tư (Data Usage Disclosure & Certifications)

*Dùng để điền và tích chọn trong mục **Privacy** -> **Data usage** trên Chrome Web Store Developer Dashboard.*

---

## 1. Khai Báo Dữ Liệu Thu Thập (Data Collection)

### Câu hỏi: Extension có thu thập dữ liệu người dùng không?
- **Lựa chọn:** **KHÔNG thu thập bất kỳ loại dữ liệu nào (No data collected).**
- Trong danh sách các loại dữ liệu (Personally identifiable information, Health, Financial, Authentication, Personal communications, Location, Web history, User activity, Website content): **KHÔNG tích chọn bất kỳ mục nào.**

### Văn bản giải trình dữ liệu (Data usage justification / explanation):
```
Halcyon does not collect, remotely store, sell, or share personal data. The extension makes requests to the services below to load its news data and article thumbnails. Those services receive the browser's ordinary request data, such as your IP address. Halcyon does not use these requests for tracking or telemetry.

1. No Personal Information: The extension does not collect names, email addresses, location, device identifiers, credentials, or browsing history. Network providers may receive ordinary request data, including IP address, when the browser connects to them.
2. Local Storage Only: The latest news snapshot and refresh timestamp are kept in chrome.storage.local. Theme preference, reading state, and cached Hugging Face avatar URLs are kept in localStorage on the device. The extension does not upload this local data.
3. No Search Tracking: Web searches initiated from the new tab page are executed directly through the browser's default search engine via chrome.search.query, without interception, logging, or redirection.
4. External services and purpose:
   - radar-ai-vn.pages.dev (Halcyon's Cloudflare Pages site): public news feeds and article data.
   - hn.algolia.com (Algolia Hacker News API): live Hacker News stories.
   - huggingface.co (Hugging Face API): trending models, daily papers, and avatar images.
   - avatars.githubusercontent.com (GitHub avatars), opengraph.githubassets.com (GitHub article preview images), and cdn-thumbnails.huggingface.co (Hugging Face article thumbnails): article/source imagery.
   - i.ytimg.com (YouTube thumbnails): video article thumbnails.
   - calendar.google.com (Google Calendar): opened when you choose to add an event to your calendar.
   - creativecommons.org: the attribution license link for Arena data.
   These requests carry normal browser request data, such as IP address, to the named provider. Requests do not include Halcyon account or browsing-history data. Search queries go directly through Chrome's default search provider using chrome.search.query.
```
*(Tiếng Việt: Halcyon không thu thập, truyền tải, bán hoặc lưu trữ bất kỳ dữ liệu cá nhân, lịch sử duyệt web hay dữ liệu đo kiểm nào. Mọi dữ liệu bộ nhớ đệm và tùy chọn giao diện đều lưu trữ cục bộ trên máy người dùng).*

---

## 2. Ba Cam Kết Bắt Buộc Của Nhà Phát Triển (The Three Certifications)

*Trên Developer Dashboard, tích chọn xác nhận cả 3 cam kết sau:*

### Cam kết 1: Không bán dữ liệu cho bên thứ ba (Not selling user data)
- **Tiêu chuẩn CWS:** "I certify that the item will not sell user data to third parties, outside of the approved use cases."
- **Thực tế Halcyon:** **ĐỒNG Ý (Tích chọn Yes).** Halcyon không thu thập và không bao giờ bán dữ liệu người dùng cho bất kỳ bên thứ ba hay nhà môi giới dữ liệu nào.

### Cam kết 2: Không sử dụng dữ liệu ngoài mục đích cốt lõi (Not using data for unrelated purposes)
- **Tiêu chuẩn CWS:** "I certify that the item will not use or transfer user data for purposes that are unrelated to the item's core functionality."
- **Thực tế Halcyon:** **ĐỒNG Ý (Tích chọn Yes).** Mọi quyền và tài nguyên chỉ phục vụ duy nhất mục đích hiển thị tin tức AI và tìm kiếm web trên tab mới.

### Cam kết 3: Không dùng dữ liệu để chấm điểm tín dụng hoặc cho vay (Not using data for creditworthiness or lending)
- **Tiêu chuẩn CWS:** "I certify that the item will not use or transfer user data to determine creditworthiness or for lending purposes."
- **Thực tế Halcyon:** **ĐỒNG Ý (Tích chọn Yes).** Halcyon là một trình đọc tin tức công nghệ, không liên quan đến tài chính, tín dụng hay cho vay.

---

## 3. Đường Dẫn Chính Sách Quyền Riêng Tư (Privacy Policy URL)
```
https://radar-ai-vn.pages.dev/chinh-sach-rieng-tu.html
```
