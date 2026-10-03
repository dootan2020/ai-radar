# Source feed verification — 2026-10-03

This is dated investigation evidence, not a replacement source catalog. The
coordinator opened the official publisher pages below with the web tool and
checked candidate feed URLs. Local direct HTTP attempts were blocked at the
socket layer, before a usable response; the web tool could not parse RSS bodies.
Consequently, no new official RSS replacement was verified end to end.

The [lab inventory](../radar/feeds.py) remains authoritative. Existing mirrors
stay explicitly attributed as community feeds. Publisher identity and
successful parsing on the hosted runner are both required before replacing an
endpoint. An accessible official news page does not prove an RSS feed exists;
an inaccessible candidate does not prove none exists.

| Source ID | Official page or feed examined | Evidence and decision |
| --- | --- | --- |
| `anthropic-news` | [News](https://www.anthropic.com/news); `/news/rss.xml`, `/rss.xml` | News page opened. Both candidate RSS addresses returned 404 through the web tool. Retain existing attributed mirror; other possible official endpoints remain unverified. |
| `anthropic-gftdon` | [News](https://www.anthropic.com/news) | Same publisher check; no official feed replacement verified. Retain the separately attributed gftdon mirror, which is not an independent publisher for ranking. |
| `anthropic-research` | [Research](https://www.anthropic.com/research); `/research/rss.xml` | Official page opened; candidate RSS inaccessible through available tools. Retain mirror; endpoint nonexistence is not established. |
| `anthropic-engineering` | [Engineering](https://www.anthropic.com/engineering); `/engineering/rss.xml` | Official page opened; candidate RSS inaccessible through available tools. Retain mirror under the same uncertainty. |
| `xai-news` | [News](https://x.ai/news); `/news/rss.xml` | Official page opened; candidate RSS returned 404 through the web tool. Retain mirror; this does not rule out other official feed addresses. |
| `meta-news` | [AI blog](https://ai.meta.com/blog/); `/blog/rss/`, `/blog/rss.xml` | Official page opened; candidate feed bodies could not be inspected. Retain mirror; no confirmed replacement. |
| `mistral-news` | [News](https://mistral.ai/news/); `/rss.xml`, `/news/rss.xml`, `/feed.xml` | Official page opened; candidates inaccessible through available tools. Retain mirror; no confirmed replacement. |
| `openai-news` | [Existing RSS](https://openai.com/news/rss.xml) | Web tool recognized XML content but could not parse it. The captured live snapshot records this source as successful. Keep current official source; no new local parse claim. |
| `google-ai` | [Existing RSS](https://blog.google/technology/ai/rss/) | Same XML/tool limit; captured snapshot records success. Keep current official source. |
| `huggingface-blog` | [Existing feed](https://huggingface.co/blog/feed.xml) | Same XML/tool limit; captured snapshot records success. Keep current official source. |
| `google-deepmind` | [Existing RSS](https://deepmind.google/blog/rss.xml) | Web tool identified XML content, which does not prove valid XML for the collector. Keep disabled under the [previous runner failure decision](p1-r2-source-status.md) until a real runner parse succeeds. |

The [Olshansk RSS mirror inventory](https://github.com/Olshansk/rss-feeds)
identifies its feeds as mirrors and lists DeepMind's official RSS. This verifies
mirror provenance, not freshness or uptime. The gftdon endpoint is independently
identified in the repository's source catalog; no stronger verification of that
mirror is asserted here.

The captured `plans/nhap/live-radar.json` snapshot supplied success records for
the currently working official feeds; it is historical evidence, not a probe
performed by this documentation task. No source URL or enabled/disabled policy
was changed in this check. Hosted-runner response-body and parser verification
remains open for any proposed replacement.
