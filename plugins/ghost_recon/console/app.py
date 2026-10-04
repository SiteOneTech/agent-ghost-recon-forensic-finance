"""``create_app``: the Ghost Recon console FastAPI app — JSON API under /api/v1 plus the static frontend."""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.db import Store
from . import CONSOLE_VERSION
from .auth import AuthService
from .deps import ConsoleContext, current_principal
from .jobs import JobService
from .routers import (audits as audits_routes, auth as auth_routes, cases as cases_routes, fs as fs_routes,
                      jobs as jobs_routes, system as system_routes, users as users_routes)
from .settings import ConsoleSettings
from .store import ConsoleStore

STATIC_DIR = Path(__file__).parent / "static"
# The Windows registry can map .js to text/plain; under nosniff the browser then refuses the ES modules.
for _mime, _ext in (("text/javascript", ".js"), ("text/css", ".css"), ("image/svg+xml", ".svg")):
    mimetypes.add_type(_mime, _ext)

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}
ROUTERS = (auth_routes, system_routes, cases_routes, audits_routes, fs_routes, jobs_routes, users_routes)


def host_allowed(host_header: str, settings: ConsoleSettings) -> bool:
    """The Host header's hostname (port ignored, IPv6 brackets stripped) must be a configured host (DNS rebinding)."""
    host = (host_header or "").strip().lower()
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else ""
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return bool(host) and (host in settings.allowed_hosts or host == settings.host.lower())


def create_app(settings: ConsoleSettings, store: Store, cstore: ConsoleStore, *,
               auth: Optional[AuthService] = None, jobs: Optional[JobService] = None) -> FastAPI:
    jobs = jobs or JobService(cstore, store, settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        jobs.start()  # find running jobs again, mark orphans, dispatch the queue; then tick in the background
        try:
            yield
        finally:
            jobs.stop()

    app = FastAPI(title="Ghost Recon Console", version=CONSOLE_VERSION, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.gr = ConsoleContext(settings=settings, store=store, cstore=cstore,
                                  auth=auth or AuthService(cstore, settings), jobs=jobs)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if host_allowed(request.headers.get("host", ""), settings):
            response = await call_next(request)
        else:
            response = JSONResponse({"error": {"code": "bad_host", "message": "host no permitido"}}, status_code=400)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"  # revalidate: no mixed old/new ES modules after an upgrade
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": f"http_{exc.status_code}",
                                                                   "message": str(exc.detail)}
        return JSONResponse({"error": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Only where/what/kind: the default entries also carry the submitted input (a password on a bad login).
        fields = [{k: e.get(k) for k in ("loc", "msg", "type")} for e in jsonable_encoder(exc.errors())]
        return JSONResponse({"error": {"code": "invalid_request", "message": "parámetros inválidos",
                                       "fields": fields}}, status_code=422)

    for module in ROUTERS:
        app.include_router(module.router, prefix="/api/v1")

    @app.get("/api/v1/openapi.json", include_in_schema=False)
    def openapi(_=Depends(current_principal)):
        return app.openapi()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    return app
