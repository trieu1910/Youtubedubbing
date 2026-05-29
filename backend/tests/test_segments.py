from pipeline.segments import merge_and_split

def seg(start, end, text):
    return {"start": start, "end": end, "text": text}

def test_merges_short_adjacent_segments():
    segs = [seg(0.0, 0.4, "Hi"), seg(0.4, 0.7, "there"), seg(0.7, 3.0, "how are you doing today")]
    out = merge_and_split(segs, merge_min_dur=0.8, split_max_dur=12.0)
    assert out[0]["text"] == "Hi there"
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 0.7

def test_keeps_long_enough_segments_untouched():
    segs = [seg(0.0, 2.0, "A full sentence here."), seg(2.0, 4.0, "Another full sentence.")]
    out = merge_and_split(segs, merge_min_dur=0.8, split_max_dur=12.0)
    assert len(out) == 2

def test_splits_overlong_segment_at_sentence_boundary():
    segs = [seg(0.0, 20.0, "First sentence. Second sentence. Third sentence.")]
    out = merge_and_split(segs, merge_min_dur=0.8, split_max_dur=12.0)
    assert len(out) >= 2
    assert out[0]["start"] == 0.0
    assert out[-1]["end"] == 20.0
    for s in out:
        assert s["end"] > s["start"]
