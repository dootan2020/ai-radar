"""Regression cases for repeated event stories in the published window."""

import unittest

from radar.clustering import merge_repeated_events


def story(id_, title, source, url, published_at, *, aliases=(), extra_coverage=()):
    item = {"id": id_ + "-item", "title": title, "source": source,
            "publisher": source, "group": "press", "kind": "other",
            "url": url, "published_at": published_at}
    return {"id": id_, "title": title, "url": url, "kind": "other",
            "published_at": published_at, "coverage": [item, *extra_coverage],
            "aliases": list(aliases), "groups": ["press"], "primary_section": "today",
            "source_count": 1}


class RepeatedEventTests(unittest.TestCase):
    def test_nvidia_affair_board_probe_and_share_reaction_form_one_story(self):
        shared_aliases = ["19af56563fcd9d85d737", "28f71a6dea5ea175b9c7",
                          "4524908e4807e4e12253", "e020f35ba82bcce76a3e"]
        board = story(
            "e68539633591cd5be6cb", "Statement From NVIDIA Board of Directors",
            "nvidia-newsroom", "https://nvidianews.nvidia.com/news/statement-from-nvidia-board-of-directors",
            "2026-11-08T20:00:00Z", aliases=shared_aliases,
            extra_coverage=[{
                "id": "7c4b344f9e34f95a3ad1", "source": "bloomberg-tech",
                "publisher": "bloomberg", "group": "press", "kind": "other",
                "title": "Nvidia Board to Probe Spying Case After CEO Jensen Huang Admits Infidelity",
                "url": "https://www.bloomberg.com/news/articles/2026-11-08/nvidia-board-to-probe-spying-case-after-ceo-jensen-huang-admits-infidelity",
                "published_at": "2026-11-08T20:00:02Z"}, {
                "id": "415f4a825c59e99b240e", "source": "bloomberg-tech",
                "publisher": "bloomberg", "group": "press", "kind": "other",
                "title": "Nvidia Shares Drop After CEO Huang’s Affair Triggers Board Probe",
                "url": "https://www.bloomberg.com/news/articles/2026-11-09/nvidia-shares-dip-on-robinhood-as-huang-affair-spurs-board-probe",
                "published_at": "2026-11-09T03:48:09Z"}])
        admission = story(
            "33a0483307191e736514", "Nvidia CEO Jensen Huang admits to affair with suspected Chinese spy",
            "semafor", "https://www.semafor.com/article/11/08/2026/nvidia-ceo-jensen-huang-admits-to-affair-with-suspected-chinese-spy",
            "2026-11-08T21:03:56Z", aliases=shared_aliases)
        shares = story(
            "ae270340cb4331c13028", "Nvidia shares fall amid spying allegations",
            "semafor", "https://www.semafor.com/article/11/09/2026/nvidia-shares-fall-amid-spying-allegations-and-ceo-jensen-huangs-affair",
            "2026-11-09T11:37:22Z")
        politics = story(
            "7036317f6c8e9a6ae532", "Nvidia spying scandal emboldens Washington's China hawks",
            "semafor", "https://www.semafor.com/article/11/09/2026/nvidia-spying-scandal-emboldens-washingtons-china-hawks",
            "2026-11-09T22:32:28Z")
        opinion = story(
            "3a3ea27b30526f5b6846", "The future of AI hinges on… Jensen Huang’s sex life?",
            "verge-ai", "https://www.theverge.com/ai-artificial-intelligence/1029990/jensen-huang-the-spy-who-loved-me",
            "2026-11-09T17:36:08Z")
        launch = story("launch", "Nvidia CEO Jensen Huang launches new AI GPU", "press-launch",
                       "https://press.example/nvidia-new-gpu", "2026-11-09T04:00:00Z")

        merged = merge_repeated_events([board, admission, shares, politics, opinion, launch])
        self.assertEqual(len(merged), 4)
        event = next(item for item in merged if item["id"] == board["id"])
        self.assertEqual({admission["id"], shares["id"]} & set(event["aliases"]),
                         {admission["id"], shares["id"]})
        self.assertEqual({item["id"] for item in merged},
                         {board["id"], politics["id"], opinion["id"], launch["id"]})
        self.assertEqual(len(event["coverage"]), 5)


if __name__ == "__main__":
    unittest.main()
