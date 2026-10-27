# Bảng chấm bản tin Halcyon

Bảng này thay điểm "x/10" chấm theo cảm giác. Mỗi bản tin được chấm bằng mười tiêu chí, mỗi tiêu chí kiểm được bằng cách đọc một bản tin cạnh bài gốc. Reviewer (Codex, agy, Claude) và bước tự kiểm của bàn Người viết dùng chung một trang này. Anh Tuấn duyệt bảng ngày 2026-10-28 (*"ai-radar: a đồng ý với đề xuất của em"*).

Lý do: hai vòng review trước chấm 6,8/10 rồi 7,1/10 trên sáu mẫu tự chọn, và lỗi lặp lại là bản tin bỏ điều kiện, phạm vi hoặc đối trọng làm nên nghĩa của câu chuyện ([vòng 3](../plans/reports/review-nguoi-viet-codex-vong3.md)). Hợp đồng viết nằm ở `phong_bao/newsroom.py` (`WRITER_PROMPT`) và `radar/summary_validation.py`; bốn câu hỏi nghiệm thu của anh (2026-10-27) là diễn biến, nguyên nhân, ví dụ, ý nghĩa.

## Mười tiêu chí

Mở bài gốc cạnh bản tin. Mỗi tiêu chí chỉ có hai kết quả: đạt hoặc trượt. Không có "đạt một phần"; nghi ngờ thì ghi trượt và nêu câu nguồn.

| Số | Tiêu chí | Cách kiểm (dưới một phút) | Ví dụ trượt | Nguồn gốc |
| --- | --- | --- | --- | --- |
| 1 | Câu đầu nói đúng tin chính | Tìm kết quả hay quyết định trung tâm của bài gốc. Câu đầu bản tin có nêu đúng điều đó không, kể cả khi đó là ai thắng, kết quả nghiên cứu hay lệnh cấm? | Bài so sánh có người thắng ("Best Overall"), bản tin chỉ nói "các tác nhân AI đang tiến bộ". | Axios: dòng đầu là tin. NN/g: kết luận lên đầu. |
| 2 | Có nguyên nhân | Tìm câu trả lời cho "vì sao". Đó có đúng là lý do bài gốc nêu, không phải lý do người viết suy ra? | Chỉ kể cách thử nghiệm, không nói vì sao cuộc thử đáng chú ý. | Axios: why it matters. Reuters: "Hold accuracy sacrosanct". |
| 3 | Có ví dụ hoặc số cụ thể kèm nguồn | Tìm ít nhất một ví dụ hoặc số. Số đó có tên thước đo, đối tượng đo và mốc so sánh không? Có trong bài gốc không? | "Đạt 84%" mà không nói đo gì, so với mức nào. | Reuters: "Hold accuracy sacrosanct". Axios: go deeper bằng chi tiết cụ thể. |
| 4 | Có ý nghĩa cho người đọc Việt Nam | Đoạn cuối có nói kết quả này đổi điều gì cho người đọc và giới hạn của nó, không chỉ nhắc lại diễn biến? | Đoạn cuối chỉ tóm lại câu đầu bằng chữ khác. | Axios: why it matters. |
| 5 | Giữ điều kiện/phạm vi của kết quả | Với mỗi kết quả, tìm điều kiện trong bài gốc (mô phỏng, benchmark, mẫu khảo sát, "có thể", "phần lớn", ai nói). Điều kiện còn nằm trong cùng câu với kết quả không? | "Moratorium" (tạm dừng) thành "cấm hoàn toàn"; cảnh báo mất ghế ở Ohio thành cảnh báo chung về ngành. | Reuters: "Hold accuracy sacrosanct". |
| 6 | Giữ đối trọng nếu bài gốc có | Bài gốc có phản ví dụ, phản đối hoặc lực kéo ngược cụ thể không? Nếu có, bản tin giữ ít nhất một cái? | Bài có "tiền công nghệ cũng tác động cuộc đua", bản tin chỉ còn áp lực từ cử tri. | Reuters: "Strive for balance and freedom from bias". |
| 7 | Không bịa | Mỗi tên, số, ngày, trích dẫn, quan hệ nhân quả trong bản tin tìm được trong bài gốc. Không có số do người viết tự tính. | Cộng hai số của nguồn thành tổng mới; gán nguyên nhân bài không nói. | Reuters: "Do not fabricate or plagiarise". |
| 8 | Không bình luận thay nguồn | Tìm từ phán xét ("đáng lo", "lạm dụng", "thành công lớn") và kiểm bài gốc có nói vậy không. Ý kiến của tác giả có được ghi là ý kiến của tác giả không? | Gọi một cách dùng là "lạm dụng" khi nguồn chỉ mô tả. | Reuters: "Avoid injecting unattributed opinion in a news story". |
| 9 | Đoạn ≤4 câu, câu ≤25 chữ | Đếm câu từng đoạn; đếm đơn vị cách nhau bằng khoảng trắng ở câu dài nhất (cách đếm của vòng 3, không phải tách từ tiếng Việt). | Một câu 40 chữ nối năm mệnh đề; đoạn năm câu. | NN/g: đọc lướt, một ý một đoạn. |
| 10 | Thuật ngữ nhất quán với bài khác trong ngày | Lấy một thuật ngữ chính (agent, benchmark, moratorium) và so với các bản tin khác cùng ngày trên trang. Có dịch hoặc giải thích giống nhau không? | "Tác nhân AI" ở bài này, "agent" ở bài kia, không giải thích cả hai. | NN/g: người đọc lướt dựa vào từ quen. |

## Quy tắc đạt

- Một bản tin đạt khi được **ít nhất 9/10** tiêu chí.
- **Trượt tiêu chí 7 (bịa) hoặc 1 (câu đầu sai tin chính) là trượt cả bản tin**, bất kể điểm. Tiêu chí 7 vì một chi tiết bịa phá niềm tin vào mọi chi tiết còn lại. Tiêu chí 1 vì người đọc điện thoại thường chỉ đọc câu đầu (NN/g); câu đầu sai thì phần còn lại không cứu được.
- Mỗi bản tin chấm riêng, không lấy trung bình giữa các bản tin.

## Cách báo cáo

Một dòng cho mỗi bản tin: `<id hoặc tiêu đề ngắn>: 9/10, trượt 5`. Bản tin trượt tiêu chí 7 hoặc 1 thêm `TRƯỢT TỰ ĐỘNG`. Mỗi tiêu chí trượt kèm một dòng bằng chứng: câu của bản tin và câu hoặc đoạn của bài gốc.

Ví dụ cách ghi, rút từ các phát hiện trong [review vòng 3](../plans/reports/review-nguoi-viet-codex-vong3.md) mục 1 (Verge, trung tâm dữ liệu): `Data center backlash: 8/10, trượt 5, 6`. Trượt 5 vì "cấm hoàn toàn" bỏ nghĩa tạm dừng và cảnh báo của tổ chức đảng thành cảnh báo chung; trượt 6 vì bỏ thế giằng co của tiền công nghệ. Báo cáo đó chưa đo tiêu chí 9 và 10, nên ví dụ giả định chúng đạt; đây không phải điểm chính thức của bản tin.

## Điều kiện đảo ngược

Tiêu chí 8 đúng khi Halcyon là bản tin trung lập, nói lại điều nguồn nói. Nếu sau này Halcyon chọn giọng bản tin có quan điểm, **tiêu chí 8 bị bỏ** (còn chín tiêu chí, ngưỡng đạt cần anh Tuấn chốt lại) và mỗi bài có bình luận phải ghi rõ là quan điểm của Halcyon.

## Ghi chú về nguồn

- `[CONFIRMED — https://www.nngroup.com/articles/how-users-read-on-the-web/, 2026-10-28]` Nielsen Norman Group: người dùng web chủ yếu đọc lướt; mỗi đoạn một ý; đưa kết luận lên trước; viết ngắn, quét được và khách quan cho kết quả dễ dùng hơn rõ rệt trong thử nghiệm của họ. Cơ sở của tiêu chí 1, 9 và 10.
- `[CONFIRMED — https://reutersagency.com/about/standards-values/, 2026-10-28]` Reuters Journalistic Standards, mục "The 10 Hallmarks of Reuters Journalism": "Hold accuracy sacrosanct" (tiêu chí 2, 3, 5), "Strive for balance and freedom from bias" (tiêu chí 6), "Do not fabricate or plagiarise" (tiêu chí 7), "Avoid injecting unattributed opinion in a news story" (tiêu chí 8). Trang cũng có "Correct errors transparently", chưa có tiêu chí tương ứng.
- `[CONFIRMED — https://www.axios.com/smart-brevity, 2026-10-28]` Trang "Smart Brevity: The Power of Saying More with Less" của những người sáng lập Axios và Politico, mang tên phương pháp và câu "Stop wasting your reader's time". Cấu trúc dòng đầu là tin, Why it matters, Go deeper (tiêu chí 1, 2, 3, 4) là định dạng bản tin Axios như trang này và cuốn sách mô tả; đây không phải câu trích từ trang.
