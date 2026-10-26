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
EDITOR_PROMPT = ("You are a newsroom editor. Decide whether each card is an actual AI news event or junk. "
                 "Return each {id, news:boolean, junk_kind:string|null, reason:string, subject:string, event_type:string, "
                 "importance:string, event_at:string|null, claims:[string], same_event_coverage_ids:[string]}. "
                 "For news=false, junk_kind must be one of non_news_page, vendor_sales, customer_case_study, tutorial, "
                 "incidental_ai, mis_merged_cluster, stale_content. Only call an item stale_content when an old item "
                 "is resurfaced without a new event; an actual launch on October 7, 8 or 13 is news even when reviewed "
                 "on October 26, and belongs in standard tier after seven days. Phase A labels distinguish old_content_reposted "
                 "from a merely old launch: Phase A marked the September 22 Claude Opus 5.5 page old_content_reposted, "
                 "but marked the October 8 Anthropic Cyber Mission and October 13 Qwen glasses launches as non-junk. "
                 "Vendor product announcements are news, not vendor_sales. "
                 "A missing or short source is uncertainty, not junk: use the title and teaser to classify the event, "
                 "and return no claims without source support. Never use source_count as proof. "
                 "Reject advertising, customer case studies, tutorials, incidental AI, social chatter without an event, "
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


def _agent_desk(desk, payload, instruction, capability, tools, discovery, runner, *, boat_exclude=()):
    candidates = [tool for tool in providers(capability, tools, discovery, boat_exclude=boat_exclude)
                  if tool.get("runner") == "batch-cli"]
    if not candidates:
        raise RunnerError(f"no configured batch CLI for {desk} on an eligible boat")
    output, batches = {}, []

    def send(batch, index=0):
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
            for row in result.rows:
                output[row["id"]] = {**row, "provider": provider["id"], "boat": provider.get("boat")}
            batches.append({"provider": provider["id"], **result.usage})

    for batch in _batches(payload):
        send(batch)
    return output, batches


def _reporter(stories, intake, articles, tools, discovery, runner, corpus):
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
    replies, usage = _agent_desk("reporter", payload, REPORTER_PROMPT, "doc-bai", tools, discovery, runner) if payload else ({}, [])
    output = {}
    for story in stories:
        row = replies.get(story["id"])
        url = row.get("selected_url") if row else None
        candidate = source_map.get(story["id"], {}).get(url)
        valid = bool(candidate and row.get("same_event") is True and (url == story["url"] or candidate["publisher"] != _publisher(story["url"])))
        reason = (_reason(row.get("reason"), "source selected") if valid else
                  _reason(row.get("reason"), "no readable same-event source") if row and not url else
                  "selected source is unreadable, wrong-event, or not independent" if row else
                  "no readable same-event candidate" if intake[story["id"]]["pass"] else "intake hold")
        output[story["id"]] = {"id": story["id"], "readable": valid, "selected_url": url if valid else None,
                               "source_text": candidate["text"] if valid else "",
                               "reason": reason,
                               "representative_status": statuses.get(story["id"], "not_checked"),
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _editor(stories, intake, reporter, tools, discovery, runner):
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
    replies, usage = _agent_desk("editor", payload, EDITOR_PROMPT, "bien-tap", tools, discovery, runner) if payload else ({}, [])
    output = {}
    for story in stories:
        row = replies.get(story["id"])
        coverage_ids = {c["id"] for c in story.get("coverage") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)}
        same = row.get("same_event_coverage_ids") if row else []
        claims = row.get("claims") if row else None
        valid = bool(row and isinstance(same, list) and all(isinstance(value, str) for value in same)
                     and set(same) <= coverage_ids
                     and isinstance(claims, list) and len(claims) <= 8
                     and all(isinstance(c, str) and 0 < len(c.strip()) <= 520 for c in claims)
                     and len({c.casefold().strip() for c in claims}) == len(claims)
                     and isinstance(row.get("subject"), str) and row["subject"].strip()
                     and isinstance(row.get("event_type"), str) and row["event_type"].strip()
                     and isinstance(row.get("importance"), str) and row["importance"] in {"top", "notable", "standard"}
                     and (row.get("event_at") is None or isinstance(row.get("event_at"), str)))
        if row and row.get("news") is True and not valid:
            raise RunnerError(f"invalid editorial response for {story['id']}")
        if row and row.get("news") is False and row.get("junk_kind") not in JUNK_KINDS:
            raise RunnerError(f"editor gave no recognized junk kind for {story['id']}")
        if row and type(row.get("news")) is not bool:
            raise RunnerError(f"editor gave no news verdict for {story['id']}")
        if not valid:
            same = []
        representative_ids = {c["id"] for c in story.get("coverage") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)
                              and _same_rep_url(c.get("url"), story.get("url"))}
        same = sorted(set(same) | representative_ids)
        output[story["id"]] = {"id": story["id"], "news": valid and row.get("news") is True if row else False,
                               "reason": _reason(row.get("reason"), "editor marked junk") if row else "earlier desk hold",
                               "junk_kind": row.get("junk_kind") if row and row.get("news") is False else None,
                               "subject": row.get("subject") if row else None, "event_type": row.get("event_type") if row else None,
                               "importance": row.get("importance", "standard") if row and row.get("news") is True else "standard",
                               "event_at": row.get("event_at") if row and row.get("news") is True else None,
                               "claims": row.get("claims", []) if valid and row.get("news") is True else [],
                               "same_event_coverage_ids": same,
                               "split_coverage_ids": sorted(coverage_ids - set(same)),
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _checker(stories, intake, reporter, editor, tools, discovery, runner):
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
                                                 boat_exclude={boat})
        replies.update(group_replies)
        usage.extend(group_usage)
    output = {}
    for story in stories:
        row = replies.get(story["id"])
        evidence = reporter[story["id"]]["source_text"]
        claims = editor[story["id"]]["claims"]
        if row and row.get("boat") == editor[story["id"]]["boat"]:
            raise RunnerError(f"checker used the editor boat for {story['id']}")
        supported = row.get("supported_claims", []) if row else []
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
                               "reason": reason,
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _chief(stories, intake, reporter, editor, checker, now):
    output = []
    for story in stories:
        sid = story["id"]
        gate = (("intake", intake[sid]["reason"]) if not intake[sid]["pass"] else
                ("editor", editor[sid]["reason"]) if not editor[sid]["news"] else None)
        tier = editor[sid]["importance"] if editor[sid]["importance"] in {"top", "notable", "standard"} else "standard"
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
        (job / "quyet-dinh.json").unlink(missing_ok=True)
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
                output, usage = _reporter(stories, state["intake"], articles, tools, discovery, runner, corpus)
            elif desk == "editor":
                output, usage = _editor(stories, state["intake"], state["reporter"], tools, discovery, runner)
            elif desk == "checker":
                output, usage = _checker(stories, state["intake"], state["reporter"], state["editor"], tools, discovery, runner)
            else:
                output, usage = _chief(stories, state["intake"], state["reporter"], state["editor"], state["checker"], now), []
            _write_json(path, output)
            state[desk] = output
            status["desks"][desk] = {"state": "done", "completed_at": datetime.now(timezone.utc).isoformat(),
                                      "count": len(output), "batches": usage}
            if desk == "chief":
                _write_json(job / "quyet-dinh.json", {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                                                     "input_generated_at": generated_at, "decisions": output})
        except Exception as error:
            status["desks"][desk] = {"state": "failed", "error": str(error)}
            _write_json(status_path, status)
            raise
        _write_json(status_path, status)
    return status
