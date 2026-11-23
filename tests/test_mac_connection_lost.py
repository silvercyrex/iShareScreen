"""HPG fork: the bridge connects again when the Mac drops the RFB connection
(a Remote Management settings change made screensharingd close it and the
picture froze until the viewer reconnected)."""
from __future__ import annotations

from isharescreen.frontend.wt.server import WebTransportBridge


def _bridge(monkeypatch):
    b = WebTransportBridge.__new__(WebTransportBridge)
    calls = []
    monkeypatch.setattr(b, "_restart_session", lambda name: calls.append(("restart", name)))
    monkeypatch.setattr(b, "stop", lambda reason, exit_code=0: calls.append(("stop", exit_code)))
    clock = [1000.0]
    monkeypatch.setattr("isharescreen.frontend.wt.server.time.monotonic", lambda: clock[0])
    return b, calls, clock


def test_reconnects_when_the_mac_closes_the_connection(monkeypatch):
    b, calls, _ = _bridge(monkeypatch)
    b._on_mac_connection_lost()
    assert calls == [("restart", "wt-session-macreconnect")]


def test_gives_up_when_the_mac_keeps_closing_it(monkeypatch):
    b, calls, clock = _bridge(monkeypatch)
    for i in range(4):
        clock[0] = 1000.0 + 10 * i
        b._on_mac_connection_lost()
    assert [c[0] for c in calls] == ["restart", "restart", "restart", "stop"]


def test_old_losses_are_forgotten(monkeypatch):
    b, calls, clock = _bridge(monkeypatch)
    for i in range(4):
        clock[0] = 1000.0 + 100 * i
        b._on_mac_connection_lost()
    assert [c[0] for c in calls] == ["restart"] * 4
