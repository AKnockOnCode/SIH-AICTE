"""AgniDrishti application factory.

Run: `uvicorn app.main:app --port 8000` from `backend/` (or use `make dev` / `scripts/dev.sh`).
On startup the database is migrated; if it is empty it is seeded (disable with SAMANVAY_AUTO_SEED=0 or AGNIDRISHTI_AUTO_SEED=0);
local models are trained if missing; alerts are refreshed and the audit chain is verified.
If `frontend/dist` exists the built UI is served from the same port.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__
from .alerts import routes as alerts_routes
from .audit import routes as audit_routes
from .complaints import routes as case_routes
from .conflicts import routes as overlap_routes
from .core import clock
from .core.api import build_openapi, docs_response, make_route
from .core.config import get_settings
from .dashboard import routes as dashboard_routes
from .db.database import connect, init_db
from .dossier import routes as dossier_routes
from .imports import routes as import_routes
from .institutions import routes as institution_routes
from .reports import routes as report_routes
from .risk import routes as risk_routes
from .scoring import routes as rules_routes
from .signals import routes as signal_routes
from .system import routes as system_routes

log = logging.getLogger("agnidrishti")

ROUTERS = [system_routes.router, dashboard_routes.router, institution_routes.router, case_routes.router,
           overlap_routes.router, risk_routes.router, alerts_routes.router, report_routes.router, dossier_routes.router,
           import_routes.router, signal_routes.router, rules_routes.router, audit_routes.router]

DESCRIPTION = (
    "AgniDrishti — integrated monitoring of institution-related complaint cases across AICTE Bureaus/Cells "
    "(Smart India Hackathon 2026 prototype, PS SIH26264). All complaint data in this demo is SYNTHETIC. "
    "Authentication is simulated with the X-Demo-User header (role switcher); permission checks run on the server."
)


def startup_tasks() -> None:
    settings = get_settings()
    init_db(settings.db_path)
    with connect(settings.db_path) as db:
        seeded = db.val("SELECT COUNT(*) FROM seed_runs", default=0)
        auto_seed = os.environ.get("AGNIDRISHTI_AUTO_SEED") or os.environ.get("SAMANVAY_AUTO_SEED", "1")
        if not seeded and auto_seed != "0":
            from .seed.runner import run_seed

            log.info("empty database: generating the synthetic demo dataset (one-off, ~10 s)")
            run_seed(db)
        if not db.val("SELECT COUNT(*) FROM seed_runs", default=0):
            return
        if settings.today_override:  # frozen date: new events must sort after everything already stored
            for sql in ("SELECT MAX(ts) FROM audit_events", "SELECT MAX(action_at) FROM case_actions",
                        "SELECT MAX(created_at) FROM alerts", "SELECT MAX(updated_at) FROM overlap_alerts"):
                clock.observe(db.val(sql))
        from .institutions import matcher
        from .scoring import classifier, priority

        classifier.ensure()
        matcher.ensure_model(db)
        with db.tx():
            priority.recompute_all(db)
        from .alerts.service import sweep

        stats = sweep(db)
        log.info("startup alert sweep: %s", stats)


@asynccontextmanager
async def lifespan(app: Starlette):
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(startup_tasks)
    yield


def create_app_spec() -> dict:
    """The OpenAPI document, built without touching the database (used by the TS type generator)."""
    endpoints = [ep for r in ROUTERS for ep in r.endpoints]
    return build_openapi(endpoints, title="AgniDrishti API", version=__version__, description=DESCRIPTION)


def create_app() -> Starlette:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    endpoints = [ep for r in ROUTERS for ep in r.endpoints]
    spec = create_app_spec()

    async def openapi(_: Request) -> Response:
        return JSONResponse(spec)

    async def docs(_: Request) -> Response:
        return docs_response()

    async def api_not_found(request: Request) -> Response:
        return JSONResponse({"error": {"code": "not_found", "message": f"No API route {request.method} {request.url.path}"}},
                            status_code=404)

    routes = [make_route(ep) for ep in endpoints]
    routes += [Route("/api/openapi.json", openapi), Route("/api/docs", docs),
               Route("/api/{rest:path}", api_not_found, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])]
    dist: Path = settings.frontend_dist
    if (dist / "index.html").exists():
        if (dist / "assets").exists():
            routes.append(Mount("/assets", StaticFiles(directory=dist / "assets"), name="assets"))

        async def spa(request: Request) -> Response:
            # Single-page app: serve real files from dist, otherwise index.html (client-side routing).
            rel = request.path_params.get("path", "")
            candidate = (dist / rel).resolve()
            if rel and dist.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

        routes.append(Route("/{path:path}", spa))
    else:
        async def root(_: Request) -> Response:
            return JSONResponse({"name": "AgniDrishti API", "docs": "/api/docs", "openapi": "/api/openapi.json",
                                 "ui": "Frontend not built yet: run `make build` (or scripts/dev.sh) to serve the UI here."})

        routes.append(Route("/", root))
    app = Starlette(routes=routes, lifespan=lifespan, middleware=[Middleware(GZipMiddleware, minimum_size=1024)],
                    max_body_size=(settings.max_upload_mb + 2) * 1024 * 1024)
    app.state.openapi = spec
    return app


app = create_app()
