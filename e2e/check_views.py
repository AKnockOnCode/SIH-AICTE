"""Load every AgniDrishti view in headless Chromium and check two things against a running server:

* at phone width (390 px): no horizontal page overflow and no JavaScript page errors;
* at desktop width: no request leaves the server (no CDNs, remote fonts, map tiles or analytics).

Usage (server already running, e.g. `make start`):
    .venv/bin/python e2e/check_views.py [http://127.0.0.1:8000]
Exit code 0 when every view passes.
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

VIEWS = [
    "/", "/overlaps", "/overlaps/OVL-0001", "/cases/PGRC-5530", "/institutions/INS-0001", "/search?q=Sankalp", "/graph",
    "/imports", "/rules", "/reports", "/alerts", "/audit", "/audit?tab=status", "/audit?tab=permissions", "/watchlist",
    "/watchlist?tab=cases", "/signals", "/match-reviews", "/cases/new", "/institutions", "/institutions/INS-0001/dossier",
]


def main(base: str) -> int:
    local_host = urlparse(base).hostname
    failures: list[str] = []
    external: list[str] = []
    requests = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in ((390, 844), (1440, 900)):
            page = browser.new_page(viewport={"width": width, "height": height})
            errors: list[str] = []
            page.on("pageerror", lambda e, errs=errors: errs.append(str(e)))

            def on_request(req) -> None:
                nonlocal requests
                requests += 1
                host = urlparse(req.url).hostname
                if host not in (local_host, "127.0.0.1", "localhost", None) and not req.url.startswith(("data:", "blob:")):
                    external.append(req.url)

            page.on("request", on_request)
            for view in VIEWS:
                page.goto(base + view, wait_until="networkidle")
                page.wait_for_timeout(300)
                scroll_width = page.evaluate("document.documentElement.scrollWidth")
                status = "ok" if scroll_width <= width else f"OVERFLOW (scrollWidth {scroll_width})"
                if scroll_width > width:
                    failures.append(f"{width}px {view}: {status}")
                print(f"{width:>5}px  {view:<34} {status}")
            failures.extend(f"{width}px page error: {e}" for e in errors)
            page.close()
        browser.close()
    print(f"\n{len(VIEWS)} views x 2 widths, {requests} requests, {len(external)} external: {external}")
    for f in failures:
        print("FAIL", f)
    return 1 if failures or external else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"))
