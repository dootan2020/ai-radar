# Ngôn ngữ thiết kế ai-radar: Bento Keynote

Anh Tuấn chốt kiểu "Bento kiểu Apple" lúc 22:57 ngày 02/10. Bản này viết theo tư thế **Keynote**: ít ô, ô lớn, số to. Token nằm ở `site/tokens.css`. Mọi token và mọi trạng thái component được trình bày ở `design/tokens.html` (trang nội bộ, không đưa lên web).

## Tính cách
Giống một slide keynote của Apple. Mỗi sáng, người đọc mở trang và thấy vài ô lớn. Mỗi ô kể một chuyện bằng một con số. Trang yên, sáng và tự tin, chỉ nói ít điều nhưng điều nào cũng có số đo đi kèm. Trang này không phải tờ báo, cũng không phải dashboard.

## Năm nguyên tắc
1. **Diện tích là thứ bậc.** Chuyện quan trọng nhất trong ngày chiếm ô lớn nhất (6/12 cột). Hai ô dọc bên cạnh là repo và lịch phát. Phần còn lại nhỏ dần. Cỡ chữ không được dùng để giành sự chú ý.
2. **Mỗi ô một con số.** Mỗi ô có một logo nguồn, một số đo thật (điểm, sao, số ngày, số tin, số nguồn) và một nhãn. Không ô nào chỉ có chữ. Trường dữ liệu nào vắng thì ô đó ẩn hoặc ghi rõ là chưa có.
3. **Logo và số là màu.** Khung trang gần như không màu. Màu đến từ logo nguồn và ảnh YouTube thật. Màu duy nhất của giao diện là Hot Coral (`892dd4019c1`, 07/11): nền coral chữ mực cho hành động chính, chữ coral đậm (`--color-accent`) cho mục đang chọn và số nổi bật, ô "đang phát" là bề mặt coral duy nhất của trang Sự kiện.
4. **Khoảng thở.** Thẻ cách nhau 12px (`--msn-gap`; 8px dưới 700px), dải cách dải 24px (`--band-gap`; 32px trên điện thoại), lề trong thẻ 12–16px, mỗi thẻ ít mục. Khoảng trống là một phần của bố cục, không phải chỗ để lấp.
5. **Chuyển động như dòng chảy.** Các ô trôi vào lần lượt, số đếm lên, vòng điểm tự vẽ, tờ chi tiết trượt ra. Mọi chuyển động dùng chung một đường cong giảm tốc. Khi người đọc bật giảm chuyển động, không còn gì trượt, phóng hay giãn; độ mờ và màu vẫn chuyển dần trong 150 ms (anh duyệt 16/11, "Duyệt theo em": giữ mờ dần, tắt trượt).

## Token suy ra từ nguyên tắc
| Nguyên tắc | Token | Giá trị và lý do |
| --- | --- | --- |
| 1 | `--msn-gap`, `--msn-card-r`, `--msn-panel-r`, `--msn-cols` | Khe 12px. Thẻ bo 12px như nhau trên điện thoại và máy tính (anh 11/11 12:4x); khung chính và mọi tấm nổi (Tùy chỉnh, ứng dụng Google, kết quả tìm) bo 16px. Tối đa 5 cột (anh 10/11 17:51). |
| 2 | `--num-hero` → `--num-md` | Thang số tách riêng khỏi thang chữ: 128 / 88 / 56 / 32px, chữ đậm 700, `tabular-nums`, giãn chữ −0,04em. |
| 2 | `--av-*`, `--av-radius` | Logo 20–72px, bo kiểu squircle 28% như icon ứng dụng. Khi không có logo đã xác minh thì dùng chữ lồng: màu nền và màu chữ là `--av-mono-bg`, `--av-mono-ink` (độ sáng và độ đậm, đổi theo giao diện), sắc độ suy ra từ tên nguồn; cỡ chữ là `--av-text-*`. Logo của một tin là logo nguồn đưa tin, trừ khi bản thân tin là một repo hay một model, khi đó là logo chủ repo. |
| 3 | `--gray-*` (hue 258), `--color-accent`, `--color-accent-fill`, `--color-current` | Dải xám lạnh nhạt cùng một hue và một màu Hot Coral. Chữ đều đạt từ 4,5:1 trở lên ở cả hai giao diện. Nhãn của mục đang chọn trên nền coral nhạt (dock) là `--color-current`: coral ở nền sáng, màu mực ở nền tối, vì coral nhạt trên nền tối chỉ đạt 3,64:1 (rà soát 16/11). |
| 3 | Độ sâu | Không viền ở đâu cả (anh 08/11 21:08; `72d1ece6ab7`). Khung chính tô màu nhạt (`--color-panel-front`); thẻ trắng nằm trên nó với bóng nghỉ `--msn-shadow-rest` (`d57fde96615`), nâng lên khi rê chuột. Tấm nổi dùng bóng sâu hơn (`--tc-shadow`, `--shadow-sheet`). Ô xương lúc tải dùng màu mặt thẻ, nên hiện rõ trên khung. |
| 4 | `--space-4` … `--space-96` | Thang 4pt. Lề trong thẻ 16px (thẻ Sự kiện cũng vậy từ 16/11); dòng danh sách 8–12px. |
| 5 | `--ease-flow`, `--motion-*` | Đường cong `cubic-bezier(0.16,1,0.3,1)`, cả carousel tin nổi bật. Gạch dưới tab và nút sắp xếp cùng trượt trong `--motion-state` (250 ms). Thời lượng theo đặc tả 02/10: ô mới 300 ms, mở chi tiết 350 ms, đóng 250 ms, số đếm 600 ms. |

**Chữ:** một họ duy nhất là Be Vietnam Pro (400, 500, 600, 700), đủ dấu tiếng Việt, theo cách Apple chỉ dùng một họ SF. Dòng chữ đọc cao 1,55 để dấu chồng tầng (ế, ộ, ữ) có chỗ.

**Dark mode** chỉ thay tầng ngữ nghĩa. Mặt ô sáng dần lên để nổi, số luôn là thứ sáng nhất. Trang theo cài đặt của hệ thống cho tới khi người đọc tự chọn. Lựa chọn đó chỉ lưu trên máy của họ.

## Phone story card

Captain, 11/11 10:50, with two Samsung News screens: *"Trên Mobile làm sạch sẽ kiểu như vậy. Nhớ tuân thủ design system"*. Below 768 px every story on the front page is its own white card on the grey page, laid out the phone's way: the source's mark and name on the first line, the headline for up to four lines, a square picture (`--story-card-pic`, 31% of the card's text width, 80–112 px) to the right, and the time closing the card under both; no dek, no border. It is the desktop story card in that layout (captain, 11/11 12:4x: *"giao diện mobile và desktop nó không đồng bộ, rõ nhất là bo góc của thẻ tin"*): corner `--story-card-r` = `--msn-card-r` (12 px), the same rest shadow and surface, the source line and time in `text-micro` as on desktop, 12 px between cards, and the picture's corner `--story-card-pic-r` = `radius-8`, the inset frame of a desktop card. A full-width card takes the desktop wide card's 16 px padding and headline (`--story-card-title` = `--msn-title-wide`). A notable story ("Đáng chú ý", a double story) keeps the same lines under a full-width 16:9 picture with the notable headline (`--story-card-title-big`): area is hierarchy. "Chuyện lớn" becomes four cards led by their rank in the number scale (`--story-card-rank`, 32 px; `text-feature` at 370 px and narrower), each with the same square picture on the right when the story has one. The panel runs edge to edge under the search with only its top corners rounded (`--msn-panel-r`), and band titles grow to `text-tile`. No "⋮" menu: a card has no actions besides opening the story. Tablet and desktop keep the bento cards. Rules: the phone block of `site/trang-msn.css`; tests: `tests/test_mobile_the_tin.py`.

## Band heading with a control

A band's heading row may carry the one control that acts on that band's own list, and only that list (`.band-head`: the title on the left, the control on the right). The order "Đáng đọc nhất / Mới nhất" lives on "Tin mới" (captain, 11/11 12:3x: *"dời đi"*): it reorders "Tin mới" and "Tin khác" and never the first screen, so it no longer sits in the header beside the tabs. It keeps the segmented control's look (`.tc-seg`: `color-seg-track`, a raised `color-seg-thumb` side, `seg-thumb-r`), 44 px sides, and the reader's choice (`air2:sort`). The header row is the logo, the tabs and "Bản tin sáng" (a phone: the logo and the tabs). Light, dark and "Theo máy" are chosen only in "Tùy chỉnh" (the top row's sliders button), as the segmented control "Giao diện" (captain, 11/11 13:54: *"nút chỉnh sáng/tối phải đặt ở trong menu tùy chỉnh, không đặt ở ngoài"*).

## Switching tabs

Captain, 11/11 12:4x: *"a cũng muốn làm cái gạch màu dưới mỗi tab đó di chuyển mượt mà từ tab này sang tab kia. đồng thời cố định những thành phần giống nhau ở mỗi tab, chỉ tải lại nội dung"*. The panel, its header row, the tabs and the phone dock are one shell that never redraws; a tab replaces only the view inside the panel, and a view once drawn is kept whole and put back when its tab returns (drawn again only for a new snapshot, another order or a save). The active tab's underline (`--msn-tab-line`, `color-accent-fill`) is a single line that glides to the new tab and takes its label's width, by transform alone, in `--motion-state` with `--ease-flow`; under reduced motion it jumps. A view without a tab of its own ("Sự kiện", `#sap-toi`) underlines no tab: the line fades out (audit 16/11). The new view fades in over the same duration, opacity only. Nothing in the shell moves: the page keeps its scrollbar's gutter (`scrollbar-gutter: stable`) and the panel reaches the window's foot however short the view. Each tab has its own address (none, `#repo`, `#xep-hang`), so Back, Forward and reload return to it. Rules: `site/trang-msn.css`, `glideLine` and `setFilter` in `site/feed.js`; tests: `tests/test_tab_switch.py`.

## UI audit, 16/11

The captain approved the audit's open questions on 16/11 with *"Duyệt theo em"*. For the front page and the shared shell:
- The extension's invitation covers nothing: a row in the page's flow under "Hôm nay", with "Thêm vào Chrome" and "Ẩn" (it was a card in the bottom-right corner, 12/11).
- "Chuyện lớn" headlines are 15 px, a card's headline; a row that no longer fits the card is left out, never cut.
- "Tùy chỉnh" carries the way to "Nguồn tin" and "Chính sách riêng tư" (the home had none since the footer went, 09/11). On the extension's new tab they open on hco.news.
- Reduced motion keeps the fades and stops the movement (principle 5).
- The secondary pages (Bản tin, Nguồn tin, a story's page, Chính sách, the 404 page) wear the home's shell: the top row with "Tùy chỉnh" and the Google apps, the tinted panel with the Coral Tile, white cards. `site/trang-phu.css` draws it from the same tokens without loading the front page's stylesheet. The 404 page marks no destination in the phone dock.
- The privacy page's reading column is 60ch (about 73 characters a line in Be Vietnam Pro).
- The contact e-mail on the privacy page waits for the captain's choice.

## Phone lead story

At widths up to 767px, the lead keeps its full headline, source/kind/time, selection evidence, measured number, and translation attribution visible. One inline disclosure reveals the original title, full summary, sources, score, actions, and related stories together. Its state survives redraws for the same lead and resets when the lead changes. Tablet and desktop retain the complete layout. Phones render all board tiles together so the next tile does not wait for a separate paint after the compact lead.
