"""Build the minimal GitHub Pages compatibility site for old shared URLs."""

import argparse
import html
from pathlib import Path
import re
from html.parser import HTMLParser

from radar.site_config import SITE_BASE_URL, SITE_URL

SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


class PreviewMetadata(HTMLParser):
    """Collect crawler-facing metadata from a built page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts = []
        self.in_title = False
        self.meta = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = attrs.get("name", "")
            prop = attrs.get("property", "")
            name_lower, prop_lower = name.lower(), prop.lower()
            if (name_lower == "description" or prop_lower == "description"
                    or name_lower.startswith(("og:", "twitter:"))
                    or prop_lower.startswith(("og:", "twitter:"))) and "content" in attrs:
                if prop_lower.startswith(("og:", "twitter:")) or prop_lower == "description":
                    key, value = "property", prop
                else:
                    key, value = "name", name
                self.meta.append((key, value, attrs["content"]))

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)


def preview_metadata(page):
    parser = PreviewMetadata()
    if page is not None and Path(page).is_file():
        parser.feed(Path(page).read_text(encoding="utf-8"))
    title = "".join(parser.title_parts).strip() or "Chuyển tới ai·radar"
    title_tag = f"<title>{html.escape(title)}</title>\n"
    meta_tags = "".join(
        f'<meta {key}="{html.escape(name, quote=True)}" content="{html.escape(content, quote=True)}">\n'
        for key, name, content in parser.meta
    )
    return title_tag + meta_tags


def redirect_page(target_url, source_page=None):
    target = html.escape(target_url, quote=True)
    preview = preview_metadata(source_page)
    return ("<!doctype html>\n<html lang=\"vi\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<link rel=\"canonical\" href=\"{target}\">\n"
            f"<meta http-equiv=\"refresh\" content=\"0; url={target}\">\n"
            f"{preview}</head>\n<body>\n"
            f"<p>Trang đã chuyển. <a href=\"{target}\">Mở ai·radar</a>.</p>\n"
            "</body>\n</html>\n")


def build_redirect_site(site, output):
    """Write previews and redirects for published root, page, and story URLs."""
    site, output = Path(site), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    home = site / "index.html"
    (output / "index.html").write_text(redirect_page(SITE_URL, home), encoding="utf-8", newline="\n")
    pages = []
    for page in sorted(site.glob("*.html")):
        if page.name == "index.html":
            continue
        target = f"{SITE_BASE_URL}/{page.name}"
        (output / page.name).write_text(redirect_page(target, page), encoding="utf-8", newline="\n")
        pages.append(page.name)
    slugs = []
    for page in sorted((site / "tin").glob("*/index.html")):
        slug = page.parent.name
        if not SLUG.fullmatch(slug):
            continue
        target = f"{SITE_BASE_URL}/tin/{slug}/"
        destination = output / "tin" / slug / "index.html"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(redirect_page(target, page), encoding="utf-8", newline="\n")
        slugs.append(slug)
    (output / "404.html").write_text(not_found_page(), encoding="utf-8", newline="\n")
    return pages, slugs


def not_found_page():
    base = html.escape(SITE_BASE_URL, quote=True)
    return ("<!doctype html>\n<html lang=\"vi\">\n<head>\n"
            "<meta charset=\"utf-8\">\n<meta name=\"robots\" content=\"noindex\">\n"
            "<title>Chuyển tới ai·radar</title>\n</head>\n<body>\n"
            "<p>Trang đã chuyển. <a id=\"fallback\">Mở ai·radar</a>.</p>\n"
            "<script>\n"
            f"const base = '{base}';\n"
            "let oldPath = window.location.pathname;\n"
            "if (oldPath === '/ai-radar') oldPath = '/';\n"
            "else if (oldPath.startsWith('/ai-radar/')) oldPath = oldPath.slice('/ai-radar'.length);\n"
            "const destination = base + oldPath + window.location.search + window.location.hash;\n"
            "document.getElementById('fallback').href = destination;\n"
            "window.location.replace(destination);\n"
            "</script>\n</body>\n</html>\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="site", help="built site containing tin/<slug>/index.html")
    parser.add_argument("--output", required=True, help="directory for the compatibility Pages artifact")
    args = parser.parse_args(argv)
    pages, slugs = build_redirect_site(args.site, args.output)
    print(f"Built root redirect, {len(pages)} page redirects, and {len(slugs)} story redirects")


if __name__ == "__main__":
    main()
