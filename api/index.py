"""Vercel entry point. Vercel serves the FastAPI `app` from this file.

The path fix for Vercel's rewrite lives in app/vercel.py as middleware.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402,F401
