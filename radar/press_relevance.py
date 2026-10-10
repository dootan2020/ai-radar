"""Conservative, cost-free subject checks for loosely tagged press feeds."""

import re
import unicodedata
from copy import deepcopy
from functools import lru_cache

from radar.common import clean_text
from radar.items import relevant


# A relationship to AI alone does not make a consumer rule an AI story.
# These are subjects, not banned topics: AI-led banking/security stories stay.
_CONSUMER_SUBJECT = re.compile(
    r"\b(?:chuyển tiền|giao dịch|thanh toán|tài khoản ngân hàng|sinh trắc học|"
    r"bank transfers?|money transfers?|transfer limits?|payments?|bank accounts?|"
    r"biometric verification)\b", re.I)
_ADMIN_CHANGE = re.compile(
    r"\b(?:quy định|hạn mức|thủ tục|yêu cầu|rules?|limits?|requirements?|regulations?)\b", re.I)
_WEAK_LINK = re.compile(
    r"\b(?:liên quan (?:đến|tới)|có nhắc (?:đến|tới)|nhắc (?:đến|tới)|"
    r"related to|relating to|with (?:a )?mention(?:s)? of|mentions?|mentioning)\s+"
    r"(?:AI|artificial intelligence|trí tuệ nhân tạo)\b|\bAI-related\b", re.I)
_MENTION = re.compile(r"\b(?:nhắc (?:đến|tới)|mentions?|mentioning)\b", re.I)
_ASIDE = re.compile(
    r"\b(?:cũng nhắc (?:đến|tới)|also mentions?|briefly mentions?|in passing mentions?)\s+"
    r"(?:AI|artificial intelligence|trí tuệ nhân tạo)\b", re.I)
# Recall guard for new product names and adjacent infrastructure. These weak
# clues are reported as uncertain, never asserted to prove an AI subject.
_CONTEXT = re.compile(
    r"\b(?:models?|agents?|assistants?|robots?|robotics|data cent(?:er|re)s?|"
    r"text-to-\w+|from (?:text )?prompts?|mô hình|trợ lý|trung tâm dữ liệu)\b", re.I)


def press_subject_reason(title, summary=""):
    """Return an explainable keep/drop reason; uncertain sparse copy stays.

    No model output, translations, URL keywords or category labels count as
    subject evidence. Named AI companies, applications and policy remain valid.
    """
    title = unicodedata.normalize("NFC", clean_text(title, 500))
    summary = unicodedata.normalize("NFC", clean_text(summary))
    main_title = _WEAK_LINK.sub("", title)
    weak_link = main_title != title
    if weak_link and _MENTION.search(title) and not relevant(main_title):
        return "drop-title-aside"
    if (weak_link and _CONSUMER_SUBJECT.search(main_title)
            and _ADMIN_CHANGE.search(main_title) and not relevant(main_title)):
        return "drop-incidental-consumer-subject"
    if relevant(title):
        return "keep-weak-title" if weak_link else "keep-title"
    # Explicit side mentions cannot rescue an otherwise unrelated headline.
    subject_summary = _ASIDE.sub("", summary)
    if relevant(subject_summary):
        return "keep-summary-only"
    if relevant(summary):
        return "drop-summary-aside"
    if _CONTEXT.search(title + " " + summary):
        return "keep-context-only"
    if summary:
        return "drop-no-ai-evidence"
    return "keep-insufficient-copy"


def accepts_feed_item(source, title, summary=""):
    if source.get("group") == "press":
        if press_subject_reason(title, summary).startswith("drop-"):
            return False
    return not source.get("filter_ai") or relevant(title, summary)


@lru_cache(maxsize=1)
def _press_sources():
    from radar.catalog import RSS

    return {row[0] for row in RSS if row[2] == "press"}


def accepts_observation(item):
    if item.get("group") != "press" and item.get("source") not in _press_sources():
        return True
    return not press_subject_reason(item.get("title", ""), item.get("summary", "")).startswith("drop-")


def filter_published_stories(stories, now, accepts=accepts_observation):
    """Remove rejected retained coverage before it can merge into fresh stories.

    Rebuild changed stories from remaining observations so an excluded primary
    cannot leave its title, image, translations or generated summary behind.
    A story whose observations no longer form one cluster under the current
    rules is rebuilt the same way, so a wrong grouping published earlier does
    not keep re-merging fresh coverage for seven days. Unchanged stories retain
    their identity and enrichment verbatim.
    """
    from radar.clustering import cluster_items

    result = []
    for story in stories:
        coverage = story.get("coverage") or []
        kept = [item for item in coverage if accepts(item)]
        if len(kept) == len(coverage):
            pieces = cluster_items(deepcopy(kept), now) if len(kept) > 1 else []
            if len(pieces) <= 1:
                result.append(story)
                continue
            # Split, nothing refused: the piece that keeps the story's id and headline keeps its
            # aliases and enrichment; the others are different events and must not claim the old id.
            siblings = {piece["id"] for piece in pieces}
            for index, piece in enumerate(pieces):
                if piece["id"] == story.get("id"):
                    aliases = sorted((set(piece.get("aliases", [])) | set(story.get("aliases", []))) - siblings)
                    if story.get("url") in {item.get("url") for item in piece["coverage"]}:
                        piece = pieces[index] = dict(deepcopy(story), coverage=piece["coverage"],
                                                     source_count=piece["source_count"], groups=piece["groups"],
                                                     primary_section=piece["primary_section"])
                    piece["aliases"] = aliases
            if not any(piece["id"] == story.get("id") for piece in pieces):
                pieces[0]["aliases"] = sorted((set(pieces[0].get("aliases", []))
                                               | set(story.get("aliases", [])) | {story["id"]}) - siblings)
            result.extend(pieces)
        elif kept:
            for rebuilt in cluster_items(deepcopy(kept), now):
                rebuilt["aliases"] = sorted((set(rebuilt.get("aliases", []))
                                             | set(story.get("aliases", []))
                                             | {story["id"]}) - {rebuilt["id"]})
                result.append(rebuilt)
    return result
