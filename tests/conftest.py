import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tone_file(tmp_path: Path) -> Path:
    """A 30 second test clip with a sine tone, made with ffmpeg."""
    out = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
         "-f", "lavfi", "-i", "color=c=black:s=64x64:d=30", "-shortest",
         "-c:a", "aac", "-c:v", "libx264", str(out)],
        check=True,
    )
    return out
