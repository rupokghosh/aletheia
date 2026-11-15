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

# Open-weight models, used when no Claude API key is configured (or when NISAR_AGENT_PROVIDER says so).
LLM_MODEL = os.environ.get("NISAR_LLM_MODEL", "qwen3:14b")
OLLAMA_HOST = os.environ.get("NISAR_OLLAMA_HOST", "http://localhost:11434")
LLM_NUM_CTX = int(os.environ.get("NISAR_LLM_NUM_CTX", 32768))
# Qwen3 and similar models "think" before answering by default. "false" is several times faster and weaker
# at planning; unset leaves the model's default.
LLM_THINK = {"true": True, "false": False}.get(os.environ.get("NISAR_LLM_THINK", "").lower())
LLM_BASE_URL = os.environ.get("NISAR_LLM_BASE_URL", "")  # any OpenAI-compatible endpoint, e.g. https://host/v1
LLM_API_KEY = os.environ.get("NISAR_LLM_API_KEY", "")


def agent_provider() -> str:
    """Which language model plans investigations: 'anthropic', 'openai_compatible' or 'ollama'."""
    chosen = os.environ.get("NISAR_AGENT_PROVIDER", "auto").lower()
    if chosen in ("anthropic", "openai_compatible", "ollama"):
        return chosen
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    return "openai_compatible" if LLM_BASE_URL else "ollama"


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

# The size of the blocks the HDF5 library's own reads are served in. Those reads are the file's metadata:
# measured on a GCOV granule they add up to about 1.3 MB, packed at the start of three places in the file
# (the superblock, the coordinate arrays and the object headers near the end). 1 MiB blocks cover each
# place in one request; 4 MiB blocks (the page size the granules are written with) took the same three
# requests and transferred 12.6 MB for them. Pixel data is not read through these blocks but asked for
# as exact byte ranges.
BLOCK_SIZE = 1024 * 1024
MAX_CACHED_BLOCKS = int(os.environ.get("NISAR_MAX_CACHED_BLOCKS", 256))
# Reader processes kept alive between requests (h5py serialises reads inside one process).
READ_PROCESSES = int(os.environ.get("NISAR_READ_PROCESSES", 8))
