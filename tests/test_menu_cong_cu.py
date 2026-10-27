from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP_HOSTS = (
    "myaccount.google.com",
    "www.google.com",
    "maps.google.com",
    "www.youtube.com",
    "mail.google.com",
    "drive.google.com",
    "calendar.google.com",
    "news.google.com",
    "photos.google.com",
    "meet.google.com",
    "translate.google.com",
    "docs.google.com",
    "gemini.google.com",
)


class GoogleAppsLauncherTests(unittest.TestCase):
    def test_launcher_is_loaded_on_each_site_header(self):
        for page in ("index.html", "ban-tin.html", "nguon.html", "tra-cuu.html", "bento.html"):
            with self.subTest(page=page):
                html = (ROOT / "site" / page).read_text(encoding="utf-8")
                self.assertIn('href="menu-cong-cu.css"', html)
                self.assertIn('src="menu-cong-cu.js"', html)

    def test_tiles_open_google_products_in_safe_new_tabs(self):
        script = (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8")
        for host in APP_HOSTS:
            with self.subTest(host=host):
                self.assertIn(host, script)
        self.assertIn("https://about.google/products/", script)
        self.assertIn("link.target = '_blank'", script)
        self.assertIn("link.rel = 'noopener noreferrer'", script)
        self.assertIn("more.rel = 'noopener noreferrer'", script)
        self.assertIn("Thêm từ Google", script)

    def test_icons_are_lazy_and_have_an_accessible_fallback(self):
        script = (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8")
        self.assertIn("image.dataset.iconUrl", script)
        self.assertIn("image.src = image.dataset.iconUrl", script)
        self.assertIn("fallback.textContent = name.slice(0, 1)", script)
        self.assertIn("image.addEventListener('error'", script)
        self.assertIn("image.alt = name", script)

    def test_panel_supports_keyboard_focus_and_responsive_motion(self):
        script = (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8")
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        self.assertIn("aria-expanded", script)
        self.assertIn("event.key === 'Escape'", script)
        self.assertIn("close(true)", script)
        self.assertIn("pointerdown", script)
        self.assertIn("grid-template-columns:repeat(3", css)
        self.assertIn("width:min(344px,calc(100vw - 24px))", css)
        self.assertIn("prefers-reduced-motion:reduce", css)
        self.assertIn("min-height:84px", css)

    def test_generated_story_pages_load_the_shared_launcher(self):
        story_page = (ROOT / "site" / "story-page.js").read_text(encoding="utf-8")
        self.assertIn("function setupToolLauncher()", story_page)
        self.assertIn("new URL('menu-cong-cu.css', import.meta.url)", story_page)
        self.assertIn("new URL('menu-cong-cu.js', import.meta.url)", story_page)


if __name__ == "__main__":
    unittest.main()
