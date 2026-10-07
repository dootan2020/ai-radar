# Cài máy riêng chạy ai-radar

Hướng dẫn này dành cho máy Windows luôn bật. Làm lần lượt từ trên xuống. Máy cần Internet; riêng Reddit có thể không phân giải được qua DNS của nhà mạng Việt Nam, nên cần DNS 1.1.1.1.

## 1. Chuẩn bị Windows

- Cài các bản ổn định hiện hành của Git for Windows, Python 3.11 trở lên và Node.js 18 trở lên.
- Cài FFmpeg và bảo đảm `ffmpeg.exe` nằm trong `PATH`, hoặc đặt `FFMPEG_PATH` trỏ tới file đó.
- Cài OmniVoice trong một virtual environment đã hoạt động, rồi sao chép model cache sẵn có sang máy này. Không tải model hay package lúc render.
- Đặt `OMNIVOICE_PYTHON` trỏ tới `python.exe` của venv và `OMNIVOICE_CACHE_DIR` trỏ tới cache. Nếu Remotion không tìm thấy Chrome, đặt `CHROME_PATH` tới Chrome/Chromium.
- Cài agy, Claude Desktop và GitHub CLI (`gh`). Captain đăng nhập agy, Claude Desktop bằng tài khoản Claude Max, và `gh` bằng token fine-grained chỉ cấp quyền cần thiết cho repo ai-radar. Không dùng token có quyền trên repo khác.

## 2. Đặt DNS và không cho máy ngủ

Trong Windows Settings → Network & Internet → thuộc tính adapter đang dùng → DNS server assignment → Edit → Manual, đặt IPv4 DNS là `1.1.1.1` (có thể đặt DNS dự phòng `1.0.0.1`). Tắt VPN hoặc chính sách DNS khác nếu chúng ghi đè thiết lập này. Checker sẽ hỏi trực tiếp DNS `1.1.1.1` để phân giải `reddit.com`.

Trong Settings → System → Power, đặt chế độ cắm điện không bao giờ sleep. Có thể kiểm tra thiết lập bằng lệnh sau trong PowerShell chạy quyền người dùng:

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

Nếu máy dùng pin, cân nhắc cấu hình riêng; đừng để hết pin làm dừng tác vụ.

## 3. Lấy mã nguồn và chuẩn bị môi trường

Captain clone repo bằng GitHub CLI sau khi đã đăng nhập, rồi mở PowerShell tại thư mục repo:

```powershell
gh repo clone dootan2020/ai-radar
Set-Location ai-radar
python --version
git --version
node --version
python -m unittest discover -s tests
```

Không cần cài `requirements-translate.txt` để chạy collector cốt lõi. File đó chứa PyTorch CPU và thư viện Transformers/Hugging Face cho dịch NLLB tùy chọn; bước cài trong GitHub Actions có thể tải package và model. Trên máy riêng, chỉ cài khi chủ máy chủ động chọn chạy dịch NLLB và đã dành dung lượng, thời gian tải phù hợp.

Chạy checker từ thư mục gốc:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\machine\check-prereqs.ps1
```

`FAIL` nghĩa là cần sửa mục tương ứng. Checker chỉ đọc cấu hình, kiểm tra lệnh/đường dẫn và hỏi DNS; nó không cài đặt, tải file, đăng nhập hoặc thay đổi hệ thống. Mục secret báo đúng tên biến và OK/MISSING, không hiển thị giá trị.

## 4. Chuyển OmniVoice và kiểm tra video

Sao chép venv OmniVoice và model cache đã chuẩn bị, sau đó đặt đường dẫn bằng biến môi trường của phiên PowerShell hiện tại hoặc cấu hình theo chính sách máy:

```powershell
$env:OMNIVOICE_PYTHON = Join-Path $env:USERPROFILE 'omnivoice-tts\venv\Scripts\python.exe'
$env:OMNIVOICE_CACHE_DIR = Join-Path $env:USERPROFILE 'omnivoice-tts\huggingface'
$env:FFMPEG_PATH = 'D:\Tools\ffmpeg\bin\ffmpeg.exe'
# Chỉ đặt nếu Remotion không tự tìm thấy Chrome:
$env:CHROME_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
node .\video\render.js .\site\data\radar-ui.json
```

Đổi các ví dụ thành vị trí thật trên máy. Để biến tồn tại sau khi đóng PowerShell, dùng giao diện Environment Variables của Windows hoặc cách quản lý cấu hình mà captain phê duyệt; không ghi chúng vào repo. Render cần dữ liệu `site/data/radar-ui.json` đã được build trước và ghi kết quả vào `video/out/`.

## 5. Cấp secrets qua secret-intake

Secrets phải được captain chuyển qua firstmate's secret-intake theo quy trình của máy; không gửi trong chat, không commit vào repo và không ghi vào tài liệu này. Không yêu cầu hoặc dán secret vào cửa sổ Codex/Lucy.

`YOUTUBE_API_KEY` giúp collector dùng YouTube Data API; collector có thể chạy với fallback nếu thiếu. `GEMINI_API_KEY` là tùy chọn cho dịch/tóm tắt/kịch bản Gemini; chỉ bật khi captain đã xác minh điều kiện free tier cho project. `RADAR_GEMINI_FREE_TIER_CONFIRMED=1` là cờ xác nhận, không phải secret, và không tự xác minh billing. Workflow còn đọc `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_AI_API_TOKEN`, `GITHUB_TOKEN` cho tạo ảnh và các công việc trên GitHub; quyền/tác dụng từng biến phụ thuộc chức năng bật. `GITHUB_TOKEN` trong workflow được GitHub cấp cho job, không phải token cố định để sao chép từ Actions sang máy.

Nếu captain bật Antigravity trên máy, mở phần AI Credit Overages và chọn **Never**. Tự kiểm tra phần này vì checker không đọc tài khoản hay gọi dịch vụ.

## 6. Lên lịch và phục hồi sau mất điện

Tạo tác vụ “Radar collect” trong Task Scheduler với Program là đường dẫn `python.exe`, Arguments là `build.py`, Start in là thư mục repo; đặt trigger lặp mỗi 30 phút. Tạo riêng “Radar daily clip” với Program là đường dẫn `node.exe`, Arguments là `video/render.js site/data/radar-ui.json`, Start in là thư mục repo; lên lịch sau lần thu thập/dịch thành công trong ngày. Nếu bật dịch NLLB, cài các thư viện từ `requirements-translate.txt` theo lựa chọn của captain và chuẩn bị model cache để không phụ thuộc tải model lúc chạy; lệnh dịch là `python -m radar.translate --input site/data/radar.json --cache data/translations-vi.json`. Dịch Gemini cần `GEMINI_API_KEY` và cờ xác nhận, theo mục secret-intake. Đặt env vars tại môi trường mà chính tài khoản chạy task nhìn thấy. Cấu hình “Run whether user is logged on or not”, “If the task fails, restart every…” cùng số lần thử hợp lý, và “Run task as soon as possible after a scheduled start is missed”. “Run with highest privileges” chỉ bật nếu thật sự cần. Workflow GitHub hiện vẫn chạy ở phút 07 và 37 mỗi giờ và tự deploy Pages; chạy collector cục bộ không thay thế việc tắt/đổi lịch workflow hoặc quyền xuất bản trên GitHub. Captain cần chọn một nơi duy nhất làm publisher để tránh lịch chồng nhau.

Trong Task Scheduler, bật “Run task as soon as possible after a scheduled start is missed”. Trong BIOS/UEFI bật khởi động lại sau khi có điện trở lại (Restore on AC Power Loss). Thử khởi động lại máy và xác nhận task chạy trước khi giao vận hành. Không đưa mật khẩu Windows vào script hoặc repo.

## 7. Kiểm tra sẵn sàng

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\machine\check-prereqs.ps1
python -m unittest discover -s tests
```

Checker trả mã lỗi khác 0 nếu có bất kỳ `FAIL`. Sau đó xác nhận thủ công: đã đăng nhập đúng tài khoản trong agy/Claude Desktop/gh; tác vụ Scheduler tồn tại và chạy dưới đúng tài khoản; máy không ngủ, tự bật lại sau mất điện; Antigravity AI Credit Overages là **Never** nếu tính năng đó được sử dụng; secret đã được chuyển an toàn; và một lần build/render thật đã tạo đúng output.

## Những phần cần captain quyết định thêm

- Chọn tác vụ nào chạy cục bộ (chỉ thu thập/build, hay cả dịch và clip), lịch chạy và cách tránh hai nơi cùng xuất bản.
- Cách giữ venv/cache OmniVoice đồng bộ khi nâng cấp, dung lượng ổ đĩa và nơi lưu bản sao dự phòng.
- Giám sát khi máy offline hoặc task lỗi: ai nhận cảnh báo, nơi lưu log, thời hạn giữ log và cách dọn `video/out`/cache.
- Điện dự phòng/UPS, truy cập từ xa có MFA và cập nhật Windows/Git/Python/Node/FFmpeg theo lịch.
- GitHub token được lưu/đưa vào tiến trình bằng cơ chế được captain duyệt; quyền token tối thiểu và hạn xoay vòng. Checker không chứng minh tài khoản hay quyền truy cập.

