"""Cloudflare hosting config and legacy GitHub Pages redirect coverage."""

from pathlib import Path
import tempfile
import unittest

from radar.legacy_redirects import build_redirect_site
from radar.site_config import SITE_BASE_URL, SITE_URL


ROOT = Path(__file__).resolve().parents[1]


class CloudflarePagesTests(unittest.TestCase):
    def test_public_site_address_is_shared_by_build_and_health_checks(self):
        from radar.health_probe import SITE_URL as health_url
        from radar.seo import SITE_URL as seo_url
        from radar.story_pages import BASE_URL

        self.assertEqual(SITE_URL, "https://radar-ai-vn.pages.dev/")
        self.assertEqual(health_url, seo_url)
        self.assertEqual(BASE_URL, SITE_BASE_URL)
        host = SITE_URL.removeprefix("https://").split(".", 1)[0]
        workflow = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
        self.assertIn(f"--project-name {host} ", workflow)
        for path in ("video/render.js", "video/src/daily-audio.js", "video/src/components/OutroScene.jsx"):
            self.assertIn(host + ".pages.dev", (ROOT / path).read_text(encoding="utf-8"))
        stale_host = "ai-radar" + ".pages.dev"
        for page in (ROOT / "site").rglob("*.html"):
            self.assertNotIn(stale_host, page.read_text(encoding="utf-8"), page)

    def test_redirect_artifact_covers_root_and_generated_story_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site, output = root / "site", root / "legacy-pages"
            (site / "tin" / "story-1").mkdir(parents=True)
            (site / "tin" / "story-1" / "index.html").write_text("story", encoding="utf-8")
            (site / "tin" / "alias_2").mkdir(parents=True)
            (site / "tin" / "alias_2" / "index.html").write_text("alias", encoding="utf-8")
            (site / "tin" / "_sample").mkdir()
            (site / "tin" / "_sample" / "index.html").write_text("sample", encoding="utf-8")
            (site / "bento.html").write_text(
                '<!doctype html><html><head><title>A &amp; B</title>'
                '<meta name="description" content="A &quot;quoted&quot; summary &amp; more">'
                '<meta property="og:title" content="A &lt;story&gt;">'
                '<meta name="twitter:card" content="summary_large_image">'
                '</head></html>', encoding="utf-8")

            pages, slugs = build_redirect_site(site, output)
            self.assertEqual(pages, ["bento.html"])
            self.assertEqual(slugs, ["alias_2", "story-1"])
            homepage = (output / "index.html").read_text(encoding="utf-8")
            story = (output / "tin" / "story-1" / "index.html").read_text(encoding="utf-8")
            page = (output / "bento.html").read_text(encoding="utf-8")
            self.assertIn(f'<link rel="canonical" href="{SITE_URL}">', homepage)
            self.assertIn(f'<meta http-equiv="refresh" content="0; url={SITE_URL}">', homepage)
            self.assertIn(f'{SITE_BASE_URL}/tin/story-1/', story)
            self.assertIn(f'<link rel="canonical" href="{SITE_BASE_URL}/bento.html">', page)
            self.assertIn("<title>A &amp; B</title>", page)
            self.assertIn('name="description" content="A &quot;quoted&quot; summary &amp; more"', page)
            self.assertIn('property="og:title" content="A &lt;story&gt;"', page)
            self.assertIn('name="twitter:card" content="summary_large_image"', page)
            self.assertTrue((output / "404.html").is_file())
            not_found = (output / "404.html").read_text(encoding="utf-8")
            self.assertIn("oldPath.slice('/ai-radar'.length)", not_found)
            self.assertIn("window.location.replace(destination)", not_found)
            self.assertFalse((output / "tin" / "_sample").exists())

    def test_workflow_deploys_cloudflare_before_publishing_legacy_redirects(self):
        workflow = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
        self.assertIn("CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_PAGES_API_TOKEN }}", workflow)
        self.assertIn("CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}", workflow)
        self.assertIn("CLOUDFLARE_PAGES_API_TOKEN is required", workflow)
        deploy = workflow.split("  deploy:\n", 1)[1].split("  deploy-legacy-redirects:\n", 1)[0]
        self.assertIn("actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020", deploy)
        self.assertIn("node-version: '22'", deploy)
        self.assertLess(deploy.index("actions/setup-node@"), deploy.index("npx --yes wrangler@4"))
        self.assertIn("needs.deploy.result == 'success'", workflow)
        self.assertIn("name: Download built site for story redirects", workflow)
        self.assertIn("name: radar-cloudflare-site-${{ github.run_id }}", workflow)
        self.assertIn("python -m radar.legacy_redirects --site site --output legacy-pages", workflow)
        self.assertLess(workflow.index("npx --yes wrangler@4 pages deploy site"),
                        workflow.index("deploy-legacy-redirects:"))
        self.assertIn('python -m radar.story_pages prepare --remote "$STORY_REMOTE"', workflow)


if __name__ == "__main__":
    unittest.main()
