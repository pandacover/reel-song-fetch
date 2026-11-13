"""Song recognition backends.

Shazam (through the open source `shazamio` library) works with no API key.
AudD is used as well when AUDD_API_TOKEN is set.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

from . import config
from .audio import Segment

log = logging.getLogger(__name__)


@dataclass
class Match:
    title: str
    artist: str
    source: str
    album: str | None = None
    release: str | None = None
    cover: str | None = None
    links: dict[str, str] = field(default_factory=dict)


def search_links(title: str, artist: str) -> dict[str, str]:
    q = quote_plus(f"{title} {artist}".strip())
    return {
        "spotify": f"https://open.spotify.com/search/{q}",
        "youtube": f"https://www.youtube.com/results?search_query={q}",
        "apple_music": f"https://music.apple.com/search?term={q}",
    }


# ---------- Shazam ----------

def parse_shazam(data: dict[str, Any]) -> Match | None:
    track = (data or {}).get("track")
    if not isinstance(track, dict) or not track.get("title"):
        return None
    title = track["title"]
    artist = track.get("subtitle") or ""
    album = release = None
    for section in track.get("sections") or []:
        for item in section.get("metadata") or []:
            if item.get("title") == "Album":
                album = item.get("text")
            elif item.get("title") == "Released":
                release = item.get("text")
    links = search_links(title, artist)
    if track.get("url"):
        links["shazam"] = track["url"]
    for option in ((track.get("hub") or {}).get("options") or []):
        for action in option.get("actions") or []:
            uri = action.get("uri") or ""
            if uri.startswith("https://music.apple.com") or uri.startswith("https://itunes.apple.com"):
                links["apple_music"] = uri.split("?")[0]
                break
    images = track.get("images") or {}
    return Match(
        title=title, artist=artist, source="Shazam", album=album, release=release,
        cover=images.get("coverart") or images.get("coverarthq"), links=links,
    )


class ShazamRecognizer:
    name = "Shazam"

    def __init__(self) -> None:
        from shazamio import Shazam  # imported lazily so tests don't need it

        self._client = Shazam()

    async def recognize(self, path: Path) -> Match | None:
        data = await self._client.recognize(str(path))
        return parse_shazam(data)


# ---------- AudD ----------

def parse_audd(data: dict[str, Any]) -> Match | None:
    if (data or {}).get("status") != "success":
        error = (data or {}).get("error") or {}
        raise RuntimeError(f"AudD error: {error.get('error_message') or 'unknown error'}")
    result = data.get("result")
    if not isinstance(result, dict) or not result.get("title"):
        return None
    title, artist = result["title"], result.get("artist") or ""
    links = search_links(title, artist)
    if result.get("song_link"):
        links["songlink"] = result["song_link"]
    cover = None
    apple = result.get("apple_music") or {}
    if apple.get("url"):
        links["apple_music"] = apple["url"]
    artwork = apple.get("artwork") or {}
    if artwork.get("url"):
        cover = artwork["url"].replace("{w}", "300").replace("{h}", "300")
    spotify = result.get("spotify") or {}
    spotify_url = (spotify.get("external_urls") or {}).get("spotify")
    if spotify_url:
        links["spotify"] = spotify_url
    if not cover:
        images = (spotify.get("album") or {}).get("images") or []
        if images:
            cover = images[0].get("url")
    return Match(
        title=title, artist=artist, source="AudD", album=result.get("album"),
        release=result.get("release_date"), cover=cover, links=links,
    )


class AuddRecognizer:
    name = "AudD"
    url = "https://api.audd.io/"

    def __init__(self, token: str) -> None:
        self._token = token

    async def recognize(self, path: Path) -> Match | None:
        async with httpx.AsyncClient(timeout=30) as client:
            with path.open("rb") as fh:
                resp = await client.post(
                    self.url,
                    data={"api_token": self._token, "return": "apple_music,spotify"},
                    files={"file": (path.name, fh, "audio/wav")},
                )
        resp.raise_for_status()
        return parse_audd(resp.json())


_shazam: ShazamRecognizer | None = None


def default_recognizers() -> list:
    global _shazam
    if _shazam is None:
        _shazam = ShazamRecognizer()  # reuse one client across requests
    recognizers: list = [_shazam]
    if config.AUDD_API_TOKEN:
        recognizers.append(AuddRecognizer(config.AUDD_API_TOKEN))
    return recognizers


# ---------- Running and merging ----------

def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\(.*?\)|\[.*?\]", "", text)  # drop "(feat. x)", "[Remix]" etc.
    text = re.sub(r"\bfeat\.?.*$|\bft\.?.*$", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def merge_matches(found: list[tuple[Segment, Match]]) -> list[dict[str, Any]]:
    """Group matches of the same song and record when it plays in the clip."""
    songs: dict[str, dict[str, Any]] = {}
    for segment, match in found:
        key = _norm(match.title) + "|" + _norm(match.artist.split(",")[0].split("&")[0])
        song = songs.get(key)
        if song is None:
            song = songs[key] = {
                "title": match.title,
                "artist": match.artist,
                "album": match.album,
                "release": match.release,
                "cover": match.cover,
                "links": dict(match.links),
                "sources": [],
                "start": segment.start,
                "end": segment.end,
                "hits": 0,
            }
        else:
            for k in ("album", "release", "cover"):
                song[k] = song[k] or getattr(match, k)
            for k, v in match.links.items():
                song["links"].setdefault(k, v)
            song["start"] = min(song["start"], segment.start)
            song["end"] = max(song["end"], segment.end)
        if match.source not in song["sources"]:
            song["sources"].append(match.source)
        song["hits"] += 1
    return sorted(songs.values(), key=lambda s: s["start"])


async def recognize_segments(
    segments: list[Segment], recognizers: list, concurrency: int = 3
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run every recognizer on every segment. Returns songs and any error notes."""
    sem = asyncio.Semaphore(concurrency)
    errors: list[str] = []

    async def run(rec, seg: Segment):
        async with sem:
            try:
                return seg, await rec.recognize(seg.path)
            except Exception as exc:  # one failed call should not sink the whole scan
                log.warning("%s failed on %.0fs: %s", rec.name, seg.start, exc)
                errors.append(f"{rec.name}: {exc}")
                return seg, None

    results = await asyncio.gather(*(run(r, s) for s in segments for r in recognizers))
    found = [(seg, m) for seg, m in results if m is not None]
    unique_errors = list(dict.fromkeys(errors))[:5]
    return merge_matches(found), unique_errors
