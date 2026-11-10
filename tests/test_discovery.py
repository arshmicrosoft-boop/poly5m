import time


def test_window_boundary():
    now = int(time.time())
    window_ts = (now // 300) * 300
    assert window_ts % 300 == 0


def test_next_window():
    window_ts = 900
    assert (window_ts + 300) % 300 == 0
