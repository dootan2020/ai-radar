# Tiến độ: bàn "Người viết" (ai-radar)

## Session Intent
Round 1: The "Người viết" desk writes Halcyon's summaries; the Gemini API only fills what the desk could not. Success: after one newsroom cycle on recent stories, the site shows the desk's Vietnamese summary for those stories with visible "phòng báo" provenance, and `radar.summarize` no longer spends API budget on them.

Round 2 (owner, 27/10 20:0x): "Vấn đề lớn nhất là cách chọn và phân bổ thông tin, chứ không phải thiếu độ dài." Desk output becomes 3-4 short Vietnamese paragraphs (~120-180 words): main development, cause, 1-2 representative examples, significance; terms explained in parentheses; fewer proper names. Acceptance: the reader can answer "chuyện gì xảy ra, vì sao, điểm đáng chú ý là gì, và nó có ý nghĩa gì". New contract, sentence-level number/name checks, site shows paragraphs with "Phòng báo Halcyon tóm tắt từ <nguồn>", shared validator stops flagging currency codes and Vietnamese renderings.

Round 3 (brief 27/10, after the gpt-6-astra review at 6.8/10): the writer desk keeps the source's conditions and scope when it concludes. Success: on a fresh batch of 6-8 recent stories mixing hard news, blogs and arXiv papers, the same reviewer grades the desk at 8 or higher, with no sentence that states a conclusion stronger than its cited paragraph.

## Files Modified
- `phong_bao/newsroom.py`: desk `writer` between checker and chief; `WRITER_PROMPT` (prose brief, round 2); `_written_prose` (sentence-level drops, shape rules), `_published_prose`, `_point_error`, `writer_window_hours` (env `PHONG_BAO_WRITER_WINDOW_HOURS`, default 48, 0 = off); `_chief` merges written prose (`summary="written"`, `written_by="nguoi-viet"`); `Articles.read` memoizes per URL.
- `phong_bao/runner.py`: non-Codex CLIs (agy, claude) run in an empty temporary working directory.
- `phong_bao/contracts.py`: `DESK_CONTRACTS["writer"]` (prose), `validate_writer_output`; `validate_chief_output` checks `written_by` rows.
- `radar/newsroom_decisions.py`: `DESK_SUMMARY_SOURCE="nguoi-viet"`, `DESK_PROMPT_VERSION="summary-vi-6-prose"`, `desk_fields_valid`, `desk_summary`, `is_desk_summary`; `apply_decisions` copies desk prose into stories.
- `radar/summary_pipeline.py`: desk-written stories are kept and skipped by the API; stats `desk_written`.
- `radar/summary_validation.py`: currency codes allowed when the evidence names that currency (`CURRENCY_EVIDENCE`); Vietnamese renderings (`Latinh`, hyphenated `Xin-ga-po`) count as Vietnamese; spelled numbers up to "twenty" support digits.
- `radar/story_pages.py`, `site/story.js`, `site/editorial-headline.js`, `site/story.css` (+ byte-identical `extension/story.css`, `extension/editorial-headline.js`, required by `test_extension_shell`): desk prose rendered as paragraphs with label "Phòng báo Halcyon tóm tắt từ <outlet>".
- Tests: `tests/test_phong_bao.py` (desk count), new `tests/test_phong_bao_writer.py`, `tests/test_newsroom_decisions_writer.py`, `tests/test_summary_validation_names.py`; added cases in `tests/test_story_pages.py`, `tests/test_summary_display.py`.

## Decisions Made
- Writer sits after checker, before chief; chief stays the single place that writes the decision row.
- Round 2 contract `summary-vi-6-prose`: reply `{id, status, title_vi, paragraphs:[{role, sentences:[{text, evidence_refs}]}], used_source_ids, limitations}`; roles development/cause/examples/significance. Each sentence and the title pass `claim_error` (same evidence assembly as the API validator). Failing sentence dropped; title failure, <3 paragraphs, development not first or significance not last, or outside 90-230 words => API fallback.
- Paragraphs are stored in `key_points` (3-4 strings) with `key_points_prompt_version="summary-vi-6-prose"`, so retention, search, editions and the video script keep working; display gates accept the prose contract only together with `key_points_source="nguoi-viet"`. The API path keeps 4-8 points under `summary-vi-5-full`.
- `partial_source` / `missing_primary` are set from the evidence, not from the model.
- Agent CLIs run in an empty directory: measured in the first round-2 run, agy spent ~20 tool turns reading this repo's validator and tests (transcript `~/.gemini/antigravity-cli/brain/3aa632fa-.../logs/transcript.jsonl`), which made batch 2 cost 96.7k input tokens. Codex keeps the checkout (sandboxed, needs Git).
- Validator currency fix requires the evidence to name the currency (HK$, RMB2.96, yuan...); an unnamed currency such as EUR stays rejected.

## Current State
- Round 3 (21:20): prompt + `conditions` slot + significance/paragraph-lost rules in place, contract still `summary-vi-6-prose`; full suite 1489 OK (skipped=8); live run 6/8 written on agy. Details and samples under "Round 3" / "Round 3 — mẫu". Nothing committed.
- Full suite: see report (last run after all edits).
- Round 1 dry run (19:10-19:21): 4 stories, 2 written as points. Recheck of round 1 drops with the fixed validator: SCMP `Latinh` -> pass; TechNode 4x `HKD`/`RMB` -> pass; TechNode `15,5` still `invented_number` (the writer computed 100-64.5-20; source does not state it).
- Round 2 live run: 6 new stories (none from round 1) from latest cycle 20261027T110008Z, agy `gemini-3.8-flash-high`, job `phong-bao/thu-nguoi-viet-2/` (untracked).
  - Run A (agy in repo cwd), 19:55-19:59: 6/6 written; batches 10.0k in/20.5k out (4 stories), 96.7k in/24.1k out (2 stories). Saved as `job/writer-luot-a-co-doc-repo.json`.
  - Run B (empty cwd, final), 20:05-20:11: 6/6 written; batches 10.0k in/32.5k out (4 stories), 27.7k in/12.2k out (2 stories). One sentence dropped (`invented_number: 11`; source says "eleven" — validator now accepts spelled numbers up to twenty, so it would pass today).

## Round 2 — mẫu
Run B, 27/10/2026 20:05-20:11 (+07), agy gemini-3.8-flash-high. Văn bản dưới đây đúng như bàn viết ra và qua bộ kiểm; đã chạy trước khi sửa "eleven", nên câu về 11 mô hình ở tin 4 bị bỏ.

### 1. “AI Skills” are worthless in 2026

Link gốc: https://fishbowl.pastiche.org/2026/10/26/ai-skills  
Đăng: 2026-10-27T06:33:34Z · 4 đoạn, 165 từ

**Tác giả Charles Miller cho rằng các kỹ năng tương tác với AI sẽ sớm mất giá trị lâu dài**

Tác giả Charles Miller nhận định kỹ năng sử dụng trí tuệ nhân tạo (AI) học trong vài tuần không có giá trị lâu dài do sẽ sớm lỗi thời. Quan điểm này trái ngược với lời kêu gọi vội vã gia nhập làn sóng AI vì sợ bị tụt hậu.

Theo Miller, các thủ thuật giúp mô hình chạy tốt hơn nếu hiệu quả đều sẽ nhanh chóng được tích hợp làm tính năng mặc định của sản phẩm sau vài tháng.

Điển hình là kỹ nghệ câu lệnh (prompt engineering - kỹ thuật viết chỉ dẫn cho mô hình) có nguy cơ thành thói quen lạc hậu, giống các mẹo tối ưu mã nguồn trong lập trình C từng bị trình biên dịch tự động hóa từ lâu.

Thực tế từ Google hay iPhone cho thấy việc làm đúng quan trọng hơn việc dẫn đầu, và người dùng chỉ cần bắt kịp tiến độ thay vì chạy theo các kỹ năng nhất thời.

### 2. The Mythical Man-Month in the Age of AI

Link gốc: https://j11g.com/the-mythical-man-month-in-the-age-of-ai  
Đăng: 2026-10-27T06:25:37Z · 4 đoạn, 177 từ

**Định luật Brooks về nhân lực phần mềm tiếp tục biến đổi trong kỷ nguyên tác nhân AI**

Định luật Brooks từ năm 1975 về quản lý phần mềm được đánh giá không hề biến mất mà đang biến đổi trong kỷ nguyên tác nhân trí tuệ nhân tạo (AI agents). Dù các tác nhân AI loại bỏ nhiều trở ngại nhân sự như thời gian hòa nhập hay họp hành, quy luật về tiến trình tuần tự vẫn không thay đổi.

Nguyên nhân là do áp lực chuyển từ quản lý con người sang điều phối tác nhân, khi lập trình viên vẫn phải kiểm duyệt mã nguồn và xử lý ảo giác (hallucinations - lỗi AI bịa đặt dữ liệu).

Điển hình là khi thả chín tác nhân tự động vào cùng một mã nguồn mà thiếu điều phối rõ ràng, chúng sẽ nhanh chóng ghi đè thành quả của nhau trong một vòng lặp hỗn loạn.

Thực tế này dẫn đến đúc kết cho năm 2026 rằng việc bổ sung thêm tác nhân vào một dự án có yêu cầu không rõ ràng chỉ giúp tạo ra kết quả sai nhanh hơn.

### 3. Thinking-in-Bets at Test Time Reduces Sycophantic Revisions in LLM Agents

Link gốc: https://arxiv.org/abs/2610.34654  
Đăng: 2026-10-26T00:00:00Z · 4 đoạn, 177 từ

**Phương pháp Thinking-in-Bets giúp tác nhân AI giảm sửa đổi a dua theo người dùng**

Tác giả Nghi D. Q. Bui công bố Thinking-in-Bets, phương pháp không cần huấn luyện lại giúp các tác nhân trí tuệ nhân tạo (AI) tránh việc từ bỏ kết quả đúng khi bị người dùng phản đối. Mô hình sẽ tự lập một hồ sơ riêng ghi nhận các khẳng định chính và độ tin cậy trước khi đọc ý kiến phản bác.

Cơ chế này khắc phục tình trạng tác nhân thường bỏ qua kiểm tra ban đầu để chiều theo ý kiến phàn nàn, trong khi việc ép giữ nguyên quan điểm lại khiến chúng bỏ lỡ sai sót thực tế.

Thử nghiệm trên năm mô hình Gemini cho thấy giải pháp gần như xóa bỏ việc đảo ngược sai trong duyệt bản vá và giảm đáng kể các chỉnh sửa tệp không cần thiết khi lập trình.

Kết quả cho thấy việc tự đối chiếu lập luận yếu nhất trước khi phản hồi giúp nâng cao độ chính xác cho hệ thống AI mà không cần tốn kém chi phí đào tạo lại.

### 4. Constrained Decoding: Harmful or Beneficial? Revisiting Its Impact on LLM Performance

Link gốc: https://arxiv.org/abs/2610.35328  
Đăng: 2026-10-26T00:00:00Z · 3 đoạn, 132 từ (đoạn ví dụ mất vì câu "11 mô hình" bị bỏ)

**Nghiên cứu bác bỏ định kiến kỹ thuật giải mã có ràng buộc làm suy giảm tư duy của AI**

Một nghiên cứu mới chỉ ra kỹ thuật giải mã có ràng buộc (constrained decoding - phương pháp ép mô hình AI trả lời theo cấu trúc định sẵn) không hề làm suy giảm khả năng suy luận. Nhóm tác giả chia kỹ thuật này thành ba nhóm: ràng buộc định dạng, ràng buộc tính hợp lệ và ràng buộc quỹ đạo tư duy.

Hiện tượng giảm hiệu năng trước đây thực chất bắt nguồn từ câu lệnh và định dạng thử nghiệm không đồng nhất, thay vì do cơ chế mặt nạ ở bộ giải mã.

Kết quả khẳng định tác động của kỹ thuật này phụ thuộc vào loại ràng buộc, giúp người phát triển tự tin áp dụng để tối ưu mô hình mà không lo hại tư duy.

- Câu bị bỏ (examples, invented_number: 11; nguồn viết "eleven open-source models"): Thử nghiệm trên 11 mô hình nguồn mở cho thấy việc loại bỏ đáp án sai giúp tăng độ tin cậy, còn việc định hình tiến trình hợp lý giúp cải thiện độ chính xác.

### 5. More Memory, Better Videos? A Controlled Study of Visual Memory in Long-Video Generation

Link gốc: https://arxiv.org/abs/2610.35001  
Đăng: 2026-10-26T00:00:00Z · 4 đoạn, 168 từ

**Thước đo VMem-Bench chỉ ra bộ nhớ thị giác có thể gây sai lệch khi tạo video dài**

Một nghiên cứu mới công bố bộ thử nghiệm VMem-Bench nhằm kiểm tra tác động thực tế của bộ nhớ thị giác (visual memory - cơ chế truy xuất hình ảnh quá khứ) trong quá trình tạo video dài.

Thử nghiệm được thực hiện vì các hệ thống tạo video ngày càng lạm dụng dữ liệu cũ để tránh lệch danh tính nhân vật, xuất phát từ giả định rằng việc xem lại lịch sử sẽ luôn giúp mạch phim nhất quán.

Kết quả cho thấy cơ chế truy xuất giúp tăng độ tương đồng với quá khứ nhưng lại làm giảm độ chính xác từ 0,977 xuống 0,915-0,938 và có thể củng cố các diện mạo đã lỗi thời sau khi câu chuyện thay đổi.

Các tác giả chỉ ra rằng hình ảnh đúng với quá khứ có thể sai lệch so với bối cảnh hiện tại, do đó tính nhất quán bề mặt chưa đủ để chứng minh độ hữu dụng thực sự của bộ nhớ.

### 6. EmbodiedLab: Benchmarking Embodied Agents That Act to Know

Link gốc: https://arxiv.org/abs/2610.35385  
Đăng: 2026-10-26T00:00:00Z · 4 đoạn, 175 từ

**EmbodiedLab công bố thước đo robot tự hành làm thí nghiệm để khám phá tri thức**

Một nhóm nghiên cứu vừa ra mắt EmbodiedLab, bộ tiêu chuẩn đánh giá khả năng của các tác nhân thể hiện (embodied agent - robot có hình thể) tự quyết định tương tác vật lý để tìm kiếm tri thức.

Thước đo này ra đời do các bài kiểm tra hiện nay chỉ tập trung vào việc thao tác theo mục tiêu định sẵn hoặc thử nghiệm lý thuyết, thay vì buộc robot phải chủ động làm thí nghiệm để tự tìm ra câu trả lời.

Trong 30 thí nghiệm trên 14 nền tảng thiết bị, ngay cả mô hình mạnh nhất với khả năng điều khiển trực tiếp cũng thành công dưới một nửa số lần, với phần lớn thất bại bắt nguồn từ việc thao tác sai với dụng cụ.

Kết quả cho thấy kỹ năng thao tác vật lý giúp ích cho các mô hình yếu nhiều hơn là năng lực nhận thức hay lập kế hoạch, nhấn mạnh trở ngại cốt lõi của robot tự hành trong nghiên cứu khoa học.

## Next Steps
- Coordinator: owner and a Codex reviewer read the six samples against the source links (selection, cause, representative examples, significance; and facts the validator cannot check, e.g. "năm mô hình Gemini", "Google hay iPhone").
- Note for review: the latest cycle was 20261027T110008Z, so 4 of 6 samples are arXiv papers and 2 are blog essays; no news story like The Verge's was in the new set. Re-measure on the 22:00 cycle for news coverage.
- Empty agy working directories (`%TEMP%/phong-bao-*`) can outlive a call by a moment; cleanup errors are ignored, so a few empty folders may accumulate.
- Commit (coordinator); `plans/` is gitignored, use `git add -f` for this file if wanted.

## Round 3
- 27/10 ~20:55: started. Read the review (plans/reports/review-nguoi-viet-codex.md), WRITER_PROMPT, _written_prose, contracts, writer tests. Found: site/editorial-headline.js and extension/editorial-headline.js hard-code 'summary-vi-6-prose' and site/ is outside this round's scope.
- Skills read: `ak-context-engineering` (kept the prompt one stable block per call so agy's prefix stays cacheable, added a cheap planning slot instead of a second model pass, recorded tokens per batch from the runner's own telemetry, never estimated); `ak-test` (no mocks to pass: new tests drive `_writer` through the fixture runner and the real `claim_error`; narrow tests first, then the full suite); `ak-cook` (full scope of the brief, regressions repaired before finishing).

### Options considered
1. Prompt only (the eight recommendations as prose). Cheap, but round 2 already asked for an "assessment the article supports" and the model still wrote "không lo hại tư duy": nothing checks it.
2. Prompt + a `conditions` planning slot + a shape rule (chosen). The model first copies the source's limiting words verbatim with their paragraph ID; the code keeps only spans found in that paragraph, and every significance sentence must cite a paragraph that holds one. A conclusion sentence without its condition paragraph is dropped; losing the significance paragraph or any whole paragraph sends the story to the API.
3. A Vietnamese hedge-word check (e.g. reject "không hề", "chắc chắn"). Rejected: brittle, would hit legitimate negations, and the reviewer's faults were missing scope, not banned words.
4. A second model pass that critiques the draft. Rejected for now: doubles agy tokens per batch and adds a model route to verify.
Reason for 2: it is the cheapest way to make "keep the condition next to the result" observable, while the meaning of each Vietnamese sentence stays with the reviewer.

### Contract version
Kept `summary-vi-6-prose`. The published shape is unchanged (3-4 paragraphs in `key_points`), and `site/editorial-headline.js` / `extension/editorial-headline.js` hard-code that string while `site/` and `extension/` are outside this round's scope; a bump would hide every desk summary on the site. The new `conditions` field is in the model reply only, never published.

### What the eight recommendations changed (prompt `WRITER_PROMPT`, shape `_written_prose`)
| # | Recommendation | Change |
|---|---|---|
| 1 | four answers right, not four paragraphs | "WHAT THE READER NEEDS": correct means at the strength the source states, inside its setting; four paragraphs that overstate fail |
| 2 | paper "why" = research problem | new paper frame: cause = problem/gap + test design; causal claim only when the source shows it |
| 3 | condition in the result's sentence | STEP 1 `conditions` (verbatim, <=25 words, paragraph ID) + STEP 3 "same sentence as the result it limits" with four contrast pairs; code: significance sentence must cite a condition paragraph (`condition_not_cited`) |
| 4 | one comparison; cut names before limits | paper examples = one comparative result; "drop proper names and counts before you drop a condition" |
| 5 | numbers only with metric/object/comparison | paper examples: name the metric, say what it measures, give the comparison; "a number without its metric and object is not allowed" |
| 6 | simulation vs benchmark vs deployment | setting is the first kind of condition; "never turn a benchmark or simulation result into a real-world capability or deployment advice" |
| 7 | plain terms, author's view kept | explain terms in plain Vietnamese incl. agent/benchmark; essays: say it is the author's view; no value judgement the source does not make |
| 8 | re-check after sentence drops | GROUNDING: write each sentence to survive a neighbour's removal; code: any whole paragraph lost -> `paragraph_lost` (API fallback) |
Prompt diff in short: SHAPE split into news/essay and paper frames, two new sections (STEP 1 CONDITIONS, STEP 3 KEEP THE CONDITION WITH THE RESULT), STYLE gains opinion/value-judgement/term rules, GROUNDING gains the survive-a-drop rule, OUTPUT gains `conditions: [{text, ref}]` and "headline keeps the same conditions". Length ~3.3k -> ~5.0k chars.

### Code and tests
- `phong_bao/newsroom.py`: `_grounded_conditions` (verbatim match after case/whitespace/curly-quote folding; rejected spans logged in `dropped_points` as `condition_not_in_source`), significance check `condition_not_cited`, `paragraph_lost` fallback, missing `conditions` list = `writer_invalid`; reason now ends "conditions <refs>|none".
- `phong_bao/contracts.py`: writer `model_reply_fields` gains `conditions`; rejectable conditions updated.
- `tests/test_phong_bao_writer.py`: fixture reply carries conditions; new tests: conclusion without its condition paragraph is dropped (and the story falls back when it was the only significance sentence), invented/misplaced conditions are rejected, missing list is invalid, a lost paragraph falls back, the paper frame validates with three paragraphs, the prompt carries the new rules.
- Narrow: `tests.test_phong_bao_writer tests.test_newsroom_decisions_writer tests.test_phong_bao` 57 OK. Full suite (21:01-21:05): `Ran 1489 tests in 234.869s` / `OK (skipped=8)`.
- Runner untouched. The live run is driven by a scratch script that removes `codex` from discovery's commands (Codex at 97% of its week; brief allows agy only) and refuses to run unless the writer lane is `["agy"]`.

### Live run (Round 3)
- Job `phong-bao/thu-nguoi-viet-3/` (untracked): input = 8 stories from the published snapshot (generated 2026-10-27T13:41:38Z); upstream desks copied read-only from cycles 20261027T110008Z (Verge, Wired, SCMP, TechNode, arXiv 2610.35328, 2610.35385) and 20261027T130009Z (IEEE Spectrum, oioannou blog). Builder and driver scripts in the coordinator's scratchpad (`build_round3.py`, `run_round3_writer.py`).
- 21:05-21:20 (+07), agy `gemini-3.8-flash-high`, writer lane forced to `["agy"]`. Result: 6/8 written, 2 to API.
- Tokens per batch (runner telemetry): 3 stories 9,968 in / 38,994 out; 2 stories 33,923 in / 34,461 out; 1 story 25,324 in / 21,697 out; 2 stories 7,023 in / 19,975 out. Total 76.2k in / 115.1k out for 8 stories (round 2: 37.7k / 44.7k for 6). Output per story roughly doubled with the conditions step; two batches again show >25k input, which suggests agy still reads something beyond the prompt in some calls (not investigated; runner untouched).
- Fallbacks: SCMP UN governance -> model returned `insufficient_evidence`; TechNode -> its development sentence was dropped by the shared validator (`unsupported_number_unit: usd` on "86,80 đô la Hồng Kông", source "HK$86.80"), so `paragraph_roles`. That is a validator false positive on a Vietnamese currency rendering; `radar/summary_validation.py` is outside this round's scope.
- Own read against the copied condition spans (not a substitute for the reviewer): Constrained Decoding now keeps "largely", "appropriate ... can preserve", "when they enforce beneficial trajectories" and ends on the "depends on the type of constraint" limit, but its headline "phần lớn không làm suy giảm năng lực suy luận" moves "largely" from the cause of the degradation onto the conclusion, a stronger claim than p009. EmbodiedLab now says "phòng thí nghiệm mô phỏng vật lý" in the first and last sentences.

## Round 3 — mẫu
Run 27/10/2026 21:05-21:20 (+07), agy gemini-3.8-flash-high. Văn bản dưới đây đúng như bàn viết ra và qua bộ kiểm. Mỗi bài kèm các điều kiện bàn viết chép nguyên văn từ nguồn (để reviewer đối chiếu câu kết với đoạn nguồn).

### 1. Data center backlash is uniting America

Link gốc: https://www.theverge.com/policy/1019152/data-centers-midterm-elections  
Đăng: 2026-10-27T10:00:00Z · 4 đoạn, 165 từ  
Bộ kiểm: đạt — `prose written: development/cause/examples/significance, 165 words, conditions outlet:p031,outlet:p033,outlet:p052`; câu bị bỏ: 0

**Ứng cử viên hai đảng tại Mỹ tìm cách né tránh trung tâm dữ liệu trước thềm bầu cử**

Tại Mỹ, nhiều ứng cử viên chính trị dường như đang tìm cách giữ khoảng cách với các trung tâm dữ liệu nhằm xoa dịu cử tri trước cuộc bầu cử giữa kỳ.

Sự phản đối của cử tri gia tăng do lo ngại việc xây dựng ồ ạt trung tâm dữ liệu tại địa phương sẽ gây quá tải lưới điện và tăng chi phí năng lượng.

Tại bang Texas, ứng viên đảng Dân chủ James Talarico đề xuất hạn chế dùng nước và bỏ ưu đãi thuế, trong khi ứng viên đảng Cộng hòa Ken Paxton muốn cấm xây ở nông thôn và ngăn chặn công nghệ Trung Quốc.

Mức độ hành động của các chính khách vẫn rất khác nhau từ cấm hoàn toàn đến trao quyền tự quyết cho địa phương, trong khi Ủy ban Thượng viện đảng Cộng hòa cảnh báo làn sóng phản đối có thể đe dọa sự phát triển tương lai của các trung tâm dữ liệu.


- Điều kiện bàn viết chép từ nguồn: `outlet:p031` “appear to be distancing themselves from data centers”; `outlet:p031` “How far they’re willing to go — including by backing an outright moratorium on development — varies.”; `outlet:p033` “emphasize different messages in their plans”; `outlet:p052` “warned that losing the Ohio Senate seat could endanger future support for data centers”

### 2. I Tested Every Major AI Agent for a Day. Here’s the Best One

Link gốc: https://www.wired.com/story/i-tested-every-major-ai-agent-for-a-day-heres-the-best-one/  
Đăng: 2026-10-27T09:30:00Z · 4 đoạn, 159 từ  
Bộ kiểm: đạt — `prose written: development/cause/examples/significance, 159 words, conditions outlet:p003,outlet:p011,outlet:p012,outlet:p013`; câu bị bỏ: 0

**Phóng viên WIRED thử nghiệm thực tế sáu tác nhân AI phổ biến trong một ngày**

Theo quan điểm của cây bút tạp chí WIRED, các tác nhân AI (phần mềm tự động thực hiện chuỗi tác vụ) hoạt động thường trực đang bùng nổ và vận hành đáng tin cậy hơn trước dù vẫn còn mắc lỗi.

Để đánh giá thực tế, người viết đã thử nghiệm sáu tác nhân AI trên điện thoại trong hai mươi bốn giờ qua năm bài kiểm tra về độ chủ động, khả năng duyệt web và tuân thủ mệnh lệnh.

Trong bài kiểm tra lập bản tin, chỉ có Dots và Muse dành phần lớn ba mươi phút yêu cầu để nghiên cứu sâu, trong khi các công cụ khác phản hồi gần như ngay lập tức.

Dù ghi nhận tiến bộ, người thử nghiệm nhấn mạnh đây chỉ là lát cắt giới hạn trên phần mềm còn non trẻ, vốn tiềm ẩn nhiều lo ngại về quyền riêng tư và bảo mật dữ liệu cá nhân.


- Điều kiện bàn viết chép từ nguồn: `outlet:p003` “at least more reliably than last year. AI agents still make mistakes”; `outlet:p011` “designed five basic tests to run each agent through, enacting all this chaos over 24 hours”; `outlet:p012` “software remains nascent and often fraught with privacy and security concerns”; `outlet:p013` “these tests are a limited sliver of what the tools can do”

### 3. Beijing pushes for UN-led governance of artificial intelligence at global forum

Link gốc: https://www.scmp.com/tech/policy/article/3372285/beijing-pushes-un-led-governance-artificial-intelligence-global-forum  
Đăng: 2026-10-27T08:34:13Z  
Bộ kiểm: **không xuất bản, chuyển API** — `insufficient_evidence`


### 4. Dongshan Precision’s Acquisition-Led AI Bet Meets a Cooler Market

Link gốc: https://technode.com/2026/10/27/dongshan-precision-acquisition-led-ai-bet-hong-kong/  
Đăng: 2026-10-27T07:02:39Z  
Bộ kiểm: **không xuất bản, chuyển API** — `paragraph_roles`

- Câu bị bỏ (development, unsupported_number_unit: usd): Dongshan Precision định giá chào bán tại Hồng Kông ở mức 86,80 đô la Hồng Kông mỗi cổ phiếu, thấp hơn khoảng 35% so với giá đóng cửa cổ phiếu A tại đại lục ngày 23 tháng 10 sau quy đổi tiền tệ, dù lợi nhuận nửa đầu năm 2026 tăng 290%.

- Điều kiện bàn viết chép từ nguồn: `outlet:p004` “approximately 35% below its October 23 A-share closing price after currency conversion”; `outlet:p022` “The company attributed the increase to additional financing associated with acquisitions and capacity expansion, as well as foreign-exchange losses.”; `outlet:p007` “The question is how quickly the businesses it bought can generate the cash needed to sustain that expansion.”; `outlet:p029` “If supply grows faster than customers’ requirements, the margin gains that encouraged expansion will become harder to sustain.”

### 5. Constrained Decoding: Harmful or Beneficial? Revisiting Its Impact on LLM Performance

Link gốc: https://arxiv.org/abs/2610.35328  
Đăng: 2026-10-26T00:00:00Z · 3 đoạn, 169 từ  
Bộ kiểm: đạt — `prose written: development/cause/significance, 169 words, conditions outlet:p009`; câu bị bỏ: 0

**Nghiên cứu: Giải mã có ràng buộc phần lớn không làm suy giảm năng lực suy luận của mô hình lớn**

Thực nghiệm trên bốn họ mô hình và mười một mô hình mã nguồn mở cho thấy sự sụt giảm hiệu năng biểu kiến phần lớn bắt nguồn từ câu lệnh và định dạng không tương đương, thay vì do việc che mặt nạ ở tầng giải mã.

Nghiên cứu kiểm tra giả định cho rằng giải mã có ràng buộc (kỹ thuật bắt buộc mô hình ngôn ngữ lớn tạo đầu ra theo khuôn mẫu) vốn dĩ làm suy giảm khả năng suy luận. Về mặt lý thuyết, các tác giả chứng minh những ràng buộc phù hợp có thể duy trì hiệu năng, đồng thời các ràng buộc suy luận có thể cải thiện độ chính xác khi ép buộc các quỹ đạo có lợi.

Kết quả này làm thay đổi cách đánh giá về giải mã có ràng buộc, nhưng bị giới hạn bởi phát hiện rằng tác động thực tế phụ thuộc vào loại ràng buộc và không gian đầu ra mà nó loại bỏ.


- Điều kiện bàn viết chép từ nguồn: `outlet:p009` “Across four model families and eleven open-source models, causal ablations on diverse benchmarks”; `outlet:p009` “appropriate constraints can preserve or improve performance by eliminating invalid paths”; `outlet:p009` “apparent performance degradation largely stems from non-equivalent prompting and output formats rather than from decoder-level masking”; `outlet:p009` “reasoning constraints can improve reasoning and, consequently, accuracy when they enforce beneficial trajectories”; `outlet:p009` “the impact of constrained decoding depends on the type of constraint and the output space it removes”

### 6. EmbodiedLab: Benchmarking Embodied Agents That Act to Know

Link gốc: https://arxiv.org/abs/2610.35385  
Đăng: 2026-10-26T00:00:00Z · 4 đoạn, 163 từ  
Bộ kiểm: đạt — `prose written: development/cause/examples/significance, 163 words, conditions outlet:p009`; câu bị bỏ: 0

**Đánh giá trong mô phỏng EmbodiedLab: Tác nhân AI mạnh nhất thành công dưới một nửa số lần thử**

Trong phòng thí nghiệm mô phỏng vật lý của chuẩn đánh giá (benchmark) EmbodiedLab, tác nhân AI (agent, thực thể tự hành) mạnh nhất cũng chỉ thành công dưới một nửa số lần với điều khiển gốc.

Thử nghiệm nhằm khắc phục các chuẩn cũ vốn bỏ qua thực nghiệm vật lý hoặc chỉ dừng ở thao tác định sẵn. Nghiên cứu so sánh sáu mô hình qua 30 thí nghiệm khoa học giữa cơ chế điều khiển gốc với các phương án bổ sung nhận thức hay kỹ năng thao tác.

Đánh giá kết quả (đo tri thức ghi nhận và trạng thái vật lý đạt được) cho thấy kỹ năng thao tác giúp các mô hình yếu cải thiện nhiều hơn so với nhận thức và lập kế hoạch.

Nghiên cứu cho thấy tương tác với thiết bị gây ra phần lớn thất bại, song kết luận này mới chỉ được xác lập trong phòng thí nghiệm mô phỏng vật lý.


- Điều kiện bàn viết chép từ nguồn: `outlet:p009` “operates a physics-based simulated laboratory”; `outlet:p009` “Across 30 experiments in five disciplines on 14 apparatus platforms”; `outlet:p009` “With native control, even the strongest agent succeeds less than half the time”; `outlet:p009` “for every agent, most failures arise in interacting with the apparatus”; `outlet:p009` “manipulation skills help weaker agents more than perception and planning”

### 7. Wikipedia's Cleanup of AI-Generated Content

Link gốc: https://spectrum.ieee.org/wikipedia-wikiproject-ai-writing-cleanup  
Đăng: 2026-10-27T11:08:15Z · 4 đoạn, 167 từ  
Bộ kiểm: đạt — `prose written: development/cause/examples/significance, 167 words, conditions outlet:p019,outlet:p021,outlet:p024`; câu bị bỏ: 0

**Wikipedia tiếng Anh cấm dùng LLM tạo bài viết và tìm cách ngăn nội dung máy ngày càng tinh vi**

Dự án WikiProject AI Cleanup đang tìm cách phát hiện văn bản máy móc tinh vi, sau khi Wikipedia tiếng Anh cấm dùng LLM (mô hình ngôn ngữ lớn) tạo bài viết.

Theo đồng sáng lập Ellia Lebleu, nỗ lực xuất phát từ việc bách khoa toàn thư bị tràn ngập nội dung do AI tạo và mối lo về các nguồn trích dẫn hoàn toàn sai lệch.

Công cụ Pangram ước tính tỷ lệ bài viết mới do AI tạo giảm từ khoảng 20% cuối năm 2025 xuống 15 đến 16% đầu năm 2026, cung cấp mức cận dưới rất thận trọng. Nhóm WikiProject AI Cleanup cũng thử nghiệm công cụ AI kiểm tra nguồn nhưng thừa nhận hệ thống không đảm bảo luôn chính xác.

Lebleu nhận định hiện còn quá sớm để khẳng định quy định cấm có hiệu lực hay do AI ngày càng tinh vi, trong khi Wikipedia nỗ lực giữ gìn bản sắc kho tư liệu thuần do con người viết.


- Điều kiện bàn viết chép từ nguồn: `outlet:p019` “so its results provide a very conservative lower bound”; `outlet:p019` “we don’t yet know whether that’s because our recent policies have had an effect or because models are getting more powerful”; `outlet:p021` “there is no guarantee that it will be correct every time.”; `outlet:p024` “It’s still a little early to tell.”

### 8. AI promised less work. I've never worked more

Link gốc: https://oioannou.com/blog/ai-promised-less-work/  
Đăng: 2026-10-27T11:08:14Z · 4 đoạn, 162 từ  
Bộ kiểm: đạt — `prose written: development/cause/examples/significance, 162 words, conditions outlet:p004,outlet:p012,outlet:p041,outlet:p042`; câu bị bỏ: 0

**Góc nhìn kỹ sư: Vận hành nhiều agent khiến khối lượng công việc tăng vọt thay vì giảm bớt**

Theo tác giả, việc vận hành nhiều agent (tác nhân phần mềm tự hành) khiến ông làm việc nhiều hơn và căng thẳng hơn dù công nghệ hứa hẹn tiết kiệm thời gian.

Khối lượng công việc tăng vì chi phí lập trình rẻ kích thích nhận thêm dự án, trong khi việc liên tục đổi ngữ cảnh để trả lời từng agent gây mệt mỏi tinh thần.

Dữ liệu GitHub cá nhân, vốn chỉ phản ánh hoạt động thô chứ không đo lường giá trị, cho thấy tác giả đạt 2.102 đóng góp đến cuối tháng 10 năm 2026, vượt cả năm giai đoạn 2021–2025. Riêng tháng 8 năm 2026 lập kỷ lục với 427 đóng góp khi ông mở hàng loạt luồng thử nghiệm mới.

Tác giả nhận định khả năng thực thi của công cụ tăng nhanh hơn năng lực tư duy của con người, dẫn tới các đợt quá tải rồi kiệt sức mà chưa có giải pháp.


- Điều kiện bàn viết chép từ nguồn: `outlet:p004` “data from my own GitHub history.”; `outlet:p012` “It is a rough signal of activity, not a measure of value.”; `outlet:p041` “capacity to implement those ideas has grown much faster than my capacity to think about them.”; `outlet:p042` “The experience, decisions and opinions are mine.”


### Round 3 — next steps
- Coordinator: send the 6 written samples (and the 2 fallbacks) to the gpt-6-astra reviewer; owner judges. Flag the Constrained Decoding headline above.
- Validator owner: "đô la Hồng Kông" read as USD (`unsupported_number_unit: usd`) cost the TechNode story; needs a fix in `radar/summary_validation.py` in a round that may touch it.
- Watch agy output tokens (~14k per story now); if it matters, test a shorter STEP 1 (cap conditions at 4).

## Round 4 — bật bàn viết
- Owner 2026-10-27 22:37 (verbatim): "bật người viết đi, bảo đảm newsroom chạy mà không cần API". Goal: key points come from the writer desk only; the Gemini API summary path no longer runs for stories.
- 22:4x: started; reading radar/summarize, update.yml, summary_validation.

### What changed (round 4)
1. **API off by default for key points.** `radar/summarize.py`: unless `RADAR_SUMMARY_API_FALLBACK=1`, the step calls the pipeline with an empty API key and no paid mode, so it sends no Gemini request and fetches no article for the API. It keeps desk prose, restores summaries already validated in the cache (no request), writes the site snapshot, sets `summary.status="skipped"`, `skipped_by="writer_desk"`, and prints one line: `Summary skipped: writer desk owns summaries (N desk-written, M restored from cache, 0 API requests; set RADAR_SUMMARY_API_FALLBACK=1 to run the API)`, exit 0. **No workflow edit needed**: `.github/workflows/update.yml` step "Summarize stories" (lines 316-329) keeps running the same command; it simply never opts in. To turn the API back on later, that step's `env:` needs `RADAR_SUMMARY_API_FALLBACK: '1'` (a workflow change, owner's call).
2. **Validator: Hong Kong dollars.** `radar/summary_validation.py`: the `usd` unit no longer matches "đô la" when "Hồng Kông/Hong Kong/HK" follows; a new `hkd` unit checks "đô la Hồng Kông / HKD / Hong Kong dollars" against the source, including the prefix form `HK$86.80` (`UNIT_PREFIXES`). Test `test_hong_kong_dollars_are_hkd_not_usd` (wrong amount still fails as `hkd`; a bare "đô la" against HK$ still fails as `usd`).
3. **No API fallback for stories the desk cannot write.** They keep no key points. Verified in code: `radar/story_pages.py` and `site/story.js renderFallbackBodyHTML` render "Đoạn trích bài viết" (publisher excerpt or an honest empty note), never an empty key-points box; existing tests `test_summary_display` (line 48) and `test_story_pages` (lines 231-232) assert it. Desk prose renders with "Phòng báo Halcyon tóm tắt từ <outlet>" on the story page and modal. The feed cards do not show key points at all, so there is no provenance to show there.
4. **Prompt, one change** (round-3 review recommendations 1-3 as the coordinator worded them): STEP 1 is now "CENTRAL RESULT AND CONDITIONS": identify the central result first (a comparison states who came out ahead), every example supports it (time spent is not quality), keep one specific counterpoint from the source. No new shape rules.
5. Tests: `tests/test_newsroom_decisions_writer.py::test_summary_cli_sends_no_api_request_without_explicit_opt_in` (Gemini transport and article fetch patched to fail; desk prose kept; one output line; status skipped). Three existing CLI tests that exercise the API path now opt in explicitly (`tests/test_summary.py`, `tests/test_summary_quota.py`, `tests/test_gemini_paid_budget.py`).
6. Full suite (22:5x-23:0x): `Ran 1491 tests in 463.467s` / `OK (skipped=8)`.

### Dry run (writer only, agy, new prompt) — `phong-bao/thu-nguoi-viet-4/`
TechNode (round 3 fallback) + two 20:00-cycle stories, snapshot 2026-10-27T15:41:13Z. One batch: 9,547 in / 28,639 out tokens. Result 2/3 written:
- TechNode now publishes (4 paragraphs, 157 words; "9,88 tỷ đô la Hồng Kông" passes). One significance sentence dropped as `condition_not_cited`, the story still stands.
- TechCrunch Nvidia/Simplismart published (168 words; keeps "in some cases" and the counterpoint that inference efficiency may help Nvidia).
- SCMP Zhang Yiming: `insufficient_evidence` again. Cause measured: the article reader gets ~1.2k characters from SCMP (header and teaser only, body not in the HTML); the round-3 SCMP story was the same (1,164 chars). With the API off, SCMP stories will carry no key points. Fixing that is a reader task, not the writer, and bot-wall bypass stays rejected.

#### Round 4 — mẫu

### 1. Dongshan Precision’s Acquisition-Led AI Bet Meets a Cooler Market

Link gốc: https://technode.com/2026/10/27/dongshan-precision-acquisition-led-ai-bet-hong-kong/  
Đăng: 2026-10-27T07:02:39Z · 4 đoạn, 157 từ  
Bộ kiểm: đạt — `prose written: development/cause/examples/significance, 157 words, conditions outlet:p004,outlet:p005,outlet:p029`; câu bị bỏ: 1

**Dongshan Precision gọi vốn tại Hồng Kông với giá chiết khấu 35% giữa áp lực chi phí mở rộng AI**

Dongshan Precision chuẩn bị chào sàn Hồng Kông với giá chiết khấu khoảng 35% so với giá cổ phiếu tại đại lục sau quy đổi tiền tệ. Đợt phát hành dự kiến thu về khoảng 9,88 tỷ đô la Hồng Kông dù nhu cầu vay mua từ nhà đầu tư cá nhân ở mức thấp.

Việc gọi vốn của Dongshan Precision nhằm tài trợ kế hoạch mở rộng hạ tầng trí tuệ nhân tạo (AI) bằng thâu tóm doanh nghiệp, yếu tố giúp lợi nhuận ròng nửa đầu năm 2026 tăng 290%.

Mảng mô-đun quang học (thiết bị chuyển đổi tín hiệu điện và ánh sáng) mang về 19,2% doanh thu, nhưng chi phí tài chính cũng tăng vọt lên khoảng 546 triệu nhân dân tệ do nợ vay.

Nếu nguồn cung linh kiện tăng nhanh hơn nhu cầu khách hàng, mức tăng biên lợi nhuận từng thúc đẩy mở rộng sẽ trở nên khó duy trì.

- Câu bị bỏ (significance, condition_not_cited): Theo bài viết, thách thức lớn nhất là các mảng kinh doanh mới phải tạo ra tiền mặt đủ nhanh để gánh chi phí mở rộng.

- Điều kiện bàn viết chép từ nguồn: `outlet:p004` “approximately 35% below its October 23 A-share closing price after currency conversion”; `outlet:p005` “That figure measures financed applications for the public tranche, excludes cash applications and does not measure overall institutional demand.”; `outlet:p029` “If supply grows faster than customers’ requirements, the margin gains that encouraged expansion will become harder to sustain.”

### 2. ByteDance’s Zhang Yiming tops China rich list with US$99.7 billion as AI fuels fortunes

Link gốc: https://www.scmp.com/economy/article/3372302/bytedances-zhang-yiming-tops-china-rich-list-us997-billion-ai-fuels-fortunes  
Đăng: 2026-10-27T11:00:11Z  
Bộ kiểm: **không xuất bản, chuyển API** — `insufficient_evidence`


### 3. Nvidia backs Indian startup helping companies run AI models with fewer GPUs

Link gốc: https://techcrunch.com/2026/10/27/nvidia-backs-indian-startup-helping-companies-run-ai-models-with-fewer-gpus/  
Đăng: 2026-10-27T11:00:00Z · 4 đoạn, 168 từ  
Bộ kiểm: đạt — `prose written: development/cause/examples/significance, 168 words, conditions outlet:p010,outlet:p020,outlet:p021`; câu bị bỏ: 0

**Nvidia đầu tư vào startup Ấn Độ giúp vận hành mô hình AI với ít GPU hơn trong một số trường hợp**

Nvidia đã tham gia vòng gọi vốn 14 triệu USD vào Simplismart của Ấn Độ, doanh nghiệp phát triển phần mềm giúp vận hành mô hình trí tuệ nhân tạo (AI) hiệu quả hơn và trong một số trường hợp dùng ít bộ xử lý đồ họa (GPU) hơn.

Khoản đầu tư diễn ra khi cơn sốt AI gây quá tải năng lực tính toán, buộc các doanh nghiệp phải tìm cách cân đối giữa chi phí, tốc độ và hiệu năng phần cứng khi mở rộng quy mô.

Simplismart cho biết đã giúp InVideo giảm 56% chi phí máy chủ GPU, song phải cạnh tranh với chính Nvidia cùng các nhà cung cấp đám mây lớn như Amazon Web Services và Google Cloud.

Thương vụ tạo ra nghịch lý khi nhà sản xuất chip thống trị hậu thuẫn phần mềm giảm lượng GPU, dù phía Simplismart cho rằng việc tối ưu hóa suy luận (quá trình chạy mô hình AI) sẽ giúp phần cứng hấp dẫn hơn.


- Điều kiện bàn viết chép từ nguồn: `outlet:p010` “helps companies run AI models more efficiently and, in some cases, with fewer GPUs.”; `outlet:p020` “Jain, however, argued that making AI inference more efficient could ultimately benefit Nvidia by making its hardware more attractive to customers”; `outlet:p021` “competing with offerings from Nvidia itself, as well as major cloud providers and hyperscalers including Amazon Web Services, Google Cloud, and Microsoft Azure.”


### What is still API (Gemini)
- Headline/summary translation: `radar.translate` (update.yml lines ~250-266) still uses `GEMINI_API_KEY`; out of this round's scope.
- Daily video script: `radar.video_script` (update.yml lines 330-342); out of scope.
- Key points: none requested. Already validated API summaries in the Actions cache are still restored (no request, no cost) for stories that have them, so older stories keep their earlier API text until they age out; new stories get desk prose or nothing. Removing that restore is a small follow-up in `radar/summarize.py` if the owner wants zero API text.

### Owner's newsroom machine (`C:/Users/Admin/ai-radar-phong-bao-chay`) — measured 27/10 ~23:00
- Scheduled task `HalcyonNewsroomCycle` runs `phong-bao/cong-cu/run-newsroom-cycle.ps1` at 06:00, 10:00, 14:00, 18:00, 20:00 (+07) (not every 2 h); last run 20:00 result 0, next 28/10 06:00.
- The script runs `python -m phong_bao cycle` from that checkout's working tree and **does not pull**. The checkout is a detached HEAD at `395a9f5174` (PR #124); `origin/main` is `6f8c33638f`. It has a modified tracked `phong-bao/decisions.json` (the script recopies it from the `newsroom-decisions` branch each run).
- The writer desk is part of the default `run(..., through="chief")`, so new code produces desk prose without config. Window default 48 h (`PHONG_BAO_WRITER_WINDOW_HOURS` unset). `agy` is on PATH and fueled per discovery.
- **Lane:** the writer uses the same provider order as the editor: `codex` first, `agy` fallback. Recent cycles ran reporter/editor on Codex. So in production the writer will run on Codex (97% of its week used tonight) until it is dry; every round 1-4 sample was written by agy, and Codex-written prose has not been reviewed.
- **Staleness:** CI ignores a decisions file older than 12 h (`DEFAULT_MAX_AGE_HOURS = 12`). The 20:00 → 06:00 gap is 10 h, so fine; if the machine is off longer than 12 h, desk prose stops reaching new builds and, with the API off, new stories show excerpts only.

### What the coordinator must do after merge to main
1. On the owner's machine: `git -C C:/Users/Admin/ai-radar-phong-bao-chay fetch origin` then `git -C C:/Users/Admin/ai-radar-phong-bao-chay checkout --detach origin/main` (keep the local `phong-bao/decisions.json`; checkout refuses only if main changed that file).
2. Decide the writer lane: accept Codex-first, or reorder/exclude Codex for `bien-tap` in the registry (not done here).
3. After the next scheduled cycle: `newsroom-decisions` branch `decisions.json` has rows with `written_by: "nguoi-viet"`; the next `update.yml` run log shows `Summary skipped: writer desk owns summaries` with a non-zero desk-written count; a story page shows "Phòng báo Halcyon tóm tắt từ …".

### Round 4 — lane decision and next steps (coordinator 27/10, after the report)
- Decision: the writer desk runs **agy first, Codex as fallback**; editor and checker unchanged. Implemented in the registry: `phong-bao/cong-cu/agy.toml` gains `[desk_priority] writer = 5` (Codex keeps priority 10); `phong_bao/registry.py` validates `desk_priority` and `providers(..., desk=...)` uses it; `_agent_desk` passes its desk name. Measured order: writer `['agy', 'codex']`, editor `['codex', 'agy']`, no desk `['codex', 'agy']`. Test `test_writer_runs_agy_first_while_the_editor_keeps_codex_first` (order + a fixture writer run dispatched to agy). `tests.test_phong_bao_writer`: 15 OK; `discover -p "test_phong_bao*.py"`: `Ran 74 tests in 1.444s` / `OK`.

## Next Steps (known gaps accepted 27/10)
- 12 h decisions window: CI ignores `decisions.json` older than 12 h (`DEFAULT_MAX_AGE_HOURS`). The 20:00 → 06:00 gap is 10 h; if the newsroom machine is off longer, new stories show excerpts only (API is off). Accepted, nothing built.
- SCMP reader limit: the article reader gets only ~1.2k characters (header and teaser) from SCMP, so the writer returns `insufficient_evidence` and SCMP stories carry no key points. Accepted, nothing built; no bot-wall bypass.
