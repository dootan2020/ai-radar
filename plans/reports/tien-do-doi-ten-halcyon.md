# Tiến độ đổi tên Halcyon

## Session Intent

Đổi mọi tên sản phẩm hiển thị cho người đọc và Chrome Web Store từ AIBit News sang Halcyon; giữ tagline, biểu tượng, màu, bố cục, URL canonical và định danh vận hành.

## Files Modified

Đã sửa nguồn tạo trang tin/video, nội dung và metadata trong `site/` và `extension/`, các script/asset/brandbook trong `brand/`, các test liên quan và `README.md`. Đã đổi nguồn brandbook từ `brand/aibit-news/` sang `brand/halcyon/`.

## Decisions Made

- Tên hiển thị chính xác là `Halcyon`; domain `halcyonnews.com` chỉ là dự kiến trong brandbook.
- Nguồn brandbook sẽ chuyển sang `brand/halcyon/`; `site/brand/` là bản xuất từ nguồn đó.
- Đầu phiên có 109 file tracked chứa `AIBit` trong phạm vi yêu cầu.
- Đã cập nhật mức byte kỳ vọng của request video trong test ngân sách, vì hai lần xuất hiện của tên ngắn hơn làm payload giảm 6 byte; test vẫn kiểm tra đúng kích thước request mới.
- Port 8098 đang phục vụ trang `LogosTab` từ một Python server không thuộc phiên này; dùng 8099 cho site và 8100 cho extension.

## Current State

Các script tạo logo, asset, publish kit và đồng bộ extension đã chạy thành công. Grep trong phạm vi còn 0 file chứa `AIBit`. Bốn trang đã được mở ở 375px và 1440px; header cùng hàng với chim bói cá và không tràn ngang. Full unittest: **1317 test, OK (skipped=8)**. Hai server của phiên đã dừng. `git add` bị sandbox từ chối tạo `index.lock` trong `.git/worktrees/ai-radar-wt-halcyon/`, nên chưa stage/commit.

## Next Steps

Lucy stage các file trong phạm vi, dùng `git add -f` cho hai report trong `plans/reports/`, không stage `.skills/`, rồi commit trên `feat/rename-halcyon`. Lucy chụp ảnh ở 375px và 1440px cho anh Tuấn; browser trong phiên này không ghi được screenshot vào report.
