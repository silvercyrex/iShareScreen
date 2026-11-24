"""HPG fork: when the Mac drops the RFB connection the bridge tells the
viewers and waits for the controlling viewer to reconnect (a Remote
Management settings change does that, but so does the person at the Mac
ending the sharing, and the bridge cannot tell which)."""
from __future__ import annotations

from isharescreen.frontend.wt.server import WebTransportBridge


class _Viewer:
    def __init__(self):
        self.controls = []

    def send_control(self, obj):
        self.controls.append(obj)


class _Handle:
    def __init__(self, fn):
        self.fn, self.cancelled = fn, False

    def cancel(self):
        self.cancelled = True


class _Loop:
    def __init__(self):
        self.later = []

    def call_later(self, delay, fn, *args):
        h = _Handle(fn)
        self.later.append((delay, h))
        return h


def _bridge(monkeypatch):
    b = WebTransportBridge.__new__(WebTransportBridge)
    calls = []
    monkeypatch.setattr(b, "_teardown_session", lambda: calls.append("teardown"))
    monkeypatch.setattr(b, "_restart_session", lambda name: calls.append(("restart", name)))
    monkeypatch.setattr(b, "stop", lambda reason, exit_code=0: calls.append(("stop", exit_code)))
    b._loop = _Loop()
    b.viewers = [_Viewer()]
    return b, calls


def test_viewers_are_told_and_nothing_logs_in_again_by_itself(monkeypatch):
    b, calls = _bridge(monkeypatch)
    b._on_mac_connection_lost()
    assert b.viewers[0].controls == [{"type": "mac_lost"}]
    assert not any(isinstance(c, tuple) and c[0] == "restart" for c in calls)
    assert b._mac_lost


def test_the_viewer_reconnects_with_one_request(monkeypatch):
    b, calls = _bridge(monkeypatch)
    b._on_mac_connection_lost()
    b._reconnect_after_mac_lost()
    assert ("restart", "wt-session-macreconnect") in calls
    assert b._loop.later[0][1].cancelled and not b._mac_lost
    b._reconnect_after_mac_lost()                 # a second click does nothing
    assert calls.count(("restart", "wt-session-macreconnect")) == 1


def test_nobody_reconnecting_ends_the_bridge(monkeypatch):
    b, calls = _bridge(monkeypatch)
    b._on_mac_connection_lost()
    delay, handle = b._loop.later[0]
    assert delay == 600.0
    handle.fn()
    assert ("stop", 1) in calls


def test_reconnect_without_a_lost_connection_is_ignored(monkeypatch):
    b, calls = _bridge(monkeypatch)
    b._reconnect_after_mac_lost()
    assert calls == []


def test_a_session_started_another_way_ends_the_wait_for_everyone(monkeypatch):
    b, calls = _bridge(monkeypatch)
    b.viewers = [_Viewer(), _Viewer()]
    b._on_mac_connection_lost()
    handle = b._loop.later[0][1]
    b._mac_back()                                 # e.g. a page reload logged in
    assert not b._mac_lost and handle.cancelled
    assert all({"type": "mac_back"} in v.controls for v in b.viewers)
    handle.fn()                                   # the old expiry can't stop it
    assert ("stop", 1) not in calls


def test_after_a_reconnect_click_the_other_viewers_are_told_too(monkeypatch):
    b, calls = _bridge(monkeypatch)
    b.viewers = [_Viewer(), _Viewer()]
    b._on_mac_connection_lost()
    b._reconnect_after_mac_lost()
    assert b._mac_lost_reconnecting
    b._mac_back()
    assert all({"type": "mac_back"} in v.controls for v in b.viewers)
    assert not b._mac_lost_reconnecting
