"""Five desks, resumable job state, and a publication decision contract."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from radar.clustering import canonical_url, titles_match
from radar.items import instant, relevant
from radar.press_relevance import press_subject_reason
from radar.summary_pipeline import fetch_article_result, story_inputs
from radar.summary_validation import number_error
from radar import shadow_collector, transport

from .registry import providers
from .runner import AdmissionError, RunnerError

DESKS = ("intake", "reporter", "editor", "checker", "chief")
BATCH_SIZE = 32
MAX_BATCH_CHARS = 60_000
ARGUMENT_BATCH_CHARS = 24_000
ARTICLE_LIMIT = 3200
REPORTER_EXCERPT_LIMIT = 900
EDITOR_EXCERPT_LIMIT = 1200
JUNK_KINDS = {"non_news_page", "vendor_sales", "customer_case_study", "tutorial", "incidental_ai", "mis_merged_cluster", "stale_content"}
CONTENT_KINDS = ("event_news", "analysis", "junk")
ANALYSIS_KINDS = ("analysis", "interview", "opinion", "podcast", "survey")
IMPORTANCE_TIERS = ("top", "notable", "standard")
EDITOR_PROMPT = ("You are a newsroom editor. Classify each card as event_news, analysis, or junk. "
                 "Return each {id, content_kind:event_news|analysis|junk, analysis_kind:string|null, news:boolean, "
                 "junk_kind:string|null, reason:string, subject:string, event_type:string, "
                 "importance:string, event_at:string|null, claims:[string], same_event_coverage_ids:[string]}. "
                 "Set news=true for event_news and analysis, news=false for junk. "
                 f"For news=true, importance must be exactly {', '.join(IMPORTANCE_TIERS[:-1])}, "
                 f"or {IMPORTANCE_TIERS[-1]}; never high, low, or none. "
                 "For news=false, use importance=standard and an exact junk_kind from the list below. "
                 "For news=true, use junk_kind=null and 0 to 8 distinct supported claims; 0 claims is valid news without a summary. "
                 f"For analysis, set analysis_kind to one of {', '.join(ANALYSIS_KINDS)} and importance=standard. "
                 "For analysis use event_type=analysis_kind and event_at=null when no dated event is reported. "
                 "Analysis includes reported trend analysis, interviews, opinion, podcasts, and literature surveys whose main subject is AI, "
                 "even without a single new dated event; event_at may be null. Publish these as standard, never top or notable. "
                 "An interview with an AI researcher, an assessment of AI market economics, or a reported account "
                 "of changes across AI vendors can qualify as analysis without a newly announced event. "
                 "Business reporting qualifies when AI is its main subject, including company results, acquisitions, "
                 "and market activity; a passing reference to AI does not qualify. "
                 f"For news=false, junk_kind must be one of {', '.join(sorted(JUNK_KINDS))}. "
                 "The absence of a new dated event alone does not make AI-focused analysis junk. "
                 "Use stale_content only when the same old item is re-posted with nothing new. "
                 "A real launch remains event_news when reviewed more than seven days later, at standard tier. "
                 "A concrete vendor launch with a dated announcement is event_news. A Show HN pitch or product landing page "
                 "consisting of demos, sales copy, or a call to buy without independent reporting or a substantive release is vendor_sales; "
                 "a bare model or dataset card with no announcement is non_news_page. "
                 "A documented release or independently reported launch can be event_news even on a model hub or social forum. "
                 "A missing or short source is uncertainty, not junk: use the title and teaser to classify the event, "
                 "and return no claims without source support. Each nonempty claim must be 1 to 520 characters. Never use source_count as proof. "
                 "Reject advertising, customer case studies, tutorials, incidental AI, casual social chatter without substantive reporting, "
                 "and genuinely stale resurfacing. Separate unrelated coverage IDs.")
REPORTER_PROMPT = "You are a reporter. Read each public article excerpt. If the representative article is unreadable, choose at most one readable candidate from a different publisher about the exact same event, or null. A 403 is not evidence of paywall. Never bypass robots, sign in, or infer facts from source_count. Return each {id, selected_url:string|null, same_event:boolean, reason:string}."
CHECKER_PROMPT = ("You are an independent fact checker. Compare the original title and each claim with the cited "
                  "source paragraphs. Return each {id, title_supported:boolean, reason:string, supported_claims:[string]}. "
                  "Only copy fully supported claims verbatim into supported_claims; reject unsupported entities, dates, "
                  "figures and wrong-event evidence. A bad title or one bad claim must not reject the whole story.")


def load_stories(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    stories = data.get("stories") if isinstance(data, dict) else data
    if not isinstance(stories, list) or any(not isinstance(s, dict) or not s.get("id") for s in stories):
        raise ValueError("input must contain stories with IDs")
    if len({s["id"] for s in stories}) != len(stories):
        raise ValueError("duplicate story IDs")
    return data.get("generated_at") if isinstance(data, dict) else None, stories


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    temporary.replace(path)


class Articles:
    def __init__(self):
        self.robots_cache = {}

    def read(self, url):
        return fetch_article_result({"url": url}, self.robots_cache)

    def search(self, title):
        query = urllib.parse.urlencode({"query": title[:150], "tags": "story", "hitsPerPage": 8})
        url = "https://hn.algolia.com/api/v1/search?" + query
        try:
            robots = shadow_collector.check_robots(url, fetch_fn=lambda target: transport.read_url(target, allow_redirects=False),
                                                   robots_cache=self.robots_cache)
            if robots["robots_status"] not in (200, 404) or robots["disallowed"]:
                return []
            response = transport.read_url(url, allow_redirects=False)
            if response.status != 200 or response.url != url:
                return []
            hits = json.loads(str(response)).get("hits", [])
        except (OSError, ValueError, AttributeError, TypeError):
            return []
        return [{"title": hit.get("title") or "", "url": hit.get("url") or "",
                 "published_at": hit.get("created_at") or "", "publisher": ""} for hit in hits if isinstance(hit, dict)]


class FixtureArticles:
    def __init__(self, fixture):
        self.fixture = fixture

    def read(self, url):
        item = self.fixture.get("articles", {}).get(url, {})
        return item.get("text", ""), item.get("reason", "unavailable")

    def search(self, title):
        return self.fixture.get("search", {}).get(title, [])


def _publisher(url):
    host = (urlsplit(url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _same_rep_url(left, right):
    if canonical_url(left) != canonical_url(right):
        return False
    left_fragment, right_fragment = urlsplit(left or "").fragment, urlsplit(right or "").fragment
    return left_fragment == right_fragment if left_fragment or right_fragment else True


def _reason(value, fallback):
    return " ".join(value.split())[:300] if isinstance(value, str) and value.strip() else fallback


def _candidate(story, item, articles, *, strict_title):
    url = item.get("url")
    if not isinstance(url, str) or not url.startswith("https://") or not canonical_url(url):
        return None
    if canonical_url(url) == canonical_url(story.get("url")) or _publisher(url) == _publisher(story.get("url", "")):
        return None
    if strict_title and not titles_match(story, item):
        return None
    text, reason = articles.read(url)
    if not text:
        return None
    return {"url": url, "title": item.get("title") or "", "publisher": _publisher(url),
            "text": text[:ARTICLE_LIMIT], "read_status": "readable", "coverage_id": item.get("id")}


def _intake(stories, now):
    output = {}
    for story in stories:
        reason = None
        date = instant(story.get("published_at"))
        if not story.get("title") or not canonical_url(story.get("url")):
            reason = "missing title or public URL"
        elif not date:
            reason = "missing reliable publication date"
        elif date > now + timedelta(days=1):
            reason = "publication date is in the future"
        elif date < now - timedelta(days=30):
            reason = "original event is over 30 days old without verified update"
        elif not relevant(story.get("title"), story.get("summary")) and press_subject_reason(story.get("title"), story.get("summary")).startswith("drop-"):
            reason = "no evidence that AI is the main subject"
        output[story["id"]] = {"id": story["id"], "pass": reason is None, "reason": reason or "eligible for reporting"}
    return output


def _batches(rows, max_chars=MAX_BATCH_CHARS):
    batch, chars = [], 0
    for row in rows:
        size = len(json.dumps(row, ensure_ascii=False))
        if batch and (len(batch) >= BATCH_SIZE or chars + size > max_chars):
            yield batch
            batch, chars = [], 0
        batch.append(row)
        chars += size
    if batch:
        yield batch


def _agent_desk(desk, payload, instruction, capability, tools, discovery, runner, *, boat_exclude=(), raw_dir=None):
    candidates = [tool for tool in providers(capability, tools, discovery, boat_exclude=boat_exclude)
                  if tool.get("runner") == "batch-cli"]
    if not candidates:
        raise RunnerError(f"no configured batch CLI for {desk} on an eligible boat")
    output, batches = {}, []

    existing_raw = list(Path(raw_dir).glob(f"{desk}-*.json")) if raw_dir is not None and Path(raw_dir).exists() else []
    batch_number = max((int(path.stem.removeprefix(f"{desk}-")) for path in existing_raw), default=0)

    def send(batch, index=0):
        nonlocal batch_number
        provider = candidates[index]
        limit = ARGUMENT_BATCH_CHARS if provider.get("prompt_transport") == "argument" else MAX_BATCH_CHARS
        for part in _batches(batch, limit):
            try:
                result = runner.run(desk, part, provider, instruction)
            except AdmissionError:
                raise
            except RunnerError as error:
                if index + 1 == len(candidates):
                    raise RunnerError(f"{provider['id']}: {error}") from error
                send(part, index + 1)
                continue
            batch_number += 1
            if raw_dir is not None:
                _write_json(Path(raw_dir) / f"{desk}-{batch_number}.json",
                            {"desk": desk, "batch": batch_number, "provider": provider["id"], "stories": result.rows})
            for row in result.rows:
                output[row["id"]] = {**row, "provider": provider["id"], "boat": provider.get("boat")}
            batches.append({"provider": provider["id"], **result.usage})

    for batch in _batches(payload):
        send(batch)
    return output, batches


def _reporter(stories, intake, articles, tools, discovery, runner, corpus, raw_dir=None):
    readers = providers("doc-bai", tools, discovery)
    searchers = providers("tim-kiem", tools, discovery)
    if not any(tool.get("runner") == "http-fetch" for tool in readers):
        raise RunnerError("no configured local article reader")
    can_search_hn = any(tool.get("runner") == "hn-algolia" for tool in searchers)
    payload, source_map = [], {}
    statuses = {}
    for story in stories:
        if not intake[story["id"]]["pass"]:
            continue
        text, reason = articles.read(story["url"])
        statuses[story["id"]] = "readable" if text else reason
        candidates = []
        if text:
            candidates.append({"url": story["url"], "title": story["title"],
                               "publisher": _publisher(story["url"]), "text": text[:ARTICLE_LIMIT],
                               "read_status": "readable"})
        else:
            for item in story.get("coverage") or []:
                if isinstance(item, dict):
                    candidate = _candidate(story, item, articles, strict_title=True)
                    if candidate and candidate["url"] not in {c["url"] for c in candidates}:
                        candidates.append(candidate)
            for item in corpus:
                if item["id"] == story["id"] or not titles_match(story, item):
                    continue
                candidate = _candidate(story, item, articles, strict_title=False)
                if candidate and candidate["url"] not in {c["url"] for c in candidates}:
                    candidates.append(candidate)
                if len(candidates) >= 5:
                    break
            for item in articles.search(story["title"]) if can_search_hn else []:
                candidate = _candidate(story, item, articles, strict_title=False)
                if candidate and candidate["url"] not in {c["url"] for c in candidates}:
                    candidates.append(candidate)
        source_map[story["id"]] = {c["url"]: c for c in candidates}
        if candidates:
            payload.append({"id": story["id"], "title": story["title"], "published_at": story.get("published_at"),
                            "representative_url": story["url"], "representative_status": statuses[story["id"]],
                            "candidates": [{**candidate, "text": candidate["text"][:REPORTER_EXCERPT_LIMIT]} for candidate in candidates]})
    replies, usage = _agent_desk("reporter", payload, REPORTER_PROMPT, "doc-bai", tools, discovery, runner, raw_dir=raw_dir) if payload else ({}, [])
    def invalid_reply(row):
        return bool(row and (type(row.get("same_event")) is not bool or
                             (row.get("selected_url") is not None and not isinstance(row.get("selected_url"), str))))

    retry_payload = [item for item in payload if invalid_reply(replies.get(item["id"]))]
    if retry_payload:
        retry, retry_usage = _agent_desk("reporter", retry_payload, REPORTER_PROMPT, "doc-bai", tools,
                                         discovery, runner, raw_dir=raw_dir)
        replies.update(retry)
        usage.extend(retry_usage)
    output = {}
    for story in stories:
        row = replies.get(story["id"])
        invalid = invalid_reply(row)
        url = row.get("selected_url") if row and not invalid else None
        candidate = source_map.get(story["id"], {}).get(url)
        valid = bool(not invalid and candidate and row.get("same_event") is True and (url == story["url"] or candidate["publisher"] != _publisher(story["url"])))
        reason = "reporter_invalid" if invalid else (_reason(row.get("reason"), "source selected") if valid else
                  _reason(row.get("reason"), "no readable same-event source") if row and not url else
                  "selected source is unreadable, wrong-event, or not independent" if row else
                  "no readable same-event candidate" if intake[story["id"]]["pass"] else "intake hold")
        output[story["id"]] = {"id": story["id"], "readable": valid, "selected_url": url if valid else None,
                               "source_text": candidate["text"] if valid else "",
                               "reason": reason,
                               "invalid_response": invalid,
                               "representative_status": statuses.get(story["id"], "not_checked"),
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _editor_news_fields_valid(row, coverage_ids, *, require_importance=True):
    if not row or row.get("news") is not True:
        return False
    same = row.get("same_event_coverage_ids")
    claims = row.get("claims")
    return bool(isinstance(same, list) and all(isinstance(value, str) for value in same)
                and set(same) <= coverage_ids
                and isinstance(claims, list) and len(claims) <= 8
                and all(isinstance(c, str) and 0 < len(c.strip()) <= 520 for c in claims)
                and len({c.casefold().strip() for c in claims}) == len(claims)
                and isinstance(row.get("subject"), str) and row["subject"].strip()
                and isinstance(row.get("event_type"), str) and row["event_type"].strip()
                and (not require_importance or
                     isinstance(row.get("importance"), str) and row["importance"] in IMPORTANCE_TIERS)
                and (row.get("event_at") is None or isinstance(row.get("event_at"), str))
                and row.get("content_kind", "event_news") in CONTENT_KINDS[:2]
                and (row.get("content_kind") != "analysis" or row.get("analysis_kind") in ANALYSIS_KINDS))


def _editor(stories, intake, reporter, tools, discovery, runner, raw_dir=None):
    payload = []
    for story in stories:
        if not intake[story["id"]]["pass"]:
            continue
        inputs = story_inputs(story)
        payload.append({"id": story["id"], "title": inputs["title"], "summary": inputs["summary"],
                        "published_at": inputs["published_at"], "original_url": story["url"],
                        "kind": story.get("kind"),
                        "coverage": [{"id": c.get("id"), "title": c.get("title"), "url": c.get("url"), "published_at": c.get("published_at")} for c in story.get("coverage") or [] if isinstance(c, dict)],
                        "source_url": reporter[story["id"]]["selected_url"],
                        "source_status": reporter[story["id"]]["representative_status"],
                        "source_excerpt": reporter[story["id"]]["source_text"][:EDITOR_EXCERPT_LIMIT]})
    replies, usage = _agent_desk("editor", payload, EDITOR_PROMPT, "bien-tap", tools, discovery, runner, raw_dir=raw_dir) if payload else ({}, [])
    coverage_by_id = {story["id"]: {c["id"] for c in story.get("coverage") or []
                                    if isinstance(c, dict) and isinstance(c.get("id"), str)} for story in stories}

    def needs_retry(row, sid):
        return (type(row.get("news")) is not bool if row else True) or (
            row.get("news") is True and not _editor_news_fields_valid(row, coverage_by_id[sid]))

    junk_hints = {sid: row["junk_kind"] for sid, row in replies.items()
                  if type(row.get("news")) is not bool and row.get("junk_kind")}
    retry_payload = [item for item in payload if needs_retry(replies.get(item["id"]), item["id"])]
    if retry_payload:
        retry, retry_usage = _agent_desk("editor", retry_payload, EDITOR_PROMPT, "bien-tap", tools,
                                         discovery, runner, raw_dir=raw_dir)
        replies.update(retry)
        usage.extend(retry_usage)
    output = {}
    for story in stories:
        sid = story["id"]
        row = replies.get(sid)
        coverage_ids = coverage_by_id[sid]
        news = row.get("news") if row else None
        valid_news_fields = _editor_news_fields_valid(row, coverage_ids)
        usable_news_fields = _editor_news_fields_valid(row, coverage_ids, require_importance=False)
        junk_kind = (row.get("junk_kind") if row else None)
        if news is not False and not junk_kind:
            junk_kind = junk_hints.get(sid)
        unknown_junk_kind = news is False and (not isinstance(junk_kind, str) or junk_kind not in JUNK_KINDS)
        invalid = bool(intake[sid]["pass"] and (needs_retry(row, sid) or unknown_junk_kind))
        is_junk = bool(news is False or (row and row.get("content_kind") == "junk")
                       or sid in junk_hints or (type(news) is not bool and junk_kind))
        is_news = not is_junk and (news is True or invalid)
        same = row.get("same_event_coverage_ids") if usable_news_fields else []
        representative_ids = {c["id"] for c in story.get("coverage") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)
                              and _same_rep_url(c.get("url"), story.get("url"))}
        same = sorted(set(same) | representative_ids)
        output[sid] = {"id": sid, "news": is_news if intake[sid]["pass"] else False,
                               "content_kind": "junk" if is_junk else "analysis" if row and row.get("content_kind") == "analysis" else "event_news",
                               "analysis_kind": (row.get("analysis_kind") if row.get("analysis_kind") in ANALYSIS_KINDS else "analysis")
                               if row and row.get("content_kind") == "analysis" and not is_junk else None,
                               "reason": "editor_invalid" if invalid and not is_junk else _reason(row.get("reason"), "editor marked junk") if row else "earlier desk hold",
                               "invalid_response": invalid,
                               "junk_kind": junk_kind if is_junk else None,
                               "subject": row.get("subject") if row else None, "event_type": row.get("event_type") if row else None,
                               "importance": row["importance"] if valid_news_fields else "standard",
                               "event_at": row.get("event_at") if usable_news_fields else None,
                               "claims": row["claims"] if usable_news_fields else [],
                               "same_event_coverage_ids": same,
                               "split_coverage_ids": sorted(coverage_ids - set(same)),
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _checker(stories, intake, reporter, editor, tools, discovery, runner, raw_dir=None):
    def cited_paragraphs(text, title, claims):
        paragraphs = [part.strip()[offset:offset + 400]
                      for part in text.splitlines() if len(part.strip()) >= 35
                      for offset in range(0, len(part.strip()), 320)]
        selected = []
        for claim in [title, *claims]:
            terms = set(re.findall(r"\w{4,}", claim.casefold()))
            if paragraphs:
                best = max(paragraphs, key=lambda part: len(terms & set(re.findall(r"\w{4,}", part.casefold()))))
                if best not in selected:
                    selected.append(best)
        return selected

    payload_by_boat = {}
    for story in stories:
        if editor[story["id"]]["news"] and reporter[story["id"]]["readable"]:
            payload_by_boat.setdefault(editor[story["id"]]["boat"], []).append(
                {"id": story["id"], "title": story["title"], "claims": editor[story["id"]]["claims"],
                 "source_url": reporter[story["id"]]["selected_url"],
                 "cited_paragraphs": cited_paragraphs(reporter[story["id"]]["source_text"], story["title"], editor[story["id"]]["claims"])})
    replies, usage = {}, []
    for boat, payload in payload_by_boat.items():
        group_replies, group_usage = _agent_desk("checker", payload, CHECKER_PROMPT, "kiem-chung", tools, discovery, runner,
                                                 boat_exclude={boat}, raw_dir=raw_dir)
        replies.update(group_replies)
        usage.extend(group_usage)
    def invalid_reply(row, boat):
        return bool(row and (row.get("boat") == boat or
                             type(row.get("title_supported", row.get("verified"))) is not bool or
                             not isinstance(row.get("supported_claims", []), list)))

    for boat, payload in payload_by_boat.items():
        retry_payload = [item for item in payload if invalid_reply(replies.get(item["id"]), boat)]
        if retry_payload:
            retry, retry_usage = _agent_desk("checker", retry_payload, CHECKER_PROMPT, "kiem-chung", tools,
                                             discovery, runner, boat_exclude={boat}, raw_dir=raw_dir)
            replies.update(retry)
            usage.extend(retry_usage)
    output = {}
    for story in stories:
        row = replies.get(story["id"])
        editor_boat = editor[story["id"]]["boat"]
        invalid = invalid_reply(row, editor_boat)
        evidence = reporter[story["id"]]["source_text"]
        claims = editor[story["id"]]["claims"]
        supported = row.get("supported_claims", []) if row and not invalid else []
        if not isinstance(supported, list):
            supported = []
        supported = [claim for claim in claims if claim in supported and not number_error(claim, evidence)] if evidence else []
        title_supported = bool(row and row.get("title_supported", row.get("verified") is True) is True
                               and not number_error(story["title"], evidence)) if evidence else False
        verified = bool(row and title_supported and len(supported) == len(claims))
        reason = ("unsupported number or amount" if evidence and any(number_error(c, evidence) for c in [story["title"], *claims]) else
                  _reason(row.get("reason"), "checked") if row else "no readable source to check")
        output[story["id"]] = {"id": story["id"], "verified": verified,
                               "title_supported": title_supported, "supported_claims": supported,
                               "rejected_claims": [claim for claim in claims if claim not in supported],
                               "reason": "checker_invalid" if invalid else reason, "invalid_response": invalid,
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _chief(stories, intake, reporter, editor, checker, now):
    output = []
    for story in stories:
        sid = story["id"]
        gate = (("intake", intake[sid]["reason"]) if not intake[sid]["pass"] else
                ("editor", editor[sid]["reason"]) if not editor[sid]["news"] else None)
        tier = editor[sid]["importance"] if editor[sid]["importance"] in IMPORTANCE_TIERS else "standard"
        original_at = instant(story.get("published_at"))
        proposed_at = instant(editor[sid]["event_at"])
        event_at = min(original_at, proposed_at) if original_at and proposed_at else original_at
        degradations = []
        if not reporter[sid]["readable"]:
            degradations.append("no readable same-event source")
        supported = checker[sid].get("supported_claims", []) if reporter[sid]["readable"] else []
        if checker[sid].get("rejected_claims"):
            degradations.append("checker rejected claims")
        use_original_title = bool(not reporter[sid]["readable"] or
                                  not checker[sid].get("title_supported", checker[sid].get("verified", False)))
        if use_original_title:
            degradations.append("original title not source-checked" if not reporter[sid]["readable"] else "checker rejected title")
        summary = "claims" if reporter[sid]["readable"] and len(supported) >= 2 else "none"
        if summary == "none":
            degradations.append("too few verified claims for summary")
        tier_capped = not reporter[sid]["readable"]
        if editor[sid].get("content_kind") == "analysis":
            tier_capped = True
            tier = "standard"
            degradations.append("analysis is standard tier")
        if tier_capped:
            tier = "standard"
        if reporter[sid]["readable"] and (checker[sid].get("rejected_claims") or use_original_title):
            tier = "standard"
            tier_capped = True
            degradations.append("incomplete checker support caps tier")
        if event_at and event_at < now - timedelta(days=7):
            tier = "standard"
            tier_capped = True
            degradations.append("event or original publication is older than seven days")
        elif tier in {"top", "notable"} and not proposed_at:
            tier = "standard"
            tier_capped = True
            degradations.append("no verified event date for promoted tier")
        if tier in {"top", "notable"} and summary == "none":
            tier = "standard"
            tier_capped = True
            degradations.append("no verified summary for promoted tier")
        if tier == "top" and not 4 <= len(supported) <= 8:
            tier = "standard"
            tier_capped = True
            degradations.append("top tier needs four to eight verified key points")
        output.append({"id": sid, "decision": "hold" if gate else "publish",
                       "content_kind": editor[sid].get("content_kind", "event_news"),
                       "analysis_kind": editor[sid].get("analysis_kind"),
                       "round": gate[0] if gate else "chief", "reason": gate[1] if gate else "; ".join(degradations) if degradations else "news and claims checked",
                       "importance_tier": tier, "tier_capped": tier_capped,
                       "summary": summary if not gate else "none", "degradation_reasons": degradations if not gate else [],
                       "use_original_title": use_original_title,
                       "source_url": reporter[sid]["selected_url"] or story.get("url"),
                       "key_points": supported if not gate and summary != "none" else [],
                       "same_event_coverage_ids": editor[sid]["same_event_coverage_ids"],
                       "split_coverage_ids": editor[sid]["split_coverage_ids"]})
    return output


def run(input_path, job, tools, discovery, runner, *, through="chief", articles=None, corpus_path=None, rerun_from=None):
    generated_at, stories = load_stories(input_path)
    now = instant(generated_at) or datetime.now(timezone.utc)
    job = Path(job)
    job.mkdir(parents=True, exist_ok=True)
    status_path = job / "status.json"
    input_hash = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
    corpus_hash = hashlib.sha256(Path(corpus_path).read_bytes()).hexdigest() if corpus_path else input_hash
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {"input": str(Path(input_path).resolve()), "input_sha256": input_hash, "corpus_sha256": corpus_hash, "desks": {}}
    if (status["input"] != str(Path(input_path).resolve()) or status.get("input_sha256") != input_hash
            or status.get("corpus_sha256") != corpus_hash):
        raise ValueError("job input differs from existing run")
    if rerun_from is not None:
        if DESKS.index(rerun_from) > DESKS.index(through):
            raise ValueError("rerun start must not follow the requested last desk")
        for desk in DESKS[DESKS.index(rerun_from):]:
            status["desks"].pop(desk, None)
        _write_json(status_path, status)
    articles = articles or Articles()
    corpus = load_stories(corpus_path)[1] if corpus_path else stories
    state = {}
    for desk in DESKS[:DESKS.index(through) + 1]:
        path = job / f"{desk}.json"
        if status["desks"].get(desk, {}).get("state") == "done" and path.exists():
            state[desk] = json.loads(path.read_text(encoding="utf-8"))
            continue
        status["desks"][desk] = {"state": "running", "started_at": datetime.now(timezone.utc).isoformat()}
        _write_json(status_path, status)
        try:
            if desk == "intake":
                output, usage = _intake(stories, now), []
            elif desk == "reporter":
                output, usage = _reporter(stories, state["intake"], articles, tools, discovery, runner, corpus, job / "raw")
            elif desk == "editor":
                output, usage = _editor(stories, state["intake"], state["reporter"], tools, discovery, runner, job / "raw")
            elif desk == "checker":
                output, usage = _checker(stories, state["intake"], state["reporter"], state["editor"], tools, discovery, runner, job / "raw")
            else:
                output, usage = _chief(stories, state["intake"], state["reporter"], state["editor"], state["checker"], now), []
            _write_json(path, output)
            state[desk] = output
            status["desks"][desk] = {"state": "done", "completed_at": datetime.now(timezone.utc).isoformat(),
                                      "count": len(output),
                                      "invalid_rows": sum(bool(row.get("invalid_response")) for row in (output.values() if isinstance(output, dict) else output)),
                                      "batches": usage}
            if desk == "chief":
                _write_json(job / "quyet-dinh.json", {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                                                     "input_generated_at": generated_at, "decisions": output})
        except Exception as error:
            status["desks"][desk] = {"state": "failed", "error": str(error)}
            _write_json(status_path, status)
            raise
        _write_json(status_path, status)
    return status
