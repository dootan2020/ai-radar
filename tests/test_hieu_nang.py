"""The front page's first load on a phone (captain, 11/11 01:03: "Sửa ngay đi e", the Chrome Web Store launch blockers).
Measured on https://hco.news with Lighthouse 13.5 mobile that night: 4.06 MB on first load and an LCP of 19.9 s, because
the lead slide's picture was a publisher's 6000x4000 original (2.0 MB) and the carousel's hidden slides fetched theirs
too; /robots.txt answered with the home page; the CSP blocked the beacon Cloudflare injects on hco.news.

These checks keep the fixes in place: robots.txt names the sitemap, every reader page's CSP admits the injected beacon's
path, the lead picture is fetched eagerly at the width its slot needs, slides 2 and on carry no address until they are
about to show, and the complete snapshot waits for the reader. The rendered top row at 1024 to 1440 px is checked by
tests/verify-top-row-fit.mjs (RenderedTopRowFit below)."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

try:
    from test_tim_kiem_giua import browser_ready
except ImportError:
    from tests.test_tim_kiem_giua import browser_ready

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
EXT = ROOT / "extension"
READER_PAGES = ("index.html", "ban-tin.html", "nguon.html", "chinh-sach-rieng-tu.html")
# The script Cloudflare injects on hco.news (11/11 console error), next to the one the pages load themselves.
INJECTED_BEACON = "https://static.cloudflareinsights.com/beacon.min.js/vce701823e78c4301a35b7e07294d87301792088814092"


def read(path):
    return path.read_text(encoding="utf-8")


def script_sources(html):
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    for part in meta.group(1).split(";"):
        words = part.split()
        if words and words[0] == "script-src":
            return words[1:]
    raise AssertionError("no script-src")


def allows(sources, url):
    """CSP3 host-source matching for an https URL: same scheme and host, and a path that equals the source's path, or
    starts with it when the source's path ends in '/'. Keywords and hashes never match a URL."""
    u = urlsplit(url)
    for s in sources:
        if s.startswith("'"):
            continue
        p = urlsplit(s)
        if (p.scheme, p.netloc) != (u.scheme, u.netloc):
            continue
        if not p.path or p.path == "/" or (p.path.endswith("/") and u.path.startswith(p.path)) or u.path == p.path:
            return True
    return False


class RobotsTxt(unittest.TestCase):
    def test_robots_txt_allows_crawling_and_names_the_sitemap(self):
        lines = [l.strip() for l in read(SITE / "robots.txt").splitlines() if l.strip()]
        self.assertEqual(lines[0], "User-agent: *")
        self.assertIn("Allow: /", lines)
        self.assertIn("Sitemap: https://hco.news/sitemap.xml", lines)
        self.assertFalse(any(l.lower().startswith("disallow: /") and l.strip().lower() == "disallow: /" for l in lines))


class BeaconPolicy(unittest.TestCase):
    def test_every_reader_page_admits_the_injected_beacon_and_nothing_wider(self):
        from radar.story_pages import CONTENT_SECURITY_POLICY
        policies = {name: read(SITE / name) for name in READER_PAGES}
        policies["story pages"] = f'<meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">'
        for name, html in policies.items():
            sources = script_sources(html)
            self.assertTrue(allows(sources, INJECTED_BEACON), name)
            # One beacon (coordinator, 11/11): the bare file, a snippet's address, is no longer admitted; nor is any
            # other script on that host.
            self.assertFalse(allows(sources, "https://static.cloudflareinsights.com/beacon.min.js"), name)
            self.assertFalse(allows(sources, "https://static.cloudflareinsights.com/other.js"), name)
            self.assertNotIn("data-cf-beacon", html, name)

    def test_the_matcher_follows_the_csp_path_rule(self):
        self.assertFalse(allows(["https://static.cloudflareinsights.com/beacon.min.js"], INJECTED_BEACON))
        self.assertTrue(allows(["https://static.cloudflareinsights.com/beacon.min.js/"], INJECTED_BEACON))


HARNESS = r"""
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
const aiBadgeHTML = () => '';
const PICS = {
  s0: { kind: 'photo', via: 'feed-media', src: 'https://img.semafor.com/a62d-6000x4000.jpg' },
  s1: { kind: 'photo', via: 'og:image', src: 'https://techcrunch.com/wp-content/uploads/2026/11/x.png?resize=1200,675' },
  s2: { kind: 'photo', via: 'og:image', src: 'https://example.org/full.jpg' },
  s3: { kind: 'cover', via: 'cover', src: 'assets/cover/a.png', tall: 'assets/cover/a-tall.png' },
};
const pickImage = st => PICS[st.id];
const titleOf = st => ({ text: st.title });
const statusClass = () => '', storyStatus = () => 'new', storyHref = st => `tin/${st.id}/`, langAttr = () => '';
const metaHTML = () => '';
__CODE__
const html = leadHTML(['s0', 's1', 's2', 's3'].map(id => ({ id, title: 'Tin ' + id })));
const slides = html.split('<article class="slide').slice(1);
const imgOf = s => (s.match(/<img [^>]*>/) || [''])[0];
const fake = tag => {
  const attrs = {}, dataset = {};
  for (const [, k, v] of tag.matchAll(/ ([\w-]+)="([^"]*)"/g)) {
    const val = v.replace(/&quot;/g, '"').replace(/&amp;/g, '&');   // as a browser reads the attribute
    if (k.startsWith('data-')) dataset[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = val; else attrs[k] = val;
  }
  return { dataset, attrs, setAttribute(k, v) { attrs[k] = v; }, getAttribute(k) { return attrs[k] ?? null; } };
};
const second = fake(imgOf(slides[1]));
wakeSlides([{ querySelectorAll: () => (second.dataset.src ? [second] : []) }]);
process.stdout.write(JSON.stringify({
  slides: slides.map(imgOf),
  woken: second.attrs,
  sized: { semafor: sizedSrc('https://img.semafor.com/a-6000x4000.jpg', 828), wp: sizedSrc('https://i0.wp.com/x.com/wp-content/uploads/a.jpg?fit=1920%2C1080&ssl=1', 640),
    wired: sizedSrc('https://media.wired.com/photos/abc/master/pass/x.jpg', 640), other: sizedSrc('https://example.org/full.jpg', 640),
    relative: sizedSrc('assets/ai/x.webp', 640) },
  card: mediaHTML(PICS.s0, 'card'),
  wide: mediaHTML(PICS.s1, 'wide'),
  cover: mediaHTML(PICS.s3, 'card'),
  margin: CARD_PICTURE_MARGIN,
  wokenCard: (() => { const c = fake(mediaHTML(PICS.s1, 'wide').match(/<img [^>]*>/)[0]); wakePicture(c); return c.attrs; })(),
}));
"""


@unittest.skipUnless(shutil.which("node"), "Node required for the lead carousel test")
class LeadPictures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        feed = read(SITE / "feed.js")
        start = feed.index("const RESIZERS = [")
        end = feed.index("\n/* With no prev/next buttons", start)
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "lead.mjs"
            harness.write_text(HARNESS.replace("__CODE__", feed[start:end]), encoding="utf-8", newline="\n")
            run = subprocess.run(["node", str(harness)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        if run.returncode != 0:
            raise AssertionError(run.stderr)
        cls.got = json.loads(run.stdout)

    def test_the_lead_picture_is_fetched_first_and_never_lazily(self):
        lead = self.got["slides"][0]
        self.assertIn('loading="eager"', lead)
        self.assertNotIn('loading="lazy"', lead)
        self.assertIn('fetchpriority="high"', lead)
        self.assertNotIn("data-src", lead)
        # At the width its slot needs, from the publisher's own resizer: never the 6000x4000 original.
        self.assertIn(' src="https://img.semafor.com/a62d-6000x4000.jpg?w=828"', lead)
        self.assertIn("?w=480 480w", lead)
        self.assertIn('sizes="(max-width: 1023px) 100vw, 50vw"', lead)

    def test_hidden_slides_carry_no_address_until_they_are_about_to_show(self):
        for tag in self.got["slides"][1:]:
            self.assertIsNone(re.search(r' (src|srcset)="', tag), tag)
            self.assertIn(' data-src="', tag)
            self.assertNotIn('fetchpriority="high"', tag)
        woken = self.got["woken"]
        self.assertTrue(woken["src"].startswith("https://techcrunch.com/wp-content/uploads/2026/11/x.png?resize=1200%2C675&w="), woken)
        self.assertIn(" 1280w", woken["srcset"])

    def test_showing_or_nearing_a_slide_wakes_its_picture(self):
        feed = read(SITE / "feed.js")
        show = feed[feed.index("function showSlide(lead, n) {"):feed.index("\n}\n", feed.index("function showSlide(lead, n) {"))]
        self.assertIn("wakeSlides([slides[k], slides[(k + 1) % slides.length]]);", show)
        self.assertIn("for (const type of ['pointerover', 'focusin', 'touchstart']) document.addEventListener(type, onLeadIntent, { passive: true });", feed)

    def test_only_publishers_own_resizers_are_asked(self):
        s = self.got["sized"]
        self.assertEqual(s["semafor"], "https://img.semafor.com/a-6000x4000.jpg?w=828")
        self.assertEqual(s["wp"], "https://i0.wp.com/x.com/wp-content/uploads/a.jpg?fit=1920%2C1080&ssl=1&w=640")
        self.assertEqual(s["wired"], "https://media.wired.com/photos/abc/master/w_640,c_limit/x.jpg")
        self.assertIsNone(s["other"])
        self.assertIsNone(s["relative"])
        # A phone's card picture is the 104 px thumbnail beside the headline; three columns (768-1023) give a card a third.
        self.assertIn('sizes="(max-width: 767px) 112px, (max-width: 1023px) 34vw, 25vw"', self.got["card"])
        self.assertIn('loading="lazy"', self.got["card"])

    def test_card_pictures_wait_until_the_card_nears_the_screen(self):
        # 11/11, live: a phone fetched the pictures of cards two and three screens down with the page (a 470 KB
        # TechCrunch PNG at w=960), because a browser's own loading="lazy" reaches 1250 px past the screen. A card's
        # picture now has no address until watchCardPictures sees it within about one screen.
        for key in ("card", "wide", "cover"):
            tag = self.got[key]
            self.assertIsNone(re.search(r' (src|srcset)="', tag), tag)
            self.assertIn(' data-src="', tag)
            self.assertNotIn('fetchpriority="high"', tag)
        self.assertIn('data-srcset="', self.got["wide"])
        self.assertIn('width="640" height="360"', self.got["wide"])   # a card keeps its card widths, not the lead's
        self.assertNotIn(" 1280w", self.got["wide"])
        self.assertEqual(self.got["margin"], "600px 0px")
        woken = self.got["wokenCard"]
        self.assertIn("&w=640", woken["src"])
        self.assertIn(" 960w", woken["srcset"])
        feed = read(SITE / "feed.js").replace("\r\n", "\n")
        init = feed[feed.index("async function init() {"):]
        self.assertIn("  watchCardPictures();\n", init[:init.index("\n}\n")])
        watch = feed[feed.index("function watchCardPictures() {"):]
        watch = watch[:watch.index("\n}\n")]
        self.assertIn("new IntersectionObserver(", watch)
        self.assertIn("img.closest('.slide')", watch)   # slides stay with wakeSlides
        self.assertIn(".observe(document.body, { childList: true, subtree: true })", watch)


class FirstLoadBudget(unittest.TestCase):
    def test_the_complete_snapshot_waits_for_the_reader_on_the_site(self):
        feed = read(SITE / "feed.js")
        self.assertIn("  whenReaderActs().then(loadComplete);\n  if (!FIELD_DATA) whenIdle()", feed.replace("\r\n", "\n"))
        self.assertNotIn("whenIdle().then(loadComplete)", feed)
        acts = feed[feed.index("function whenReaderActs() {"):]
        types = re.search(r"const types = \[([^\]]*)\]", acts).group(1)
        for t in ("scroll", "pointerdown", "click", "keydown", "touchstart", "focusin", "wheel"):
            self.assertIn(f"'{t}'", types)

    def test_the_saved_list_and_a_section_wait_for_the_complete_snapshot(self):
        # Not driven in a browser: any click that opens a chip is also the reader's first interaction, which loads the
        # complete snapshot anyway, so a rendered check could not tell the two paths apart.
        feed = read(SITE / "feed.js").replace("\r\n", "\n")
        body = feed[feed.index("function setFilter(f, fromHash = false) {"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("if (!complete && (f === 'saved' || f.startsWith('sec:'))) {", body)
        self.assertIn("loadComplete().then(() => { setLoading(false); if (filter === f) renderFeed(); });", body)
        self.assertIn("} else renderFeed();", body)

    def test_the_first_draw_s_files_are_asked_for_with_the_page(self):
        html = read(SITE / "index.html")
        for mod in ("story.js", "arena.js", "thoi-tiet.js", "the-lich.js", "lich-am.js", "trinh-phat.js", "editorial-headline.js", "worth-score.js"):
            self.assertIn(f'<link rel="modulepreload" href="{mod}">', html)
        for data in ("feed-images.json", "data/radar-window.json"):
            self.assertIn(f'<link rel="preload" href="{data}" as="fetch" crossorigin>', html)
        tab = read(EXT / "newtab.html")
        self.assertNotIn('rel="preload"', tab)
        self.assertNotIn("trinh-phat.js", tab)


@unittest.skipUnless(browser_ready(), "Node, Chrome and puppeteer are needed for the rendered top row")
class RenderedTopRowFit(unittest.TestCase):
    """Coordinator, 11/11 (the Store screenshot at 1280x800): the search ran over the date ("Thứ Tư, 11/11/202…") and the
    order control showed only "Đáng đọc". At 1024, 1280, 1366 and 1440 on the site and the unpacked new tab: the corner
    ends before the search, nothing in it is cut, the search stays centred, and both orders show whole."""

    @classmethod
    def setUpClass(cls):
        run = subprocess.run(["node", "tests/verify-top-row-fit.mjs"], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", timeout=300)
        if run.returncode != 0:
            raise AssertionError(run.stderr[-2000:])
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])

    def test_every_width_fits(self):
        pages = self.out["pages"]
        self.assertEqual(len(pages), 8)
        for name, m in pages.items():
            self.assertLessEqual(m["cornerRight"], m["searchLeft"] - 8, f"{name}: the corner runs under the search {m}")
            self.assertLessEqual(m["cornerOverflow"], 0, f"{name}: the corner is cut {m}")
            self.assertLessEqual(abs(m["searchCentre"]), 1, f"{name}: the search left the middle {m}")
            self.assertTrue(m["date"], name)
            self.assertEqual(m["orders"], [], f"{name}: the order lives on Tin mới now (captain, 11/11 12:3x)")
            self.assertEqual(m["ordersCut"], [], name)
            self.assertLessEqual(m["headOverflow"], 0, name)
            self.assertFalse(m["sideways"], name)

    def test_at_1280_the_whole_date_or_its_day_and_month_show(self):
        for target in ("site", "ext"):
            m = self.out["pages"][f"{target}-1280"]
            self.assertRegex(m["date"], r"\d{2}/\d{2}", target)

    def test_the_complete_snapshot_waits_for_the_first_scroll(self):
        self.assertEqual(self.out["complete"]["untouched"], 0)
        self.assertGreaterEqual(self.out["complete"]["afterScroll"], 1)

    def test_no_errors(self):
        self.assertEqual(self.out["errors"], [])


if __name__ == "__main__":
    unittest.main()
