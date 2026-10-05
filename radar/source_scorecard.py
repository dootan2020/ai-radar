"""Source scorecard analysis: measuring earliness, pipeline lag, quality, and reliability across snapshot history."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
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


def categorize_error(error_str, http_status=None):
    """Categorize raw error strings and HTTP status into standardized error kinds."""
    if not error_str and http_status is None:
        return "None"
    err = str(error_str or "")
    if "Disabled:" in err:
        return "Disabled"
    if http_status == 403 or "403" in err:
        return "HTTP 403"
    if http_status == 404 or "404" in err:
        return "HTTP 404"
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
        except Exception as e:
            # Skip unreadable snapshots gracefully
            continue

    # Secondary sort by parsed generated_at if available
    snapshots.sort(key=lambda s: s["generated_at"] or datetime.min.replace(tzinfo=timezone.utc))
    return snapshots


def analyze_snapshots(snapshots):
    """Process loaded snapshots and compute all 4 scorecard dimensions for each source."""
    if not snapshots:
        return {
            "summary": {"snapshots_count": 0},
            "sources": {}
        }

    # Tracking structures
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

    item_first_seen = {}  # url/canonical_url -> {first_seen_at, snapshot_name, item}
    story_clusters = {}   # story_id -> {id, title, published_at, coverage: {item_id: item}}

    for snap in snapshots:
        snap_dt = snap["generated_at"]
        snap_name = snap["name"]
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
                kind = categorize_error(s.get("error"), s.get("http_status"))
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

                if item_url not in item_first_seen:
                    item_first_seen[item_url] = {
                        "url": item_url,
                        "id": item_id,
                        "source": item.get("source"),
                        "publisher": item.get("publisher"),
                        "group": item.get("group"),
                        "title": item.get("title", ""),
                        "summary": item.get("summary", ""),
                        "published_at": item.get("published_at"),
                        "first_seen_at": snap_dt,
                        "first_snap": snap_name,
                        "story_id": sid
                    }
                # Update story coverage
                story_clusters[sid]["coverage"][item_id] = item

    # Group items by source
    items_by_source = defaultdict(list)
    for it in item_first_seen.values():
        src = it.get("source")
        if src:
            items_by_source[src].append(it)

    # 3. Compute Earliness across multi-source stories
    # A multi-source story is one with coverage from >= 2 distinct sources
    multi_source_stories = [
        s for s in story_clusters.values()
        if len({it.get("source") for it in s["coverage"].values() if it.get("source")}) > 1
    ]

    source_earliness = defaultdict(lambda: {
        "multi_count": 0,
        "first_count": 0,
        "lags_behind_hours": []
    })

    for s in multi_source_stories:
        coverage_items = list(s["coverage"].values())
        parsed_items = []
        for it in coverage_items:
            src = it.get("source")
            p_dt = parse_iso_datetime(it.get("published_at"))
            if src and p_dt:
                parsed_items.append((src, p_dt))

        if not parsed_items:
            continue

        # Story's overall earliest publication time
        t_first = min(p_dt for _, p_dt in parsed_items)

        # For each distinct source in this story, get their earliest publication time
        source_earliest_in_story = {}
        for src, p_dt in parsed_items:
            if src not in source_earliest_in_story or p_dt < source_earliest_in_story[src]:
                source_earliest_in_story[src] = p_dt

        for src, t_s in source_earliest_in_story.items():
            edata = source_earliness[src]
            edata["multi_count"] += 1
            diff_seconds = (t_s - t_first).total_seconds()
            # Allow up to 60s tolerance for clock jitter/feed generation sync
            if diff_seconds <= 60:
                edata["first_count"] += 1
            else:
                edata["lags_behind_hours"].append(diff_seconds / 3600.0)

    # 4. Synthesize per-source scorecard
    scorecard = {}
    all_source_ids = sorted(set(source_records.keys()) | set(items_by_source.keys()))

    for sid in all_source_ids:
        s_rec = source_records[sid]
        items = items_by_source.get(sid, [])

        # Reliability
        runs_tot = s_rec["runs_total"]
        runs_fail = s_rec["runs_failed"]
        runs_ok = runs_tot - runs_fail
        fail_rate = (runs_fail / runs_tot) if runs_tot > 0 else 0.0

        # Earliness
        e_data = source_earliness[sid]
        multi_cnt = e_data["multi_count"]
        first_cnt = e_data["first_count"]
        first_rate = (first_cnt / multi_cnt) if multi_cnt > 0 else None
        lags_behind = e_data["lags_behind_hours"]
        med_lag_behind = statistics.median(lags_behind) if lags_behind else None
        mean_lag_behind = statistics.mean(lags_behind) if lags_behind else None
        thin_earliness = (multi_cnt < 5)

        # Pipeline Lag & Quality
        item_cnt = len(items)
        ai_cnt = 0
        corrob_cnt = 0
        rewrite_cnt = 0
        missing_ts_cnt = 0
        implausible_ts_cnt = 0
        pipeline_lags = []

        my_pub = s_rec.get("publisher") or sid

        for it in items:
            # AI relevance
            if relevant(it.get("title", ""), it.get("summary", "")):
                ai_cnt += 1

            # Timestamps & Pipeline Lag
            p_str = it.get("published_at")
            p_dt = parse_iso_datetime(p_str)
            seen_dt = it.get("first_seen_at")

            if not p_str or not p_dt:
                missing_ts_cnt += 1
            else:
                if seen_dt:
                    lag_hours = (seen_dt - p_dt).total_seconds() / 3600.0
                    # Implausible: published in future > 1h (timezone bug) or > 30 days old (stale/archive)
                    if lag_hours < -1.0 or lag_hours > 30 * 24:
                        implausible_ts_cnt += 1
                    else:
                        pipeline_lags.append(lag_hours)
                else:
                    pipeline_lags.append(0.0)

            # Corroboration & Rewrites
            sid_story = it.get("story_id")
            cluster = story_clusters.get(sid_story)
            if cluster and p_dt:
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
        ts_issue_cnt = missing_ts_cnt + implausible_ts_cnt
        ts_issue_share = (ts_issue_cnt / item_cnt) if item_cnt > 0 else 0.0

        med_pipe_lag = statistics.median(pipeline_lags) if pipeline_lags else None
        min_pipe_lag = min(pipeline_lags) if pipeline_lags else None
        max_pipe_lag = max(pipeline_lags) if pipeline_lags else None

        thin_quality = (item_cnt < 5)
        thin_lag = (len(pipeline_lags) < 5)

        # Recommendation Verdict
        verdict, rationale = derive_verdict(
            runs_tot=runs_tot,
            fail_rate=fail_rate,
            is_disabled=s_rec["is_disabled"],
            item_cnt=item_cnt,
            ai_share=ai_share,
            first_rate=first_rate,
            multi_cnt=multi_cnt,
            med_pipe_lag=med_pipe_lag,
            ts_issue_share=ts_issue_share,
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
                "implausible_timestamp_count": implausible_ts_cnt,
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
        "total_unique_items": len(item_first_seen),
        "total_stories": len(story_clusters),
        "multi_source_stories_count": len(multi_source_stories)
    }

    return {
        "summary": summary,
        "sources": scorecard
    }


def derive_verdict(runs_tot, fail_rate, is_disabled, item_cnt, ai_share, first_rate,
                   multi_cnt, med_pipe_lag, ts_issue_share, rewrite_share, error_kinds):
    """Derive an actionable recommendation for a source based on its empirical scorecard."""
    if is_disabled or fail_rate >= 0.99:
        if "HTTP 404" in error_kinds:
            return "CUT", "Lỗi 100% 404 URL chết; cần gỡ bỏ ngay."
        if "Disabled" in error_kinds or is_disabled:
            return "CUT", "Đã bị vô hiệu hóa trong catalog (HTTP 403 / XML hỏng)."
        return "CUT", f"Tỷ lệ lỗi {fail_rate*100:.0f}%; không thể thu thập."

    if fail_rate >= 0.20:
        return "FIX", f"Tỷ lệ lỗi cao ({fail_rate*100:.1f}%), cần khắc phục kết nối/endpoint."

    if item_cnt > 0 and ts_issue_share >= 0.80:
        return "FIX", f"Timestamp lỗi/thiếu nghiêm trọng ({ts_issue_share*100:.0f}% items); cần sửa parser ngày tháng."

    if item_cnt > 0 and ai_share < 0.30:
        return "FILTER_OR_CUT", f"Tỷ lệ bài AI quá thấp ({ai_share*100:.1f}%); cần bộ lọc filter_ai chặt hoặc loại bỏ."

    if multi_cnt >= 5 and first_rate is not None and first_rate >= 0.60 and (med_pipe_lag is not None and med_pipe_lag <= 24.0):
        return "PROMOTE", f"Nguồn sớm xuất sắc: dẫn đầu {first_rate*100:.0f}% multi-source stories, độ tin cậy cao."

    if med_pipe_lag is not None and med_pipe_lag <= 3.0 and ai_share >= 0.80:
        return "PROMOTE", f"Tốc độ pipeline cực nhanh ({med_pipe_lag:.1f}h) và độ liên quan AI cao ({ai_share*100:.0f}%)."

    if multi_cnt >= 5 and first_rate is not None and first_rate == 0.0 and rewrite_share >= 0.10:
        return "REVISE", "Không bao giờ đưa tin đầu tiên trong các tin đa nguồn; chủ yếu xào lại/chép lại."

    if item_cnt < 5:
        return "MONITOR", f"Mẫu mỏng ({item_cnt} bài); cần thêm thời gian theo dõi lịch sử dài hơn."

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

    lines = []
    lines.append("# Bảng điểm Nguồn tin AI Radar (Source Scorecard)")
    lines.append("")
    lines.append(f"- **Số snapshot phân tích**: {summary.get('snapshots_count', 0)} bản chụp")
    lines.append(f"- **Khoảng thời gian**: {summary.get('history_start')} đến {summary.get('history_end')} ({summary.get('duration_hours')} giờ)")
    lines.append(f"- **Tổng số nguồn theo dõi**: {summary.get('total_sources', 0)}")
    lines.append(f"- **Tổng số item độc nhất**: {summary.get('total_unique_items', 0)}")
    lines.append(f"- **Tổng số story clusters**: {summary.get('total_stories', 0)} (trong đó có {summary.get('multi_source_stories_count', 0)} stories đa nguồn)")
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> **Quy tắc mẫu mỏng (`*` thin)**: Mọi chỉ số có cỡ mẫu dưới 5 stories/items đều được đánh dấu dấu hoa thị `*` (thin) để tránh kết luận vội vàng dựa trên dữ liệu 3 ngày.")
    lines.append("")

    # Master Table
    lines.append("## 1. Bảng điểm Tổng hợp (Master Scorecard)")
    lines.append("")
    lines.append("| Nguồn tin | Nhóm | Lượt chạy | Lỗi (%) | Số bài | AI (%) | Sớm/Đa nguồn | Tỷ lệ sớm | Trễ so với tin 1 (h) | Pipeline Lag (h) | Kiểm chứng (%) | Xào lại (%) | Lỗi Time (%) | Đánh giá |")
    lines.append("|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---|")

    sorted_sources = sorted(sources.values(), key=lambda s: (s["verdict"], -(s["earliness"]["first_rate"] or 0), s["id"]))

    for s in sorted_sources:
        sid = s["id"]
        grp = s["group"]
        rel = s["reliability"]
        ear = s["earliness"]
        lag = s["pipeline_lag"]
        qua = s["quality"]

        fail_str = f"{rel['failure_rate']*100:.1f}%" if rel['runs_total'] > 0 else "N/A"
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
        ts_str = f"{qua['timestamp_issues_share']*100:.1f}%" if item_cnt > 0 else "N/A"

        verdict = s["verdict"]

        lines.append(f"| `{sid}` | {grp} | {rel['runs_total']} | {fail_str} | {item_cnt} | {ai_str} | {multi_str} | {first_pct} | {lag_behind} | {pipe_lag} | {corrob_str} | {rewrite_str} | {ts_str} | **{verdict}** |")

    lines.append("")

    # Section 2: Earliness Ranking
    lines.append("## 2. Bảng xếp hạng Độ sớm (Earliness Leaderboard)")
    lines.append("")
    lines.append("### A. Nguồn có mẫu vững chắc ($N_{multi} \\ge 5$)")
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
        lines.append(f"| {idx} | `{s['id']}` ({s['name']}) | {ear['multi_stories_count']} | {ear['first_count']} | {ear['first_rate']*100:.1f}% | {lag_b} | {s['rationale']} |")

    lines.append("")
    lines.append("### B. Nguồn mẫu mỏng ($N_{multi} < 5$) — Cần theo dõi thêm")
    lines.append("")
    lines.append("| Nguồn tin | Đa nguồn | Về nhất | Tỷ lệ sớm (%) | Trễ trung vị (h) | Nhận xét |")
    lines.append("|:---|---:|---:|---:|---:|:---|")

    thin_earliness = [
        s for s in sources.values()
        if s["earliness"]["thin"] and s["earliness"]["multi_stories_count"] > 0
    ]
    thin_earliness.sort(key=lambda s: (-s["earliness"]["first_rate"] if s["earliness"]["first_rate"] is not None else 0, s["id"]))

    for s in thin_earliness:
        ear = s["earliness"]
        lag_b = f"{ear['median_lag_behind_hours']:.2f}h" if ear['median_lag_behind_hours'] is not None else "0.0h"
        first_p = f"{ear['first_rate']*100:.1f}%" if ear['first_rate'] is not None else "0.0%"
        lines.append(f"| `{s['id']}` | {ear['multi_stories_count']}* | {ear['first_count']} | {first_p}* | {lag_b} | {s['rationale']} |")

    lines.append("")

    # Section 3: Pipeline Lag Ranking
    lines.append("## 3. Bảng xếp hạng Tốc độ Pipeline (Pipeline Ingestion Lag)")
    lines.append("")
    lines.append("| Thứ hạng | Nguồn tin | Nhóm | Số bài đo | Lag trung vị (h) | Min lag (h) | Max lag (h) | Tình trạng |")
    lines.append("|---:|:---|:---|---:|---:|---:|---:|:---|")

    valid_lag_sources = [
        s for s in sources.values()
        if s["pipeline_lag"]["median_hours"] is not None
    ]
    valid_lag_sources.sort(key=lambda s: s["pipeline_lag"]["median_hours"])

    for idx, s in enumerate(valid_lag_sources, 1):
        pl = s["pipeline_lag"]
        thin_flag = "*" if pl["thin"] else ""
        lines.append(f"| {idx} | `{s['id']}` | {s['group']} | {pl['items_measured']}{thin_flag} | {pl['median_hours']:.2f}h | {pl['min_hours']:.2f}h | {pl['max_hours']:.2f}h | {'Mẫu mỏng' if pl['thin'] else 'Ổn định'} |")

    lines.append("")

    # Section 4: Reliability & Failures
    lines.append("## 4. Độ tin cậy & Thống kê Lỗi (Reliability & Failures)")
    lines.append("")
    lines.append("| Nguồn tin | Lượt chạy | Thất bại | Tỷ lệ lỗi (%) | Phân loại lỗi chi tiết |")
    lines.append("|:---|---:|---:|---:|:---|")

    failing_sources = [s for s in sources.values() if s["reliability"]["failure_rate"] > 0]
    failing_sources.sort(key=lambda s: -s["reliability"]["failure_rate"])

    for s in failing_sources:
        rel = s["reliability"]
        err_details = ", ".join(f"{k}: {v}" for k, v in rel["error_kinds"].items())
        lines.append(f"| `{s['id']}` ({s['name']}) | {rel['runs_total']} | {rel['runs_failed']} | **{rel['failure_rate']*100:.1f}%** | {err_details} |")

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


if __name__ == "__main__":
    main()
