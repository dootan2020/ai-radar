"""Self-authored dense-report fixture for the editorial summary contract."""

import unittest

from radar.summary_sources import publish_summary, source_record
from radar.summary_validation import validate_summary
from radar.summary_gemini import PROMPT_VERSION
from radar.site_payload import page_payload


PARAGRAPHS = [
    "A local newsroom tested an autonomous writing assistant during a closed newsroom trial. "
    "It drafted pitches and article outlines from public meeting notes. Editors reviewed every draft; "
    "the newsroom did not publish any of the assistant's drafts during the trial.",
    "Editors found that one draft attributed a statement to a speaker who had not made it. "
    "A second draft described a proposal as an approved decision. Both errors appeared in draft copy "
    "that the assistant produced from incomplete meeting notes.",
    "The newsroom discovered the errors by comparing drafts with meeting recordings and a corrected "
    "transcript. An editor kept a review log showing which claims had been checked and which had not. "
    "The trial report does not say how often similar errors occurred outside the reviewed drafts.",
    "The assistant supplier said it changed the instruction prompt and repeated the two failed examples. "
    "Both examples passed in that repeat test, according to the supplier. The supplier did not provide "
    "results from an independent evaluation or a larger test set.",
    "The newsroom paused plans for automatic publication. Editors now require a named human reviewer "
    "to check source links, attribution and the status of decisions before a draft can enter its normal "
    "publication process. The newsroom has not announced a date for resuming automation.",
    "An outside media researcher said the repeat test is useful for finding a narrow defect but cannot "
    "establish reliability on unfamiliar meetings. The researcher recommended keeping a record of "
    "corrections and checking drafts against original records rather than trusting generated citations.",
    "The trial leaves unresolved how the assistant behaves with missing recordings and whether a human "
    "reviewer can catch every attribution error under deadline pressure. The newsroom's conclusion is "
    "to treat drafts as leads for reporting, not as verified articles ready to publish.",
]


POINTS = [
    "Một tòa soạn địa phương thử trợ lý viết bài tự động trong phạm vi nội bộ. Công cụ soạn đề xuất và dàn ý từ biên bản họp công khai, còn biên tập viên đọc từng bản nháp. Tòa soạn chưa đăng bài nào do trợ lý tạo ra trong đợt thử; đây chưa phải quy trình xuất bản tự động cho độc giả.",
    "Biên tập viên phát hiện một phát biểu bị gán cho người không nói câu đó. Bản nháp khác biến đề xuất thành quyết định đã được phê duyệt. Cả hai lỗi xuất hiện khi công cụ dựa trên ghi chép cuộc họp chưa đầy đủ, cho thấy câu văn trôi chảy vẫn có thể làm sai chủ thể hoặc trạng thái sự việc.",
    "Nhóm biên tập đối chiếu bản nháp với bản ghi cuộc họp và bản chép lời đã sửa để tìm sai lệch. Một biên tập viên ghi lại khẳng định đã kiểm tra và điểm còn bỏ ngỏ. Báo cáo không cho biết lỗi tương tự xuất hiện thường xuyên đến đâu ngoài các bản nháp được xem xét, nên chưa thể suy ra tỷ lệ lỗi chung.",
    "Nhà cung cấp cho biết họ sửa hướng dẫn rồi chạy lại hai ví dụ từng thất bại; theo họ, cả hai lần đều đạt yêu cầu. Kết quả này do chính nhà cung cấp báo cáo trên các trường hợp đã biết. Chưa có đánh giá độc lập hoặc tập thử lớn hơn để kết luận thay đổi ấy xử lý được tình huống mới.",
    "Tòa soạn tạm dừng kế hoạch đăng bài tự động. Quy trình hiện tại yêu cầu người rà soát được nêu tên kiểm tra liên kết nguồn, người được dẫn lời và trạng thái quyết định trước khi bản nháp đi vào khâu xuất bản. Tòa soạn chưa công bố ngày khôi phục tự động hóa; người duyệt cũng chưa phải bảo đảm rằng mọi lỗi được phát hiện.",
    "Một nhà nghiên cứu truyền thông bên ngoài nhận xét chạy lại ca lỗi chỉ kiểm tra một khiếm khuyết hẹp, chưa chứng minh độ tin cậy trên cuộc họp mới. Người này đề xuất lưu các lần sửa sai và so bản nháp với hồ sơ gốc, thay vì chỉ tin trích dẫn do công cụ tạo. Đây là góc nhìn chuyên môn, không phải đánh giá độc lập về bản sửa của nhà cung cấp.",
    "Đợt thử còn để ngỏ cách trợ lý xử lý cuộc họp thiếu bản ghi và khả năng người duyệt nhận ra lỗi gán lời dưới áp lực thời hạn. Tòa soạn kết luận nên xem bản nháp là đầu mối để phóng viên xác minh tiếp, thay vì bài đã kiểm chứng để đăng. Giới hạn đó vẫn cần được kiểm tra trước khi mở rộng công cụ.",
]


class DenseEditorialSummaryTests(unittest.TestCase):
    def test_dense_summary_is_grounded_and_reaches_reader_projection(self):
        source = source_record("outlet", "outlet", "https://example.org/newsroom-trial",
                               "Newsroom trial", "Example Press", "\n".join(PARAGRAPHS))
        inputs = {"id": "dense-trial", "sources": [source]}
        claim = lambda text, index: {"text": text, "evidence_refs": [f"outlet:p{index:03}"]}
        output = {"id": "dense-trial", "status": "ready",
                  "title_vi": {"text": "Tòa soạn tạm dừng đăng bài tự động sau khi trợ lý viết sai chi tiết cuộc họp",
                               "evidence_refs": ["outlet:p002", "outlet:p005"]},
                  "key_points": [claim(text, i) for i, text in enumerate(POINTS, 1)],
                  "used_source_ids": ["outlet"], "limitations": []}
        self.assertEqual(validate_summary(inputs, output), (output, None))
        self.assertEqual(len(POINTS), 7)
        self.assertGreaterEqual(sum(len(point.split()) for point in POINTS), 380)
        self.assertLessEqual(sum(len(point.split()) for point in POINTS), 520)
        story = {"id": "dense-trial", "title": "Newsroom trial"}
        publish_summary(story, output, inputs, PROMPT_VERSION)
        public = page_payload({"stories": [story]})["stories"][0]
        self.assertEqual(public["key_points"], POINTS)
        self.assertEqual(public["summary_sources"][0]["url"], source["url"])
        self.assertNotIn("paragraphs", public)
