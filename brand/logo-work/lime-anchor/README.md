# Halcyon • Lime Anchor
Bộ nhận diện thương hiệu cơ bản / Visual Identity Kit v1.0

## Chọn file nhanh
- Logo trên nền sáng: logos/halcyon-primary.svg hoặc PNG primary (trong suốt).
- Logo trên nền tối: logos/halcyon-dark.svg hoặc PNG dark (trong suốt).
- Bản một màu: mono-ink / mono-white. Bản đã có nền: on-surface / on-ink.
- Icon ứng dụng, avatar: icons/halcyon-icon-primary.svg hoặc PNG 512/1024.
- Favicon: favicons/favicon.ico và favicon.svg. Apple touch icon: 180 px.
- Extension: PNG 16, 32, 48, 128 px trong icons; cấu hình ở web/extension-icons.json.
- PWA: favicon 192/512 px và web/site.webmanifest. Các icon này là purpose=any, không phải maskable.

## Tài sản và nguồn
Wordmark được vector hóa từ mẫu Halcyon Lime Anchor đã duyệt, làm sạch thành đường Bézier và màu phẳng chính xác. Giữ silhouette cùng chi tiết mỏ chim trên chữ y; đường cong có sai khác nhỏ so với ảnh AI ban đầu, không phải bản gõ lại bằng một font. SVG dùng path, không phụ thuộc font. Icon rút từ chính chữ y và chi tiết mỏ, không dùng toàn bộ chữ ở kích thước nhỏ.

## Hệ màu
Signature #2F6B00; Secondary #174A34; Accent #D7FF2F; Surface #F8FBF3; Ink #142018.
Lime là điểm nhấn, không dùng làm chữ nhỏ trên nền sáng. Ưu tiên Ink trên Surface; Surface trên Secondary; Ink trên Accent. Không dùng xanh Signature trên nền Secondary/Ink. Bản âm dùng chữ Surface và mỏ Lime.

## Quy tắc logo
Khoảng trống tối thiểu: nửa chiều cao thân chữ h, tính từ mép hình thực tế. File crop gọn không chứa toàn bộ khoảng trống này; khi dàn trang cần thêm padding. Wordmark tối thiểu khuyến nghị 160 px trên màn hình hoặc 30 mm khi in; dưới ngưỡng này dùng icon. Thử bản in thực tế trước sản xuất. Không kéo giãn, xoay, thêm viền, đổ bóng, gradient hoặc đổi vị trí mỏ. Không đặt trên ảnh nền rối.

## Chữ và giao diện
Wordmark là hình đồ họa riêng, không dùng để viết nội dung. Font UI: system-ui, -apple-system, Segoe UI, sans-serif. Dùng Regular 400 cho nội dung, Semibold 600 cho nhãn, Bold 700 cho tiêu đề. Body 16 px, line-height 1.5; nút và nhãn tối thiểu 14 px. Không kèm file font hoặc giấy phép font ngoài.

## Triển khai
Copy thư mục favicons và web tới vị trí tương ứng trên website; chỉnh lại URL trong head-snippet.html và site.webmanifest theo đường dẫn thực tế. extension-icons.json là đoạn cấu hình, không phải manifest extension hoàn chỉnh. Dùng SVG cho web và sản phẩm số; PNG khi nền tảng không hỗ trợ SVG. Bộ này dùng sRGB, chưa có bản CMYK/Pantone đã được nhà in xác nhận.

## Phạm vi
Đây là bộ nhận diện thị giác cơ bản, chưa phải chiến lược thương hiệu đầy đủ. Chưa bao gồm kiểm tra đăng ký/độc quyền nhãn hiệu, brand voice, bộ văn phòng phẩm hay hệ template chiến dịch. Các tài sản hình ảnh AI và vector phát triển từ chúng cần được rà soát quyền sở hữu trước đăng ký thương hiệu.
