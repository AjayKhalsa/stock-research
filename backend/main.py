"""
main.py — FastAPI app factory. Configuration in config.py, routes in
routers/, business logic in stock_service.py, scraping in
screener_scraper.py, indicator math in indicators.py.
"""

import config  # noqa: F401  — loads .env before anything reads the environment

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import screener, screens, stocks, watchlist

app = FastAPI(title="Stock Research API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    # Local dev (any LAN host on :3000) + any *.vercel.app deployment
    allow_origin_regex=r"(http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+):3000|https://.*\.vercel\.app)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(watchlist.router)
app.include_router(screener.router)
app.include_router(screens.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
