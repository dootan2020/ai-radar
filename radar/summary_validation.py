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
    "usd": r"(?:USD|dollars?|đô la)",
}
PERCENT_RANGE = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(?:to|[-–])\s*\d+(?:[.,]\d+)?\s*(?:%|percent|phần trăm)", re.I)
MONEY = re.compile(r"(?P<dollar>\$)?(?P<value>\d+(?:[.,]\d+)?)\s*(?P<scale>billion|million|tỷ|triệu|[BM])\b(?:\s*(?:USD|dollars?))?", re.I)

COMMON_ACRONYMS = {"AI", "IPO", "CEO", "CTO", "CFO", "COO", "GPU", "CPU", "API", "USD",
                   "LLM", "LLMS", "AGI", "SEC", "PAC", "FPGA", "JSON", "XML", "SQL", "HTTP",
                   "HTTPS", "RISC", "UI", "UX", "US", "UK", "EU"}
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


def number_error(text, evidence):
    evidence = normalized(evidence)
    source_money = money_claims(evidence)
    for value, role in money_claims(text):
        if not any(value == number and (role is None or role == source_role)
                   for number, source_role in source_money):
            return "unsupported_amount_role"
    # Remove scaled currency amounts before ordinary numeric comparison; notation may translate.
    source_numbers = {n.replace(",", ".").casefold() for n in NUMBER.findall(MONEY.sub("", evidence))}
    source_words = set(re.findall(r"[a-z]+", evidence.casefold()))
    for index, word in enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")):
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
            direct = re.search(r"\b" + number + r"\s*(?:" + pattern + r")", evidence, re.I)
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
    for full_name, surname in (("Donald Trump", "Trump"), ("Elon Musk", "Musk")):
        if re.search(r"(?<!\w)" + re.escape(surname) + r"(?!\w)", evidence):
            text = re.sub(r"(?<!\w)" + re.escape(full_name) + r"(?!\w)", " ", text)
    # Ai2 is the Allen Institute for AI's published short name.
    if re.search(r"(?<!\w)Ai2(?!\w)", evidence, re.I):
        text = re.sub(r"(?<!\w)(?:Viện Allen|Allen Institute(?: for AI)?)(?!\w)", " ", text)
    allowed = {folded(token) for token in ENTITY_WORD.findall(evidence)}
    for word in ENTITY_WORD.findall(text):
        if (word[0].isupper() and not vietnamese_syllable(word)
                and word.upper() not in COMMON_ACRONYMS and folded(word) not in allowed):
            return "invented_entity: " + word
    # Names made of distinctive tokens must also occur as a complete name.
    for name in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,}\b", text):
        if any(not vietnamese_syllable(word) for word in name.split()) and folded(name) not in folded(evidence):
            return "unsupported_name: " + name
    return None


def claim_error(claim, refs, paragraph_refs, *, max_length):
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
    # Headline/date metadata never licenses body facts. Publisher metadata only licenses attribution.
    error = number_error(text, evidence) or entity_error(text, evidence)
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


def validate_summary(inputs, output):
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
    for source in sources:
        for p in [*source["paragraphs"], source["publisher"]]:
            if p["id"] in refs:
                return None, "duplicate_input_ref"
            refs[p["id"]], owners[p["id"]] = p["text"], source["id"]
        paragraph_refs.update(p["id"] for p in source["paragraphs"])
    claims = [(output["title_vi"], 240), *[(p, 520) for p in output["key_points"]]]
    for claim, limit in claims:
        claim_refs = dict(refs)
        for ref in claim["evidence_refs"]:
            if ref in owners:
                publisher = next(s["publisher"]["text"] for s in sources if s["id"] == owners[ref])
                claim_refs[ref] += " " + publisher
        error = claim_error(claim, claim_refs, paragraph_refs, max_length=limit)
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
