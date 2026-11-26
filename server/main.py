"""FastAPI application for DuCO Agent."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST, ENVIRONMENT
from .db import init_db
from .routers import auth, cases, demo, documents, families, mock, policies, workspace


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="DuCO Agent API",
    description=(
        "Dynamic coordination-of-benefits platform. AI reads the documents; a deterministic "
        "Decimal engine calculates the money. Insurer endpoints under /mock-insurers are simulated."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith(("/api", "/mock-insurers")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok", "environment": ENVIRONMENT, "database": "connected"}


for router in (auth.router, families.router, policies.router, documents.router, cases.router, mock.router, workspace.router, demo.router):
    app.include_router(router)


# ---------------------------------------------------------------------------
# Serve the built React app (single-port demo). In development, run Vite on
# :5173 and keep this API on :8000.
# ---------------------------------------------------------------------------
if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith(("api/", "mock-insurers", "docs", "openapi.json", "redoc")):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (FRONTEND_DIST / full_path).resolve()
        if FRONTEND_DIST.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"detail": "Frontend build not found"}, status_code=404)
