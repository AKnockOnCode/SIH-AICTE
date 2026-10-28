"""End-to-end fixtures: a real SAMANVAY server on a fresh temporary database plus headless Chromium.

Run from the repository root:   .venv/bin/python -m pytest e2e -q      (or `make e2e`)
Needs: the built UI in frontend/dist and Playwright's Chromium (`python -m playwright install chromium`).
The server seeds the synthetic dataset itself on first start (fresh-setup path), so the first test
waits up to ~90 s.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SHOTS = ROOT / "docs" / "screenshots"
ANCHOR = "2026-10-27"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="agnidrishti-e2e-"))
        self.db_path = self.tmp / "agnidrishti.db"
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.env = {**os.environ, "DATABASE_URL": f"sqlite:///{self.db_path}",
                    "AGNIDRISHTI_TODAY": ANCHOR, "SAMANVAY_TODAY": ANCHOR,
                    "AGNIDRISHTI_SEED_ANCHOR": ANCHOR, "SAMANVAY_SEED_ANCHOR": ANCHOR,
                    "AGNIDRISHTI_MODELS_DIR": str(self.tmp / "models"), "SAMANVAY_MODELS_DIR": str(self.tmp / "models"),
                    "AGNIDRISHTI_STORAGE_DIR": str(self.tmp / "storage"), "SAMANVAY_STORAGE_DIR": str(self.tmp / "storage"),
                    "PYTHONUNBUFFERED": "1"}
        self.env["ANTHROPIC_API_KEY"] = ""  # the app must work without it (empty beats any .env value)

    def start(self, timeout: float = 180) -> None:
        self.log = (self.tmp / "server.log").open("a")  # closed in stop()
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.port),
                                      "--log-level", "warning"], cwd=BACKEND, env=self.env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early; see {self.tmp / 'server.log'}")
            try:
                with urllib.request.urlopen(f"{self.url}/api/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.5)
        raise RuntimeError("server did not become healthy in time")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if getattr(self, "log", None):
            self.log.close()

    def api(self, method: str, path: str, body: dict | None = None, user: str = "competent.authority") -> tuple[int, dict]:
        req = urllib.request.Request(self.url + path, method=method, headers={"X-Demo-User": user, "Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


@pytest.fixture(scope="session")
def server():
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        pytest.skip("frontend/dist is missing: build the UI first (make build)")
    s = Server()
    s.start()
    yield s
    s.stop()
    shutil.rmtree(s.tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def open_page(browser, server):
    """open_page(role, path) -> page logged in as the demo role (role stored as the UI does)."""
    contexts = []
    pages = []

    def _open(role: str = "competent.authority", path: str = "/", width: int = 1440, height: int = 900):
        ctx = browser.new_context(viewport={"width": width, "height": height}, accept_downloads=True, locale="en-IN",
                                  timezone_id="Asia/Kolkata")
        ctx.add_init_script(f"try {{ localStorage.setItem('samanvay.demoUser', '{role}') }} catch (e) {{}}")
        contexts.append(ctx)
        page = ctx.new_page()
        page.errors = []  # type: ignore[attr-defined]
        page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
        page.goto(server.url + path)
        pages.append(page)
        return page

    yield _open
    errors = [e for p in pages for e in p.errors]  # type: ignore[attr-defined]
    for c in contexts:
        c.close()
    assert not errors, f"uncaught errors in the browser: {errors}"


def shot(page, name: str) -> None:
    """Full-page screenshot for the README. The viewport is temporarily made as tall as the page so
    sticky and viewport-height panels (header, sidebar, intake preview) render as a person scrolling would see them."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.evaluate("() => window.scrollTo(0, 0)")
    viewport = page.viewport_size or {"width": 1440, "height": 900}
    height = page.evaluate("() => document.documentElement.scrollHeight")
    page.set_viewport_size({"width": viewport["width"], "height": max(viewport["height"], min(int(height), 4000))})
    page.wait_for_timeout(300)
    png = page.screenshot(full_page=True)
    page.set_viewport_size(viewport)
    page.wait_for_timeout(150)
    _save_compact_png(png, SHOTS / name)


def _save_compact_png(png: bytes, path: Path) -> None:
    """Store the screenshot as a 256-colour PNG (about a third of the size; UI screenshots stay legible)."""
    try:
        from PIL import Image
    except ImportError:  # Pillow is normally present (ReportLab depends on it); fall back to the raw capture
        path.write_bytes(png)
        return
    import io

    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, "PNG", optimize=True)
