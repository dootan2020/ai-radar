"""Deterministic evidence checks, not a claim of general semantic entailment."""

from decimal import Decimal
import re
import unicodedata

from radar.translate import VIETNAMESE, NUMBER_WORDS


def valid_shape(value, schema):
    kind = schema["type"]
    if kind == "object":
        return (isinstance(value, dict) and set(value) == set(schema["required"])
                and all(valid_shape(value[k], s) for k, s in schema["properties"].items()))
    if kind == "array":
        return (isinstance(value, list) and len(value) <= schema.get("maxItems", len(value))
                and all(valid_shape(v, schema["items"]) for v in value))
    return isinstance(value, str) and ("enum" not in schema or value in schema["enum"])


def normalized(text):
    return unicodedata.normalize("NFC", text).replace("**", "")


NUMBER = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?:[pP](?!\w))?")
WORD_NUMBERS = {
    "hai": "two", "ba": "three", "bốn": "four", "năm": "five", "sáu": "six",
    "bảy": "seven", "tám": "eight", "chín": "nine", "mười": "ten",
}
UNITS = {
    "fps": r"(?:frames?\s*(?:per|/)\s*second|fps|khung hình\s*/\s*giây)",
    "seconds": r"(?:seconds?|giây)",
    "percent": r"(?:%|percent|phần trăm)",
    # "đô la Hồng Kông" is the Hong Kong dollar, never USD; it is checked as hkd below.
    "usd": r"(?:USD|dollars?|đô la(?!\s+(?:Hồng Kông|Hong Kong|HK)\b))",
    "hkd": r"(?:HKD|Hong Kong dollars?|đô la\s+(?:Hồng Kông|Hong Kong|HK)\b)",
}
# Sources often write a currency before the number (HK$86.80); this form also supports the unit.
UNIT_PREFIXES = {"hkd": r"(?:HK\$|HKD)\s*"}
PERCENT_RANGE = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(?:to|[-–])\s*\d+(?:[.,]\d+)?\s*(?:%|percent|phần trăm)", re.I)
MONEY = re.compile(r"(?P<dollar>\$)?(?P<value>\d+(?:[.,]\d+)?)\s*(?P<scale>billion|million|tỷ|triệu|[BM])\b(?:\s*(?:USD|dollars?))?", re.I)

COMMON_ACRONYMS = {"AI", "IPO", "CEO", "CTO", "CFO", "COO", "GPU", "CPU", "API", "USD",
                   "LLM", "LLMS", "AGI", "SEC", "PAC", "FPGA", "JSON", "XML", "SQL", "HTTP",
                   "HTTPS", "RISC", "UI", "UX", "US", "UK", "EU",
                   # Plain technical acronyms name file formats and parts, never a person or company.
                   "PDF", "URL", "HTML", "CSS", "RAM", "VRAM", "SSD", "NPU", "TPU", "SDK", "OS", "PC", "USB",
                   "ID", "FAQ", "SMS", "GPS", "VPN", "AR", "VR", "IT", "CSV", "PNG", "JPEG", "MP3", "MP4"}
# A currency code is a unit, not a name: allow it when the evidence names that currency in any form
# (sources write RMB2.96 billion, HK$86.80, 680 million yuan).
CURRENCY_EVIDENCE = {
    "USD": r"\$|USD|dollars?", "HKD": r"HK\$|HKD|Hong Kong dollars?", "RMB": r"RMB|CNY|yuan|renminbi",
    "CNY": r"RMB|CNY|yuan|renminbi", "EUR": r"€|EUR|euros?", "JPY": r"¥|JPY|yen",
    "GBP": r"£|GBP|pounds? sterling|British pounds?", "VND": r"VND|đồng|\bdong\b",
    "KRW": r"₩|KRW|\bwon\b", "INR": r"₹|INR|rupees?", "TWD": r"NT\$|TWD|Taiwan dollars?",
    "SGD": r"S\$|SGD|Singapore dollars?",
}
# Conventional Vietnamese renderings that are not spelled as native syllables.
VIETNAMESE_TRANSLITERATIONS = {"latinh"}
VIETNAMESE_ONSETS = ("ngh", "ng", "nh", "ch", "gh", "gi", "kh", "ph", "qu", "th", "tr",
                    "b", "c", "d", "g", "h", "k", "l", "m", "n", "p", "r", "s", "t", "v", "x", "")
VIETNAMESE_CODAS = ("ch", "ng", "nh", "c", "m", "n", "p", "t", "")
ENTITY_WORD = re.compile(r"(?u)\b[^\W\d][\w]*(?:[.+-][\w]+)*\b")


def folded(text):
    text = text.casefold().replace("đ", "d")
    return "".join(char for char in unicodedata.normalize("NFD", text)
                   if unicodedata.category(char) != "Mn")


def vietnamese_syllable(word):
    """Recognize Vietnamese spelling even when tones are omitted."""
    plain = folded(word)
    if plain in VIETNAMESE_TRANSLITERATIONS:
        return True
    if "-" in word:
        # Hyphenated phonetic renderings (Xin-ga-po, Ca-na-đa) are runs of Vietnamese syllables.
        parts = word.split("-")
        return len(parts) > 1 and all(part and vietnamese_syllable(part) for part in parts)
    if not plain.isalpha():
        return False
    for onset in VIETNAMESE_ONSETS:
        if not plain.startswith(onset):
            continue
        rest = plain[len(onset):]
        for coda in VIETNAMESE_CODAS:
            if coda and not rest.endswith(coda):
                continue
            vowel = rest[:-len(coda)] if coda else rest
            if 1 <= len(vowel) <= 3 and all(char in "aeiouy" for char in vowel):
                return True
    return False


def money_claims(text):
    claims = set()
    for match in MONEY.finditer(text):
        value = Decimal(match["value"].replace(",", "."))
        scale = match["scale"].casefold()
        value *= 1000000000 if scale in {"billion", "b", "tỷ"} else 1000000
        before = text[max(0, match.start() - 60):match.start()].casefold()
        after = text[match.end():match.end() + 40].casefold()
        # Stop context at adjacent amounts; the nearest amount role owns the value.
        before = re.split(r"\d", before)[-1]
        after = re.split(r"\d|[.;]", after)[0]
        role_pattern = r"valuation|valued|định giá|rais\w*|funding|huy động|gọi vốn"
        preceding = list(re.finditer(role_pattern, before))
        following = re.search(role_pattern, after)
        role_word = preceding[-1][0] if preceding else ""
        if following and (not preceding or following.start() < len(before) - preceding[-1].end()):
            role_word = following[0]
        role = ("valuation" if re.search(r"valu|định giá", role_word) else "funding") if role_word else None
        claims.add((value, role))
    return claims


def number_error(text, evidence, *, publication_years=()):
    evidence = normalized(evidence)
    source_money = money_claims(evidence)
    for value, role in money_claims(text):
        if not any(value == number and (role is None or role == source_role)
                   for number, source_role in source_money):
            return "unsupported_amount_role"
    # Remove scaled currency amounts before ordinary numeric comparison; notation may translate.
    source_numbers = {n.replace(",", ".").casefold() for n in NUMBER.findall(MONEY.sub("", evidence))}
    source_numbers.update(publication_years)
    source_words = set(re.findall(r"[a-z]+", evidence.casefold()))
    if "hundred" in source_words:
        source_numbers.add("100")
    for index, word in enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                                  "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
                                  "seventeen", "eighteen", "nineteen", "twenty")):
        if word in source_words:
            source_numbers.add(str(index))
    for number, word in NUMBER_WORDS.items():
        if word in source_words:
            source_numbers.add(number)
    for number in NUMBER.findall(MONEY.sub("", text)):
        if number.replace(",", ".").casefold() not in source_numbers:
            return "invented_number: " + number
    for vietnamese, english in WORD_NUMBERS.items():
        # Avoid interpreting the word for year or an ordinary indefinite article as a count.
        counts_text = re.sub(r"một phần ba", "", text, flags=re.I)
        if re.search(r"\b" + vietnamese + r"\s+(?:lượt|con|người|công ty|mô hình|tháng|ngày|giây|nhóm)\b", counts_text, re.I):
            index = list(WORD_NUMBERS).index(vietnamese) + 2
            if english not in source_words and str(index) not in source_numbers and vietnamese not in evidence.casefold():
                return "invented_number_word"
    if "một phần ba" in text.casefold() and not re.search(r"a third|one.third|1/3|một phần ba", evidence, re.I):
        return "invented_fraction"
    for unit, pattern in UNITS.items():
        for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(?:" + pattern + r")", text, re.I):
            number = re.escape(match[1].replace(",", ".")).replace(r"\.", "[.,]")
            direct = (re.search(r"\b" + number + r"\s*(?:" + pattern + r")", evidence, re.I)
                      or (unit in UNIT_PREFIXES
                          and re.search(UNIT_PREFIXES[unit] + number + r"(?![\d.,]\d)", evidence, re.I)))
            ranged = (unit == "percent" and any(
                re.fullmatch(number, match[1])
                for match in PERCENT_RANGE.finditer(evidence)))
            if not direct and not ranged:
                return "unsupported_number_unit: " + unit
    return None


def entity_error(text, evidence):
    # These cross-language renderings remain an explicit fallback for names
    # whose Vietnamese words alone cannot identify them as proper names.
    for source, vietnamese in (
        (r"(?i:Silicon Valley)", "Thung lũng Silicon"),
        (r"(?i:European Union)", "Liên minh châu Âu"),
        (r"(?i:United States)|U\.S\.|US", "Hoa Kỳ"),
    ):
        if re.search(r"(?<!\w)" + re.escape(vietnamese) + r"(?!\w)", text, re.I):
            if not re.search(r"(?<!\w)(?:" + source + r")(?!\w)", evidence):
                return "unsupported_name: " + vietnamese
            text = re.sub(r"(?<!\w)" + re.escape(vietnamese) + r"(?!\w)", " ", text, flags=re.I)
    # A cited surname can support the conventional full name of that same person.
    # Keep the mapping narrow: an unrelated given name must still fail.
    for full_name, surname in (("Donald Trump", "Trump"),):
        if re.search(r"(?<!\w)" + re.escape(surname) + r"(?!\w)", evidence):
            text = re.sub(r"(?<!\w)" + re.escape(full_name) + r"(?!\w)", " ", text)
    # Ai2 is the Allen Institute for AI's published short name.
    if re.search(r"(?<!\w)Ai2(?!\w)", evidence, re.I):
        text = re.sub(r"(?<!\w)(?:Viện Allen|Allen Institute(?: for AI)?)(?!\w)", " ", text)
    allowed = {folded(token) for token in ENTITY_WORD.findall(evidence)}
    allowed.update(code.casefold() for code, pattern in CURRENCY_EVIDENCE.items()
                   if re.search(pattern, evidence, re.I))
    for word in ENTITY_WORD.findall(text):
        if (word[0].isupper() and not vietnamese_syllable(word)
                and word.upper() not in COMMON_ACRONYMS and folded(word) not in allowed):
            return "invented_entity: " + word
    # Names made of distinctive tokens must also occur as a complete name.
    for name in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,}\b", text):
        if any(not vietnamese_syllable(word) for word in name.split()) and folded(name) not in folded(evidence):
            return "unsupported_name: " + name
    return None


def claim_error(claim, refs, paragraph_refs, *, max_length, entity_evidence=None,
                publication_years=()):
    text = normalized(claim["text"]).strip()
    used = claim["evidence_refs"]
    if (len(text) < 15 or len(text) > max_length or not used or len(set(used)) != len(used)
            or not set(used) <= refs.keys() or not set(used) & paragraph_refs):
        return "invalid_evidence_or_length"
    if re.search(r"[<>]|https?://|\[[^\]]+\]\(|[`#]", text) or claim["text"].count("**") % 2:
        return "invalid_markup"
    if not VIETNAMESE.search(text):
        return "untranslated_vietnamese_missing"
    evidence = " ".join(refs[ref] for ref in used)
    # Only the source publication year is allowed from date metadata; other numbers stay with citations.
    error = number_error(text, evidence, publication_years=publication_years) or entity_error(
        text, evidence if entity_evidence is None else entity_evidence)
    if error:
        return error
    # English connective prose is different from technical names such as CUDA or GPU.
    language_text = text
    for name in re.findall(r"\b[A-Z][A-Za-z0-9.+-]*(?:\s+[A-Z][A-Za-z0-9.+-]*)*", evidence):
        language_text = re.sub(r"\b" + re.escape(name) + r"\b", "", language_text)
    language_words = re.findall(r"\w+", language_text.casefold())
    english = sum(w in {"the", "is", "are", "was", "were", "with", "and", "that", "which", "its", "their", "for", "from"}
                  for w in language_words)
    if english >= 3 and english / max(1, len(language_words)) > 0.2:
        return "untranslated_english_prose"
    # Narrow, high-risk polarity checks. Arbitrary semantic equivalence still needs live review.
    if re.search(r"not yet|has not|have not|chưa", evidence, re.I) and re.search(r"đã (?:hoàn tất|hoàn thành|giải quyết)", text, re.I) and not re.search(r"chưa|không", text, re.I):
        return "unsupported_completion"
    if re.search(r"replay|re.test|kiểm tra lại|thử lại", evidence, re.I) and re.search(r"(?:chặn|ngăn|giải quyết).*?(?:mọi|toàn bộ|tất cả)", text, re.I) and not re.search(r"thử lại|kiểm tra lại|đã biết|được thử", text, re.I):
        return "missing_replay_qualification"
    words = re.findall(r"\w+", text.casefold())
    source_words = " ".join(re.findall(r"\w+", evidence.casefold()))
    if any(" ".join(words[i:i + 12]) in source_words for i in range(len(words) - 11)):
        return "needs_review: long_source_overlap"
    if re.search(r"\b(\w+)(?:\s+\1){2}\b", text, re.I):
        return "repetition_detected"
    return None


# Who says what, and why. These are lexical checks for the newsroom writer's Vietnamese prose against the
# English paragraphs it cites. They catch the visible forms of three faults: a purpose ("nhằm ...") the cited
# paragraphs never state, a judgement or cause that drops the attribution its paragraph carries ("ORG found
# that ..."), and a speaker ("Theo Opera", "nguồn tin nội bộ") that the cited paragraphs do not name. They
# cannot tell who holds an opinion written in the outlet's own voice, nor whether an "average" or a one-mode
# trade-off kept its scope; those stay with the prompt and the reviewer.
# Bare "để" is left to the prompt: in Vietnamese it mostly marks use or result ("dùng để", "khung để tác tử
# hoạt động"); the round-4 sample of 13 stories had 13 "để" and 9 "nhằm", and every "nhằm" stated a purpose.
PURPOSE_VI = re.compile(r"(?<!\w)(?:nhằm|với mục đích|mục đích (?:là|của)|với mục tiêu|mục tiêu là"
                        r"|đặt mục tiêu)(?!\w)", re.I)
PURPOSE_EN = re.compile(
    r"\b(?:in order to|so that|so as to|aim(?:s|ed|ing)? (?:to|at)|goals?|targets?|purpose|intend(?:s|ed)? to|intention"
    r"|designed to|meant to|in a bid to|in an effort to|bid to|effort to|mission|objective|strategy|to help"
    r"|hop(?:e|es|ed|ing) to|want(?:s|ed)? to|push(?:es|ed|ing)? to|plan(?:s|ned)? to|looking to"
    r"|allow(?:s|ed|ing)?|let(?:s|ting)?|enabl(?:e|es|ed|ing)|used to|to ensure|to make sure|to prevent"
    r"|to protect|to avoid|to stay|to keep|to compete|to reduce|to cut|to save|to free|to focus|to boost"
    r"|to improve|to maximi[sz]e|to minimi[sz]e|for the purpose"
    r"|help(?:s|ed|ing)? (?:you|users?|people|developers|companies|customers))\b", re.I)
# Reporting verbs: a sentence that has one names a speaker or a finding.
SAYING_VI = (r"cho biết|cho rằng|cho thấy|cho hay|nhận định|nhận xét|nhận thấy|thấy rằng|khẳng định|tuyên bố"
             r"|ước tính|dự báo|cảnh báo|tiết lộ|thừa nhận|lập luận|đánh giá|phát hiện|kết luận|công bố|thông báo"
             r"|giải thích|tin rằng|kỳ vọng|nhấn mạnh|lưu ý|đưa tin|dẫn lời|chia sẻ|xác nhận|bác bỏ|ghi nhận|mô tả"
             r"|viết rằng|phát biểu|trả lời|nói")
SAYING = re.compile(r"(?<!\w)(?:" + SAYING_VI + r")(?!\w)", re.I)
# "Theo X," at the start of a clause, or ", theo X." at its end; "theo dõi" and "theo đó" are not attributions.
THEO = re.compile(r"(?:^|[,;:(]\s*|(?<!\w)(?:và|nhưng|còn|song)\s+)theo\s+(?!(?:dõi|đuổi|kịp|sau|đó|tỷ lệ|cách|hướng"
                  r"|thời gian|kế hoạch)(?!\w))([^,.;:()]{2,60}?)\s*(?:,|[.;]?\s*$)", re.I)
NAMED_SPEAKER = re.compile(r"((?:[^\W\d_][\w.+-]*\s+){0,3}[^\W\d_][\w.+-]*)\s+(?:" + SAYING_VI + r")(?!\w)")
SOURCE_ATTRIBUTION = re.compile(
    r"\b(?:according to|said|says|say|told|tells|found|finds|argues?|argued|believes?|believed|claim(?:s|ed)?"
    r"|estimates?|estimated|warns?|warned|thinks?|predicts?|predicted|suggests?|suggested|wrote|writes|noted"
    r"|insists?|insisted|contends?|contended|reports? that|reported that|reportedly|alleges?|alleged|concluded"
    r"|revealed|announced|disclosed|question(?:s|ed|ing)|per the \w+|in (?:his|her|their|its) view)\b", re.I)
JUDGEMENT_VI = re.compile(
    r"(?<!\w)(?:hơn|nhất|quyết liệt|rủi ro|nguy cơ|nghiêm trọng|đáng kể|đáng chú ý|thất bại|không đạt|vượt trội"
    r"|đột phá|bước ngoặt|lo ngại|thách thức|rào cản|khó khăn|ảo giác|không phù hợp|sai sót|tham vọng|ấn tượng"
    r"|hiệu quả|vì|bởi|nguyên nhân|dẫn đến|dẫn tới|khiến|nhờ|là do|gây ra|kéo theo|hệ quả)(?!\w)", re.I)
# Words that only look like judgements: "Thống nhất" in a name, "hơn 15%" (more than a figure).
NOT_JUDGEMENT = re.compile(r"(?<!\w)(?:thống nhất|duy nhất|hợp nhất|nhất quán|đồng nhất|nhất định|nhất là"
                           r"|hơn nữa|hơn(?=\s+(?:\d|khoảng|một|hai|ba|gấp)))(?!\w)", re.I)
LEAD_IN_WORDS = 6
OUTLET_SPEAKER = re.compile(r"tác giả|bài viết|bài báo|bài phân tích|tòa soạn|tờ báo|phóng viên|nhà báo|người viết",
                            re.I)
INSIDER_SPEAKER = (re.compile(r"nguồn tin|người trong cuộc|người thạo tin|người am hiểu|giấu tên|nội bộ", re.I),
                   re.compile(r"\binsiders?\b|\bsources? (?:say|said|says|told|familiar|close)|familiar with"
                              r"|according to (?:a |two |three |several |multiple )?(?:people|person|sources?)"
                              r"|anonymity|not authori[sz]ed to", re.I))
EXPERT_SPEAKER = (re.compile(r"chuyên gia|nhà phân tích|giới phân tích|nhà quan sát|giới quan sát|nhà nghiên cứu"
                             r"|nhà khoa học|giới khoa học|học giả", re.I),
                  re.compile(r"\b(?:experts?|analysts?|researchers?|scientists?|economists?|academics?|professors?"
                             r"|specialists?|scholars?|observers?)\b", re.I))


def _speakers(text):
    """Speakers a Vietnamese sentence names: "Theo X," and "X cho biết/cho rằng/..." with a capitalised X."""
    found = [match[1].strip() for match in THEO.finditer(text)]
    for match in NAMED_SPEAKER.finditer(text):
        words = match[1].split()
        while words and not words[0][0].isupper():
            words.pop(0)
        if words:
            found.append(" ".join(words))
    return found


def _speaker_in(speaker, paragraph, publisher):
    """Whether one cited paragraph can carry a named speaker: it names them or its outlet, or it reports
    someone's words ("the company said", "per the outlet"); None when the speaker has no foreign name token."""
    names = [word for word in ENTITY_WORD.findall(speaker)
             if word[0].isupper() and not vietnamese_syllable(word) and word.upper() not in COMMON_ACRONYMS]
    if not names:
        return None
    keys = {folded(word) for word in names}
    if len(names) > 1:
        keys.add(folded("".join(word[0] for word in names)))
    return (bool(keys & {folded(word) for word in re.findall(r"\w+", paragraph + " " + publisher)})
            or bool(SOURCE_ATTRIBUTION.search(paragraph)))


def _outlet_voice(clause, paragraphs):
    """Whether an unattributed judgement can be the outlet's own narration rather than a quoted finding.

    The clause belongs to an attributed source sentence when it shares a number or a foreign name with one
    ("9%" with "ORG found ... 9 percent"), or when every sentence of the cited paragraphs is attributed.
    Otherwise the paragraph holds narration in the outlet's voice ("the domestic economy remains a drag"),
    which the outlet byline already attributes.
    """
    sentences = [s for p in paragraphs for s in re.split(r"(?<=[.!?])[\"”’]?\s+(?=[\"“A-Z])", p) if s.strip()]
    attributed = [s for s in sentences if SOURCE_ATTRIBUTION.search(s)]
    if len(attributed) == len(sentences):
        return False
    numbers = {n.replace(",", ".") for n in NUMBER.findall(clause)}
    names = {folded(word) for word in ENTITY_WORD.findall(clause)
             if word[0].isupper() and not vietnamese_syllable(word) and word.upper() not in COMMON_ACRONYMS}
    for sentence in attributed:
        if numbers & {n.replace(",", ".") for n in NUMBER.findall(sentence)}:
            return False
        if names & {folded(word) for word in re.findall(r"\w+", sentence)}:
            return False
    return True


def attribution_error(text, cited):
    """Who-said-what error for one writer sentence, or None.

    cited is a list of (paragraph text, publisher name) pairs for the paragraphs the sentence cites.
    """
    text = normalized(text)
    paragraphs = [paragraph for paragraph, _ in cited]
    if PURPOSE_VI.search(text) and not any(PURPOSE_EN.search(p) for p in paragraphs):
        return "unsupported_purpose"
    judgement = bool(JUDGEMENT_VI.search(NOT_JUDGEMENT.sub(" ", text)))
    speakers = _speakers(text)
    for speaker in speakers:
        if OUTLET_SPEAKER.search(speaker):
            continue
        for vietnamese, english in (INSIDER_SPEAKER, EXPERT_SPEAKER):
            # An unnamed group must be the one each cited paragraph quotes.
            if vietnamese.search(speaker) and not all(english.search(p) for p in paragraphs):
                return "speaker_not_in_source: " + speaker
        if INSIDER_SPEAKER[0].search(speaker) or EXPERT_SPEAKER[0].search(speaker):
            continue
        # A named speaker needs a cited paragraph that can carry them; a judgement needs every cited one to.
        found = [_speaker_in(speaker, *pair) for pair in cited]
        if None in found:
            continue
        if not any(found) or (judgement and not all(found)):
            return "speaker_not_in_source: " + speaker
    if judgement and any(SOURCE_ATTRIBUTION.search(p) for p in paragraphs):
        # A clause is attributed when it, or an earlier main clause, names a speaker or a reporting verb; a
        # short lead-in ("Bên cạnh nguy cơ tài chính,") takes the attribution of the clause right after it.
        # A concessive clause ("Dù ước tính ...,") does not carry its attribution to the next one.
        # Narration in the outlet's own voice needs no speaker (see _outlet_voice).
        attributed, pending = False, None
        for clause in re.split(r"[,;:]", NOT_JUDGEMENT.sub(" ", text)):
            says = bool(SAYING.search(clause) or THEO.search(clause.strip() + ","))
            if pending is not None and not says and not _outlet_voice(pending, paragraphs):
                return "unattributed_judgement"
            pending = None
            if says and not re.match(r"\s*(?:dù|mặc dù|tuy|dẫu)(?!\w)", clause, re.I):
                attributed = True
            elif JUDGEMENT_VI.search(clause) and not says and not attributed:
                if len(clause.split()) <= LEAD_IN_WORDS:
                    pending = clause
                elif not _outlet_voice(clause, paragraphs):
                    return "unattributed_judgement"
        if pending is not None and not _outlet_voice(pending, paragraphs):
            return "unattributed_judgement"
    return None


def validate_summary(inputs, output, *, source_entity_evidence=None):
    from radar.summary_gemini import OUTPUT_SCHEMA
    if not valid_shape(output, OUTPUT_SCHEMA) or output["id"] != inputs.get("id"):
        return None, "invalid_contract"
    sources = inputs.get("sources", [])
    if not sources or not any(s["role"] != "coverage" and s.get("paragraphs") and not s.get("excerpt_kind") for s in sources):
        return None, "insufficient_evidence"
    if output["status"] != "ready":
        claims = [output[k] for k in ("title_vi",)]
        empty = all(c == {"text": "", "evidence_refs": []} for c in claims)
        if not empty or output["key_points"] or output["used_source_ids"] or "insufficient_evidence" not in output["limitations"]:
            return None, "invalid_insufficient_evidence"
        return None, "insufficient_evidence"
    if not 4 <= len(output["key_points"]) <= 8:
        return None, "point_count"
    points = [normalized(p["text"]).strip().casefold() for p in output["key_points"]]
    if len(set(points)) != len(points):
        return None, "duplicate_points"
    refs, owners, paragraph_refs = {}, {}, set()
    source_by_id = {source["id"]: source for source in sources}
    for source in sources:
        for p in [*source["paragraphs"], source["publisher"]]:
            if p["id"] in refs:
                return None, "duplicate_input_ref"
            refs[p["id"]], owners[p["id"]] = p["text"], source["id"]
        paragraph_refs.update(p["id"] for p in source["paragraphs"])
    claims = [(output["title_vi"], 240), *[(p, 520) for p in output["key_points"]]]
    for claim, limit in claims:
        claim_refs = dict(refs)
        cited_sources = {owners[ref] for ref in claim["evidence_refs"] if ref in owners}
        entity_evidence = " ".join(
            part for source_id in cited_sources
            for part in (source_by_id[source_id].get("title", ""), source_by_id[source_id]["publisher"]["text"],
                         (source_entity_evidence or {}).get(source_id) or " ".join(
                             p["text"] for p in source_by_id[source_id]["paragraphs"])))
        publication_years = {
            match[1] for source_id in cited_sources
            if (match := re.match(r"^(20\d{2})-\d{2}-\d{2}(?:T|$)",
                                  str(source_by_id[source_id].get("published_at") or "")))
        }
        for ref in claim["evidence_refs"]:
            if ref in owners:
                publisher = next(s["publisher"]["text"] for s in sources if s["id"] == owners[ref])
                claim_refs[ref] += " " + publisher
        error = claim_error(claim, claim_refs, paragraph_refs, max_length=limit,
                            entity_evidence=entity_evidence, publication_years=publication_years)
        if error:
            return None, error
    used = {owners[ref] for claim, _ in claims for ref in claim["evidence_refs"]}
    if used != set(output["used_source_ids"]) or len(used) != len(output["used_source_ids"]):
        return None, "source_ref_mismatch"
    limitations = output["limitations"]
    if len(set(limitations)) != len(limitations) or "insufficient_evidence" in limitations:
        return None, "invalid_limitations"
    if inputs.get("missing_primary") and "missing_primary" not in limitations:
        return None, "missing_primary_flag"
    if any(not s["body_complete"] for s in sources if s["id"] in used) and "partial_source" not in limitations:
        return None, "missing_partial_flag"
    return output, None
