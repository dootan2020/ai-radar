# Ngôn ngữ thiết kế ai-radar: Bento Keynote

Anh Tuấn chốt kiểu "Bento kiểu Apple" lúc 22:57 ngày 02/10. Bản này viết theo tư thế **Keynote**: ít ô, ô lớn, số to. Token nằm ở `site/tokens.css`. Mọi token và mọi trạng thái component được trình bày ở `site/tokens.html`.

## Tính cách
Giống một slide keynote của Apple. Mỗi sáng, người đọc mở trang và thấy vài ô lớn. Mỗi ô kể một chuyện bằng một con số. Trang yên, sáng và tự tin, chỉ nói ít điều nhưng điều nào cũng có số đo đi kèm. Trang này không phải tờ báo, cũng không phải dashboard.

## Năm nguyên tắc
1. **Diện tích là thứ bậc.** Chuyện quan trọng nhất trong ngày chiếm ô lớn nhất (6/12 cột). Hai ô dọc bên cạnh là repo và lịch phát. Phần còn lại nhỏ dần. Cỡ chữ không được dùng để giành sự chú ý.
2. **Mỗi ô một con số.** Mỗi ô có một logo nguồn, một số đo thật (điểm, sao, số ngày, số tin, số nguồn) và một nhãn. Không ô nào chỉ có chữ. Trường dữ liệu nào vắng thì ô đó ẩn hoặc ghi rõ là chưa có.
3. **Logo và số là màu.** Khung trang gần như không màu. Màu đến từ logo nguồn và ảnh YouTube thật. Xanh dùng cho hành động và mục đang chọn, đỏ chỉ dùng cho "đang phát" và "nóng".
4. **Khoảng thở.** Ô cách nhau 24px, lề trong ô 32–48px, mỗi ô ít mục. Khoảng trống là một phần của bố cục, không phải chỗ để lấp.
5. **Chuyển động như dòng chảy.** Các ô trôi vào lần lượt, số đếm lên, vòng điểm tự vẽ, tờ chi tiết trượt ra. Mọi chuyển động dùng chung một đường cong giảm tốc. Khi người đọc bật giảm chuyển động, chỉ còn hiệu ứng mờ dần 150 ms.

## Token suy ra từ nguyên tắc
| Nguyên tắc | Token | Giá trị và lý do |
| --- | --- | --- |
| 1 | `--grid-gap`, `--tile-radius`, lưới 12 cột | Khe 24px, bo góc ô 24px. Bo 24px là ngoại lệ có chủ đích: neo so sánh là bento của Apple. |
| 2 | `--num-hero` → `--num-md` | Thang số tách riêng khỏi thang chữ: 128 / 88 / 56 / 32px, chữ đậm 700, `tabular-nums`, giãn chữ −0,04em. |
| 2 | `--av-*`, `--av-radius` | Logo 20–72px, bo kiểu squircle 28% như icon ứng dụng. Khi không có logo đã xác minh thì dùng chữ lồng. |
| 3 | `--gray-*` (hue 265, chroma ≤ 0,012), `--color-accent`, `--color-live` | Dải xám lạnh nhạt cùng một hue. Một màu xanh, một màu đỏ. Chữ đều đạt từ 4,5:1 trở lên ở cả hai giao diện (đo trong `tokens.html`). |
| 3 | Độ sâu | Chỉ một cách: ô sáng hơn nền. Ô đứng yên không có viền, không có bóng. Bóng chỉ xuất hiện khi ô được nâng lên và ở tờ chi tiết. |
| 4 | `--space-4` … `--space-96`, `--tile-pad(-hero)` | Thang 4pt. Lề ô 32px, ô chính 48px, điện thoại 24px. |
| 5 | `--ease-flow`, `--motion-*` | Đường cong `cubic-bezier(0.16,1,0.3,1)`. Thời lượng theo đặc tả 02/10: ô mới 300 ms, mở chi tiết 350 ms, đóng 250 ms, số đếm 600 ms. |

**Chữ:** một họ duy nhất là Be Vietnam Pro (400, 500, 600, 700), đủ dấu tiếng Việt, theo cách Apple chỉ dùng một họ SF. Dòng chữ đọc cao 1,55 để dấu chồng tầng (ế, ộ, ữ) có chỗ.

**Dark mode** chỉ thay tầng ngữ nghĩa. Mặt ô sáng dần lên để nổi, số luôn là thứ sáng nhất. Trang theo cài đặt của hệ thống cho tới khi người đọc tự chọn. Lựa chọn đó chỉ lưu trên máy của họ.
