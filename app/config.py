import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


AUDD_API_TOKEN = os.getenv("AUDD_API_TOKEN", "").strip()
INSTAGRAM_COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE", "").strip()
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 100)
MAX_SCAN_SECONDS = _int("MAX_SCAN_SECONDS", 180)

# Audio is cut into windows of this length, starting every SEGMENT_STEP seconds.
SEGMENT_LENGTH = 12
SEGMENT_STEP = 10
