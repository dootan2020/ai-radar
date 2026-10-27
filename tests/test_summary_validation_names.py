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


if __name__ == "__main__":
    unittest.main()
