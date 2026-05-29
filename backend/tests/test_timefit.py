from pipeline.timefit import target_duration, compute_fit

def test_target_duration_borrows_capped_gap():
    seg = {"start": 1.0, "end": 3.0}
    assert target_duration(seg, next_start=8.0, gap_borrow_max=1.2) == 3.2

def test_target_duration_no_next():
    seg = {"start": 1.0, "end": 3.0}
    assert target_duration(seg, next_start=None, gap_borrow_max=1.2) == 2.0

def test_fit_within_band_pads_when_short():
    fit = compute_fit(actual=1.0, target=2.0, max_speedup=1.4)
    assert fit["atempo"] == 1.0
    assert abs(fit["pad"] - 1.0) < 1e-6

def test_fit_too_long_speeds_up_capped():
    fit = compute_fit(actual=3.0, target=2.0, max_speedup=1.4)
    assert fit["atempo"] == 1.4
    assert fit["pad"] == 0.0

def test_fit_slightly_long_within_band_no_change():
    fit = compute_fit(actual=2.2, target=2.0, max_speedup=1.4)
    assert fit["atempo"] == 1.0
    assert fit["pad"] == 0.0
