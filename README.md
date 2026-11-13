# Reel Song Finder

A small web app that finds the songs used in an Instagram reel.

Paste a reel link, or upload the video (or audio) file if the link does not work. The app:

1. Downloads the reel with [yt-dlp](https://github.com/yt-dlp/yt-dlp).
2. Reads the song Instagram itself tagged on the reel, when Instagram shares it.
3. Cuts the audio into overlapping 12 second pieces with ffmpeg and runs song recognition on each, so it can catch more than one song.
4. Merges the matches and shows each song with when it plays, cover art and links to Spotify, Apple Music, YouTube and Shazam.

## Song recognition

| Service | Key needed | Notes |
| --- | --- | --- |
| Shazam (via the open source [shazamio](https://github.com/shazamio/ShazamIO) library) | No | On by default. Uses Shazam's unofficial endpoints, so it can break or be rate limited. |
| [AudD](https://audd.io) | Yes, `AUDD_API_TOKEN` | Optional second opinion. Turned on when the token is set. |

## Run it

You need Python 3.11+ and ffmpeg.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional, all settings have defaults
uvicorn app.main:app --reload
```

Open http://localhost:8000.

Or with Docker:

```bash
docker build -t reel-song-finder .
docker run -p 8000:8000 --env-file .env reel-song-finder
```

## Settings

All optional. See `.env.example`.

- `AUDD_API_TOKEN`: turns on AudD.
- `INSTAGRAM_COOKIES_FILE`: path to a `cookies.txt` from a logged in Instagram browser session. Helps when Instagram blocks logged out downloads, for private reels, and for getting Instagram's song tag.
- `MAX_UPLOAD_MB` (default 100) and `MAX_SCAN_SECONDS` (default 180).

## When a link fails

Instagram often blocks logged out downloads, especially from cloud servers. If that happens, the app tells you and offers the upload tab. Save the reel to your phone or computer and upload it there.

## API

- `POST /api/identify/url` with JSON `{"url": "https://www.instagram.com/reel/..."}`
- `POST /api/identify/file` with a multipart `file`
- `GET /api/health`

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
