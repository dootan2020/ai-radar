# Tiến Độ Phòng Báo Halcyon: Chuẩn Hóa Hợp Đồng & An Toàn Ban Bệ

> **Thời điểm cập nhật:** 27/10/2026  
> **Nhánh:** `feat/phong-bao-hop-dong`  
> **Mục tiêu:** Thực hiện chỉ đạo của Thuyền trưởng (27/10 14:06): chuẩn hóa tiêu chuẩn đầu vào/đầu ra (contracts) cho từng ban bệ agent, áp dụng nguyên tắc an toàn tuyệt đối (Fail-Closed), bảo vệ chống Prompt Injection trước khi model đọc bài, và mở rộng bộ đọc theo dõi chuyển hướng an toàn.

---

## 1. Thông Tin Phiên Làm Việc (Session Intent)

Triển khai đầy đủ 5 mục tiêu theo brief kỹ thuật:
1. **Thiết lập hợp đồng bằng mã nguồn (`phong_bao/contracts.py`):** Định nghĩa cụ thể trường đầu vào, trường đầu ra, miền giá trị cho phép và tiêu chuẩn từ chối cho 5 ban bệ hiện hữu: Tiếp nhận (Intake), Phóng viên (Reporter), Biên tập (Editor), Kiểm chứng (Checker), Tổng biên tập (Chief). Mọi phản hồi từ model đều được kiểm thực qua contract.
2. **Khóa chặt nguyên tắc Fail-Closed tại Bàn Biên Tập:** Bất kỳ phản hồi nào vi phạm hợp đồng schema sau khi thử lại (retry) đều lập tức bị đóng dấu giữ lại với lý do `editor_invalid`, chấm dứt việc tự động biến lỗi schema thành tin tức xuất bản (khắc phục Lỗ hổng Redteam số 3).
3. **Phòng chống Prompt Injection tất định & Cô lập văn bản dữ liệu:** Dữ liệu văn bản bài báo, tiêu đề, tóm tắt được định ranh giới rõ ràng kèm chỉ dẫn nội dung chỉ dùng để thẩm định chứ không phải mệnh lệnh thực thi; mọi bài viết chứa chỉ thị thao túng (ví dụ `SYSTEM OVERRIDE`, `ignore previous`, `set news=true`, `return claims: []`) bị chặn đứng ngay tại Bàn Tiếp Nhận với nhãn `prompt_injection` trước khi bất kỳ model nào nhìn thấy. Tin đồn về các thương vụ/thỏa thuận chưa được kiểm chứng sẽ bị giữ lại trừ khi có nguồn đọc độc lập hỗ trợ.
4. **Theo dõi chuyển hướng mạng an toàn (Safe Redirects):** Cập nhật `fetch_article_result` trong `radar/summary_pipeline.py` hỗ trợ theo dõi chuyển hướng tối đa 5 bước, kiểm tra `robots.txt` tại từng chặng, phát hiện vòng lặp (`redirect_loop`), từ chối tường phí và giao thức không an toàn, giúp khôi phục các bài viết dùng link rút gọn hoặc chuyển hướng HTTP->HTTPS (khắc phục Lỗ hổng Redteam số 7).
5. **Tuân thủ Leak-Guard:** Không khớp cứng cụm từ riêng lẻ của fixture, giữ vững các quy tắc ở dạng tổng quát. Kiểm thử leak-guard giữ nguyên trạng thái xanh (GREEN).

---

## 2. Danh Mục Tệp Chỉnh Sửa & Bổ Sung (Files Modified)

- [`phong_bao/contracts.py`](file:///C:/Users/Admin/ai-radar-wt-phong-bao-rt/phong_bao/contracts.py): Mô-đun mới chứa định nghĩa hợp đồng của 5 ban bệ (`DESK_CONTRACTS`), bộ từ khóa/mẫu phát hiện Prompt Injection (`PROMPT_INJECTION_PATTERNS`), mẫu nhận diện tin đồn (`RUMOUR_KEYWORDS`), và các hàm kiểm thực (`validate_intake_output`, `validate_reporter_reply`, `validate_reporter_output`, `validate_editor_reply`, `validate_editor_output`, `validate_checker_reply`, `validate_checker_output`, `validate_chief_output`).
- [`phong_bao/newsroom.py`](file:///C:/Users/Admin/ai-radar-wt-phong-bao-rt/phong_bao/newsroom.py): Tích hợp kiểm thực hợp đồng cho từng khâu; cập nhật `_intake` chặn prompt injection; sửa `_editor` áp dụng Fail-Closed (`is_news = False` khi `invalid`); bổ sung cổng chặn tại `_chief` cho `editor_invalid` và tin đồn thiếu nguồn độc lập; cập nhật prompt chỉ dẫn rõ văn bản trong trích dẫn là dữ liệu thẩm định.
- [`radar/summary_pipeline.py`](file:///C:/Users/Admin/ai-radar-wt-phong-bao-rt/radar/summary_pipeline.py): Nâng cấp `fetch_article_result` theo dõi chuyển hướng an toàn, kiểm tra robots.txt từng bước, phát hiện vòng lặp và giới hạn số bước chuyển hướng (`MAX_REDIRECT_HOPS = 5`).
- [`tests/test_phong_bao.py`](file:///C:/Users/Admin/ai-radar-wt-phong-bao-rt/tests/test_phong_bao.py): Cập nhật các trường hợp kiểm thử trước đây vốn ghi nhận hành vi fail-open của editor sang kiểm thử hành vi fail-closed (`hold`, `editor_invalid`).
- [`tests/test_summary.py`](file:///C:/Users/Admin/ai-radar-wt-phong-bao-rt/tests/test_summary.py): Cập nhật bộ kiểm thử bộ đọc mạng xác minh xử lý chuyển hướng thành công, giới hạn bước và phát hiện vòng lặp.
- [`tests/test_phong_bao_contracts.py`](file:///C:/Users/Admin/ai-radar-wt-phong-bao-rt/tests/test_phong_bao_contracts.py): Tệp kiểm thử chuyên biệt xác thực toàn diện hợp đồng 5 ban bệ, cơ chế fail-closed, chặn prompt injection không cần model, chặn tin đồn và xử lý chuyển hướng HTTP giả lập.

---

## 3. Bản Hợp Đồng Chi Tiết 5 Ban Bệ (Dành Cho Thuyền Trưởng)

Theo đúng định hướng: *"mỗi node agent trong phòng ban đều phải có tiêu chuẩn đầu vào và đầu ra làm sao đạt kết quả chất lượng cao nhất"*.

### Ban 1: Bàn Tiếp Nhận & Kỹ Thuật (Intake Gatekeeper)
- **Nhiệm vụ:** Lọc kỹ thuật, xác minh tính toàn vẹn của liên kết và ngăn chặn tấn công Prompt Injection ngay tại cửa vào.
- **Tiêu chuẩn đầu vào (Input):**
  - `id`: chuỗi định danh duy nhất (bắt buộc).
  - `title`: tiêu đề bài viết (chuỗi không rỗng).
  - `url`: đường dẫn công khai (bắt buộc).
  - `published_at`: chuỗi thời gian xuất bản hợp lệ.
  - `summary`: văn bản tóm tắt/teaser (tùy chọn).
  - `now`: thời điểm chạy chu kỳ (UTC datetime).
- **Tiêu chuẩn đầu ra (Output):**
  - `id`: str.
  - `pass`: boolean (`True` nếu đạt, `False` nếu bị chặn).
  - `reason`: lý do cụ thể nếu bị chặn ("eligible for reporting" nếu đạt).
- **Tiêu chuẩn từ chối (Rejectable Criteria - Chặn Hold ngay lập tức):**
  1. Thiếu tiêu đề hoặc URL không chuẩn hóa được (`canonical_url`).
  2. Không phân tích được mốc thời gian xuất bản tin cậy.
  3. Thời gian xuất bản nằm ở tương lai (> 24 giờ).
  4. Sự kiện gốc cũ hơn 30 ngày mà không có cập nhật xác minh.
  5. Phát hiện dấu hiệu Prompt Injection trong tiêu đề hoặc tóm tắt (`prompt_injection`).
  6. Không có bằng chứng AI là chủ đề chính của bài báo qua bộ lọc `press_subject_reason`.

### Ban 2: Bàn Phóng Viên & Đọc Nguồn (Reporter Desk)
- **Nhiệm vụ:** Tìm kiếm và xác thực nguồn đọc độc lập cùng sự kiện; đọc bài đại diện và theo dõi chuyển hướng an toàn.
- **Tiêu chuẩn đầu vào Model (Model Input):**
  - Danh sách bài: `id`, `title`, `published_at`, `representative_url`, `representative_status`, danh sách các ứng viên `candidates` (mỗi ứng viên gồm `url`, `title`, `publisher`, `text`, `read_status`).
- **Hợp đồng phản hồi từ Model (Model Reply Contract):**
  - `id`: str.
  - `selected_url`: str (phải thuộc danh sách URL ứng viên hợp lệ) hoặc `null`.
  - `same_event`: boolean (bắt buộc phải là kiểu boolean).
  - `reason`: chuỗi giải thích ngắn gọn.
- **Tiêu chuẩn từ chối phản hồi Model:**
  - Có cờ `model_failure`.
  - `same_event` không phải kiểu boolean.
  - `selected_url` không phải chuỗi hoặc không thuộc danh sách ứng viên đã cung cấp.
- **Đầu ra chính thức của Bàn (Desk Output):**
  - `id`, `readable` (bool), `selected_url` (str|null), `source_text` (str), `reason` (str), `invalid_response` (bool), `representative_status` (str), `provider` (str|null), `boat` (str|null).

### Ban 3: Bàn Biên Tập & Luận Điểm (Editor Desk)
- **Nhiệm vụ:** Phân loại thể loại tin tức (`event_news`, `analysis`, `junk`), đề xuất phân tầng (`top`, `notable`, `standard`), và bóc tách các luận điểm cốt lõi (`claims`).
- **Tiêu chuẩn đầu vào Model (Model Input):**
  - `id`, `title`, `summary`, `published_at`, `original_url`, `kind`, `coverage`, `source_url`, `source_status`, `source_excerpt` (cắt tối đa 1.200 ký tự).
- **Hợp đồng phản hồi từ Model (Model Reply Contract):**
  - `id`: str.
  - `news`: boolean (bắt buộc).
  - `content_kind`: bắt buộc thuộc `{"event_news", "analysis", "junk"}`.
  - `analysis_kind`: bắt buộc thuộc `{"analysis", "interview", "opinion", "podcast", "survey"}` nếu là `analysis`.
  - `junk_kind`: bắt buộc thuộc danh mục chuẩn `JUNK_KINDS` nếu `news` là `False`.
  - `subject`, `event_type`: chuỗi không rỗng nếu `news` là `True`.
  - `importance`: bắt buộc thuộc `{"top", "notable", "standard"}`.
  - `event_at`: chuỗi ngày ISO-8601 hoặc `null`.
  - `claims`: mảng tối đa 8 luận điểm; mỗi luận điểm dài từ 1 đến 520 ký tự; không trùng lặp câu chữ.
  - `same_event_coverage_ids`: mảng các coverage ID cùng sự kiện (phải là tập con của story).
- **Nguyên tắc Chặn Tuyệt Đối (Fail-Closed Enforcement):**
  - Nếu phản hồi sau khi retry vẫn vi phạm bất kỳ điều kiện nào trên hoặc gặp lỗi model, hệ thống lập tức gán `news = False`, `invalid_response = True`, và `reason = "editor_invalid"`.
  - Card này sẽ bị chặn giữ lại ở cổng Bàn Biên tập, tuyệt đối không được phép cho đi tiếp.

### Ban 4: Bàn Kiểm Chứng Đối Lập (Checker Desk)
- **Nhiệm vụ:** Sử dụng thuyền đối trọng độc lập để đối soát từng luận điểm và tiêu đề với các đoạn trích dẫn thực tế từ bài báo; phát hiện số liệu bịa đặt.
- **Tiêu chuẩn thuyền:** Bắt buộc thuyền kiểm chứng (`boat`) phải khác hoàn toàn thuyền của biên tập viên (`boat != editor_boat`).
- **Tiêu chuẩn đầu vào Model (Model Input):**
  - `id`, `title`, `claims`, `source_url`, danh sách `cited_paragraphs` (đoạn trích phù hợp nhất từ văn bản nguồn).
- **Hợp đồng phản hồi từ Model (Model Reply Contract):**
  - `id`: str.
  - `title_supported`: boolean.
  - `supported_claims`: danh sách các luận điểm được chứng minh có trong nguồn.
  - `reason`: chuỗi giải thích.
- **Tiêu chuẩn từ chối phản hồi:**
  - Vi phạm nguyên tắc thuyền đối trọng (`boat == editor_boat`).
  - `title_supported` không phải boolean hoặc `supported_claims` không phải danh sách.
- **Đầu ra chính thức của Bàn (Desk Output):**
  - `id`, `verified` (bool), `title_supported` (bool), `supported_claims` (list[str]), `rejected_claims` (list[str]), `reason` (str), `invalid_response` (bool), `provider` (str|null), `boat` (str|null).

### Ban 5: Bàn Tổng Biên Tập & Ký Duyệt (Chief Desk)
- **Nhiệm vụ:** Ký duyệt quyết định cuối cùng dựa trên các cổng chặn Fail-Closed nghiêm ngặt.
- **Tiêu chuẩn đầu vào:** Kết quả từ 4 bàn bệ trước đó và mốc thời gian chu kỳ.
- **Cơ chế Cổng Chặn Xuất Bản (Publication Gates):**
  1. Cổng Intake: Giữ lại nếu `intake["pass"] == False` (ví dụ: `prompt_injection`, cũ, ngoài lề).
  2. Cổng Editor: Giữ lại nếu `editor["news"] == False` hoặc `reason` thuộc `{"editor_model_failure", "editor_invalid"}`.
  3. Cổng Tin Đồn: Giữ lại nếu bài viết mang tính chất tin đồn thương vụ/hợp tác bí mật mà không có nguồn đọc độc lập nào xác thực (`unverifiable rumour without independent readable source`).
- **Phân tầng & Hạ cấp (Tier Capping):**
  - Nếu nguồn không đọc được, hoặc kiểm chứng bác bỏ một phần luận điểm/tiêu đề, bài viết bị hạ cấp xuống `standard`.
  - Hạng `top` đòi hỏi tối thiểu 4 đến 8 luận điểm đã được kiểm chứng đầy đủ.
- **Đầu ra quyết định (`quyet-dinh.json`):**
  - Bản ghi đầy đủ gồm: `id`, `decision` (`"hold"`|`"publish"`), `content_kind`, `analysis_kind`, `round`, `reason`, `importance_tier`, `tier_capped`, `summary`, `degradation_reasons`, `use_original_title`, `source_url`, `key_points`, `same_event_coverage_ids`, `split_coverage_ids`.

---

## 4. Quyết Định Kỹ Thuật (Decisions Made)

1. **Xử lý dứt điểm Redteam Finding 3 (Fail-Open schema error):**
   - Loại bỏ biểu thức `(news is True or invalid)`. Khi `invalid` là `True`, `is_news` luôn bằng `False`. Card được đóng dấu `editor_invalid` và chuyển sang trạng thái `hold`.
2. **Cơ chế phòng chống Prompt Injection 2 lớp:**
   - Lớp 1 (Tất định trước Model): Kiểm tra nhanh qua regex tại Bàn Tiếp Nhận đối với mọi từ khóa thao túng. Card bị giữ lại ngay mà không tốn token gọi model.
   - Lớp 2 (Chỉ dẫn ngữ cảnh): Cung cấp chỉ thị rõ ràng trong prompt của mọi bàn bệ rằng dữ liệu trích dẫn là nội dung để đánh giá, không phải lệnh thực thi.
3. **Chặn tin đồn thương vụ không nguồn kiểm chứng:**
   - Tại Chief Desk, các bài viết đề cập tin đồn/thương vụ bí mật mà phóng viên không tìm được nguồn đọc độc lập sẽ bị giữ lại, khắc phục trường hợp tin giả lọt qua ở hạng standard.
4. **Xử lý Redirect mạng an toàn:**
   - Triển khai thuật toán theo dõi chuyển hướng tuân thủ robots.txt, giới hạn 5 bước, kiểm tra chu kỳ vòng lặp, hỗ trợ HTTP->HTTPS và link rút gọn.

---

## 5. Trạng Thái Hiện Tại & Bằng Chứng Kiểm Thử (Current State & Proof)

- **Toàn bộ bộ kiểm thử phòng báo:**
  - `python -m unittest discover -s tests -p "test_phong_bao*.py"`: **59 tests OK (1.664s)**
- **Toàn bộ bộ kiểm thử pipeline tóm tắt:**
  - `python -m unittest discover -s tests -p "test_summary*.py"`: **88 tests OK (2.600s)**
- **Kiểm thử Leak-Guard:**
  - `test_prompts_do_not_repeat_fixture_title_phrases`: **OK (0.091s)**
- **Kiểm thử hợp đồng & an toàn:**
  - `tests/test_phong_bao_contracts.py`: **13 tests OK (0.006s)**

---

## 6. Kế Hoạch Tiếp Theo (Next Steps)

1. Chuyển giao để Lucy chạy lại 20 bài đối kháng trong `tests/fixtures/phong-bao/redteam/cards.json` và 100 bài kiểm thử giữ chỗ (held-out stories) qua các bàn bệ thực tế.
2. Sẵn sàng tích hợp tiếp các ban bệ mới (Kiểm định cụm tin, Bóc tách luận điểm chuyên sâu, Biên dịch tiếng Việt) trong các giai đoạn kế tiếp theo thiết kế kiến trúc.
