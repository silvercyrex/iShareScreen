"""A still screen (no video, host RTCP still arriving) is left alone; a
stream with neither video nor host RTCP is warned about and the media session
is offered again every 20 s (HPG fork; ISS_MEDIA_DEAD=end ends the session
after Apple's 48 s instead). Never armed if the host sent no RTCP at all."""
from __future__ import annotations

import threading

import pytest

import isharescreen.proxy.session as S
from isharescreen.proxy.session import Session


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(S.time, "monotonic", lambda: t["now"])
    return t


def _session(video_age, rtcp_age, now=1000.0):
    s = Session.__new__(Session)
    s._connected = True
    s._fresh_evt = threading.Event()
    s._last_video_pkt_t = now - video_age
    s._last_host_rtcp_t = 0.0 if rtcp_age is None else now - rtcp_age
    s._media_silence_warned = False
    s.reoffers = []
    s._send_cursor_rearm = lambda: None
    s._schedule_post_layout_arm = lambda: (s.reoffers.append(S.time.monotonic()),
                                           setattr(s, "_last_reoffer_t", S.time.monotonic()))
    return s


def test_still_screen_is_left_alone(clock):
    s = _session(video_age=120, rtcp_age=0.5)
    s._check_media_liveness()
    assert s._connected and not s._media_silence_warned


def test_never_armed_without_host_rtcp(clock):
    s = _session(video_age=120, rtcp_age=None)
    s._check_media_liveness()
    assert s._connected and not s._media_silence_warned


def test_silence_warns_then_ends_when_asked(clock, monkeypatch):
    monkeypatch.setenv("ISS_MEDIA_DEAD", "end")
    s = _session(video_age=12, rtcp_age=12)
    s._check_media_liveness()
    assert s._connected and s._media_silence_warned
    clock["now"] += 40                                   # 52 s of silence
    s._check_media_liveness()
    assert not s._connected and s._fresh_evt.is_set()


def test_recovery_clears_the_warning(clock):
    s = _session(video_age=12, rtcp_age=12)
    s._check_media_liveness()
    s._last_host_rtcp_t = clock["now"]                   # reports resume
    s._check_media_liveness()
    assert s._connected and not s._media_silence_warned


def test_silence_reoffers_every_20_s_and_keeps_the_session(clock, monkeypatch):
    monkeypatch.delenv("ISS_MEDIA_DEAD", raising=False)
    s = _session(video_age=12, rtcp_age=12)
    s._check_media_liveness()
    assert s._media_silence_warned and s.reoffers == []      # warn only
    clock["now"] += 9                                        # 21 s
    s._check_media_liveness()
    assert len(s.reoffers) == 1
    clock["now"] += 10                                       # 31 s: too soon
    s._check_media_liveness()
    assert len(s.reoffers) == 1
    clock["now"] += 10                                       # 41 s
    s._check_media_liveness()
    assert len(s.reoffers) == 2
    clock["now"] += 30                                       # 71 s
    s._check_media_liveness()
    assert s._connected and not s._fresh_evt.is_set()
