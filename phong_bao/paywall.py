"""Stories whose own article needs a subscription or an account, and nothing readable replaces it.

Captain, 2026-11-05: "Cái nào đòi tài khoản hoặc paywall mà không có nguồn thay thế thì loại luôn".
The chief holds such a story instead of publishing a headline with no readable source. Evidence is
either the fetch result itself (reason "paywall") or a publisher measured as paywalled. Bot walls,
robots.txt refusals, timeouts and JavaScript-only pages are not evidence of a paywall and keep
today's behaviour.
"""

from __future__ import annotations

from urllib.parse import urlsplit

HOLD_REASON = "paywalled or login-only source, no readable alternative"
# Host, path prefix, evidence. Measured 2026-11-04 in nguon-khong-doc-duoc-halcyon.md (readonly probe
# of every lost URL with the runner's own reader). x.com is not here: that report measured a robots.txt
# refusal there, not a login wall.
PAYWALLED = (
    ("bloomberg.com", "/", "subscription site behind a PerimeterX wall; 0 of 47 approved stories readable since 02/11"),
    ("ft.com", "/", "subscription site, Cloudflare challenge; report: 'also paywalled'"),
    ("businessinsider.com", "/", "251 visible characters, JSON-LD articleBody partial: paywall"),
    ("scmp.com", "/plus/", "SCMP Plus subscriber article, empty body"),
)


def _host(url):
    host = (urlsplit(url or "").hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def paywalled_publisher(url):
    """The evidence line when the URL belongs to a publisher measured as paywalled, else None."""
    host, path = _host(url), urlsplit(url or "").path or "/"
    for name, prefix, evidence in PAYWALLED:
        if (host == name or host.endswith("." + name)) and path.startswith(prefix):
            return evidence
    return None


def held_for_paywall(url, readable, representative_status):
    """True when the story's source is paywalled and the reporter found nothing readable instead."""
    if readable or representative_status == "readable":
        return False
    if isinstance(representative_status, str) and representative_status.split(":", 1)[0] == "paywall":
        return True
    return paywalled_publisher(url) is not None
