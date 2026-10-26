"""Five desks, resumable job state, and a publication decision contract."""

from __future__ import annotations

import gzip
import hashlib
import json
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
BATCH_SIZE = 8
MAX_BATCH_CHARS = 20_000
ARTICLE_LIMIT = 3200
EDITOR_PROMPT = "You are a newsroom editor. For each story, decide news or junk; main AI subject, event type, importance (top/notable/standard), event date, claims supported by the readable source, and coverage IDs about the same event. Never use source_count as proof. Return each {id, news:boolean, reason:string, subject:string, event_type:string, importance:string, event_at:string|null, claims:[string], same_event_coverage_ids:[string]}. Reject advertising, customer case studies, evergreen tutorials, social chatter without a reported event, incidental AI, and stale resurfacing. A product announcement on a vendor blog can be news."
REPORTER_PROMPT = "You are a reporter. Read each public article excerpt. If the representative article is unreadable, choose at most one readable candidate from a different publisher about the exact same event, or null. A 403 is not evidence of paywall. Never bypass robots, sign in, or infer facts from source_count. Return each {id, selected_url:string|null, same_event:boolean, reason:string}."
CHECKER_PROMPT = "You are an independent fact checker. Compare the original title and every editor claim with the selected source excerpt. Reject unsupported entities, dates, figures and wrong-event sources. Return each {id, verified:boolean, reason:string, supported_claims:[string]}."


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


def _batches(rows):
    batch, chars = [], 0
    for row in rows:
        size = len(json.dumps(row, ensure_ascii=False))
        if batch and (len(batch) >= BATCH_SIZE or chars + size > MAX_BATCH_CHARS):
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
    for batch in _batches(payload):
        failures = []
        for provider in candidates:
            try:
                result = runner.run(desk, batch, provider, instruction)
                for row in result.rows:
                    output[row["id"]] = {**row, "provider": provider["id"], "boat": provider.get("boat")}
                batches.append({"provider": provider["id"], **result.usage})
                break
            except AdmissionError:
                raise
            except RunnerError as error:
                failures.append(f"{provider['id']}: {error}")
        else:
            raise RunnerError("; ".join(failures))
    return output, batches


def _reporter(stories, intake, articles, tools, discovery, runner, corpus):
    readers = providers("doc-bai", tools, discovery)
    searchers = providers("tim-kiem", tools, discovery)
    if not any(tool.get("runner") == "http-fetch" for tool in readers):
        raise RunnerError("no configured local article reader")
    can_search_hn = any(tool.get("runner") == "hn-algolia" for tool in searchers)
    payload, source_map = [], {}
    for story in stories:
        if not intake[story["id"]]["pass"]:
            continue
        text, reason = articles.read(story["url"])
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
        payload.append({"id": story["id"], "title": story["title"], "published_at": story.get("published_at"),
                        "representative_url": story["url"], "representative_status": "readable" if text else reason,
                        "candidates": candidates})
    replies, usage = _agent_desk("reporter", payload, REPORTER_PROMPT, "doc-bai", tools, discovery, runner) if payload else ({}, [])
    output = {}
    for story in stories:
        row = replies.get(story["id"])
        url = row.get("selected_url") if row else None
        candidate = source_map.get(story["id"], {}).get(url)
        valid = bool(candidate and row.get("same_event") is True and (url == story["url"] or candidate["publisher"] != _publisher(story["url"])))
        reason = (_reason(row.get("reason"), "source selected") if valid else
                  _reason(row.get("reason"), "no readable same-event source") if row and not url else
                  "selected source is unreadable, wrong-event, or not independent" if row else "intake hold")
        output[story["id"]] = {"id": story["id"], "readable": valid, "selected_url": url if valid else None,
                               "source_text": candidate["text"] if valid else "",
                               "reason": reason,
                               "representative_status": next((p["representative_status"] for p in payload if p["id"] == story["id"]), "not_checked"),
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _editor(stories, intake, reporter, tools, discovery, runner):
    payload = []
    for story in stories:
        if not intake[story["id"]]["pass"] or not reporter[story["id"]]["readable"]:
            continue
        inputs = story_inputs(story)
        payload.append({"id": story["id"], "title": inputs["title"], "summary": inputs["summary"],
                        "published_at": inputs["published_at"], "coverage": [{"id": c.get("id"), "title": c.get("title"), "url": c.get("url"), "published_at": c.get("published_at")} for c in story.get("coverage") or [] if isinstance(c, dict)],
                        "source_url": reporter[story["id"]]["selected_url"], "source_text": reporter[story["id"]]["source_text"]})
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
                     and isinstance(row.get("event_type"), str) and row["event_type"].strip())
        if not valid:
            same = []
        representative_ids = {c["id"] for c in story.get("coverage") or [] if isinstance(c, dict) and isinstance(c.get("id"), str)
                              and _same_rep_url(c.get("url"), story.get("url"))}
        same = sorted(set(same) | representative_ids)
        output[story["id"]] = {"id": story["id"], "news": valid and row.get("news") is True if row else False,
                               "reason": _reason(row.get("reason"), "invalid editorial response") if valid else "invalid editorial response" if row else "earlier desk hold",
                               "subject": row.get("subject") if row else None, "event_type": row.get("event_type") if row else None,
                               "importance": row.get("importance", "standard") if row else "standard",
                               "event_at": row.get("event_at") if row else None,
                               "claims": row.get("claims", []) if valid else [],
                               "same_event_coverage_ids": same,
                               "split_coverage_ids": sorted(coverage_ids - set(same)),
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _checker(stories, intake, reporter, editor, tools, discovery, runner):
    payload_by_boat = {}
    for story in stories:
        if editor[story["id"]]["news"]:
            payload_by_boat.setdefault(editor[story["id"]]["boat"], []).append(
                {"id": story["id"], "title": story["title"], "claims": editor[story["id"]]["claims"],
                 "source_url": reporter[story["id"]]["selected_url"], "source_text": reporter[story["id"]]["source_text"]})
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
        numeric_error = any(number_error(text, evidence) for text in [story["title"], *(c for c in claims if isinstance(c, str))]) if evidence else None
        valid = bool(row and row.get("verified") is True and row.get("boat") != editor[story["id"]]["boat"]
                     and not numeric_error and isinstance(row.get("supported_claims"), list)
                     and set(row["supported_claims"]) == set(c for c in claims if isinstance(c, str)))
        reason = ("unsupported number or amount" if numeric_error else
                  _reason(row.get("reason"), "verified") if valid else
                  _reason(row.get("reason"), "checker rejected evidence") if row and row.get("verified") is False else
                  "checker output did not independently verify all claims" if row else "earlier desk hold")
        output[story["id"]] = {"id": story["id"], "verified": valid,
                               "reason": reason,
                               "provider": row.get("provider") if row else None, "boat": row.get("boat") if row else None}
    return output, usage


def _chief(stories, intake, reporter, editor, checker, now):
    output = []
    for story in stories:
        sid = story["id"]
        gate = next(((desk, item["reason"]) for desk, item, key in (("intake", intake[sid], "pass"),
                    ("reporter", reporter[sid], "readable"), ("editor", editor[sid], "news"),
                    ("checker", checker[sid], "verified")) if not item[key]), None)
        tier = editor[sid]["importance"] if editor[sid]["importance"] in {"top", "notable", "standard"} else "standard"
        original_at = instant(story.get("published_at"))
        proposed_at = instant(editor[sid]["event_at"])
        event_at = min(original_at, proposed_at) if original_at and proposed_at else original_at
        if tier in {"top", "notable"} and (not proposed_at or not event_at or event_at < now - timedelta(days=7)):
            tier = "standard"
        if tier == "top" and not 4 <= len(editor[sid]["claims"]) <= 8:
            tier = "standard"
        output.append({"id": sid, "decision": "hold" if gate else "publish",
                       "round": gate[0] if gate else "chief", "reason": gate[1] if gate else "readable source and independent check passed",
                       "importance_tier": tier, "source_url": reporter[sid]["selected_url"],
                       "key_points": editor[sid]["claims"] if not gate else [],
                       "same_event_coverage_ids": editor[sid]["same_event_coverage_ids"],
                       "split_coverage_ids": editor[sid]["split_coverage_ids"]})
    return output


def run(input_path, job, tools, discovery, runner, *, through="chief", articles=None, corpus_path=None):
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
