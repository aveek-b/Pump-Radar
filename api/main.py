"""Guide-compatible ASGI entry point; preserves the already tested API implementation.

Run: uvicorn api.main:app --reload
Demo routes live in pumpradar.api; B1 read routes and stream live in api.routes.platform.
"""

from pumpradar.api import app

__all__ = ["app"]
