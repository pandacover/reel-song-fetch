"""Vercel entry point.

vercel.json rewrites /api/<path> to /api/index?path=<path>, and the Python
function then sees /api/index as the request path. This wrapper puts the
original path back before FastAPI routes the request.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app as fastapi_app  # noqa: E402

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
    return {
        **scope,
        "path": path,
        "raw_path": path.encode(),
        "query_string": urlencode(rest).encode(),
    }


async def app(scope, receive, send):
    await fastapi_app(restore_path(scope), receive, send)
