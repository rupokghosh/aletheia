"""Entry point for hosts that look for `main:app` (Vercel). Locally the API is started with
`uvicorn nisar_investigator.api:app`."""

from nisar_investigator.api import app

__all__ = ["app"]
