"""Source-conditioned mistakes that a structural translation check cannot catch."""

import re


# Each pair names a meaning-changing rendering observed in the audited snapshot.
# Check raw output before glossary repair so a stale cache entry is retranslated.
_BAD_MEANINGS = tuple(
    (re.compile(source, re.IGNORECASE), re.compile(vi, re.IGNORECASE))
    for source, vi in (
        (r"\bfrontier AI models?\b", r"\bhàng rào\b"),
        (r"\bcredentials?\b", r"\bthông tin tín dụng\b"),
        (r"\blocales?\b", r"\bđịa phương\b"),
        (r"\bgenerally available\b", r"\b(?:thường có sẵn|sẵn có chung)\b"),
        (r"\bliterature landscape\b", r"\bvăn học\b"),
        (r"\bfabs?\b", r"\bphim truyền hình\b"),
        (r"\bserving harness\b", r"\bvòng xoáy\b"),
        (r"\bsole-source award\b", r"\bgiải thưởng nguồn duy nhất\b"),
        (r"\bvital\b", r'\bdịch vụ\s+["“]?trách nhiệm\b'),
        (r"^Quick Study$", r"\bnghiên cứu nhanh chóng\b"),
        (r"\beach operator\b", r"\bnhà điều hành\b"),
        (r"\bcompilation problem\b", r"\bvấn đề tổng hợp\b"),
        (r"\bformal software verification\b", r"\bxác minh phần mềm chính thức\b"),
        (r"\bhigh-dimensional spaces\b", r"\bkhông gian chiều cao\b"),
        (r"\bagentic insider\b", r"\bbên trong của nhân viên\b"),
        (r"\bthe Singularity\b", r"\bsự kỳ lạ\b"),
        (r"\bTPUs?, Natively\b", r"\bbản địa\b"),
        (r"\bbiggest shot at\b", r"\bvụ tấn công\b"),
        (r"\bDiffusion\b", r"\bsự pha trộn\b"),
        (r"\bopen-source AI\b.*\bthe best\b", r"\bngười tốt nhất\b"),
    )
)


def changes_meaning(source, translated):
    """Reject a known wrong sense only when the English source has that sense."""
    return isinstance(translated, str) and any(
        english.search(source) and vietnamese.search(translated)
        for english, vietnamese in _BAD_MEANINGS
    )
