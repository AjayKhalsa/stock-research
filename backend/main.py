"""
main.py — FastAPI app factory. Configuration in config.py, routes in
routers/, business logic in stock_service.py, scraping in
screener_scraper.py, indicator math in indicators.py.
"""

import time
import uuid
from contextlib import asynccontextmanager

import config  # noqa: F401  — loads .env before anything reads the environment

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from routers import cfo_workspace, paper_trades, screener, screens, stocks, watchlist
import cfo_engine
import db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    db.close()


app = FastAPI(title="Stock Research API", version="2.8.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Local dev (any LAN host on :3000) + any *.vercel.app deployment
    # Accept any local development port. Locking this to :3000 made preview
    # and QA builds on :3001/:3002 look like the backend was offline even
    # though the API itself was healthy.
    allow_origin_regex=r"(http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+):\d{2,5}|https://.*\.vercel\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(watchlist.router)
app.include_router(screener.router)
app.include_router(screens.router)
app.include_router(paper_trades.router)
app.include_router(cfo_workspace.router)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    """Expose latency and a request id without leaking payloads or secrets."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 — preserve FastAPI's registered handlers
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"[api] {request_id} {request.method} {request.url.path} "
              f"500 {elapsed_ms:.1f}ms unhandled")
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    print(f"[api] {request_id} {request.method} {request.url.path} "
          f"{response.status_code} {elapsed_ms:.1f}ms")
    return response


@app.get("/api/health")
def health():
    return {"ok": db.ping(), "storage": db.storage_status(), "version": app.version,
            "model_version": cfo_engine.MODEL_VERSION,
            "features": {
                "cfo_workspace_v1": config.CFO_WORKSPACE_V1,
                "daily_job_auth": ["github_job_token", "shared_secret"],
            }}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
