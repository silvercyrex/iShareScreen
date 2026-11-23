"""HPG fork: a mid-session RFBMediaStreamMessage1 (0x3f2) makes iss offer the
media session again (the login-window user switch froze the picture)."""
from __future__ import annotations

from isharescreen.proxy.session import Session, SessionConfig


def _session(monkeypatch):
    s = Session(SessionConfig(host="mac", username="u", password="p"))
    calls = []
    monkeypatch.setattr(s, "_send_cursor_rearm", lambda: calls.append("rearm"))

    def offer():
        calls.append("offer")
        s._last_reoffer_t = clock[0]
    monkeypatch.setattr(s, "_schedule_post_layout_arm", offer)
    clock = [100.0]
    monkeypatch.setattr("isharescreen.proxy.session.time.monotonic", lambda: clock[0])
    return s, calls, clock


def test_first_announcement_is_setup_and_left_alone(monkeypatch):
    s, calls, _ = _session(monkeypatch)
    s._on_media_stream_reinit()
    assert calls == []


def test_a_later_announcement_offers_the_media_session_again(monkeypatch):
    s, calls, clock = _session(monkeypatch)
    s._on_media_stream_reinit()
    clock[0] = 160.0
    s._on_media_stream_reinit()
    assert calls == ["rearm", "offer"]
    assert s._last_ctrl_event[0] == "media streams re-initialised"


def test_repeats_within_two_seconds_are_one_offer(monkeypatch):
    s, calls, clock = _session(monkeypatch)
    s._on_media_stream_reinit()
    clock[0] = 160.0
    s._on_media_stream_reinit()
    clock[0] = 161.0
    s._on_media_stream_reinit()
    assert calls.count("offer") == 1
    clock[0] = 170.0
    s._on_media_stream_reinit()
    assert calls.count("offer") == 2


def test_a_new_connection_starts_counting_again(monkeypatch):
    s, calls, clock = _session(monkeypatch)
    s._on_media_stream_reinit()
    s._teardown()
    clock[0] = 200.0
    s._on_media_stream_reinit()
    assert calls == []
