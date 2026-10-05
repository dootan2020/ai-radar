"""Source scorecard analysis: measuring earliness, pipeline lag, quality, and reliability across snapshot history."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
from collections import Counter, defaultdict

from radar.items import relevant


def parse_iso_datetime(value):
    """Safely parse an ISO-8601 string or datetime into UTC datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def is_date_only(p_str, p_dt):
    """Check if a timestamp is date-only (midnight UTC 00:00:00 without specific time)."""
    if not p_str or not p_dt:
        return False
    if "T00:00:00" in p_str or p_str.endswith("00:00:00Z") or len(p_str) <= 10:
        return True
    return p_dt.hour == 0 and p_dt.minute == 0 and p_dt.second == 0 and p_dt.microsecond == 0


def categorize_error(error_str, http_status=None, is_disabled=False, disabled_reason=None):
    """Categorize raw error strings, HTTP status, and disabled flags into standardized error kinds."""
    if is_disabled:
        reason = str(disabled_reason or error_str or "")
        r_low = reason.lower()
        if "substack" in r_low or ("403" in r_low and "substack" in r_low):
            return "Disabled (Substack 403)"
        if "cnbc" in r_low or ("403" in r_low and "cnbc" in r_low):
            return "Disabled (CNBC 403)"
        if "xml" in r_low or "parse" in r_low:
            return "Disabled (Invalid XML)"
        if "403" in r_low:
            return "Disabled (HTTP 403)"
        return "Disabled"

    if not error_str and http_status is None:
        return "None"
    err = str(error_str or "")
    if "Disabled:" in err:
        err_low = err.lower()
        if "substack" in err_low:
            return "Disabled (Substack 403)"
        if "cnbc" in err_low:
            return "Disabled (CNBC 403)"
        if "xml" in err_low or "parse" in err_low:
            return "Disabled (Invalid XML)"
        return "Disabled"
    if http_status == 404 or "404" in err:
        return "HTTP 404 (Address Changed)"
    if http_status == 403 or "403" in err:
        return "HTTP 403"
    if http_status == 429 or "429" in err:
        return "HTTP 429"
    if http_status == 500 or "500" in err:
        return "HTTP 500"
    if http_status == 502 or "502" in err:
        return "HTTP 502"
    if http_status == 503 or "503" in err:
        return "HTTP 503"
    if "timeout" in err.lower() or "deadline" in err.lower():
        return "Timeout / Deadline"
    if any(k in err.lower() for k in ("xml", "parse", "received another document")):
        return "Parse Error"
    if ":" in err:
        return err.split(":", 1)[0].strip()
    return err[:30].strip() or "Unknown Error"


def discover_snapshots(snapshots_dir):
    """Discover all snapshot directories containing radar.json, sorted chronologically."""
    root = Path(snapshots_dir)
    if not root.exists():
        raise FileNotFoundError(f"Snapshots directory does not exist: {snapshots_dir}")

    candidates = []
    for item in root.iterdir():
        if item.is_dir():
            radar_file = item / "radar.json"
            if radar_file.exists():
                candidates.append((item.name, radar_file))

    # Sort chronologically by snapshot name (YYYY-MM-DDTHHMMSSZ)
    candidates.sort(key=lambda x: x[0])

    snapshots = []
    for name, path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            gen_at = parse_iso_datetime(data.get("generated_at"))
            snapshots.append({
                "name": name,
                "path": str(path),
                "generated_at": gen_at,
                "data": data
            })
        except Exception:
            continue

    snapshots.sort(key=lambda s: s["generated_at"] or datetime.min.replace(tzinfo=timezone.utc))
    return snapshots


def find_duplicate_feeds(source_items):
    """Find pairs of feeds that duplicate each other (same publisher or mirror feed)."""
    source_item_urls = defaultdict(set)
    source_publishers = {}

    for (src, url), it in source_items.items():
        source_item_urls[src].add(url)
        if it.get("publisher"):
            source_publishers[src] = it.get("publisher")

    duplicates = []
    sources = sorted(source_item_urls.keys())
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            s1 = sources[i]
            s2 = sources[j]
            p1 = source_publishers.get(s1)
            p2 = source_publishers.get(s2)
            if p1 and p2 and p1 == p2:
                common = source_item_urls[s1] & source_item_urls[s2]
                if common:
                    duplicates.append({
                        "source_1": s1,
                        "source_2": s2,
                        "publisher_1": p1,
                        "publisher_2": p2,
                        "shared_items_count": len(common),
                        "s1_total": len(source_item_urls[s1]),
                        "s2_total": len(source_item_urls[s2])
                    })

    duplicates.sort(key=lambda d: -d["shared_items_count"])
    return duplicates


def analyze_snapshots(snapshots):
    """Process loaded snapshots and compute all 4 scorecard dimensions for each source."""
    if not snapshots:
        return {
            "summary": {"snapshots_count": 0},
            "sources": {}
        }

    first_snap_dt = snapshots[0]["generated_at"]

    source_records = defaultdict(lambda: {
        "id": "",
        "name": "",
        "group": "",
        "publisher": "",
        "runs_total": 0,
        "runs_failed": 0,
        "error_kinds": Counter(),
        "http_statuses": Counter(),
        "is_disabled": False,
        "disabled_reason": None
    })

    source_items = {}   # (source_id, url) -> item_dict
    story_clusters = {} # story_id -> {id, title, published_at, coverage: {item_id: item}}

    for snap_idx, snap in enumerate(snapshots):
        snap_dt = snap["generated_at"]
        data = snap["data"]

        # 1. Process sources
        for s in data.get("sources", []):
            sid = s.get("id")
            if not sid:
                continue
            rec = source_records[sid]
            rec["id"] = sid
            if not rec["name"] and s.get("name"):
                rec["name"] = s.get("name")
            if not rec["group"] and s.get("group"):
                rec["group"] = s.get("group")
            if not rec["publisher"] and s.get("publisher"):
                rec["publisher"] = s.get("publisher")

            rec["runs_total"] += 1
            is_ok = bool(s.get("ok", False))
            if s.get("disabled"):
                rec["is_disabled"] = True
                rec["disabled_reason"] = s.get("disabled_reason")

            if not is_ok:
                rec["runs_failed"] += 1
                kind = categorize_error(
                    s.get("error"),
                    s.get("http_status"),
                    is_disabled=rec["is_disabled"],
                    disabled_reason=rec["disabled_reason"]
                )
                rec["error_kinds"][kind] += 1

            if s.get("http_status") is not None:
                rec["http_statuses"][str(s.get("http_status"))] += 1

        # 2. Process stories & coverage items
        for story in data.get("stories", []):
            sid = story.get("id")
            if not sid:
                continue
            if sid not in story_clusters:
                story_clusters[sid] = {
                    "id": sid,
                    "title": story.get("title", ""),
                    "published_at": story.get("published_at"),
                    "coverage": {}
                }

            for item in story.get("coverage", []):
                item_url = item.get("canonical_url") or item.get("url")
                if not item_url:
                    continue
                item_id = item.get("id") or item_url

                src = item.get("source")
                if src:
                    key = (src, item_url)
                    if key not in source_items:
                        p_str = item.get("published_at")
                        p_dt = parse_iso_datetime(p_str)
                        source_items[key] = {
                            "url": item_url,
                            "id": item_id,
                            "source": src,
                            "publisher": item.get("publisher"),
                            "group": item.get("group"),
                            "title": item.get("title", ""),
                            "summary": item.get("summary", ""),
                            "published_at": p_str,
                            "p_dt": p_dt,
                            "is_date_only": is_date_only(p_str, p_dt),
                            "first_seen_at": snap_dt,
                            "first_snap_idx": snap_idx,
                            "story_id": sid
                        }

                story_clusters[sid]["coverage"][item_id] = item

    # Group items by source
    items_by_source = defaultdict(list)
    for it in source_items.values():
        items_by_source[it["source"]].append(it)

    # 3. Multi-publisher Stories (Rule 2: Earliness counts only clusters with >= 2 distinct publishers)
    multi_publisher_stories = [
        s for s in story_clusters.values()
        if len({it.get("publisher") for it in s["coverage"].values() if it.get("publisher")}) > 1
    ]

    source_earliness = defaultdict(lambda: {
        "multi_count": 0,
        "first_count": 0,
        "lags_behind_hours": [],
        "date_only_items_count": 0
    })

    for s in multi_publisher_stories:
        coverage_items = list(s["coverage"].values())
        parsed_items = []
        for it in coverage_items:
            src = it.get("source")
            p_str = it.get("published_at")
            p_dt = parse_iso_datetime(p_str)
            if src and p_dt:
                parsed_items.append({
                    "source": src,
                    "dt": p_dt,
                    "date_only": is_date_only(p_str, p_dt)
                })

        if not parsed_items:
            continue

        # Story's overall earliest publication time
        t_first = min(it["dt"] for it in parsed_items)

        # For each distinct source in this story, get their earliest publication time
        source_earliest_in_story = {}
        for it in parsed_items:
            src = it["source"]
            if src not in source_earliest_in_story or it["dt"] < source_earliest_in_story[src]["dt"]:
                source_earliest_in_story[src] = it

        for src, s_info in source_earliest_in_story.items():
            edata = source_earliness[src]
            edata["multi_count"] += 1
            if s_info["date_only"]:
                edata["date_only_items_count"] += 1

            diff_seconds = (s_info["dt"] - t_first).total_seconds()
            if diff_seconds <= 60:
                edata["first_count"] += 1
            else:
                edata["lags_behind_hours"].append(diff_seconds / 3600.0)

    # Find duplicate feeds
    duplicate_feeds = find_duplicate_feeds(source_items)

    # 4. Synthesize per-source scorecard
    scorecard = {}
    all_source_ids = sorted(set(source_records.keys()) | set(items_by_source.keys()))

    for sid in all_source_ids:
        s_rec = source_records[sid]
        items = items_by_source.get(sid, [])

        # Reliability (Rule 4: Disabled vs Failing)
        runs_tot = s_rec["runs_total"]
        runs_fail = s_rec["runs_failed"]
        runs_ok = runs_tot - runs_fail
        fail_rate = (runs_fail / runs_tot) if runs_tot > 0 else 0.0

        if s_rec["is_disabled"]:
            tech_status = "DISABLED"
        elif runs_tot > 0 and runs_fail == runs_tot:
            tech_status = "FAILING"
        elif fail_rate > 0.05:
            tech_status = "UNSTABLE"
        else:
            tech_status = "HEALTHY"

        # Earliness (Rule 2)
        e_data = source_earliness[sid]
        multi_cnt = e_data["multi_count"]
        first_cnt = e_data["first_count"]
        first_rate = (first_cnt / multi_cnt) if multi_cnt > 0 else None
        lags_behind = e_data["lags_behind_hours"]
        med_lag_behind = statistics.median(lags_behind) if lags_behind else None
        mean_lag_behind = statistics.mean(lags_behind) if lags_behind else None
        thin_earliness = (multi_cnt < 5)

        # Pipeline Lag (Rule 1: items older than first snapshot excluded, must not be present in first snap)
        item_cnt = len(items)
        pipeline_lags = []
        for it in items:
            if it["first_snap_idx"] > 0 and it["p_dt"] and it["p_dt"] > first_snap_dt:
                lag_h = (it["first_seen_at"] - it["p_dt"]).total_seconds() / 3600.0
                pipeline_lags.append(lag_h)

        med_pipe_lag = statistics.median(pipeline_lags) if pipeline_lags else None
        min_pipe_lag = min(pipeline_lags) if pipeline_lags else None
        max_pipe_lag = max(pipeline_lags) if pipeline_lags else None
        thin_lag = (len(pipeline_lags) < 5)

        # Quality & Timestamp Breakdown (Rule 3: Separate missing, future, date-only; leave age out)
        ai_cnt = 0
        corrob_cnt = 0
        rewrite_cnt = 0
        missing_ts_cnt = 0
        future_ts_cnt = 0
        date_only_ts_cnt = 0
        archive_items_cnt = 0

        my_pub = s_rec.get("publisher") or sid

        for it in items:
            # AI relevance
            if relevant(it.get("title", ""), it.get("summary", "")):
                ai_cnt += 1

            p_str = it.get("published_at")
            p_dt = it.get("p_dt")
            seen_dt = it.get("first_seen_at")

            # Timestamp classification
            if not p_str or not p_dt:
                missing_ts_cnt += 1
            else:
                diff_hours = (seen_dt - p_dt).total_seconds() / 3600.0 if seen_dt else 0.0
                if diff_hours < -0.1:  # published in future relative to first seen
                    future_ts_cnt += 1
                elif it["is_date_only"]:
                    date_only_ts_cnt += 1
                elif diff_hours > 30 * 24:
                    archive_items_cnt += 1

            # Corroboration & Rewrites (only across independent publishers)
            sid_story = it.get("story_id")
            cluster = story_clusters.get(sid_story)
            if cluster and p_dt:
                cluster_pubs = {x.get("publisher") for x in cluster["coverage"].values() if x.get("publisher")}
                if len(cluster_pubs) > 1:
                    other_items = [
                        x for x in cluster["coverage"].values()
                        if x.get("publisher") and x.get("publisher") != my_pub
                    ]
                    is_corroborated = False
                    is_rewrite = False
                    for other in other_items:
                        op_dt = parse_iso_datetime(other.get("published_at"))
                        if op_dt:
                            if op_dt >= p_dt:
                                is_corroborated = True
                            if op_dt < p_dt:
                                is_rewrite = True
                    if is_corroborated:
                        corrob_cnt += 1
                    if is_rewrite:
                        rewrite_cnt += 1

        ai_share = (ai_cnt / item_cnt) if item_cnt > 0 else 0.0
        corrob_share = (corrob_cnt / item_cnt) if item_cnt > 0 else 0.0
        rewrite_share = (rewrite_cnt / item_cnt) if item_cnt > 0 else 0.0

        ts_issue_cnt = missing_ts_cnt + future_ts_cnt + date_only_ts_cnt
        ts_issue_share = (ts_issue_cnt / item_cnt) if item_cnt > 0 else 0.0
        missing_share = (missing_ts_cnt / item_cnt) if item_cnt > 0 else 0.0
        future_share = (future_ts_cnt / item_cnt) if item_cnt > 0 else 0.0
        date_only_share = (date_only_ts_cnt / item_cnt) if item_cnt > 0 else 0.0

        thin_quality = (item_cnt < 5)

        # Recommendation Verdict
        verdict, rationale = derive_verdict(
            runs_tot=runs_tot,
            fail_rate=fail_rate,
            is_disabled=s_rec["is_disabled"],
            disabled_reason=s_rec["disabled_reason"],
            item_cnt=item_cnt,
            ai_share=ai_share,
            first_rate=first_rate,
            multi_cnt=multi_cnt,
            med_pipe_lag=med_pipe_lag,
            missing_share=missing_share,
            future_share=future_share,
            date_only_share=date_only_share,
            rewrite_share=rewrite_share,
            error_kinds=s_rec["error_kinds"]
        )

        scorecard[sid] = {
            "id": sid,
            "name": s_rec["name"] or sid,
            "group": s_rec["group"] or "unknown",
            "publisher": s_rec["publisher"] or sid,
            "reliability": {
                "runs_total": runs_tot,
                "runs_failed": runs_fail,
                "runs_ok": runs_ok,
                "failure_rate": round(fail_rate, 4),
                "is_disabled": s_rec["is_disabled"],
                "disabled_reason": s_rec["disabled_reason"],
                "tech_status": tech_status,
                "error_kinds": dict(s_rec["error_kinds"]),
                "http_statuses": dict(s_rec["http_statuses"])
            },
            "earliness": {
                "multi_stories_count": multi_cnt,
                "first_count": first_cnt,
                "first_rate": round(first_rate, 4) if first_rate is not None else None,
                "behind_count": len(lags_behind),
                "median_lag_behind_hours": round(med_lag_behind, 2) if med_lag_behind is not None else None,
                "mean_lag_behind_hours": round(mean_lag_behind, 2) if mean_lag_behind is not None else None,
                "date_only_items_count": e_data["date_only_items_count"],
                "thin": thin_earliness
            },
            "pipeline_lag": {
                "items_measured": len(pipeline_lags),
                "median_hours": round(med_pipe_lag, 2) if med_pipe_lag is not None else None,
                "min_hours": round(min_pipe_lag, 2) if min_pipe_lag is not None else None,
                "max_hours": round(max_pipe_lag, 2) if max_pipe_lag is not None else None,
                "thin": thin_lag
            },
            "quality": {
                "total_items": item_cnt,
                "ai_items_count": ai_cnt,
                "ai_share": round(ai_share, 4),
                "corroborated_count": corrob_cnt,
                "corroborated_share": round(corrob_share, 4),
                "rewrite_count": rewrite_cnt,
                "rewrite_share": round(rewrite_share, 4),
                "missing_timestamp_count": missing_ts_cnt,
                "future_timestamp_count": future_ts_cnt,
                "date_only_timestamp_count": date_only_ts_cnt,
                "archive_items_count": archive_items_cnt,
                "timestamp_issues_count": ts_issue_cnt,
                "timestamp_issues_share": round(ts_issue_share, 4),
                "thin": thin_quality
            },
            "verdict": verdict,
            "rationale": rationale
        }

    # Summary metadata
    first_snap_time = snapshots[0]["generated_at"]
    last_snap_time = snapshots[-1]["generated_at"]
    duration_hours = (last_snap_time - first_snap_time).total_seconds() / 3600.0 if first_snap_time and last_snap_time else 0.0

    summary = {
        "snapshots_count": len(snapshots),
        "history_start": first_snap_time.isoformat() if first_snap_time else None,
        "history_end": last_snap_time.isoformat() if last_snap_time else None,
        "duration_hours": round(duration_hours, 2),
        "total_sources": len(scorecard),
        "total_unique_items": len(source_items),
        "total_stories": len(story_clusters),
        "multi_publisher_stories_count": len(multi_publisher_stories),
        "duplicate_feeds": duplicate_feeds
    }

    return {
        "summary": summary,
        "sources": scorecard
    }


def derive_verdict(runs_tot, fail_rate, is_disabled, disabled_reason=None, item_cnt=0,
                   ai_share=0.0, first_rate=None, multi_cnt=0, med_pipe_lag=None,
                   missing_share=0.0, future_share=0.0, date_only_share=0.0,
                   rewrite_share=0.0, error_kinds=None, ts_issue_share=None):
    """Derive an actionable recommendation for a source based on its empirical scorecard."""
    error_kinds = error_kinds or {}
    if ts_issue_share is None:
        ts_issue_share = missing_share + future_share + date_only_share

    # 1. Dead / Disabled sources (Rule 4)
    if is_disabled:
        reason_hint = disabled_reason or "vô hiệu hóa trong catalog"
        return "CUT", f"Đã bị vô hiệu hóa trong pipeline ({reason_hint}); cần tìm route hoặc sửa feed."

    if fail_rate >= 0.99:
        if "HTTP 404 (Address Changed)" in error_kinds or "HTTP 404" in error_kinds:
            return "CUT", "Lỗi 100% 404 URL chết; địa chỉ feed đã đổi, cần cập nhật URL mới hoặc gỡ bỏ."
        return "CUT", f"Tỷ lệ lỗi {fail_rate*100:.0f}%; không thể thu thập."

    if fail_rate >= 0.20:
        return "FIX", f"Tỷ lệ lỗi cao ({fail_rate*100:.1f}%), cần khắc phục kết nối/endpoint."

    # 2. Timestamp issues (Rule 3)
    if item_cnt > 0 and missing_share >= 0.80:
        return "FIX", f"Thiếu timestamp nghiêm trọng ({missing_share*100:.0f}% bài); cần sửa parser ngày tháng."

    if item_cnt > 0 and future_share >= 0.80:
        return "FIX", f"Timestamp ở tương lai ({future_share*100:.0f}% bài) do lỗi timezone; cần chuẩn hóa UTC."

    if item_cnt > 0 and date_only_share >= 0.80:
        return "REVISE", f"Timestamp dạng date-only ({date_only_share*100:.0f}% bài); không thể xếp hạng độ sớm theo giờ."

    # 3. Quality / AI relevance
    if item_cnt > 0 and ai_share < 0.30:
        return "FILTER_OR_CUT", f"Tỷ lệ bài AI quá thấp ({ai_share*100:.1f}%); cần bộ lọc filter_ai chặt hoặc loại bỏ."

    # 4. Earliness & Evidence requirement:
    # "when a source has too few independent clusters, say 'not enough evidence yet' rather than KEEP or CUT."
    if multi_cnt >= 5 and first_rate is not None and first_rate >= 0.60 and (med_pipe_lag is not None and med_pipe_lag <= 24.0):
        return "PROMOTE", f"Nguồn sớm xuất sắc: dẫn đầu {first_rate*100:.0f}% cụm tin độc lập ($N={multi_cnt}$), độ tin cậy cao."

    if multi_cnt >= 5 and first_rate is not None and first_rate == 0.0 and rewrite_share >= 0.10:
        return "REVISE", "Không bao giờ đưa tin đầu tiên trong các cụm tin độc lập; chủ yếu đi sau/xào lại."

    if multi_cnt >= 5:
        return "KEEP", f"Nguồn ổn định, có đủ bằng chứng kiểm chứng độc lập ($N_{{multi}}={multi_cnt}$). Đạt chuẩn."

    # Insufficient independent clusters: say "not enough evidence yet" rather than KEEP or CUT
    if item_cnt < 5 or multi_cnt < 5:
        return "NOT_ENOUGH_EVIDENCE", f"Chưa đủ bằng chứng (not enough evidence yet): chỉ có {multi_cnt}/5 cụm tin độc lập ($N_{{items}}={item_cnt}$); chưa thể kết luận KEEP hay CUT."

    return "KEEP", "Nguồn ổn định, đáp ứng tiêu chuẩn chất lượng và độ tin cậy."


def export_json(scorecard_data, output_path):
    """Write scorecard data to JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scorecard_data, f, ensure_ascii=False, indent=2)


def export_markdown(scorecard_data, output_path):
    """Write comprehensive human-readable Markdown table and rankings."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    summary = scorecard_data.get("summary", {})
    sources = scorecard_data.get("sources", {})
    duplicates = summary.get("duplicate_feeds", [])

    lines = []
    lines.append("# Bảng điểm Nguồn tin AI Radar (Source Scorecard) - Round 2")
    lines.append("")
    lines.append(f"- **Số snapshot phân tích**: {summary.get('snapshots_count', 0)} bản chụp")
    lines.append(f"- **Khoảng thời gian**: {summary.get('history_start')} đến {summary.get('history_end')} ({summary.get('duration_hours')} giờ)")
    lines.append(f"- **Tổng số nguồn theo dõi**: {summary.get('total_sources', 0)}")
    lines.append(f"- **Tổng số item độc nhất**: {summary.get('total_unique_items', 0)}")
    lines.append(f"- **Tổng số story clusters**: {summary.get('total_stories', 0)}")
    lines.append(f"- **Số story đa nhà xuất bản độc lập (Multi-publisher stories)**: {summary.get('multi_publisher_stories_count', 0)}")
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> **Quy tắc mẫu mỏng & Bằng chứng độc lập**:")
    lines.append("> 1. **Earliness & Corroboration**: Chỉ tính các cụm tin có từ $\\ge 2$ nhà xuất bản (publisher) độc lập. Các feed cùng một nhà xuất bản (như `anthropic-news` và `anthropic-gftdon`) không được tính là tự đua với chính mình.")
    lines.append("> 2. **Pipeline Lag**: Chỉ đo các bài có `published_at` sau bản chụp đầu tiên và không nằm trong bản chụp đầu tiên để tránh thổi phồng độ trễ bởi tin tồn kho.")
    lines.append("> 3. **Phân loại lỗi thời gian**: Tách riêng bài thiếu ngày (Missing), bài ở tương lai do timezone (Future), bài chỉ có ngày (Date-only). Không coi bài lưu trữ (> 30 ngày) là lỗi timestamp.")
    lines.append("> 4. **Nguyên tắc xếp hạng**: Khi một nguồn có dưới 5 cụm tin độc lập ($N_{multi} < 5$), hệ thống đánh giá `NOT_ENOUGH_EVIDENCE` (chưa đủ bằng chứng) thay vì vội vàng kết luận KEEP hay CUT.")
    lines.append("")

    # Master Table
    lines.append("## 1. Bảng điểm Tổng hợp (Master Scorecard)")
    lines.append("")
    lines.append("| Nguồn tin | Nhóm | Lượt chạy | Lỗi (%) | Tình trạng | Số bài | AI (%) | Sớm/Đa nguồn | Tỷ lệ sớm | Trễ tin 1 (h) | Pipeline Lag (h) | Kiểm chứng (%) | Xào lại (%) | Lỗi Time (M/F/D) | Đánh giá |")
    lines.append("|:---|:---|---:|---:|:---|---:|---:|---:|---:|---:|---:|---:|---:|:---|:---|")

    sorted_sources = sorted(sources.values(), key=lambda s: (s["verdict"], -(s["earliness"]["first_rate"] or 0), s["id"]))

    for s in sorted_sources:
        sid = s["id"]
        grp = s["group"]
        rel = s["reliability"]
        ear = s["earliness"]
        lag = s["pipeline_lag"]
        qua = s["quality"]

        fail_str = f"{rel['failure_rate']*100:.1f}%" if rel['runs_total'] > 0 else "N/A"
        tech_status = rel.get("tech_status", "UNKNOWN")
        item_cnt = qua["total_items"]
        ai_str = f"{qua['ai_share']*100:.1f}%" if item_cnt > 0 else "N/A"

        mc = ear["multi_stories_count"]
        fc = ear["first_count"]
        if mc > 0:
            thin_mark = "*" if ear["thin"] else ""
            multi_str = f"{fc}/{mc}{thin_mark}"
            first_pct = f"{ear['first_rate']*100:.1f}%" if ear['first_rate'] is not None else "N/A"
        else:
            multi_str = "0/0"
            first_pct = "N/A"

        lag_behind = f"{ear['median_lag_behind_hours']:.1f}h" if ear['median_lag_behind_hours'] is not None else "-"
        pipe_lag = f"{lag['median_hours']:.1f}h" if lag['median_hours'] is not None else "-"
        if lag["thin"] and lag['median_hours'] is not None:
            pipe_lag += "*"

        corrob_str = f"{qua['corroborated_share']*100:.1f}%" if item_cnt > 0 else "N/A"
        rewrite_str = f"{qua['rewrite_share']*100:.1f}%" if item_cnt > 0 else "N/A"
        m_cnt = qua.get("missing_timestamp_count", 0)
        f_cnt = qua.get("future_timestamp_count", 0)
        d_cnt = qua.get("date_only_timestamp_count", 0)
        ts_detail = f"{m_cnt}/{f_cnt}/{d_cnt}" if (m_cnt + f_cnt + d_cnt) > 0 else "0"

        verdict = s["verdict"]

        lines.append(f"| `{sid}` | {grp} | {rel['runs_total']} | {fail_str} | {tech_status} | {item_cnt} | {ai_str} | {multi_str} | {first_pct} | {lag_behind} | {pipe_lag} | {corrob_str} | {rewrite_str} | {ts_detail} | **{verdict}** |")

    lines.append("")

    # Section 2: Earliness Leaderboard
    lines.append("## 2. Bảng xếp hạng Độ sớm Độc lập (Independent Earliness Leaderboard)")
    lines.append("")
    lines.append("### A. Nguồn có bằng chứng vững chắc ($N_{multi} \\ge 5$ cụm tin đa publisher)")
    lines.append("")
    lines.append("| Thứ hạng | Nguồn tin | Đa nguồn | Về nhất | Tỷ lệ sớm (%) | Trễ trung vị khi không nhất | Nhận xét |")
    lines.append("|---:|:---|---:|---:|---:|---:|:---|")

    solid_earliness = [
        s for s in sources.values()
        if not s["earliness"]["thin"] and s["earliness"]["first_rate"] is not None
    ]
    solid_earliness.sort(key=lambda s: (-s["earliness"]["first_rate"], s["earliness"]["median_lag_behind_hours"] or 999))

    for idx, s in enumerate(solid_earliness, 1):
        ear = s["earliness"]
        lag_b = f"{ear['median_lag_behind_hours']:.2f}h" if ear['median_lag_behind_hours'] is not None else "0.0h"
        lines.append(f"| {idx} | `{s['id']}` ({s['name']}) | {ear['multi_stories_count']} | {ear['first_count']} | **{ear['first_rate']*100:.1f}%** | {lag_b} | {s['rationale']} |")

    lines.append("")
    lines.append("### B. Nguồn mẫu mỏng ($N_{multi} < 5$) — Chưa đủ bằng chứng (Not Enough Evidence Yet)")
    lines.append("")
    lines.append("| Nguồn tin | Đa nguồn | Về nhất | Tỷ lệ sớm (%) | Trễ trung vị (h) | Đánh giá | Nhận xét |")
    lines.append("|:---|---:|---:|---:|---:|:---|:---|")

    thin_earliness = [
        s for s in sources.values()
        if s["earliness"]["thin"] and s["earliness"]["multi_stories_count"] > 0
    ]
    thin_earliness.sort(key=lambda s: (-s["earliness"]["first_rate"] if s["earliness"]["first_rate"] is not None else 0, s["id"]))

    for s in thin_earliness:
        ear = s["earliness"]
        lag_b = f"{ear['median_lag_behind_hours']:.2f}h" if ear['median_lag_behind_hours'] is not None else "0.0h"
        first_p = f"{ear['first_rate']*100:.1f}%" if ear['first_rate'] is not None else "0.0%"
        lines.append(f"| `{s['id']}` | {ear['multi_stories_count']}* | {ear['first_count']} | {first_p}* | {lag_b} | `{s['verdict']}` | {s['rationale']} |")

    lines.append("")

    # Section 3: Duplicate Feeds
    lines.append("## 3. Các Cặp Feed Trùng lặp Nội dung (Duplicate Feeds)")
    lines.append("")
    lines.append("| Feed 1 | Feed 2 | Nhà xuất bản | Số bài trùng lặp | Bản chất trùng lặp |")
    lines.append("|:---|:---|:---|---:|:---|")

    for d in duplicates:
        p_info = d["publisher_1"] if d["publisher_1"] == d["publisher_2"] else f"{d['publisher_1']} / {d['publisher_2']}"
        lines.append(f"| `{d['source_1']}` | `{d['source_2']}` | {p_info} | **{d['shared_items_count']}** | Cùng một publisher/kho bài viết; không tính là cạnh tranh độc lập. |")

    lines.append("")

    # Section 4: Pipeline Lag Ranking
    lines.append("## 4. Bảng xếp hạng Tốc độ Pipeline (Pipeline Ingestion Lag - Realtime Window)")
    lines.append("")
    lines.append("> Chỉ đo các bài có `published_at > first_snapshot` và xuất hiện sau bản chụp đầu tiên.")
    lines.append("")
    lines.append("| Thứ hạng | Nguồn tin | Nhóm | Số bài đo | Lag trung vị (h) | Min lag (h) | Max lag (h) | Đánh giá |")
    lines.append("|---:|:---|:---|---:|---:|---:|---:|:---|")

    valid_lag_sources = [
        s for s in sources.values()
        if s["pipeline_lag"]["median_hours"] is not None
    ]
    valid_lag_sources.sort(key=lambda s: s["pipeline_lag"]["median_hours"])

    for idx, s in enumerate(valid_lag_sources, 1):
        pl = s["pipeline_lag"]
        thin_flag = "*" if pl["thin"] else ""
        lines.append(f"| {idx} | `{s['id']}` | {s['group']} | {pl['items_measured']}{thin_flag} | **{pl['median_hours']:.2f}h** | {pl['min_hours']:.2f}h | {pl['max_hours']:.2f}h | {'Mẫu mỏng' if pl['thin'] else 'Ổn định'} |")

    lines.append("")

    # Section 5: Reliability & Dead Sources
    lines.append("## 5. Độ tin cậy & Phân loại Nguồn Chết / Tê liệt (Disabled vs Failing)")
    lines.append("")
    lines.append("| Nguồn tin | Lượt chạy | Thất bại | Tình trạng | Phân loại lỗi chi tiết | Giải pháp đề xuất |")
    lines.append("|:---|---:|---:|:---|:---|:---|")

    dead_or_failing = [s for s in sources.values() if s["reliability"]["failure_rate"] > 0]
    dead_or_failing.sort(key=lambda s: -s["reliability"]["failure_rate"])

    for s in dead_or_failing:
        rel = s["reliability"]
        err_details = ", ".join(f"{k}: {v}" for k, v in rel["error_kinds"].items())
        t_stat = rel["tech_status"]
        if t_stat == "DISABLED":
            sol = "Cần giải pháp thay thế (proxy runner, alternate feed URL hoặc sửa parser XML)."
        elif sid == "vnexpress-so-hoa":
            sol = "URL feed đã thay đổi trên máy chủ gốc (404 vĩnh viễn); cần cập nhật địa chỉ RSS mới."
        elif rel["failure_rate"] > 0.2:
            sol = "Chập chờn kết nối / YouTube endpoint; cần cơ chế retry hoặc xử lý lỗi mềm."
        else:
            sol = "Lỗi ngẫu nhiên thoáng qua (timeout/build deadline)."

        lines.append(f"| `{s['id']}` ({s['name']}) | {rel['runs_total']} | {rel['runs_failed']} | **{t_stat}** | {err_details} | {sol} |")

    lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="AI Radar Source Scorecard Analyzer")
    parser.add_argument("--snapshots", default="plans/reports/ban-chup", help="Path to snapshots directory")
    parser.add_argument("--json-out", default="plans/reports/nguon-som-scorecard.json", help="Path to output JSON file")
    parser.add_argument("--md-out", default="plans/reports/nguon-som-scorecard.md", help="Path to output Markdown file")

    args = parser.parse_args()

    print(f"Loading snapshots from {args.snapshots}...")
    snapshots = discover_snapshots(args.snapshots)
    print(f"Loaded {len(snapshots)} snapshots.")

    print("Computing source scorecard metrics...")
    scorecard = analyze_snapshots(snapshots)

    print(f"Exporting JSON scorecard to {args.json_out}...")
    export_json(scorecard, args.json_out)

    print(f"Exporting Markdown scorecard to {args.md_out}...")
    export_markdown(scorecard, args.md_out)

    summary = scorecard.get("summary", {})
    print("Done!")
    print(f"  Total sources analyzed: {summary.get('total_sources')}")
    print(f"  Duration covered: {summary.get('duration_hours')} hours")
    print(f"  Multi-publisher stories: {summary.get('multi_publisher_stories_count')}")


if __name__ == "__main__":
    main()
