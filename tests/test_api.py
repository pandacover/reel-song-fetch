from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.instagram import InstagramError
from app.recognizers import Match


class FakeRecognizer:
    name = "Fake"

    async def recognize(self, path: Path):
        return Match("Test Song", "Test Artist", "Fake")


class BrokenRecognizer:
    name = "Broken"

    async def recognize(self, path: Path):
        raise RuntimeError("rate limited")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "get_recognizers", lambda: [FakeRecognizer(), BrokenRecognizer()])
    return TestClient(main.app)


def test_index_and_health(client):
    assert "Reel Song Finder" in client.get("/").text
    assert client.get("/api/health").json()["ffmpeg"] is True


def test_upload_finds_song(client, tone_file):
    with tone_file.open("rb") as fh:
        res = client.post("/api/identify/file", files={"file": ("clip.mp4", fh, "video/mp4")})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["songs"][0]["title"] == "Test Song"
    assert data["errors"] == ["Broken: rate limited"]


def test_upload_rejects_non_media(client):
    res = client.post("/api/identify/file", files={"file": ("notes.txt", b"hello world", "text/plain")})
    assert res.status_code == 422


def test_url_validation(client):
    assert client.post("/api/identify/url", json={"url": "https://example.com/x"}).status_code == 400


def test_url_flow_with_instagram_metadata(client, monkeypatch, tone_file):
    def fake_download(url, out_dir):
        return tone_file, {"title": "A reel", "instagram_music": {
            "title": "Tagged Song", "artist": "Tagged Artist", "original_audio": False}}

    monkeypatch.setattr(main, "download_reel", fake_download)
    data = client.post("/api/identify/url", json={"url": "https://www.instagram.com/reel/ABC123/"}).json()
    assert data["instagram_music"]["title"] == "Tagged Song"
    assert data["songs"][0]["artist"] == "Test Artist"


def test_url_download_failure_suggests_upload(client, monkeypatch):
    def fail(url, out_dir):
        raise InstagramError("Login required.")

    monkeypatch.setattr(main, "download_reel", fail)
    res = client.post("/api/identify/url", json={"url": "https://www.instagram.com/reel/ABC123/"})
    assert res.status_code == 502
    assert "upload" in res.json()["detail"].lower()
