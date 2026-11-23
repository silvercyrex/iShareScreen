"""HPG fork: the video-stall report says where video stops (counts only)."""
from __future__ import annotations

import logging

from isharescreen.proxy.session import Session, SessionConfig


def _session(clock):
    s = Session(SessionConfig(host="mac", username="u", password="p"))
    s._connected = True
    s._last_publish_t = clock[0]
    return s


def _tick(s, clock, monkeypatch, t):
    clock[0] = t
    monkeypatch.setattr("isharescreen.proxy.session.time.monotonic", lambda: clock[0])
    s._report_video_stall()


def test_reports_deltas_by_reason_while_stalled(monkeypatch, caplog):
    clock = [1000.0]
    s = _session(clock)
    caplog.set_level(logging.INFO, logger="isharescreen.proxy.session")
    _tick(s, clock, monkeypatch, 1003.0)          # under 5 s: nothing
    _tick(s, clock, monkeypatch, 1006.0)          # baseline only
    assert "video stall" not in caplog.text
    s._rx_pkts_video += 120
    s._stall_diag["decrypt_ok"] += 120
    s._stall_diag["drop_unmapped"] += 4
    s._last_ctrl_event = ("user session change", 1004.0)
    _tick(s, clock, monkeypatch, 1012.0)          # within 10 s of the last tick
    assert "video stall" not in caplog.text
    _tick(s, clock, monkeypatch, 1016.0)
    line = [r.getMessage() for r in caplog.records if "video stall" in r.getMessage()][-1]
    assert "udp +120" in line and "decrypt ok +120 fail +0" in line
    assert "unmapped ssrc +4" in line
    assert "user session change 12s ago" in line


def test_says_when_frames_flow_again_and_stays_quiet_otherwise(monkeypatch, caplog):
    clock = [1000.0]
    s = _session(clock)
    caplog.set_level(logging.INFO, logger="isharescreen.proxy.session")
    _tick(s, clock, monkeypatch, 1001.0)
    assert caplog.text == ""                       # healthy: no lines
    _tick(s, clock, monkeypatch, 1006.0)
    s._last_publish_t = 1020.0
    _tick(s, clock, monkeypatch, 1021.0)
    assert "frames flowing again" in caplog.text


def test_slows_to_once_a_minute_after_the_first_minute(monkeypatch, caplog):
    clock = [100.0]
    s = _session(clock)
    caplog.set_level(logging.INFO, logger="isharescreen.proxy.session")
    t = 100.0
    while t < 700.0:
        t += 1.0
        _tick(s, clock, monkeypatch, t)
    n = sum("video stall" in r.getMessage() for r in caplog.records)
    assert 10 <= n <= 18                           # ~6 in the first minute, then 1/min
