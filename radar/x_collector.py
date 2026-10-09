"""Official, read-only X search helpers for AI-related public posts."""

import json
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError

from radar.common import clean_text
from radar.items import observation, relevant

API_URL = "https://api.x.com/2/tweets/search/recent"
MAX_RESULTS = 10
AI_QUERY = '(AI OR LLM OR GPT OR "artificial intelligence" OR "machine learning" OR '
AI_QUERY += 'Claude OR Gemini OR DeepSeek OR Qwen OR Llama OR agentic)'
ACCOUNT_ROLES = {"leader", "product", "official", "researcher", "analyst", "leaderboard", "early-signal"}


def groups(accounts, size=10):
    """Return deterministic account chunks small enough for recent search."""
    if type(size) is not int or size < 1:
        raise ValueError("Account group size must be positive")
    ordered = sorted(accounts, key=lambda account: account["handle"].casefold())
    return [ordered[index:index + size] for index in range(0, len(ordered), size)]


def load_accounts(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("X account roster is unavailable or invalid") from error
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("accounts"), list) or not data["accounts"]):
        raise ValueError("X account roster is unavailable or invalid")
    handles, ids = set(), set()
    for account in data["accounts"]:
        if (not isinstance(account, dict) or set(account) != {"id", "handle", "name", "role"}
                or not isinstance(account["id"], str) or not re.fullmatch(r"[0-9]{1,20}", account["id"])
                or not isinstance(account["handle"], str) or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", account["handle"])
                or not isinstance(account["name"], str) or not clean_text(account["name"], 120)
                or not isinstance(account["role"], str) or account["role"] not in ACCOUNT_ROLES):
            raise ValueError("X account roster is unavailable or invalid")
        if account["id"] in ids or account["handle"].casefold() in handles:
            raise ValueError("X account roster is unavailable or invalid")
        ids.add(account["id"])
        handles.add(account["handle"].casefold())
    return data["accounts"]


def build_query(accounts):
    handles = [account["handle"] for account in accounts]
    if not handles or any(not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle) for handle in handles):
        raise ValueError("Invalid X account group")
    query = "(" + " OR ".join("from:" + handle for handle in handles) + ") " + AI_QUERY + " -is:retweet"
    if len(query) > 512:
        raise ValueError("X recent-search query exceeds 512 characters")
    return query


def search_url(accounts, *, since_id=None, pagination_token=None):
    params = {"query": build_query(accounts), "max_results": MAX_RESULTS,
              "tweet.fields": "author_id,created_at,id,text"}
    if since_id:
        params["since_id"] = since_id
    if pagination_token:
        params["pagination_token"] = pagination_token
    return API_URL + "?" + urlencode(params)


def parse_search(text, accounts, observed_at):
    """Parse a fixture or API response without user expansions or extra reads."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid X search JSON") from error
    if not isinstance(data, dict) or not isinstance(data.get("data", []), list):
        raise ValueError("Expected X search response with a data list")
    by_id = {str(account.get("id")): account for account in accounts if account.get("id")}
    items = []
    for post in data.get("data", []):
        if not isinstance(post, dict):
            continue
        account = by_id.get(str(post.get("author_id")))
        post_id, body = post.get("id"), post.get("text")
        if not account or not isinstance(post_id, str) or not re.fullmatch(r"[0-9]{1,19}", post_id):
            continue
        title = clean_text(body, 500)
        if not title or not relevant(title):
            continue
        handle = account["handle"]
        source = {"id": "x-" + handle.casefold(), "publisher": "x:@" + handle,
                  "group": "forum", "kind": "json"}
        item = observation(source, title, f"https://x.com/{handle}/status/{post_id}",
                           post.get("created_at"), observed_at, kind="social", summary=title,
                           author_handle=handle, author_name=clean_text(account.get("name"), 120),
                           author_id=str(account["id"]))
        if item:
            items.append(item)
    return items


def response_state(text):
    """Return response ids and the next page cursor without retaining post text."""
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("data", []), list):
        raise ValueError("Expected X search response with a data list")
    ids = [post["id"] for post in data.get("data", [])
           if isinstance(post, dict) and isinstance(post.get("id"), str)
           and re.fullmatch(r"[0-9]{1,19}", post["id"])]
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    token = meta.get("next_token")
    return (max(ids, key=int) if ids else None,
            token if isinstance(token, str) and token else None)


def _response_count(text):
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("data", []), list):
        raise ValueError("Expected X search response with a data list")
    return len(data.get("data", []))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(url, token):
    request = Request(url, headers={"Authorization": "Bearer " + token,
                                    "Accept": "application/json",
                                    "User-Agent": "AI-Radar/1.0"})
    with build_opener(_NoRedirect()).open(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError("X API returned an unexpected HTTP status")
        raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("X API response exceeded the 8 MiB limit")
        return raw.decode("utf-8")


def _post_ids(stories):
    ids = set()
    for story in stories if isinstance(stories, list) else []:
        for item in story.get("coverage", []) if isinstance(story, dict) else []:
            match = re.search(r"https?://(?:www\.)?x\.com/[^/]+/status/([0-9]{1,19})", item.get("url", "")) \
                if isinstance(item, dict) else None
            if match:
                ids.add(match.group(1))
    return sorted(ids, key=int)


def _reconciliation_url(ids):
    if not ids or len(ids) > 100 or any(not re.fullmatch(r"[0-9]{1,19}", value) for value in ids):
        raise ValueError("Invalid X reconciliation batch")
    return "https://api.x.com/2/tweets?" + urlencode({"ids": ",".join(ids), "tweet.fields": "id"})


def _returned_ids(body):
    try:
        data = json.loads(body)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid X reconciliation response") from error
    if not isinstance(data, dict) or not isinstance(data.get("data", []), list):
        raise ValueError("Invalid X reconciliation response")
    ids = []
    for post in data.get("data", []):
        if (not isinstance(post, dict) or not isinstance(post.get("id"), str)
                or not re.fullmatch(r"[0-9]{1,19}", post["id"])):
            raise ValueError("Invalid X reconciliation resource")
        ids.append(post["id"])
    return ids


def reconcile_published(stories, published, ledger_path, *, now, transport=None, env=None):
    """Reconcile published X IDs daily; on failure, expire X observations older than 24h."""
    from datetime import timezone
    from radar import x_paid_budget
    from radar.items import instant

    env = os.environ if env is None else env
    today = now.astimezone(timezone.utc).date().isoformat()
    local = x_paid_budget._read_local(ledger_path, now.timestamp())
    due = local is None or local.get("reconciled_day") != today
    published_stories = published.get("stories", []) if isinstance(published, dict) else []
    ids = _post_ids(published_stories)
    returned = set()
    success = local is not None and not due
    if due and env.get("RADAR_X_ENABLED") == "1" and env.get("X_BEARER_TOKEN"):
        success = True
        send = transport or _request
        try:
            for start in range(0, len(ids), 100):
                batch = ids[start:start + 100]
                error, request_id = x_paid_budget.reserve(ledger_path, now=now.timestamp(),
                                                          max_results=max(10, len(batch)))
                if error:
                    success = False
                    break
                body = send(_reconciliation_url(batch), env["X_BEARER_TOKEN"])
                found_ids = _returned_ids(body)
                if len(found_ids) > len(batch) or any(post_id not in batch for post_id in found_ids):
                    success = False
                    break
                if x_paid_budget.settle(ledger_path, request_id, len(found_ids), now=now.timestamp()):
                    success = False
                    break
                returned.update(found_ids)
            if success:
                x_paid_budget.mark_reconciled(ledger_path, today, now=now.timestamp())
        except (HTTPError, OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            success = False

    cutoff = now.timestamp() - 86400
    for story in stories if isinstance(stories, list) else []:
        kept = []
        for item in story.get("coverage", []) if isinstance(story, dict) else []:
            match = re.search(r"https?://(?:www\.)?x\.com/[^/]+/status/([0-9]{1,19})", item.get("url", "")) \
                if isinstance(item, dict) else None
            if not match:
                kept.append(item)
                continue
            post_id = match.group(1)
            if success and not due:
                kept.append(item)
                continue
            if success and due:
                # Reconcile only items that were in the published snapshot and
                # actually included in a successful lookup. New current-run X
                # items were not queried and must survive this pass.
                if post_id in ids and post_id not in returned:
                    continue
            elif instant(item.get("published_at") or item.get("observed_at")) is None or \
                    instant(item.get("published_at") or item.get("observed_at")).timestamp() < cutoff:
                continue
            kept.append(item)
        if isinstance(story, dict):
            story["coverage"] = kept
    return [story for story in stories if not isinstance(story, dict) or story.get("coverage")] if isinstance(stories, list) else stories


def _group_id(accounts):
    handles = ",".join(account["handle"].casefold() for account in accounts)
    return hashlib.sha256(handles.encode("utf-8")).hexdigest()[:16]


def collect(accounts, ledger_path, *, now, transport=None, env=None):
    """Collect one bounded, server-filtered page per account group with no retries."""
    env = os.environ if env is None else env
    from radar import x_paid_budget
    enabled = env.get("RADAR_X_ENABLED") == "1"
    if not enabled or not env.get("X_BEARER_TOKEN"):
        reason = "X collection disabled" if not enabled else "X bearer token unavailable"
        return [], [_disabled_result(_source(account), reason) for account in accounts]
    ledger = x_paid_budget._read_local(ledger_path, now.timestamp())
    if ledger is None or ledger.get("run_key") is None:
        reason = x_paid_budget.MISSING_CODE
        records = [_disabled_result(_source(account), reason) for account in accounts]
        records.append(_disabled_result({"id": "x-collector", "name": "X", "url": API_URL,
                                         "kind": "json", "group": "forum", "publisher": "x", "lab": ""}, reason))
        return [], records
    items, successes, failures = [], {}, {}
    send = transport or _request
    for chunk in groups(accounts):
        identity = _group_id(chunk)
        cursor = ledger["cursors"].get(identity, {})
        url = search_url(chunk, since_id=cursor.get("since_id"),
                         pagination_token=cursor.get("next_token"))
        try:
            error, request_id = x_paid_budget.reserve(ledger_path, now=now.timestamp(), max_results=MAX_RESULTS)
        except (OSError, ValueError, TypeError) as reserve_error:
            error = f"X ledger unavailable: {type(reserve_error).__name__}"
            request_id = None
        if error:
            for account in chunk:
                failures[account["handle"].casefold()] = error
            break
        try:
            body = send(url, env["X_BEARER_TOKEN"])
            response_count = _response_count(body)
            parsed = parse_search(body, chunk, now)
            newest, next_token = response_state(body)
            settle_error = x_paid_budget.settle(ledger_path, request_id, response_count, now=now.timestamp())
            if settle_error:
                raise ValueError(settle_error)
            if next_token:
                # Continue the identical query until the page token is exhausted.
                next_since = cursor.get("since_id")
            else:
                next_since = newest or cursor.get("since_id")
            cursor_error = x_paid_budget.update_cursor(ledger_path, identity, next_since,
                                                       next_token, now=now.timestamp())
            if cursor_error:
                raise ValueError(cursor_error)
            items.extend(parsed)
            for account in chunk:
                source = _source(account)
                count = sum(item["source"] == source["id"] for item in parsed)
                successes[account["handle"].casefold()] = _source_result(source, count)
        except HTTPError as error:
            # Leave the maximum reservation in place when a response is ambiguous.
            for account in chunk:
                failures[account["handle"].casefold()] = f"X API HTTP {error.code}"
        except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            # Never include the request URL, token, or provider body in diagnostics.
            for account in chunk:
                failures[account["handle"].casefold()] = f"X collection failed: {type(error).__name__}"
    records = []
    for account in accounts:
        key = account["handle"].casefold()
        records.append(successes.get(key) or _disabled_result(
            _source(account), failures.get(key, "X collection not attempted")))
    if failures:
        reason = next(iter(failures.values()))
        records.append(_disabled_result({"id": "x-collector", "name": "X", "url": API_URL,
                                         "kind": "json", "group": "forum", "publisher": "x", "lab": ""}, reason))
    return items, records


def _source(account):
    handle = account["handle"]
    return {"id": "x-" + handle.casefold(),
            "name": f"{clean_text(account.get('name'), 120)} (@{handle})",
            "url": "https://x.com/" + handle, "kind": "json", "group": "forum",
            "publisher": "x:@" + handle, "lab": ""}


def _source_result(source, count=0, error=None):
    from radar.common import source_result
    return source_result(source, count, error) | {
        key: source[key] for key in ("url", "group", "publisher", "first_wave") if key in source
    }


def _disabled_result(source, reason):
    record = _source_result(source, error="Disabled: " + reason)
    record.update(disabled=True, disabled_reason=reason)
    return record
