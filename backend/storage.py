"""storage.py — tiny JSON-file persistence helpers (watchlist etc.)."""

from __future__ import annotations

import json
import os

from config import DATA_DIR, WATCHLIST_FILE  # noqa: F401  (re-exported)


def load_json(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return default


def save_json(path, data):
    json.dump(data, open(path, "w"), indent=2)
