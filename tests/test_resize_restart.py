"""HPG fork: a resize request that brings no video and no re-offer within
1.5 s offers the media session once (the Mac stops its streams on every
display change and waits for an offer)."""
from __future__ import annotations

import pytest

import isharescreen.proxy.session as S
from isharescreen.proxy.session import Session


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(S.time, "monotonic", lambda: t["now"])
    return t


def _session(clock):
    s = Session.__new__(Session)
    s._connected = True
    s._last_video_pkt_t = clock["now"] - 0.1
    s._resize_sent_t = clock["now"]
    s.offers = []
    s._send_cursor_rearm = lambda: None
    s._schedule_post_layout_arm = lambda: s.offers.append(clock["now"])
    return s


def test_no_video_after_a_resize_offers_once(clock):
    s = _session(clock)
    clock["now"] += 1.0
    s._check_resize_restart()
    assert s.offers == []                        # not yet
    clock["now"] += 1.0
    s._check_resize_restart()
    s._check_resize_restart()
    assert len(s.offers) == 1                    # once


def test_video_after_the_resize_needs_nothing(clock):
    s = _session(clock)
    clock["now"] += 0.5
    s._last_video_pkt_t = clock["now"]
    clock["now"] += 1.5
    s._check_resize_restart()
    assert s.offers == []


def test_a_re_offer_from_the_layout_path_is_enough(clock):
    s = _session(clock)
    s._last_reoffer_t = clock["now"] + 0.3
    clock["now"] += 2.0
    s._check_resize_restart()
    assert s.offers == []
