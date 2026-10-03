"""Generate the sitemap from the accepted publication's original timestamp."""

import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from radar.common import iso_date
from radar.items import instant

SITE_URL = "https://dootan2020.github.io/ai-radar/"


def sitemap_xml(generated_at):
    stamp = instant(generated_at)
    if stamp is None:
        raise ValueError("sitemap needs an explicit publication timestamp")
    root = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    entry = ET.SubElement(root, "url")
    ET.SubElement(entry, "loc").text = SITE_URL
    ET.SubElement(entry, "lastmod").text = iso_date(stamp)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def write_sitemap(generated_at, path):
    content = sitemap_xml(generated_at)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".sitemap-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
