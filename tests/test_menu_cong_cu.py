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
        for page in ("index.html", "ban-tin.html", "nguon.html", "bento.html"):
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

    def test_icons_are_sharp_colour_logos(self):
        # Captain, 08/11: the remote 64px favicons were blurry on the iPhone ("Logo Account bị nhoè"). Each tile keeps
        # the product's own colour logo, as Google's app picker does, but from a sharp source: vector logos shipped
        # with the site (CC0 set, licence alongside) or Google's 192px product icons. Nothing loads until the panel opens.
        logos = ROOT / "site" / "google-apps"
        for name in ("site", "extension"):
            with self.subTest(copy=name):
                script = (ROOT / name / "menu-cong-cu.js").read_text(encoding="utf-8")
                self.assertNotIn("s2/favicons", script)
                self.assertIn("https://ssl.gstatic.com/images/branding/product/2x/", script)
                self.assertIn("image.alt = ''", script)
                self.assertIn("image.src = image.dataset.iconUrl", script)
                self.assertIn("link.setAttribute('aria-label', name)", script)
                self.assertEqual(script.count("['"), 13 + 4, "13 apps and 4 phone destinations")
                for svg in logos.glob("*.svg"):
                    self.assertTrue((ROOT / name / "google-apps" / svg.name).is_file(), svg.name)
        self.assertIn("['Account', 'myaccount.google.com', 'google.svg']", (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8"))
        for svg in ("google", "maps", "youtube", "gmail", "drive", "calendar", "photos", "meet", "gemini"):
            with self.subTest(logo=svg):
                self.assertTrue((logos / f"{svg}.svg").read_text(encoding="utf-8").startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox='))
        self.assertIn("CC0", (logos / "LICENSE.txt").read_text(encoding="utf-8"))
        services = (ROOT / "extension" / "vung-dau.js").read_text(encoding="utf-8")
        self.assertNotIn("s2/favicons", services)
        for svg in ("youtube", "maps", "gemini"):
            self.assertIn(f"'google-apps/{svg}.svg'", services)
        self.assertIn("translate_96dp.png", services)

    def test_phone_navigation_is_a_floating_dock(self):
        # Captain, 08/11: "Menu ở chuyển thành appdock nổi như các dock hiện đại". The dock clears the screen edges and
        # the home indicator, the current page's plate sits one padding inside the dock and its radius is the dock's
        # radius minus that padding (the dock rule approved 03/11), and the page keeps room for it.
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        mobile = css.split("@media(max-width:767px){", 1)[1]
        self.assertIn("bottom:calc(var(--dock-gap) + env(safe-area-inset-bottom))", mobile)
        self.assertIn("left:max(var(--space-16),env(safe-area-inset-left))", mobile)
        self.assertIn("border-radius:var(--dock-radius)", mobile)
        self.assertIn("padding:var(--dock-pad)", mobile)
        self.assertIn("border-radius:calc(var(--dock-radius) - var(--dock-pad))", mobile)
        self.assertIn("body{padding-bottom:calc(var(--mobile-nav-h) + var(--dock-gap) * 2 + env(safe-area-inset-bottom))}", mobile)
        # Coordinator, 08/11: through a translucent dock the headline behind it stayed readable; the dock is solid now.
        dock = mobile.split(".mobile-nav{", 1)[1].split("}", 1)[0]
        self.assertIn("background:var(--color-surface)", dock)
        self.assertNotIn("backdrop-filter", dock)
        self.assertNotIn("transparent", dock.split("background:", 1)[1].split(";", 1)[0])
        self.assertNotIn("inset-inline:0;bottom:0", mobile)

    def test_panel_supports_keyboard_focus_and_responsive_motion(self):
        script = (ROOT / "site" / "menu-cong-cu.js").read_text(encoding="utf-8")
        css = (ROOT / "site" / "menu-cong-cu.css").read_text(encoding="utf-8")
        self.assertIn("aria-expanded", script)
        self.assertIn("event.key === 'Escape'", script)
        self.assertIn("close(true)", script)
        self.assertIn("pointerdown", script)
        # The first tile takes focus only when the panel was opened from the keyboard; a click or tap focuses the
        # panel, so no ring shows on Account (coordinator, 08/11).
        self.assertIn("open(event.detail === 0)", script)
        self.assertIn("if (fromKeyboard) panel.querySelector('a')?.focus();", script)
        self.assertIn(".tool-launcher-panel:focus{outline:none}", css)
        self.assertIn(".tool-launcher-tile:focus-visible", css)
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
