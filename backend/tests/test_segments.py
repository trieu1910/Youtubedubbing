from pipeline.segments import merge_and_split, group_sentences

def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def test_group_sentences_joins_fragments_until_punctuation():
    segs = [seg(0.0, 1.0, "I really"), seg(1.0, 2.0, "like cats."), seg(2.0, 3.0, "Dogs too.")]
    out = group_sentences(segs, max_dur=8.0)
    assert [s["text"] for s in out] == ["I really like cats.", "Dogs too."]
    assert out[0]["start"] == 0.0 and out[0]["end"] == 2.0


def test_group_sentences_caps_at_max_dur():
    segs = [seg(0.0, 5.0, "no punctuation here"), seg(5.0, 9.0, "still going")]
    out = group_sentences(segs, max_dur=4.0)
    # first fragment alone already exceeds max_dur -> emitted on its own
    assert out[0]["text"] == "no punctuation here"
    assert len(out) == 2


def test_group_sentences_flushes_trailing_without_punctuation():
    segs = [seg(0.0, 1.0, "hello there")]
    out = group_sentences(segs, max_dur=8.0)
    assert out == [{"start": 0.0, "end": 1.0, "text": "hello there"}]

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
