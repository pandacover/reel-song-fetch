"""Audio helpers built on ffmpeg."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config


class AudioError(Exception):
    """Raised when audio cannot be read from a file."""


@dataclass
class Segment:
    start: float
    end: float
    path: Path


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_duration(path: Path) -> float:
    """Return the audio duration in seconds, or raise if there is no audio."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise AudioError("This file could not be read as audio or video.")
    data = json.loads(result.stdout or "{}")
    if not data.get("streams"):
        raise AudioError("This file has no audio track.")
    try:
        return float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        raise AudioError("Could not tell how long this audio is.")


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
                "ffmpeg", "-v", "error", "-y",
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
