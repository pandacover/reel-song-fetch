"""Download Instagram reels with yt-dlp and pull Instagram's own song info."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.extractor.instagram import InstagramIE
from yt_dlp.utils import DownloadError

from . import config
from .audio import ffmpeg_path

INSTAGRAM_URL_RE = re.compile(
    r"^https?://(?:www\.|m\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/[\w-]+", re.I
)


class InstagramError(Exception):
    """Raised when a reel cannot be fetched."""


def is_instagram_url(url: str) -> bool:
    return bool(INSTAGRAM_URL_RE.match(url.strip()))


def _clean(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def find_music_info(data: Any) -> dict[str, Any] | None:
    """Search Instagram's raw media JSON for the song attached to the reel.

    Instagram has used a few shapes over time, so we walk the whole tree and
    look for the known keys instead of relying on one fixed path.
    """
    licensed: dict | None = None
    original: dict | None = None
    attribution: dict | None = None

    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if licensed is None and isinstance(node.get("music_asset_info"), dict):
                licensed = node["music_asset_info"]
            if original is None and isinstance(node.get("original_sound_info"), dict):
                original = node["original_sound_info"]
            if attribution is None and isinstance(node.get("clips_music_attribution_info"), dict):
                attribution = node["clips_music_attribution_info"]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)

    if licensed:
        title = _clean(licensed.get("title"))
        artist = _clean(licensed.get("display_artist"))
        if title or artist:
            return {"title": title, "artist": artist, "original_audio": False}

    if attribution:
        title = _clean(attribution.get("song_name"))
        artist = _clean(attribution.get("artist_name"))
        if title or artist:
            return {
                "title": title,
                "artist": artist,
                "original_audio": bool(attribution.get("uses_original_audio")),
            }

    if original:
        owner = original.get("ig_artist") or {}
        title = _clean(original.get("original_audio_title"))
        artist = _clean(owner.get("username") if isinstance(owner, dict) else None)
        if title or artist:
            return {"title": title, "artist": artist, "original_audio": True}

    return None


def _short_error(message: str) -> str:
    """Turn a long yt-dlp error into one readable sentence."""
    message = re.sub(r"^ERROR:\s*", "", message)
    message = re.sub(r"^\[[^\]]+\]\s*[\w-]+:\s*", "", message)  # "[Instagram] ID: "
    message = re.split(r"\s*\(caused by|;\s*please report|\. See https", message)[0]
    message = message.strip().rstrip(".")
    if "login" in message.lower() or "registered users" in message.lower():
        message += ". Instagram wants a login for this reel"
    return message[:300] + "."


class _MusicAwareInstagramIE(InstagramIE):
    """Same as yt-dlp's Instagram extractor, but keeps the reel's song info."""

    def _extract_product(self, product_info, *args, **kwargs):
        info = super()._extract_product(product_info, *args, **kwargs)
        music = find_music_info(product_info)
        if music and isinstance(info, dict):
            info["instagram_music"] = music
        return info


def download_reel(url: str, out_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Download the reel's audio (or video) into out_dir.

    Returns the downloaded file path and a small metadata dict.
    """
    params: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "reel.%(ext)s"),
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "max_filesize": config.MAX_UPLOAD_MB * 1024 * 1024,
        "cachedir": False,  # home dir is read only on serverless hosts
    }
    ffmpeg = ffmpeg_path()
    if ffmpeg:
        params["ffmpeg_location"] = ffmpeg
    if config.INSTAGRAM_COOKIES_FILE:
        params["cookiefile"] = config.INSTAGRAM_COOKIES_FILE

    try:
        with YoutubeDL(params, auto_init=False) as ydl:
            # Our extractor goes first so it wins over the stock Instagram one.
            ydl.add_info_extractor(_MusicAwareInstagramIE())
            ydl.add_default_info_extractors()
            info = ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise InstagramError(_short_error(str(exc))) from exc

    if info and info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        info = entries[0] if entries else None
    if not info:
        raise InstagramError("No video found at that link.")

    files = sorted(p for p in out_dir.glob("reel.*") if p.is_file())
    if not files:
        raise InstagramError("The reel could not be downloaded.")

    meta = {
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "webpage_url": info.get("webpage_url") or url,
        "instagram_music": info.get("instagram_music"),
    }
    return files[0], meta
