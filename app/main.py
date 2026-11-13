"""FastAPI app: paste a reel link or upload a video, get the songs back."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .audio import AudioError, extract_segments, ffmpeg_available
from .instagram import InstagramError, download_reel, is_instagram_url
from .recognizers import default_recognizers, recognize_segments

logging.basicConfig(level=logging.INFO)
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

app = FastAPI(title="Reel Song Finder")

# Tests swap this out to avoid real network calls.
get_recognizers = default_recognizers


class UrlRequest(BaseModel):
    url: str


async def _identify(media: Path, work_dir: Path) -> dict[str, Any]:
    try:
        duration, segments = await run_in_threadpool(extract_segments, media, work_dir)
    except AudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    songs, errors = await recognize_segments(segments, get_recognizers())
    return {
        "duration": round(duration, 1),
        "scanned_seconds": round(min(duration, config.MAX_SCAN_SECONDS), 1),
        "songs": songs,
        "errors": errors,
    }


@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health() -> dict[str, Any]:
    return {
        "ok": ffmpeg_available(),
        "ffmpeg": ffmpeg_available(),
        "recognizers": ["Shazam"] + (["AudD"] if config.AUDD_API_TOKEN else []),
        "instagram_cookies": bool(config.INSTAGRAM_COOKIES_FILE),
    }


@app.post("/api/identify/url")
async def identify_url(body: UrlRequest) -> dict[str, Any]:
    url = body.url.strip()
    if not is_instagram_url(url):
        raise HTTPException(
            status_code=400,
            detail="Please paste an Instagram reel link, like https://www.instagram.com/reel/ABC123/",
        )
    with tempfile.TemporaryDirectory(prefix="reel-") as tmp:
        work = Path(tmp)
        try:
            media, meta = await run_in_threadpool(download_reel, url, work)
        except InstagramError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not download this reel. {exc} You can upload the video file instead.",
            )
        result = await _identify(media, work)
    return {"source": "instagram", "reel": meta, "instagram_music": meta.get("instagram_music"), **result}


@app.post("/api/identify/file")
async def identify_file(file: UploadFile = File(...)) -> dict[str, Any]:
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="upload-") as tmp:
        work = Path(tmp)
        suffix = Path(file.filename or "").suffix[:10] or ".bin"
        media = work / f"upload{suffix}"
        size = 0
        with media.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"File is larger than {config.MAX_UPLOAD_MB} MB.")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        result = await _identify(media, work)
    return {"source": "upload", "reel": {"title": file.filename}, "instagram_music": None, **result}


@app.api_route("/", methods=["GET", "HEAD"])
async def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


# On Vercel, files in public/ are served by the CDN. Locally FastAPI serves them.
app.mount("/static", StaticFiles(directory=PUBLIC_DIR / "static"), name="static")
