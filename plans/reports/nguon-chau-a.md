# Asian sources for the Vietnamese morning

Measured 2026-11-12 06:29 UTC (13:29 Vietnam) with the radar's own code: `source_probe.default_fetch` and `check_robots` (radar User-Agent), `v2feeds.parse_feed`, `press_relevance.accepts_feed_item` (AI = what a `filter_ai` press source would keep) and `summary_pipeline.parse_article` (readable = the radar extractor gets the body). "Morning" = published 23:00–06:00 UTC = 06:00–13:00 Vietnam. 54 candidate feeds, one retry each; scripts were kept out of the repo.

## Prediction

**8 new AI items per morning** from the three added sources (Yonhap 6 + Analytics India Magazine 1.3 + MediaNama 1). It is a prediction to check after a week of runs. Two limits: Yonhap and MediaNama feeds hold less than a day, so their numbers come from one morning, and that morning was a heavy Nvidia news day. About 2 of Yonhap's 6 were Seoul stock-market wraps that mention Nvidia, which the newsroom may decline.

## Added (all `press`, robots.txt allows the radar UA)

| id | feed | 7-day / window measured | AI | morning AI | readable sample |
|---|---|---|---|---|---|
| `yonhap` (filter on) | en.yna.co.kr/RSS/news.xml | 50 items in 6.5 h (00:00–06:29 UTC) | 6 | 6 | 5/5 own Yonhap bylines, `isAccessibleForFree: true`, 1.5–2.3k chars extracted |
| `analytics-india-mag` (filter off, AI magazine) | analyticsindiamag.com/feed/ | 38 items / 7 d | 35 | 9 / 7 d = 1.3 | 5/5 staff bylines, free=true, 2.2–8k chars |
| `medianama` (filter on) | medianama.com/feed/ | 10 items / 23 h | 3 | 1 | 3/3 staff bylines, ~8k chars (extract starts with site chrome) |

- [CONFIRMED — https://en.yna.co.kr/RSS/news.xml, 2026-11-12] feed 200, robots 200 allowed, 6 AI items between 00:00 and 06:29 UTC; Yonhap is a state-subsidised wire, explicitly allowed by the brief.
- [CONFIRMED — https://analyticsindiamag.com/feed/, 2026-11-12] feed reaches back to 2026-11-03, so the 7-day window is complete; 3 of 38 were non-AI business items, which the press subject check already drops.
- [CONFIRMED — https://www.medianama.com/feed/, 2026-11-12] original Indian tech-policy reporting; [UNVERIFIED — feed holds only 23 h] the weekly rate.

## Rejected

| candidate | reason (boundary) |
|---|---|
| ETtech (all-tech and AI feeds) | 21 morning AI items in 3 days, but 5/5 sampled were AFP/Bloomberg/Reuters copy; AI feed 3/5 wire or ANI plus a contributor op-ed (2, re-posts) [CONFIRMED — economictimes.indiatimes.com/tech/rssfeeds/13357270.cms, 2026-11-12] |
| CNA Business/Tech (cat. 6936) | 7 morning AI in 11 h, but every sample cites Reuters 1–6 times (2) [CONFIRMED — channelnewsasia.com rss-outbound-feed, 2026-11-12] |
| Taipei Times | 6 AI/day, one batch stamped 00:00 UTC; ≥2/5 samples Bloomberg/wire reprints, 2/5 local with CNA (2, see concerns) [CONFIRMED — taipeitimes.com/xml/index.rss, 2026-11-12] |
| e27 | 23 morning AI / 6 d, but article pages return ~435 words of login shell, no body (4) [UNVERIFIED — may render with JS; not checked in a browser] |
| DigiTimes Asia | 26 AI today, but 5/5 articles stop at ~290 words (4) [UNVERIFIED — consistent with its subscription teaser] |
| Kyodo, The Hindu | own stories `isAccessibleForFree: false`, 211–398 words; also carry Reuters/AFP/Yonhap (2, 4) |
| Indian Express tech, Livemint tech | 4/5 and 3/5 samples Reuters/NYT/ANI copy (2) |
| YourStory, Inc42 | ~1 morning AI per day; YourStory 3/5 partner content; Inc42 answers 201 with an empty body (4) |
| Korea Times | every item's pubDate is the feed build time (06:27:02 GMT), so no publish time |
| Japan Times | robots.txt and articles answer 403 to the radar UA (3) |
| Korea Herald, Tech in Asia, Entrackr, Focus Taiwan | HTTP 403; Yomiuri Japan News 202 bot challenge (3) |
| Nikkei Asia | paywalled; 0 items parsed in 7 d (4) |
| KrASIA, JoongAng Daily, Kyodo all.xml, Sony AI, LG AI Research, Zhipu, Moonshot | no feed: 404 and no autodiscovered link |
| KED Global, CnTechPost, Straits Times | 502 / connection failed / tech RSS 400 |
| Synced, The Bridge, Chosun, BusinessKorea, Moneycontrol, NHK (ja) | no item in the last 7 days (Synced last post 2025-08) |
| Samsung Newsroom | 4 items / 7 d, 1 AI, 0 in the morning |
| PFN tech blog, Baidu Research, Naver Clova, Alibaba Cloud blog | feed not well-formed, not RSS, or redirect without feed |
| Global Times, China Daily, CGTN, Xinhua, Sixth Tone, Yicai | not probed (5) [UNVERIFIED — excluded by rule, not measured] |
| Caixin | not probed, known hard paywall (4) [UNVERIFIED] |

## Concerns

- Taiwan has no new source: Focus Taiwan blocks (403), DigiTimes is paywalled, Taipei Times re-posts wire copy. Adding Taipei Times would give about 6 AI items each morning, roughly half re-posted; I left it out to keep boundary 2.
- Japan and Southeast Asia gain nothing new: every Japanese newsroom tried blocked, paywalled or re-posted, and e27 could not be read without JavaScript.
- No Asian lab blog has a working feed today (PFN malformed, LG/Naver/Moonshot/Zhipu none).
