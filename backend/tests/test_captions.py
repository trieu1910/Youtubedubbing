from pipeline.captions import parse_json3, parse_vtt, pick_track, pick_format_url


def test_parse_json3_basic_lines():
    data = {"events": [
        {"tStartMs": 0, "segs": [{"utf8": "Hello world"}]},
        {"tStartMs": 2000, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 2000, "segs": [{"utf8": "How are you"}]},
        {"tStartMs": 4000, "segs": [{"utf8": "\n"}]},
    ]}
    segs = parse_json3(data)
    assert [s["text"] for s in segs] == ["Hello world", "How are you"]
    assert segs[0]["start"] == 0.0 and segs[0]["end"] == 2.0


def test_parse_json3_cumulative_rolling_autocaption():
    # Rolling auto-caption: same line refreshed cumulatively, then a new line.
    data = {"events": [
        {"tStartMs": 0, "segs": [{"utf8": "I"}]},
        {"tStartMs": 100, "segs": [{"utf8": "I like"}]},
        {"tStartMs": 200, "segs": [{"utf8": "I like cats"}]},
        {"tStartMs": 3000, "segs": [{"utf8": "Dogs are great"}]},
    ]}
    segs = parse_json3(data)
    # The cumulative refresh collapses into one segment, not three duplicates.
    assert [s["text"] for s in segs] == ["I like cats", "Dogs are great"]


def test_parse_json3_aappend():
    data = {"events": [
        {"tStartMs": 0, "aAppend": 1, "segs": [{"utf8": "Hel"}]},
        {"tStartMs": 50, "aAppend": 1, "segs": [{"utf8": "lo"}]},
        {"tStartMs": 1000, "segs": [{"utf8": "\n"}]},
    ]}
    segs = parse_json3(data)
    assert segs[0]["text"] == "Hello"


def test_parse_vtt_dedups_consecutive():
    vtt = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000
Hello world

00:00:02.000 --> 00:00:04.000
Hello world

00:00:04.000 --> 00:00:06.000
<c>Second</c> line
"""
    segs = parse_vtt(vtt)
    assert [s["text"] for s in segs] == ["Hello world", "Second line"]
    assert segs[0]["start"] == 0.0 and segs[1]["end"] == 6.0


def test_pick_track_prefers_manual_then_auto_by_language():
    info = {
        "language": "en",
        "subtitles": {"en": [{"ext": "json3", "url": "MANUAL_EN"}]},
        "automatic_captions": {"en": [{"ext": "json3", "url": "AUTO_EN"}]},
    }
    track = pick_track(info)
    assert track[0]["url"] == "MANUAL_EN"


def test_pick_track_auto_only_when_language_known():
    # No manual subs, language unknown -> do NOT guess an auto-translated track.
    info = {"language": None, "subtitles": {}, "automatic_captions": {"fr": [{"ext": "json3", "url": "X"}]}}
    assert pick_track(info) is None
    # Language known -> use the matching auto-caption.
    info2 = {"language": "fr", "subtitles": {}, "automatic_captions": {"fr": [{"ext": "json3", "url": "AUTO_FR"}]}}
    assert pick_track(info2)[0]["url"] == "AUTO_FR"


def test_pick_format_url_prefers_json3():
    track = [{"ext": "vtt", "url": "V"}, {"ext": "json3", "url": "J"}]
    assert pick_format_url(track) == ("json3", "J")
