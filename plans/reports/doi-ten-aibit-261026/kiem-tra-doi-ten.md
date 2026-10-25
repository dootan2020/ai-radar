# Kiểm tra đổi tên AIBit News

## Kết quả hiện có

- `LogosTab` trong `site/ extension/ brand/ tests/ README.md`: **103 file trước, 0 file sau** (`git grep -l -i`). Brandbook nguồn đã chuyển sang `brand/aibit-news/`; script xuất bản và các link nội bộ của brandbook đã cập nhật. `aibitnews.com` chỉ nằm trong brandbook, kèm nhãn **Tên miền dự kiến**.
- `brand/assets/store/promo-small.png` đã tạo lại ở 440 × 280 với chữ **AIBit News** và **Những mẩu tin AI ngắn gọn**. Store icon 16/32/48/128 px vẫn dùng đúng pixel chim bói cá cũ vì mark không đổi. `og-default.png`, các cover và khung 9:16 đã tạo lại; kiểm tra trực quan thấy tên và tagline vừa trong khung.
- Hai ảnh `brand/assets/store/new-tab-light.png` và `new-tab-dark.png` cũ còn hiển thị tên cũ. Đã gỡ khỏi worktree để chúng không được dùng nhầm; cần chạy lại `brand/store-shots.js` khi có snapshot trực tiếp và browser chạy được.

## Lệnh và exit code

| Lệnh | Exit | Kết quả |
| --- | ---: | --- |
| `python brand/logo/build-logo.py` | 0 | Lockup SVG/PNG đã tạo; `viewBox` theo chiều dài tên mới. |
| `python brand/build-assets.py --site` | 0 | SVG brand/Store tạo lại và kit được publish. |
| `python brand/publish_kit.py` | 0 | 58 file publishable đồng bộ sang `site/brand/`. |
| `python extension/sync-site.py` | 0 | New tab và CSS đồng bộ từ site. |
| `python brand/export-png.py` | 0 | Icon Store và promo xuất đúng kích thước; Chrome thất bại, ImageMagick fallback. |
| `python brand/export-png.py --site` | 1 | PNG site và Store xuất xong; `brand/store-shots.js` timeout 30 giây khi chờ snapshot trực tiếp. |
| `python -m unittest discover -s tests -p test_brand_meta.py` | 0 | 11 tests qua. |
| `python -m unittest discover -s tests -p test_extension_shell.py` | 0 | 11 tests qua. |
| `python -m unittest discover -s tests` | 1 | 1317 tests; 18 failures, 18 errors, 8 skipped. Xem chặn bên dưới. |
| `git diff --check` | 0 | Không có whitespace error trong diff theo cấu hình Git của repo. |
| `git add -- README.md brand extension site tests` | 128 | Sandbox từ chối tạo `.git/worktrees/ai-radar-wt-aibit/index.lock`; chưa stage hoặc commit. |

## Kiểm tra trình duyệt

Port 8098 đã có tiến trình khác chiếm. Không thể xác minh command line của PID do `Get-CimInstance` bị từ chối, nên không dừng tiến trình đó. Site của worktree được phục vụ tạm trên 8099/8101/8102; extension trên 8100. Các server do phiên này mở sẽ được dừng trước khi bàn giao.

| Trang | 375px | 1440px | Sáng/tối |
| --- | --- | --- | --- |
| `/` | Tên cạnh chim bói cá một dòng sau chỉnh CSS; không tràn ngang. | Tên một dòng; không tràn ngang. | Đã mở cả hai. |
| `/ban-tin.html` | Tên một dòng; badge “Bản tin” ẩn ở mobile vì ngữ cảnh đã có ngay trong tiêu đề trang. | Tên và badge vừa header; không tràn ngang. | Đã mở cả hai. |
| `/tin/_sample/` | Tên ở header và `<title>` mới; không tràn ngang. | Tên ở header và `<title>` mới; không tràn ngang. | Đã mở cả hai qua theme lưu từ trang chủ. |
| `extension/newtab.html` | Tên một dòng cạnh chim bói cá; không tràn ngang. | Tên một dòng; không tràn ngang. | Đã mở cả hai. |

Browser tương tác chụp được ảnh trong phiên nhưng không có khả năng ghi chúng vào thư mục report. Puppeteer riêng không khởi động được trong 30 giây, nên không có screenshot file 375/1440 để bàn giao. Khi phục vụ extension như trang tĩnh, không có `chrome.storage`, nên phần dữ liệu hiện trạng thái lỗi; kiểm tra này chỉ xác nhận shell, tên, theme và bố cục.

## Chặn còn lại

Scope của brief không có `radar/`, nhưng `radar/health_probe.py` vẫn chỉ nhận tên cũ, `radar/story_page_template.html` và `radar/story_pages.py` vẫn tạo trang tin mang tên cũ, `radar/video_script.py` vẫn dùng tên cũ trong prompt/validation, và `radar/legacy_redirects.py` vẫn hiển thị tên cũ. Đây là nguyên nhân chính của các lỗi test và sẽ đưa tên cũ trở lại khi build. Đã hỏi anh Tuấn có cho mở scope sang các file reader-facing đó không; chưa nhận được quyết định. `radar-ai-vn.pages.dev`, workflow và tên dữ liệu giữ nguyên đúng brief.

Các định danh cũ được giữ có chủ đích: host/canonical `radar-ai-vn.pages.dev`, tên workflow `Update AI Radar`, khóa theme `air2:theme`, đường dẫn dữ liệu `radar-*.json`, và `ai-radar` trong `PRODID`/`UID` của lịch để không đổi nhận dạng sự kiện đã xuất. Tên cũ trong fixture/test nội bộ hoặc đường dẫn plan cũng không được đưa ra bề mặt người đọc.

Store screenshot cần môi trường có thể tải snapshot từ `https://radar-ai-vn.pages.dev/data/radar-window.json`; trong phiên này HTTP request thất bại. Không thay bằng tin mẫu hoặc ảnh Store cũ.

## Round 2: pipeline và kiểm tra cuối

Anh Tuấn đã mở scope `radar/` cho mọi chuỗi người đọc, search engine hoặc share card nhìn thấy. Đã đổi template/trình tạo trang tin, redirect cũ, health probe, prompt biên tập và video sang **AIBit News**. Tên workflow, host/canonical, Pages project, secrets và tên tệp dữ liệu không đổi; `.github/workflows/` không bị sửa.

`git grep -n -i -E "LogosTab|AI Radar" -- radar/ site/ extension/ brand/ tests/ README.md` giảm từ **32** dòng trước round 2 xuống **15** dòng sau; `LogosTab` còn **0**. 15 dòng còn lại gồm tên workflow `Update AI Radar` (README, mã kiểm tra, test), thông báo sự cố nội bộ, mô tả/scorecard nội bộ và dữ liệu test cho ô tìm kiếm. Không dòng nào là tên hiển thị trong site, extension, trang tin hay metadata.

Các lệnh đồng bộ `python brand/logo/build-logo.py`, `python brand/build-assets.py --site`, `python brand/publish_kit.py`, `python extension/sync-site.py`, `python brand/export-png.py` đều exit 0. `python -m unittest discover -s tests`: **Ran 1317 tests in 156.936s; OK (skipped=8)**. `node --check brand/store-shots.js`, `python -m py_compile` cho các module radar sửa và `git diff --check` cũng exit 0.

Trình duyệt kiểm tra `/`, `/tin/_sample/` và `extension/newtab.html` ở 375px và 1440px. Wordmark **AIBit News** trong header nằm một dòng tại 375px và không có tràn ngang ở các trang. Port 8098 đã được một tiến trình khác sử dụng; phiên này phục vụ site trên 8099 và extension trên 8100, sau đó dừng hai server. Browser không ghi được screenshot vào thư mục report.

`brand/store-shots.js` đã chuyển sang nạp `site/data/radar-window.json` local. Snapshot thực trong fixture được sao chép tạm để thử. Puppeteer timeout khi khởi động Chrome và Edge headless, nên hai ảnh Store 1280 × 800 vẫn **chưa có**; ảnh cũ chứa tên cũ tiếp tục được gỡ. Cần chạy lại `node brand/store-shots.js` ở môi trường headless browser hoạt động sau khi tạo `site/data/radar-window.json`.

`git add -- README.md brand extension radar site tests` exit 128: sandbox không cho tạo `.git/worktrees/ai-radar-wt-aibit/index.lock`. Vì vậy chưa stage/commit. Lucy cần stage các tệp phạm vi brief, dùng `git add -f` cho hai report trong `plans/`, và không stage `.skills/`.
