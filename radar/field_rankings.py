"""Daily topic catalogue and measured rolling-window net star rankings."""

from copy import deepcopy
from datetime import timedelta

from radar.common import clean_text, iso_date
from radar.field_api import APIError, MAX_CALLS, MAX_CORE_CALLS, MAX_SEARCH_CALLS
from radar.field_config import (CLASSIFIER_VERSION, FIELDS, FIELD_LIMIT, MIN_RANKED, MIN_STARS,
                               RETENTION_DAYS, classify, configuration_fingerprint, license_eligible)
from radar.items import instant

WINDOW_SECONDS = 7 * 86400
TOLERANCE_SECONDS = 3 * 3600


def empty_state():
    return dict(schema_version=1, snapshots={}, catalogue={}, first_seen={}, last_output=None)


def measurement(repo_id, stars, observed_at, state):
    now = instant(observed_at)
    candidates = []
    for snapshot in state["snapshots"].values():
        point = snapshot.get(str(repo_id))
        if point:
            elapsed = (now - instant(point["observed_at"])).total_seconds()
            if abs(elapsed - WINDOW_SECONDS) <= TOLERANCE_SECONDS:
                candidates.append((abs(elapsed - WINDOW_SECONDS), point["observed_at"], point, elapsed))
    result = dict(stars_net_7d=None, window_start=None, window_end=observed_at,
                  window_seconds=None, method=None, approximate=False)
    if candidates:
        _, start, point, elapsed = min(candidates, key=lambda item: item[:2])
        result.update(stars_net_7d=stars - point["stars"], window_start=start,
                      window_seconds=int(elapsed), method="snapshot_net", approximate=elapsed != WINDOW_SECONDS)
    return result


def public_row(repo, state, now, native):
    identity = str(repo["id"])
    since = state["first_seen"].get(identity, iso_date(now))
    licence = repo.get("license")
    spdx = licence.get("spdx_id") if isinstance(licence, dict) else None
    return dict(repository_id=repo["id"], full_name=repo["full_name"],
                url="https://github.com/" + repo["full_name"], description=clean_text(repo.get("description"), 1000),
                topics=repo["topics"], stars=repo["stargazers_count"], observed_at=iso_date(now), tracking_since=since,
                license_spdx=spdx if isinstance(spdx, str) else None, license_status="publisher_declared" if spdx and spdx != "NOASSERTION" else "unknown",
                open_source_verified=False, native_history=native,
                **measurement(repo["id"], repo["stargazers_count"], iso_date(now), state))


def search_groups(topics, cutoff):
    """One query per topic; GitHub search rejects OR across topic qualifiers."""
    suffix = f" pushed:>={cutoff[:10]} stars:>={MIN_STARS} archived:false fork:false"
    for topic in topics:
        yield [topic], f"topic:{topic}{suffix}"


def collect(api, now, state=None):
    """Bounded catalogue; successful daily samples survive partial-source retries."""
    state = deepcopy(state) if state is not None else empty_state()
    previous = state.get("last_output")
    fingerprint = configuration_fingerprint()
    if previous:
        age = (now - instant(previous["generated_at"])).total_seconds()
        same_day = previous["generated_at"][:10] == iso_date(now)[:10]
        if (previous.get("config_fingerprint") == fingerprint and 0 <= age and same_day
                and (previous["complete"] or age < 6 * 3600)):
            return deepcopy(previous), state
    discovered, diagnostics, successes, refresh_diagnostics = {}, {}, {}, {}
    cutoff = iso_date(now - timedelta(days=30))
    for field, _, topics, _ in FIELDS:
        diagnostics[field], successes[field] = [], 0
        for group, query in search_groups(topics, cutoff):
            diagnostic = dict(topic=",".join(group), topics=group, count_scope="query_group", status="ok", total_count=None, truncated=False,
                              excluded_license=0, excluded_gate_or_evidence=0)
            try:
                if sum(len(items) for items in diagnostics.values()) >= MAX_SEARCH_CALLS:
                    raise APIError("budget_exhausted")
                result = api.get("/search/repositories", q=query, sort="stars", order="desc", per_page=100, page=1)
                if (not isinstance(result, dict) or not isinstance(result.get("items"), list)
                        or type(result.get("total_count")) is not int or result["total_count"] < 0
                        or type(result.get("incomplete_results")) is not bool or len(result["items"]) > 100):
                    raise APIError("unknown_schema")
                diagnostic.update(total_count=result["total_count"],
                                  truncated=result["total_count"] > len(result["items"]),
                                  status="incomplete" if result["incomplete_results"] else "ok")
                successes[field] += 1
                for repo in result["items"]:
                    if classify(repo, now):
                        discovered[str(repo["id"])] = repo
                    elif not license_eligible(repo):
                        diagnostic["excluded_license"] += 1
                    else:
                        diagnostic["excluded_gate_or_evidence"] += 1
            except APIError as error:
                diagnostic.update(status=str(error), http_status=error.status)
            diagnostics[field].append(diagnostic)
    # Numeric IDs survive renames; refresh the existing bounded catalogue even if Search loses it.
    # Oldest attempted IDs go first, so the bounded refresh budget cannot freeze
    # one prefix forever. Deferred IDs remain explicit failures and retry in 6h.
    refresh_order = sorted(state["catalogue"], key=lambda key: (state["catalogue"][key].get("last_refresh_attempt", ""), int(key)))
    refreshed = 0
    for identity in refresh_order:
        old = state["catalogue"][identity]
        if identity in discovered:
            continue
        try:
            if refreshed >= MAX_CORE_CALLS:
                raise APIError("refresh_deferred")
            refreshed += 1
            old["last_refresh_attempt"] = iso_date(now)
            repo = api.get(f"/repositories/{identity}")
            if not isinstance(repo, dict) or str(repo.get("id")) != identity:
                raise APIError("unknown_schema")
            refresh_diagnostics[identity] = dict(status="ok", full_name=old["full_name"])
            if classify(repo, now):
                discovered[identity] = repo
        except APIError as error:
            refresh_diagnostics[identity] = dict(status=str(error), http_status=error.status, full_name=old["full_name"])
    membership = {identity: classify(repo, now) for identity, repo in discovered.items()}
    selected, counts = {}, {}
    for field, *_ in FIELDS:
        eligible = [key for key, matches in membership.items() if field in matches]
        counts[field] = len(eligible)
        # Everyone competes under the same rule; incumbency is not a membership gate.
        eligible.sort(key=lambda key: (-discovered[key]["stargazers_count"], int(key)))
        selected[field] = eligible[:FIELD_LIMIT]
    identities = sorted({identity for group in selected.values() for identity in group}, key=int)
    rows, catalogue = {}, deepcopy(state["catalogue"])
    for identity in identities:
        repo = discovered[identity]
        row = public_row(repo, state, now, dict(status="not_requested", usable_for_net=False))
        rows[identity] = row
        state["first_seen"].setdefault(identity, row["tracking_since"])
        catalogue[identity] = dict(tracking_since=row["tracking_since"], full_name=repo["full_name"], last_refresh_attempt=iso_date(now))
    fields = []
    old_fields = {f["id"]: f for f in previous["fields"]} if previous else {}
    for field, name, topics, _ in FIELDS:
        selected_rows = [dict(rows[key], **membership[key][field]) for key in selected[field]]
        ranked = sorted((r for r in selected_rows if r["stars_net_7d"] is not None),
                        key=lambda r: (-r["stars_net_7d"], -r["stars"], r["repository_id"]))
        tracking = sorted((r for r in selected_rows if r["stars_net_7d"] is None), key=lambda r: (-r["stars"], r["repository_id"]))
        old = old_fields.get(field, {})
        stale_rows = [dict(row, stale=True) for row in old.get("ranked", []) + old.get("tracking", [])
                      if str(row["repository_id"]) not in rows
                      and refresh_diagnostics.get(str(row["repository_id"]), {}).get("status", "ok") != "ok"][:FIELD_LIMIT]
        tracking += stale_rows
        failed = bool(stale_rows) or any(d["status"] != "ok" for d in diagnostics[field])
        thin = 0 < len(ranked) < MIN_RANKED
        status = "partial" if failed or thin else "ready" if ranked else "tracking" if tracking else "empty"
        stale = (not successes[field] or bool(stale_rows)) and not selected_rows
        if stale and field in old_fields:
            tracking = stale_rows
            status = "stale"
        elif stale:
            status = "unavailable"
        fields.append(dict(id=field, name=name, topics=list(topics), status=status, diagnostics=diagnostics[field],
                           status_reason="source_incomplete" if failed else "insufficient_ranked_rows" if thin else None,
                           ranked=ranked, tracking=tracking, candidate_count=counts[field], cap=FIELD_LIMIT,
                           truncated=counts[field] > FIELD_LIMIT or any(d["truncated"] for d in diagnostics[field]),
                           observed_at=iso_date(now) if not stale else old_fields.get(field, {}).get("observed_at")))
    output = dict(schema_version=1, generated_at=iso_date(now), stale_after_seconds=129600, metric="stars_net_7d",
                  classifier_version=CLASSIFIER_VERSION, config_fingerprint=fingerprint,
                  complete=all(d["status"] == "ok" for group in diagnostics.values() for d in group)
                  and all(d["status"] == "ok" for d in refresh_diagnostics.values()),
                  scope="bounded_topic_catalogue", fields=fields, requests=api.requests, refresh_diagnostics=refresh_diagnostics,
                  limits=dict(min_stars=MIN_STARS, pushed_days=30, candidates_per_field=FIELD_LIMIT,
                              search_page_size=100, minimum_ranked=MIN_RANKED, max_search_calls=MAX_SEARCH_CALLS,
                              max_refresh_calls=MAX_CORE_CALLS, max_calls=MAX_CALLS, deadline_seconds=210,
                              history_tolerance_seconds=TOLERANCE_SECONDS))
    date = iso_date(now)[:10]
    snapshot = state["snapshots"].setdefault(date, {})
    # Save admitted discovery counters even outside the visible top 20. A future
    # entrant then has observed history rather than an invented initial baseline.
    for identity, repo in discovered.items():
        snapshot.setdefault(identity, dict(stars=repo["stargazers_count"], observed_at=iso_date(now)))
        state["first_seen"].setdefault(identity, iso_date(now))
    oldest = (now.date() - timedelta(days=RETENTION_DAYS - 1)).isoformat()
    state["snapshots"] = {day: value for day, value in state["snapshots"].items() if day >= oldest}
    # Keep unavailable members to retry next run, without letting unbounded new cohorts accumulate.
    kept = identities + [key for key in catalogue if key not in identities]
    state.update(catalogue={key: catalogue[key] for key in kept[:len(FIELDS) * FIELD_LIMIT]}, last_output=output)
    return output, state
