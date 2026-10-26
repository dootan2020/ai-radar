"""Collect public article evidence for the fixed 26 October review sample."""

import json
import gzip
import random
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from radar.summary_pipeline import parse_article


ROOT = Path(__file__).parent
SNAPSHOT = ROOT / "snapshot-261026.json.gz"
EVIDENCE = ROOT / "evidence-261026.json"
USER_AGENT = "Halcyon-review-audit/1.0"
SEED = 261026
MAX_SITE_SECONDS = 180


def read_public(session, url):
    for attempt in range(2):
        try:
            response = session.get(url, timeout=12, allow_redirects=False,
                                   headers={"User-Agent": USER_AGENT})
            if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(1)
                continue
            return response, None
        except requests.RequestException as error:
            if attempt:
                return None, type(error).__name__
            time.sleep(1)
    return None, "retry_exhausted"


def collect_site(host, rows):
    session = requests.Session()
    deadline = time.monotonic() + MAX_SITE_SECONDS
    first = rows[0][1]["url"]
    robots_url = f"{urlsplit(first).scheme}://{host}/robots.txt"
    robots_response, robots_error = read_public(session, robots_url)
    parser = RobotFileParser()
    robots_status = robots_response.status_code if robots_response is not None else None
    if robots_status == 200:
        parser.parse(robots_response.text.splitlines())
    allow = robots_status in (200, 404)
    results = []
    for index, story in rows:
        url = story["url"]
        result = {"index": index, "id": story["id"], "url": url,
                  "robots_status": robots_status, "robots_error": robots_error}
        if not allow or (robots_status == 200 and not parser.can_fetch(USER_AGENT, url)):
            result["access"] = "robots_blocked"
        elif time.monotonic() >= deadline:
            result["access"] = "site_budget_exceeded"
        else:
            response, error = read_public(session, url)
            result["http_status"] = response.status_code if response is not None else None
            result["error"] = error
            if response is None:
                result["access"] = "request_error"
            elif response.status_code in (301, 302, 303, 307, 308):
                result["access"] = "redirect"
                result["location"] = response.headers.get("Location", "")[:500]
            elif response.status_code in (401, 402, 403, 429, 451):
                result["access"] = "http_blocked"
            elif response.status_code != 200:
                result["access"] = "http_error"
            elif "html" not in response.headers.get("Content-Type", "").lower():
                result["access"] = "non_html"
            else:
                try:
                    article = parse_article(response.text, url)
                    text = "\n".join(article.parts)
                    result["article_chars"] = len(text)
                    result["article_excerpt"] = text[:1600]
                    result["article_tail"] = text[-350:]
                    result["page_title"] = (re.search(r"<title[^>]*>(.*?)</title>", response.text,
                                                       re.I | re.S) or [None, ""])[1].strip()[:250]
                    result["date_signals"] = re.findall(
                        r'(?:article:published_time|datePublished|published_time)[^\n]{0,180}',
                        response.text, re.I)[:3]
                    result["access"] = "parsed"
                except Exception as error:
                    result["access"] = "parse_error"
                    result["error"] = type(error).__name__
        results.append(result)
        time.sleep(0.3)
    session.close()
    return results


def main():
    snapshot = json.loads(gzip.decompress(SNAPSHOT.read_bytes()))
    ranked = sorted(snapshot["stories"],
                    key=lambda story: (-(story.get("importance_weight") or 0), story["id"]))
    sample = ranked[:40] + random.Random(SEED).sample(ranked[40:], 110)
    by_host = defaultdict(list)
    for index, story in enumerate(sample):
        by_host[urlsplit(story["url"]).netloc].append((index, story))
    found = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(collect_site, host, rows): host for host, rows in by_host.items()}
        for job in as_completed(jobs):
            rows = job.result()
            found.extend(rows)
            print(jobs[job], len(rows), [row["access"] for row in rows], flush=True)
    EVIDENCE.write_bytes(json.dumps({"seed": SEED, "generated_at": snapshot["generated_at"],
                                     "stories": sorted(found, key=lambda row: row["index"])},
                                    ensure_ascii=False, indent=2).encode("utf-8"))


def resolve_redirects():
    evidence = json.loads(EVIDENCE.read_bytes())
    by_host = defaultdict(list)
    for row in evidence["stories"]:
        if row["access"] != "redirect":
            continue
        target = urljoin(row["url"], row.get("location", ""))
        if not target.startswith("https://"):
            continue
        by_host[urlsplit(target).netloc].append((row["index"], {"id": row["id"], "url": target}))
    found = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [pool.submit(collect_site, host, rows) for host, rows in by_host.items()]
        for job in as_completed(jobs):
            found.extend(job.result())
    by_index = {row["index"]: row for row in found}
    for row in evidence["stories"]:
        if row["index"] in by_index:
            resolved = by_index[row["index"]]
            original_url = row["url"]
            row.update(resolved)
            row["url"] = original_url
            row["resolved_url"] = resolved["url"]
    EVIDENCE.write_bytes(json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8"))


if __name__ == "__main__":
    if "--redirects" in sys.argv:
        resolve_redirects()
    else:
        main()
