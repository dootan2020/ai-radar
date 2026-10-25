# LogosTab — màu emerald

## Hướng thiết kế

Register: Product. Scene: người đi làm Việt Nam mở tab mới nhiều lần trong ngày, đọc nhanh trên điện thoại hoặc desktop trong ánh sáng và bóng tối. Direction: giấy sáng/tối tĩnh và một emerald sống, vì tin cần được đọc trước khi giao diện được chú ý. Color: restrained; nền giữ `--gray-96`/`--gray-13`, mực giữ `--gray-21`/`--gray-96`, accent `#007A55`/`#00D68F`. Type: Be Vietnam Pro như cũ. Signature: chim bói cá emerald. Dials: variance 2, motion 2, density 6.

Emerald chỉ dẫn đến thao tác chính, tab đang chọn, focus và link khi tương tác. Dấu tin mới, đếm ngược, nhãn loại và trạng thái thành mực/xám để tin tức giữ thứ bậc. `#007A55` giữ sắc của ô logo nhưng đủ đậm để đọc trên giấy sáng; `#00D68F` rõ trên nền tối mà không nhuộm xám. Trạng thái “ok” dùng mực trung tính, tránh cạnh tranh với màu thương hiệu. Chip Translated tiếp tục xanh Google.

## Token và contrast

Chạy `python plans/reports/mau-emerald-261025/contrast.py`. Script tính WCAG 2.x từ sRGB, chuyển các token OKLCH sang sRGB trước khi đo. Các số dưới đây đo trên nền của đúng thành phần:

| Vai trò | Cũ → mới | Contrast cũ → mới |
| --- | --- | ---: |
| Accent sáng / surface | `oklch(0.50 0.20 256)` → `#007A55` | 5.95 → 5.26:1 |
| Accent sáng / canvas | như trên | 5.44 → 4.80:1 |
| Chữ trên nút accent sáng | `--gray-99` → giữ nguyên | 5.26:1 |
| Accent tối / surface | `oklch(0.74 0.14 252)` → `#00D68F` | 8.23 → 9.95:1 |
| Accent tối / canvas | như trên | 8.69 → 10.50:1 |
| Chữ trên nút accent tối | `--gray-13` → giữ nguyên | 10.50:1 |
| OK sáng / fill | xanh lá cũ → `--gray-44` | 5.69 → 6.36:1 |
| OK tối / fill | xanh lá cũ → `--gray-80` | 9.02 → 8.56:1 |
| Nhãn tĩnh sáng / surface | accent cũ → `--gray-44` | 5.95 → 7.61:1 |
| Nhãn tĩnh tối / surface | accent cũ → `--gray-80` | 8.23 → 10.15:1 |
| Caption OG / `#F1F2F5` | `#005CD1` → `#007A55` | 5.44 → 4.79:1 |
| Translated sáng / tối | Google blue giữ nguyên | 4.68 / 5.44:1 |

Không thay lightness, hue hay chroma của thang xám. `#007D56` là phương án chữ thứ hai có thể dùng, nhưng `#007A55` cho thêm dư địa trên canvas mà vẫn gần emerald của brandbook. Ô logo `#00B377` không dùng làm chữ trên nền sáng.

## Đồng bộ và kiểm tra

`site/tokens.css` là nguồn CSS. `brand/build-assets.py --site` tạo `brand/tokens.css` và publish kit; `brand/publish_kit.py` tạo `site/brand/`; `extension/sync-site.py` chép CSS sang extension. Bốn bản token cuối giống byte. `brand/build-assets.py` nay lấy emerald từ token nguồn để các lần dựng sau không sinh lại caption xanh. Bốn SVG đổi caption `#005CD1` thành `#007A55` ở cả nguồn brand và bản public. `brand/export-png.py` được gọi cho hai job có SVG tương ứng: `og-default.png` và `khung-9x16.png`; ImageMagick render thành công khi Chrome headless lỗi GPU. `site/og-image.png` đồng bộ từ OG mặc định. Script export không có job PNG cho `og-story.svg` hoặc `short-9x16.svg`.

Trên homepage, coordinator đếm **56** phần tử xanh trước khi sửa ở desktop. Browser UI của lần này đếm **6** phần tử có computed accent sau sửa tại viewport thực tế **360px**; số này là quan sát mobile, chưa phải phép so sánh cùng viewport với 56. Trang chủ có tin và nhãn “Mới” màu trung tính; `ban-tin.html` hiển thị shell nhưng dữ liệu ở trạng thái “Đang tải” khi quan sát; `tin/_sample/` hiển thị bài, liên kết và chip Translated trong chế độ tối. Sau lượt review CSS, kicker, dấu danh sách và biểu tượng trạng thái tĩnh của bản tin cũng chuyển sang mực trung tính. Browser UI không áp dụng được 375/1440 dù đã yêu cầu. Chrome và Edge headless đều dừng vì GPU process; giao thức `file:` của extension bị browser chặn. Vì vậy không có bộ screenshot 16 trạng thái đạt yêu cầu trong report này. Các ảnh thử có độ phân giải 90px đã được loại bỏ, không dùng làm bằng chứng.

## Chạy test

- `python plans/reports/mau-emerald-261025/contrast.py`: exit 0.
- `python -m unittest discover -s tests -p test_brand_meta.py`: 11 test, exit 0.
- `python -m unittest discover -s tests -p test_extension_shell.py`: 11 test, exit 0.
- Lần chạy full đầu: 1.317 test, 2 fail do các bản token khác line endings; đã sửa LF và đồng bộ lại.
- Lần chạy full cuối sau các thay đổi CSS: 1.317 test, exit 0, 8 skip. Các lượt riêng 11 test brand và 11 test extension đều exit 0.
- `git diff --check`: không báo lỗi.
- `git add -u` và `git add` report: sandbox từ chối tạo `index.lock` trong Git worktree metadata ngoài thư mục được ghi. Chưa stage/commit. Thư mục `plans/` bị `.gitignore` bỏ qua; Lucy cần `git add -f` riêng hai file report và progress, tuyệt đối không stage `.skills/`.

## Giới hạn còn lại

Lucy cần chụp `/`, `/ban-tin.html`, một trang `site/tin/` và extension newtab ở sáng/tối, 375/1440 trên máy có browser capture hoạt động rồi review cùng reviewer thứ hai. Browser ở đây không cấp được ảnh đúng kích thước. Các bản PNG xuất bằng ImageMagick cần được nhìn lại cùng SVG khi thực hiện lượt chụp đó.

## Round 2

Khôi phục trạng thái tốt bằng xanh lá dịu, tách sắc emerald thương hiệu: sáng `--color-ok: oklch(0.52 0.10 145)` với wash `oklch(0.95 0.018 145)`; tối `oklch(0.78 0.10 145)` với wash `oklch(0.28 0.025 145)`. Header CTA `.ed-link` được tô `--color-accent`/`--color-on-accent`, hover dùng emerald sâu hơn; focus ring và pill tab đang chọn giữ nguyên. Chip Translated không đổi.

| Cặp mới | Contrast | Ngưỡng |
| --- | ---: | ---: |
| Trạng thái tốt sáng / wash | 4.58:1 | 4.5:1 |
| Dot tốt sáng / surface | 5.17:1 | 3:1 |
| Dot tốt sáng / fill | 4.32:1 | 3:1 |
| Trạng thái tốt tối / wash | 7.50:1 | 4.5:1 |
| Dot tốt tối / surface | 9.83:1 | 3:1 |
| Dot tốt tối / fill | 8.29:1 | 3:1 |
| Chữ CTA sáng / hover emerald | 6.52:1 | 4.5:1 |
| Chữ CTA tối / hover emerald | 9.22:1 | 4.5:1 |

`contrast.py` đo những cặp này bên cạnh bảng Round 1. `site/tokens.css`, `site/brand/tokens.css`, `brand/tokens.css`, `extension/tokens.css` giống byte sau khi chạy `brand/build-assets.py --site`, `brand/publish_kit.py`, `extension/sync-site.py` (cả ba exit 0). `python -m unittest discover -s tests`: 1.317 test, 6 skip, exit 0. `git diff --check`: exit 0.

### Walk giao diện và giới hạn capture

Mở `/` và `/ban-tin.html` trên server local 8097, đổi theme sáng/tối trên từng trang. Ảnh trình duyệt hiển thị pill “Bản tin sáng” màu emerald ở home; pill tab chọn vẫn đen, chip Translated vẫn xanh Google. Trang `/ban-tin.html` giữ trạng thái “Đang tải bản tin...” trong lượt xem này. Không tạo được ảnh `v2-*.png` ở 375px/1440px: browser capture hiện tại không có viewport override và chỉ trả ảnh viewport nhỏ; URL `javascript:` dùng để đọc computed style bị chính sách browser chặn. Vì thế không ghi nhận computed DOM của `.lab.dung-ngay`, `.dot.ok` hay `.ed-link`; các giá trị trong bảng là số đo từ token script, không phải DOM. Chưa có screenshot phù hợp để lưu vào thư mục report.
