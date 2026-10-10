"""Observations that are not news are refused with a reason; news about hiring is not."""

import unittest

from radar.noise import REASONS, noise_reason
if __package__:
    from .test_v2_support import coverage
else:
    from test_v2_support import coverage


def forum(title, url="https://example.org/post"):
    return coverage("hn-front", url, publisher="hacker-news", group="forum", kind="forum", title=title,
                    discussion_url="https://news.ycombinator.com/item?id=1")


class JobPostTests(unittest.TestCase):
    def test_forum_job_ads_and_hiring_threads_are_refused(self):
        for title in ("Synthetica (YC S24) is hiring founding ML engineers",
                      "We're hiring: inference engineers in Berlin",
                      "Ask HN: Who is hiring? (November 2026)",
                      "Ask HN: Who wants to be hired? (November 2026)"):
            with self.subTest(title=title):
                self.assertEqual(noise_reason(forum(title)), "job-post")

    def test_links_to_job_boards_are_refused_whoever_posts_them(self):
        for url in ("https://jobs.ashbyhq.com/example", "https://boards.greenhouse.io/example/jobs/1",
                    "https://jobs.lever.co/example/abc", "https://www.ycombinator.com/companies/example/jobs/x"):
            with self.subTest(url=url):
                item = coverage("press-a", url, title="Senior research engineer, agents")
                self.assertEqual(noise_reason(item), "job-post")

    def test_reporting_on_hiring_and_ordinary_posts_stay(self):
        kept = [
            coverage("press-a", "https://press.example/a", title="Synthetic lab is hiring a head of preparedness"),
            forum("Hiring freezes spread as AI coding tools mature"),
            forum("Show HN: An open-source evaluator for agent tool calls"),
            coverage("press-a", "https://www.ycombinator.com/blog/agents", title="Notes on agents"),
        ]
        for item in kept:
            with self.subTest(title=item["title"]):
                self.assertIsNone(noise_reason(item))

    def test_every_reason_has_a_reader_sentence(self):
        self.assertTrue(all(REASONS.values()))
        self.assertIn(noise_reason(forum("Example (YC W26) is hiring")), REASONS)

    def test_malformed_urls_do_not_raise(self):
        for url in (None, "", "not a url", "https://[::1"):
            with self.subTest(url=url):
                self.assertIsNone(noise_reason(dict(coverage(title="Model release"), url=url)))


class AssemblyTests(unittest.TestCase):
    def test_build_refuses_job_posts_and_tells_a_retitled_report_once(self):
        from copy import deepcopy
        from radar import assembly
        from radar.clustering import cluster_items
        if __package__:
            from .test_v2_support import NOW
        else:
            from test_v2_support import NOW
        job = forum("Example (YC W26) is hiring research engineers", url="https://jobs.ashbyhq.com/example")
        fresh = coverage("wire", "https://wire.example/videos/chips", publisher="wire",
                         title="Lattice in Early Financing Talks for OpenAI Chips")
        old_retitle = coverage("wire", "https://wire.example/articles/chips", publisher="wire",
                               title="Lattice Holds Early Talks About Financing for OpenAI Chips",
                               published_at="2026-10-01T22:00:00Z")
        old_job = forum("Other (YC S25) is hiring", url="https://boards.greenhouse.io/other")
        published = dict(schema_version=2, generated_at=NOW.isoformat(),
                         stories=cluster_items([old_retitle], NOW) + cluster_items([old_job], NOW))
        before = deepcopy(published)
        result = assembly.finish(dict(sources=[], trending={}), [job, fresh], [], NOW, None,
                                 published=published, resolve_images=False)
        self.assertEqual(published, before)
        self.assertEqual(len(result["stories"]), 1)
        story = result["stories"][0]
        self.assertEqual(sorted(c["url"] for c in story["coverage"]), sorted([fresh["url"], old_retitle["url"]]))
        self.assertIn(published["stories"][0]["id"], story["aliases"])
        self.assertTrue(all(set(ids) <= {story["id"]} for ids in result["sections"].values()))


if __name__ == "__main__":
    unittest.main()
