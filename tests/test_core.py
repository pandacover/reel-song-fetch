from pathlib import Path

from yt_dlp import YoutubeDL

from app import audio, instagram
from app.audio import Segment
from app.recognizers import Match, merge_matches, parse_audd, parse_shazam


def test_instagram_url_check():
    assert instagram.is_instagram_url("https://www.instagram.com/reel/C1a2B3c4D5e/")
    assert instagram.is_instagram_url("https://instagram.com/reels/C1a2B3c4D5e?igsh=abc")
    assert instagram.is_instagram_url("https://www.instagram.com/p/C1a2B3c4D5e/")
    assert instagram.is_instagram_url("https://www.instagram.com/someuser/reel/C1a2B3c4D5e/")
    assert not instagram.is_instagram_url("https://www.youtube.com/watch?v=x")
    assert not instagram.is_instagram_url("https://www.instagram.com/someuser/")


def test_music_info_licensed_song():
    raw = {"clips_metadata": {"music_info": {"music_asset_info": {
        "title": "Espresso", "display_artist": "Sabrina Carpenter"}}, "original_sound_info": None}}
    assert instagram.find_music_info(raw) == {
        "title": "Espresso", "artist": "Sabrina Carpenter", "original_audio": False}


def test_music_info_original_audio():
    raw = {"items": [{"clips_metadata": {"music_info": None, "original_sound_info": {
        "original_audio_title": "Original audio", "ig_artist": {"username": "someone"}}}}]}
    assert instagram.find_music_info(raw) == {
        "title": "Original audio", "artist": "someone", "original_audio": True}


def test_music_info_attribution_and_missing():
    raw = {"clips_music_attribution_info": {"song_name": "Song", "artist_name": "Band",
                                            "uses_original_audio": False}}
    assert instagram.find_music_info(raw)["title"] == "Song"
    assert instagram.find_music_info({"video_url": "x"}) is None


def test_our_extractor_runs_before_stock_instagram():
    with YoutubeDL({"quiet": True}, auto_init=False) as ydl:
        ydl.add_info_extractor(instagram._MusicAwareInstagramIE())
        ydl.add_default_info_extractors()
        keys = list(ydl._ies)
    assert keys.index("_MusicAwareInstagram") < keys.index("Instagram")
    assert instagram._MusicAwareInstagramIE.suitable("https://www.instagram.com/reel/C1a2B3c4D5e/")


def test_plan_segments():
    assert audio.plan_segments(8) == [(0.0, 8.0)]
    windows = audio.plan_segments(30)
    assert windows[0] == (0.0, 12.0)
    assert windows[-1][1] >= 27
    assert len(audio.plan_segments(10_000)) <= 20  # capped by MAX_SCAN_SECONDS


def test_extract_segments(tone_file: Path, tmp_path: Path):
    duration, segments = audio.extract_segments(tone_file, tmp_path)
    assert 29 <= duration <= 31
    assert len(segments) >= 2
    assert all(s.path.exists() for s in segments)


def test_parse_shazam():
    data = {"track": {
        "key": "1", "title": "Blinding Lights", "subtitle": "The Weeknd",
        "url": "https://www.shazam.com/track/1", "images": {"coverart": "https://img/c.jpg"},
        "sections": [{"metadata": [{"title": "Album", "text": "After Hours"},
                                   {"title": "Released", "text": "2019"}]}],
        "hub": {"options": [{"actions": [{"uri": "https://music.apple.com/us/album/x?i=1&mt=1"}]}]},
    }}
    m = parse_shazam(data)
    assert (m.title, m.artist, m.album, m.release) == ("Blinding Lights", "The Weeknd", "After Hours", "2019")
    assert m.links["apple_music"] == "https://music.apple.com/us/album/x"
    assert m.links["shazam"].startswith("https://www.shazam.com")
    assert parse_shazam({"matches": []}) is None


def test_parse_audd():
    data = {"status": "success", "result": {
        "title": "Levitating", "artist": "Dua Lipa", "album": "Future Nostalgia",
        "song_link": "https://lis.tn/x",
        "spotify": {"external_urls": {"spotify": "https://open.spotify.com/track/1"}},
    }}
    m = parse_audd(data)
    assert m.links["spotify"] == "https://open.spotify.com/track/1"
    assert parse_audd({"status": "success", "result": None}) is None


def test_merge_groups_same_song_and_orders_by_time():
    s = lambda a: Segment(a, a + 12, Path("x"))
    found = [
        (s(20), Match("Song B", "Artist B", "Shazam")),
        (s(0), Match("Song A (Remix)", "Artist A feat. X", "Shazam")),
        (s(10), Match("Song A", "Artist A", "AudD", album="Alb")),
    ]
    songs = merge_matches(found)
    assert [x["title"] for x in songs] == ["Song A (Remix)", "Song B"]
    first = songs[0]
    assert first["sources"] == ["Shazam", "AudD"]
    assert (first["start"], first["end"], first["album"], first["hits"]) == (0, 22, "Alb", 2)


def test_short_error():
    raw = ("ERROR: [_MusicAwareInstagram] C1a2: Unable to download webpage: curl: (7) failed. "
           "See https://curl.se/x (caused by ProxyError('x')); please report this issue on https://github.com")
    assert instagram._short_error(raw) == "Unable to download webpage: curl: (7) failed."
