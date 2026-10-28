#!/usr/bin/env python3
"""Optional public-data acquisition (run on a machine with internet access).

Downloads and caches the public sources listed in backend/data/public/public_signals.json so the
app can show their cached provenance offline. For every URL it first reads the site's
robots.txt (Python's urllib.robotparser) and skips the URL if fetching is disallowed. It never
bypasses logins, captchas or paywalls, and never invents content: a failure is recorded as a
failure. The application itself never needs this script or the network at runtime.

Usage:  python scripts/acquire_public_data.py [--timeout 30]
Output: backend/var/public_cache/<hash>.<ext> and backend/var/public_cache/manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "backend" / "data" / "public" / "public_signals.json"
CACHE = ROOT / "backend" / "var" / "public_cache"
AGENT = "AgniDrishti-prototype/0.9 (SIH 2026 research prototype; respects robots.txt)"


def robots_allows(url: str, timeout: float) -> tuple[bool | None, str]:
    parts = urllib.parse.urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            rp.parse(resp.read().decode("utf-8", "ignore").splitlines())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"robots.txt returned {e.code}: treating as disallowed"
        return True, f"no robots.txt ({e.code}); allowed by convention"
    except Exception as e:  # network blocked, DNS, TLS ...
        return None, f"could not read robots.txt: {type(e).__name__}: {e}"
    return rp.can_fetch(AGENT, url), f"robots.txt at {robots_url}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["signals"]
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "agent": AGENT, "items": []}
    for s in sources:
        url = s["source_url"]
        item = {"title": s["title"], "url": url, "status": None, "detail": None}
        allowed, why = robots_allows(url, args.timeout)
        item["robots"] = why
        if allowed is False:
            item.update(status="SKIPPED_ROBOTS", detail="Disallowed by robots.txt")
        elif allowed is None:
            item.update(status="FAILED", detail=why)
        else:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": AGENT})
                with urllib.request.urlopen(req, timeout=args.timeout) as resp:
                    data = resp.read()
                    ctype = resp.headers.get("Content-Type", "")
                ext = ".pdf" if "pdf" in ctype or url.lower().endswith(".pdf") else ".html"
                name = hashlib.sha256(url.encode()).hexdigest()[:16] + ext
                (CACHE / name).write_bytes(data)
                item.update(status="CACHED", file=name, bytes=len(data), content_type=ctype,
                            sha256=hashlib.sha256(data).hexdigest(),
                            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"))
            except Exception as e:
                item.update(status="FAILED", detail=f"{type(e).__name__}: {e}")
        manifest["items"].append(item)
        print(f"[{item['status']}] {url} — {item.get('detail') or item.get('file')}")
    (CACHE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    ok = sum(1 for i in manifest["items"] if i["status"] == "CACHED")
    print(f"{ok}/{len(manifest['items'])} sources cached in {CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
