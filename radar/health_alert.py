"""Keep live-site incidents independent from update workflow incidents."""

from datetime import timedelta, timezone
import json
import re

from radar.failure_alert import AlertError, plain
from radar.health_probe import SITE_URL
from radar.items import instant

HEALTH_MARKER = "<!-- radar-live-health -->"
OBSERVATION_PATTERN = r"<!-- radar-health-observation:(\{[^\n]+\}) -->"


def issue_observation(issue, pattern=OBSERVATION_PATTERN):
    match = re.search(pattern, issue.get("body") or "")
    try:
        value = json.loads(match[1]) if match else {}
        stamp = instant(value.get("checked_at"))
    except (TypeError, ValueError):
        stamp = None
    if stamp is None:
        raise AlertError("Health issue has invalid observation metadata; inspect it before retrying.")
    return stamp


def valid_run(repository, run_id, run_attempt):
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                and re.fullmatch(r"[1-9][0-9]*", str(run_id)) and re.fullmatch(r"[1-9][0-9]*", str(run_attempt)))


def bot_issues(api, marker, pattern):
    """The workflow bot's issues carrying marker, each with the observation time recorded in its body."""
    issues = [issue for issue in api.pages("/issues?state=all&creator=github-actions%5Bbot%5D")
              if "pull_request" not in issue and marker in (issue.get("body") or "")
              and issue.get("user", {}).get("login") == "github-actions[bot]"]
    return [(issue_observation(issue, pattern), issue) for issue in issues]


def reconcile_report(report, api, repository, run_id, run_attempt, owner):
    if report.get("status") == "inconclusive":
        return "unchanged"
    stamp = instant(report.get("checked_at"))
    status = report.get("status")
    confirmed = report.get("confirmed_failures")
    if (stamp is None or status not in ("healthy", "failed") or not isinstance(confirmed, list)
            or (status == "failed" and not confirmed) or (status == "healthy" and confirmed)
            or not valid_run(repository, run_id, run_attempt)):
        raise AlertError("Invalid health report or workflow metadata; refusing to change an issue.")
    ordered = bot_issues(api, HEALTH_MARKER, OBSERVATION_PATTERN)
    if any(prior > stamp or (prior == stamp and status == "failed" and issue.get("state") == "closed")
           for prior, issue in ordered):
        return "superseded"
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
    observation = "<!-- radar-health-observation:" + json.dumps({"checked_at": report["checked_at"]}, sort_keys=True) + " -->"
    open_issues = [issue for _, issue in sorted(ordered, key=lambda pair: pair[0], reverse=True)
                   if issue.get("state") == "open"]
    if status == "healthy":
        for issue in open_issues:
            body = re.sub(OBSERVATION_PATTERN + r"\s*", "", issue["body"])
            body += (f"\n\nRecovered: all live checks passed at {plain(report['checked_at'])}. "
                     f"[Monitor run and logs]({run_url}).\n\n{observation}")
            api.request("PATCH", f"/issues/{int(issue['number'])}",
                        {"body": body, "state": "closed", "state_reason": "completed"})
        return "resolved" if open_issues else "unchanged"
    body = [HEALTH_MARKER, observation, f"Confirmed live health failure: [{SITE_URL}]({SITE_URL}).",
            f"Observed at: {plain(report['checked_at'])}.",
            f"Snapshot generated_at: {plain(report.get('generated_at') or 'unavailable')}.",
            f"[Monitor run and logs]({run_url}).", "These checks failed in both probes, 30 seconds apart:"]
    for row in confirmed:
        body.append(f"- {plain(row['id'])}: {plain(row['detail'])}")
    body.append("Repeated failures update this issue without comments. A healthy live probe closes it. "
                "This incident does not represent update workflow status or diagnose the cause of stale data.")
    if re.fullmatch(r"[A-Za-z0-9-]+", owner):
        body.append(f"Owner: @{owner}. Notification delivery depends on GitHub account/repository settings.")
    payload = {"title": "AI Radar live health check failed", "body": "\n\n".join(body)}
    if open_issues:
        issue = open_issues[0]
        if issue.get("body") == payload["body"] and issue.get("title") == payload["title"]:
            return "unchanged"
        api.request("PATCH", f"/issues/{int(issue['number'])}", payload)
        return "updated"
    api.request("POST", "/issues", payload)
    return "created"


QUIET_MARKER = "<!-- radar-quiet-feed -->"
QUIET_OBSERVATION_PATTERN = r"<!-- radar-quiet-observation:(\{[^\n]+\}) -->"
# The quiet-feed issue is read by the site owner, in Vietnamese; markers and metadata stay machine-readable.
DIAGNOSIS_LABELS = {"quiet-news": "có vẻ do ít tin", "pipeline": "có vẻ pipeline lỗi",
                    "unknown": "chưa chẩn đoán được"}
DISPLAY_TZ = timezone(timedelta(hours=7))


def duration(seconds):
    """Compact duration for logs: 5h 12m."""
    minutes = int(seconds) // 60
    return f"{minutes // 60}h {minutes % 60:02d}m"


def duration_vi(seconds):
    """Duration for the owner: 5 giờ 12 phút, 45 phút, 3 giờ."""
    hours, minutes = divmod(int(seconds) // 60, 60)
    if not hours:
        return f"{minutes} phút"
    return f"{hours} giờ {minutes} phút" if minutes else f"{hours} giờ"


def local_time(value):
    stamp = instant(value)
    return stamp.astimezone(DISPLAY_TZ).strftime("%H:%M ngày %d/%m") if stamp else "không rõ"


def age(seconds):
    return f"{duration_vi(seconds)} trước" if isinstance(seconds, int) else "không rõ bao lâu"


def quiet_body(report, run_url, owner):
    """The quiet-feed issue: how long, the last new story, and the measured signals behind the diagnosis."""
    signals = report["signals"]
    plus = "+" if report["quiet_at_least"] else ""
    quiet = duration_vi(report["quiet_seconds"]) + (" trở lên" if plus else "")
    lines = [QUIET_MARKER, "<!-- radar-quiet-observation:" + json.dumps({"checked_at": report["checked_at"]},
                                                                        sort_keys=True) + " -->",
             f"[{SITE_URL}]({SITE_URL}) đã **{quiet}** chưa có tin mới "
             f"(cảnh báo bật khi quá {duration_vi(report['threshold_seconds'])}).",
             f"Kiểm tra lúc {local_time(report['checked_at'])}. [Lượt kiểm tra và log]({run_url})."]
    last = report.get("last_new_story")
    if last:
        lines.append(f"Tin mới gần nhất: {plain(last.get('title') or last['id'], 300)} (id {plain(last['id'], 40)}), "
                     f"lên trang ở lần build lúc {local_time(last['appeared_at'])}.")
    else:
        lines.append("Trong khoảng lịch sử đã tải (khoảng một tuần) không có tin nào mới hơn điểm bắt đầu, "
                     "nên thời gian im ở trên là mức tối thiểu.")
    label = DIAGNOSIS_LABELS[report["diagnosis"]]
    lines.append(f"Chẩn đoán: **{label}**.")
    for text in report["problems"]:
        lines.append(f"- Lỗi: {plain(text, 300)}")
    for text in report["unknowns"]:
        lines.append(f"- Chưa đo được: {plain(text, 300)}")
    build, newsroom = signals["build"], signals["newsroom"]
    sources, intake = signals["sources"], signals["intake"]
    interval = build.get("expected_interval_seconds")
    since = newsroom.get("dispatches_since_last_story")
    lines += ["Số đo:",
              f"- Build gần nhất của trang: {local_time(build.get('generated_at'))}, {age(build.get('age_seconds'))}"
              + (f"; bình thường {duration_vi(interval)} build một lần." if interval else "."),
              f"- Lần chạy newsroom gần nhất: {local_time(newsroom.get('last_dispatch_at'))}, "
              f"{age(newsroom.get('age_seconds'))}; số lần chạy từ tin mới gần nhất: "
              + (f"{since}{' trở lên' if newsroom.get('dispatches_at_least') else ''}." if since is not None
                 else "không rõ."),
              f"- Nguồn: {sources['failing']} trên {sources['enabled']} nguồn đang bật bị lỗi"
              + (f" ({plain(', '.join(sources['failing_ids'][:10]), 300)})." if sources["failing_ids"] else "."),
              "- Intake: " + (f"{intake['stories_in_window']} tin intake có giờ đăng ở nguồn sau tin mới gần nhất "
                              "(ứng viên newsroom có thể đăng)."
                              if intake.get("stories_in_window") is not None else "không rõ.")]
    lines.append("Issue này được cập nhật bằng cách sửa nội dung, không thêm bình luận. Tin mới tiếp theo lên trang "
                 "sẽ tự đóng nó. Cảnh báo này tách riêng với sự cố sức khoẻ trang và cảnh báo update lỗi.")
    if re.fullmatch(r"[A-Za-z0-9-]+", owner):
        lines.append(f"Owner: @{owner}. Thông báo đến hay không tuỳ cài đặt tài khoản/repository trên GitHub.")
    title = f"Halcyon: {quiet} chưa có tin mới ({label})"
    return {"title": title, "body": "\n\n".join(lines)}


def reconcile_quiet(report, api, repository, run_id, run_attempt, owner):
    """Open or update one issue while the feed is quiet; close it when a new story appears. Unknown changes nothing."""
    status = report.get("status")
    if status not in ("quiet", "fresh"):
        return "unchanged"
    stamp = instant(report.get("checked_at"))
    quiet = report.get("quiet_seconds")
    if (stamp is None or isinstance(quiet, bool) or not isinstance(quiet, int) or quiet < 0
            or report.get("diagnosis") not in DIAGNOSIS_LABELS or not valid_run(repository, run_id, run_attempt)):
        raise AlertError("Invalid quiet-feed report or workflow metadata; refusing to change an issue.")
    ordered = bot_issues(api, QUIET_MARKER, QUIET_OBSERVATION_PATTERN)
    if any(prior > stamp or (prior == stamp and status == "quiet" and issue.get("state") == "closed")
           for prior, issue in ordered):
        return "superseded"
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
    observation = ("<!-- radar-quiet-observation:" + json.dumps({"checked_at": report["checked_at"]}, sort_keys=True)
                   + " -->")
    open_issues = [issue for _, issue in sorted(ordered, key=lambda pair: pair[0], reverse=True)
                   if issue.get("state") == "open"]
    if status == "fresh":
        last = report.get("last_new_story") or {}
        for issue in open_issues:
            body = re.sub(QUIET_OBSERVATION_PATTERN + r"\s*", "", issue["body"])
            body += (f"\n\nĐã có tin mới lên trang: {plain(last.get('title') or last.get('id') or 'không rõ', 300)}, "
                     f"lên lúc {local_time(last.get('appeared_at'))}. Tự đóng lúc "
                     f"{local_time(report['checked_at'])}. [Lượt kiểm tra và log]({run_url}).\n\n{observation}")
            api.request("PATCH", f"/issues/{int(issue['number'])}",
                        {"body": body, "state": "closed", "state_reason": "completed"})
        return "resolved" if open_issues else "unchanged"
    payload = quiet_body(report, run_url, owner)
    if open_issues:
        issue = open_issues[0]
        if issue.get("body") == payload["body"] and issue.get("title") == payload["title"]:
            return "unchanged"
        api.request("PATCH", f"/issues/{int(issue['number'])}", payload)
        return "updated"
    api.request("POST", "/issues", payload)
    return "created"
