"""Undo Vercel's rewrite so FastAPI sees the original request path.

vercel.json rewrites /api/<path> to /api/index?path=<path>. Vercel then calls
the FastAPI app with /api/index as the path. This middleware runs inside the
app, so it works however Vercel loads the module.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

REWRITTEN_PATHS = {"/api/index", "/api/index.py"}


def restore_path(scope: dict) -> dict:
    if scope.get("type") != "http" or scope.get("path") not in REWRITTEN_PATHS:
        return scope
    query = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
    original = next((v for k, v in query if k == "path"), None)
    if original is None:
        return scope
    rest = [(k, v) for k, v in query if k != "path"]
    path = "/api/" + original.lstrip("/")
    return {**scope, "path": path, "raw_path": path.encode(), "query_string": urlencode(rest).encode()}


class VercelPathMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(restore_path(scope), receive, send)
