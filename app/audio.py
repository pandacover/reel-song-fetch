"""Audio helpers built on ffmpeg."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import config


class AudioError(Exception):
    """Raised when audio cannot be read from a file."""


@dataclass
class Segment:
    start: float
    end: float
    path: Path


def _ensure_executable(path: str) -> str:
    """Serverless hosts can drop the exec bit. Copy to /tmp and fix it if so."""
    if os.access(path, os.X_OK):
        return path
    target = Path(tempfile.gettempdir()) / "ffmpeg"
    if not target.exists():
        shutil.copyfile(path, target)
        target.chmod(0o755)
    return str(target)


@lru_cache(maxsize=1)
def ffmpeg_path() -> str | None:
    """System ffmpeg if installed, otherwise the copy bundled by imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return _ensure_executable(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


def _ffmpeg() -> str:
    path = ffmpeg_path()
    if not path:
        raise AudioError("ffmpeg is not installed on the server.")
    return path


def probe_duration(path: Path) -> float:
    """Return the audio duration in seconds, or raise if there is no audio."""
    # `ffmpeg -i` with no output prints the file info to stderr and exits 1.
    result = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    info = result.stderr
    if "Invalid data found" in info or "Duration:" not in info:
        raise AudioError("This file could not be read as audio or video.")
    if not re.search(r"Stream #\S+.*: Audio:", info):
        raise AudioError("This file has no audio track.")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    if not match:
        raise AudioError("Could not tell how long this audio is.")
    h, m, sec = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(sec)


def plan_segments(duration: float) -> list[tuple[float, float]]:
    """Pick overlapping windows across the clip so we can catch song changes."""
    duration = min(duration, float(config.MAX_SCAN_SECONDS))
    length, step = config.SEGMENT_LENGTH, config.SEGMENT_STEP
    if duration <= length + 1:
        return [(0.0, round(duration, 2))]
    windows = []
    start = 0.0
    while start + length <= duration:
        windows.append((start, start + length))
        start += step
    # Make sure the tail of the clip is covered too.
    if windows[-1][1] < duration - 3:
        windows.append((max(0.0, duration - length), duration))
    return [(round(a, 2), round(b, 2)) for a, b in windows]


def extract_segments(source: Path, out_dir: Path) -> tuple[float, list[Segment]]:
    """Cut the source into short mono WAV clips ready for recognition."""
    duration = probe_duration(source)
    segments = []
    for i, (start, end) in enumerate(plan_segments(duration)):
        out = out_dir / f"segment_{i:03d}.wav"
        result = subprocess.run(
            [
                _ffmpeg(), "-v", "error", "-y",
                "-ss", str(start), "-t", str(end - start),
                "-i", str(source),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(out),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
            continue
        segments.append(Segment(start=start, end=end, path=out))
    if not segments:
        raise AudioError("Could not extract any audio from this file.")
    return duration, segments
