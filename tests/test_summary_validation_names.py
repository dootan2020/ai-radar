"""Currency codes and Vietnamese renderings are not invented names; real inventions still fail."""

import unittest

from radar.summary_validation import entity_error, number_error, vietnamese_syllable

TECHNODE = ("Dongshan Precision reported net profit of RMB2.96 billion. Its Hong Kong offering was priced "
            "at HK$86.80 a share, and cornerstone investors committed US$680 million.")


class CurrencyAndTransliterationTests(unittest.TestCase):
    def test_currency_codes_named_in_the_source_are_units(self):
        self.assertIsNone(entity_error("Dongshan Precision huy động khoảng 9,88 tỷ HKD.", TECHNODE))
        self.assertIsNone(entity_error("Lợi nhuận ròng đạt 2,96 tỷ RMB.", TECHNODE))
        self.assertIsNone(entity_error("Nhà đầu tư cam kết 680 triệu USD.", TECHNODE))
        self.assertIsNone(entity_error("Doanh thu đạt 5 tỷ CNY.", "Revenue reached 5 billion yuan."))

    def test_a_currency_the_source_never_names_is_still_rejected(self):
        self.assertEqual(entity_error("Dongshan Precision huy động 9 tỷ EUR.", TECHNODE), "invented_entity: EUR")
        self.assertEqual(entity_error("Công ty thu 2 tỷ JPY.", TECHNODE), "invented_entity: JPY")

    def test_hong_kong_dollars_are_hkd_not_usd(self):
        sentence = "Cổ phiếu được chào bán ở mức 86,80 đô la Hồng Kông mỗi cổ phiếu."
        self.assertIsNone(number_error(sentence, TECHNODE))
        self.assertIsNone(number_error("Giá chào bán là 86,80 HKD.", TECHNODE))
        self.assertIsNone(number_error("Giá chào bán là 86.80 Hong Kong dollars.", TECHNODE))
        # The amount must still match the source, and a plain dollar figure stays a USD claim.
        self.assertEqual(number_error("Cổ phiếu được chào bán ở mức 86,80 đô la Hồng Kông.",
                                      "Shares were priced at HK$86.8 each, or 86,80 euro."),
                         "unsupported_number_unit: hkd")
        self.assertEqual(number_error("Cổ phiếu được chào bán ở mức 86,80 đô la.", TECHNODE),
                         "unsupported_number_unit: usd")

    def test_vietnamese_renderings_of_place_names_pass(self):
        evidence = "Delegates came from Latin America, Africa, Greece and Singapore."
        for text in ("Đại biểu đến từ Mỹ Latinh và châu Phi.", "Đại biểu đến từ Hy Lạp.",
                     "Đại biểu đến từ Xin-ga-po và Ca-na-đa."):
            self.assertIsNone(entity_error(text, evidence), text)
        self.assertTrue(vietnamese_syllable("Latinh"))
        self.assertFalse(vietnamese_syllable("GPT-5"))

    def test_spelled_numbers_up_to_twenty_support_digits(self):
        evidence = "Across four model families and eleven open-source models, the method held."
        self.assertIsNone(number_error("Thử nghiệm trên 11 mô hình nguồn mở.", evidence))
        self.assertEqual(number_error("Thử nghiệm trên 12 mô hình nguồn mở.", evidence), "invented_number: 12")

    def test_invented_names_still_fail(self):
        evidence = "Delegates came from Latin America and Africa."
        self.assertEqual(entity_error("Zorblax tham dự diễn đàn.", evidence), "invented_entity: Zorblax")
        self.assertEqual(entity_error("Mô hình GPT-5 được nhắc tới.", evidence), "invented_entity: GPT-5")


LENOVO = ("Lenovo reports case temperatures of about 33 degrees Celsius at idle and 41 degrees under full load in "
          "a 25-degree room. The NPU has 24GB of dedicated memory.")


class UnitsAfterNumbersTests(unittest.TestCase):
    """Sentences the writer wrote in newsroom cycles of 2026-11-02 to 2026-11-04, against their source wording."""

    def test_a_unit_after_a_number_is_not_a_name(self):
        self.assertIsNone(entity_error("Vỏ máy đạt 41 độ C khi đầy tải trong phòng 25 độ C.", LENOVO))
        self.assertIsNone(entity_error("NPU có 24 GB bộ nhớ riêng.", LENOVO))
        # A number inside a model name stays part of that name.
        self.assertIsNone(entity_error("SenseTime phát hành SenseNova Loop-9B-Preview.",
                                       "SenseTime has released SenseNova Loop-9B-Preview."))

    def test_a_unit_or_name_the_source_never_writes_after_a_number_still_fails(self):
        self.assertEqual(entity_error("Vỏ máy đạt 41 độ C khi đầy tải.", "The case reached 41 degrees Fahrenheit."),
                         "invented_entity: C")
        self.assertEqual(entity_error("NPU có 24 TB bộ nhớ riêng.", LENOVO), "invented_entity: TB")
        self.assertEqual(entity_error("Có 3 Zorb tham dự thử nghiệm.", LENOVO), "invented_entity: Zorb")

    def test_quarters_ranges_and_shared_units_follow_the_source(self):
        self.assertIsNone(number_error("Kết quả quý 3 của AMD vượt dự báo.", "AMD’s third-quarter earnings beat estimates."))
        self.assertIsNone(number_error("Thương vụ hoàn tất trong quý 3.", "The financing closed in the third quarter."))
        self.assertIsNone(number_error("Meta nhận 58 tỷ USD đăng ký cho đợt trái phiếu 15 đến 20 tỷ USD.",
                                       "Meta drew $58 billion in orders for a bond offering that’s expected to be "
                                       "$15 billion to $20 billion."))
        self.assertIsNone(number_error("Mỗi truy vấn có thời gian chờ 60 giây.", "It ran read-only with a 60-second timeout."))
        self.assertIsNone(number_error("Độ trễ phát hiện 69 giây và phục hồi 94 giây.",
                                       "Mean detection and recovery-action latencies of 69 and 94 seconds respectively."))
        self.assertIsNone(number_error("Ông chi tới 200.000 USD mỗi năm.", "I spend about $200,000 a year on tokens."))
        self.assertIsNone(number_error("Thương vụ định giá Fal ở mức 16 tỷ USD.", "The deal values Fal at $16 billion."))

    def test_numbers_of_the_same_shapes_without_support_still_fail(self):
        self.assertEqual(number_error("Kết quả quý 2 của AMD vượt dự báo.", "AMD’s third-quarter earnings beat estimates."),
                         "invented_number: 2")
        self.assertEqual(number_error("Đợt trái phiếu dự kiến 5 đến 20 tỷ USD.",
                                      "A bond offering that’s expected to be $15 billion to $20 billion."),
                         "unsupported_amount_role")
        self.assertEqual(number_error("Mỗi truy vấn có thời gian chờ 90 giây.", "It ran with a 60-second timeout."),
                         "invented_number: 90")
        self.assertEqual(number_error("Độ trễ phát hiện 69 giây.", "Latencies of 69 and 94 milliseconds."),
                         "unsupported_number_unit: seconds")
        self.assertEqual(number_error("Giá chào bán là 86,80 USD.", TECHNODE), "unsupported_number_unit: usd")
        self.assertEqual(number_error("Fal huy động 16 tỷ USD.", "The deal values Fal at $16 billion."),
                         "unsupported_amount_role")


class NameFormTests(unittest.TestCase):
    def test_inflected_spelled_out_and_partial_forms_of_a_source_name_pass(self):
        cases = [
            ("Công ty khởi nghiệp 42AI của Israel gọi vốn hạt giống.", "Israeli startup 42AI raised seed funding."),
            ("Một dự án ở Australia bị hoãn tiến độ.", "A data center in the Australian outback was delayed."),
            ("Hai hãng cam kết ngừng dùng NDA với chính quyền.", "Amazon and Microsoft will no longer use NDAs."),
            ("Người dùng bản Pro chuyển sang GLM-5.3.", "Users of openPangu-2.0-Pro are pointed to GLM-5.3."),
            ("Kính nhận bản cập nhật OTA vào tháng 11.", "The glasses received an over-the-air update in November."),
            ("Theo CSA, dự thảo đã được công bố.", "Authors: Cloud Security Alliance AI Safety Initiative"),
            ("Theo tờ South China Morning Post, Baidu ra mắt trình mô phỏng.",
             "scmp Baidu has developed a new AI-driven simulator."),
            ("Ứng dụng từng có trên Google Play Store.", "A user review on Google’s Play Store stated it."),
        ]
        for text, evidence in cases:
            self.assertIsNone(entity_error(text, evidence), text)

    def test_invented_names_of_the_same_shapes_still_fail(self):
        self.assertEqual(entity_error("Công ty khởi nghiệp của Iran gọi vốn.", "Israeli startup 42AI raised seed funding."),
                         "invented_entity: Iran")
        self.assertEqual(entity_error("Người dùng bản Ultra chuyển sang GLM-5.3.",
                                      "Users of openPangu-2.0-Pro are pointed to GLM-5.3."), "invented_entity: Ultra")
        self.assertEqual(entity_error("Kính nhận bản cập nhật FOTA.", "The glasses received an over-the-air update."),
                         "invented_entity: FOTA")
        self.assertEqual(entity_error("Theo tờ South Asia Morning Post, Baidu ra mắt.", "scmp Baidu has developed it."),
                         "invented_entity: South")
        self.assertEqual(entity_error("Ứng dụng từng có trên Play Store Google.", "A user review on Google’s Play Store."),
                         "unsupported_name: Play Store Google")

    def test_a_vietnamese_word_before_a_name_is_not_part_of_it(self):
        # Cycle 2026-11-04 16:31, WIRED: "Anh" is Britain, the name is Kanishka Narayan.
        evidence = ("But the UK AI minister admitted last week that figure was significantly higher. AI minister "
                    "Kanishka Narayan, answering a parliamentary question, said the estimate was uncertain. Economist "
                    "Priya Shah disagreed.")
        self.assertIsNone(entity_error("Bộ trưởng phụ trách AI của Anh Kanishka Narayan thừa nhận ước tính này.",
                                       evidence))
        # The name after the Vietnamese word must still occur complete.
        self.assertEqual(entity_error("Bộ trưởng phụ trách AI của Anh Priya Narayan thừa nhận ước tính này.",
                                      evidence), "unsupported_name: Anh Priya Narayan")
        self.assertEqual(entity_error("Nhà kinh tế Kanishka Priya Shah phản đối.", evidence),
                         "unsupported_name: Kanishka Priya Shah")


if __name__ == "__main__":
    unittest.main()
