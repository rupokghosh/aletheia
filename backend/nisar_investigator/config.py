"""Runtime configuration. Nothing here logs or returns credentials."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent


def load_env() -> None:
    """Read KEY=VALUE lines from backend/.env into the environment without overriding what is already set."""
    path = BACKEND_DIR / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

AGENT_MODEL = os.environ.get("NISAR_AGENT_MODEL", "claude-opus-5-5")
AGENT_EFFORT = os.environ.get("NISAR_AGENT_EFFORT", "medium")


def cache_dir() -> Path:
    path = Path(os.environ.get("NISAR_CACHE_DIR", BACKEND_DIR / ".cache"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifacts_dir() -> Path:
    path = cache_dir() / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def earthdata_token() -> str | None:
    """Bearer token for deployed environments. Locally ~/.netrc is used instead."""
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    return token or None


# Largest window a single request may read (pixels per layer). 25 M px is 100 MB of float32.
MAX_WINDOW_PIXELS = int(os.environ.get("NISAR_MAX_WINDOW_PIXELS", 25_000_000))

# NISAR granules are written with 4 MiB HDF5 file-space pages, so 4 MiB aligned blocks fetch whole pages.
BLOCK_SIZE = 4 * 1024 * 1024
MAX_CACHED_BLOCKS = int(os.environ.get("NISAR_MAX_CACHED_BLOCKS", 64))
