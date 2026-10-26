"""Deterministic shadow-only labels for the Vietnamese-origin news trial."""

import re
import unicodedata

from radar.clustering import canonical_url, titles_match
from radar.items import relevant


ENTITY_TERMS = re.compile(
    r"(?<!\w)(?:việt(?:\s+nam)?|vietnam(?:ese)?|người việt|made in vietnam|make in vietnam|"
    r"hà nội|ha noi|hanoi|tp\.?\s*(?:hcm|hồ chí minh)|thành phố hồ chí minh|"
    r"sài gòn|hòa lạc|đà nẵng|hải phòng|cần thơ|huế|gia lai|phú thọ|"
    r"tuyên quang|khánh hòa|lâm đồng|đồng nai|tây ninh|an giang|đồng tháp|"
    r"quảng ninh|quảng ngãi|quảng trị|nghệ an|hà tĩnh|ninh bình|"
    r"thanh hóa|sơn la|lai châu|điện biên|lào cai|lạng sơn|cao bằng|"
    r"bắc ninh|hưng yên|thái nguyên|vĩnh long|cà mau|đắk lắk|"
    r"bình dương|bình định|bà rịa|vũng tàu|kiên giang|bắc giang|"
    r"bình thuận|ninh thuận|long an|tiền giang|bến tre|trà vinh|"
    r"sóc trăng|bạc liêu|hậu giang|quảng nam|phú yên|"
    r"hà giang|yên bái|thái bình|hà nam|nam định|hải dương|"
    r"bắc kạn|vĩnh phúc|kon tum|đắk nông|bình phước|"
    r"fpt|viettel|vng|zalo|vinai|vingroup|vinfast|vinbrain|greennode|"
    r"mobifone|vietnam post|vnpt|cmc|hiếu pc|sao khuê|"
    r"bộ (?:khoa học và công nghệ|kh&cn|khcn|công an|thông tin và truyền thông)|"
    r"nghị quyết 57(?:-nq/tw)?|"
    r"luật trí tuệ nhân tạo|triển lãm chăn nuôi|vietstock)(?!\w)", re.I
)
FOREIGN_TERMS = re.compile(
    r"(?<!\w)(?:trung quốc|nhật bản|hàn quốc|singapore|ấn độ|mỹ|hoa kỳ|"
    r"vương quốc anh|pháp|đức|úc|canada|ukraine|nga|hy lạp|new york|silicon valley|"
    r"china|chinese|us|american|india|indian|hong kong|"
    r"openai|anthropic|google|microsoft|meta|apple|amazon|nvidia|"
    r"samsung|xiaomi|huawei|spacex|chatgpt|claude|gemini|sam altman|"
    r"elon musk|jeff bezos|donald trump|ông trump|"
    r"thượng viện anh|eu)(?!\w)", re.I
)
OFFICIAL_TERMS = re.compile(r"(?<!\w)(?:(?:phó )?thủ tướng|bộ trưởng|chính phủ|quốc hội)(?!\w)", re.I)
DOMESTIC_CONTEXT = re.compile(
    r"(?<!\w)(?:công an|\d+(?:[.,]\d+)?\s*(?:triệu|tỷ|nghìn)\s+đồng)(?!\w)", re.I
)
PERSON = re.compile(
    r"(?<!\w)(?:ông|bà|gs\.?|pgs\.?|ts\.?)\s+"
    r"(?:nguyễn|trần|lê|phạm|hoàng|huỳnh|phan|vũ|võ|đặng|bùi|đỗ|hồ|ngô|"
    r"dương|lý|mai|đinh|tô)\s+(?:[A-ZÀ-Ỹ][\wÀ-ỹ]+\s*){1,3}", re.I
)


def classify_origin_item(item, live_stories=None, vietnamese_language=False):
    """Label feed text only; a publisher's nationality never proves story origin.

    `live_stories=None` means the live comparison was unavailable. A match is
    evidence of a likely relay, not proof that an article was copied.
    """
    title = unicodedata.normalize("NFC", item.get("title") or "")
    summary = unicodedata.normalize("NFC", item.get("summary") or "")
    text = title + " " + summary
    title_domestic = bool(ENTITY_TERMS.search(title) or PERSON.search(title)
                          or (OFFICIAL_TERMS.search(title) and not FOREIGN_TERMS.search(title)))
    # The title identifies the story's main actor. A Vietnamese name mentioned
    # only in a foreign story's summary does not make that story domestic.
    has_entity = title_domestic or (not FOREIGN_TERMS.search(title) and bool(
        ENTITY_TERMS.search(summary) or PERSON.search(summary)
        or (OFFICIAL_TERMS.search(summary) and not FOREIGN_TERMS.search(summary))
        or (vietnamese_language and DOMESTIC_CONTEXT.search(text))))
    is_ai = relevant(title, summary)
    matched_url = None
    if live_stories is not None:
        own_url = canonical_url(item.get("url"))
        for story in live_stories:
            observations = [story] + (story.get("coverage") or [])
            for observation in observations:
                if not isinstance(observation, dict):
                    continue
                other_url = canonical_url(observation.get("url"))
                if (own_url and own_url == other_url) or titles_match(item, observation):
                    matched_url = observation.get("url")
                    break
            if matched_url:
                break
    return {
        "is_ai": is_ai,
        "has_vn_entity": has_entity,
        "vn_origin_ai": is_ai and has_entity,
        "live_match_checked": live_stories is not None,
        "live_match_url": matched_url,
        "likely_foreign_republish": not has_entity or bool(matched_url),
    }
