"""Measure clustering and hot-rank changes against the checked-in UI snapshot."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar.clustering import cluster_items
from radar.ranking import rank_stories


SNAPSHOTS = [Path(__file__).resolve().parents[1] / "plans" / "reports" / name
             for name in ("radar-ui-live.json", "radar-ui-fresh.json")]


def _ranked(stories):
    eligible = [story for story in stories if isinstance(story.get("hot_score"), (int, float))]
    return sorted(eligible, key=lambda story: (-story["hot_score"], story["id"]))


def _target_rank(stories, predicate):
    return next((index for index, story in enumerate(stories, 1) if predicate(story)), None)


def _measurement(stories):
    ranked = _ranked(stories)
    return {
        "multi_source_stories": sum(story.get("source_count", 0) >= 2 for story in stories),
        "null_hot_score": sum(story.get("hot_score") is None for story in stories),
        "ranks": {
            "Reflection Beam": _target_rank(
                ranked, lambda story: any("reflection" in item.get("title", "").lower()
                                          and "beam" in item.get("title", "").lower()
                                          for item in story.get("coverage", []))),
            "Mistral Large 4": _target_rank(
                ranked, lambda story: any("mistral large 4" in item.get("title", "").lower()
                                          for item in story.get("coverage", []))),
            "Meta Muse iPad": _target_rank(
                ranked, lambda story: any("muse" in item.get("title", "").lower()
                                          and "ipad" in item.get("title", "").lower()
                                          for item in story.get("coverage", []))),
            "DeepSeek 4.1 Flash HN": _target_rank(
                ranked, lambda story: any("why isn't the industry freaking out about deepseek 4.1 flash"
                                          in item.get("title", "").lower()
                                          for item in story.get("coverage", []))),
        },
        "top_20": [{"rank": index, "title": story["title"], "hot_score": story["hot_score"]}
                   for index, story in enumerate(ranked[:20], 1)],
    }


def main():
    results = {}
    for path in SNAPSHOTS:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        before = snapshot["stories"]
        observations = {}
        for story in before:
            for item in story.get("coverage", []):
                observations[(item.get("source"), item.get("id"))] = item
        raw_items = list(observations.values())
        now = snapshot["generated_at"]
        after = rank_stories(cluster_items(raw_items, now), now)
        results[path.name] = {"before": _measurement(before), "after": _measurement(after)}
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
