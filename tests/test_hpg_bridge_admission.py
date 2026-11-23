"""HPG fork: bridge admission (tickets / token), viewer rights, events."""
from __future__ import annotations

import io
import json
import time

import pytest

from isharescreen.frontend.wt import hpg
from isharescreen.frontend.wt.server import WebTransportBridge
from isharescreen.proxy.session import SessionConfig

KEY = bytes(range(32))
HOST = "100.64.0.4"


def _payload(**over):
    now = int(time.time())
    p = {"v": 1, "iat": now, "exp": now + 30, "host": HOST, "port": 5900,
         "sid": "c" + "a" * 32, "ro": False, "user": "it-person", "n": "nonce-1"}
    p.update(over)
    return p


def _verifier(started_at=None):
    return hpg.TicketVerifier(KEY, HOST, 5900,
                              started_at=time.time() - 1 if started_at is None else started_at)


def test_valid_ticket_admits():
    adm = _verifier().check(hpg.sign_ticket(KEY, _payload()))
    assert adm.user == "it-person" and adm.read_only is False and not adm.is_joiner


@pytest.mark.parametrize("over, why", [
    ({"exp": int(time.time()) - 1}, "expired"),
    ({"iat": int(time.time()) - 10, "exp": int(time.time()) + 80}, "lifetime"),
    ({"host": "100.64.0.9"}, "different Mac"),
    ({"port": 5901}, "different Mac"),
    ({"v": 2}, "version"),
    ({"n": ""}, "nonce"),
])
def test_bad_tickets_refused(over, why):
    with pytest.raises(hpg.AdmissionError, match=why):
        _verifier().check(hpg.sign_ticket(KEY, _payload(**over)))


def test_wrong_key_refused():
    with pytest.raises(hpg.AdmissionError, match="signature"):
        _verifier().check(hpg.sign_ticket(b"x" * 32, _payload()))


def test_relay_ticket_prefix_not_accepted():
    # A ticket signed with the relay's prefix must not open the bridge.
    import base64, hashlib, hmac
    p = base64.urlsafe_b64encode(json.dumps(_payload()).encode()).rstrip(b"=").decode()
    sig = hmac.new(KEY, b"hpg-relay-ticket-v1\x00" + p.encode(), hashlib.sha256).digest()
    t = p + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    with pytest.raises(hpg.AdmissionError, match="signature"):
        _verifier().check(t)


def test_ticket_is_one_time():
    v = _verifier()
    t = hpg.sign_ticket(KEY, _payload())
    v.check(t)
    with pytest.raises(hpg.AdmissionError, match="already used"):
        v.check(t)


def test_ticket_from_before_bridge_start_refused():
    v = _verifier(started_at=time.time() + 100)
    with pytest.raises(hpg.AdmissionError, match="not issued for this bridge"):
        v.check(hpg.sign_ticket(KEY, _payload()))


def test_token_verifier():
    tv = hpg.TokenVerifier()
    assert tv.check(tv.token).user == "local"
    with pytest.raises(hpg.AdmissionError):
        tv.check("nope")


def test_event_lines(monkeypatch):
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    ev = hpg.EventSink(True, "TJG7HR9K4C")
    ev.emit("ready", udp_port=4433)
    ev.user_connected("it-person")
    ev.user_active("it-person")
    ev.user_active("it-person")          # within 5 s: suppressed
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    assert lines[0]["event"] == "ready" and lines[0]["udp_port"] == 4433
    assert lines[1]["line"] == 'User "it-person" connected to connection "TJG7HR9K4C".'
    assert sum(1 for x in lines if "active on" in x.get("line", "")) == 1


def test_clean_log_text():
    assert hpg.clean_log_text("a\nb\x00c" + "x" * 500) == "a b c" + "x" * 295


# -- bridge rights, without any network ------------------------------------

class _V:
    """Minimal stand-in for _ViewerSession."""
    def __init__(self, sid):
        self.session_id = sid
        self.admission = None
        self.read_only = True
        self.joined_t = 0.0
        self.last_seen_t = time.monotonic()
        self.sent = []
        self.ended = False
        self.close_cb = None

    def send_control(self, obj):
        self.sent.append(obj)

    def send_frame(self, payload):
        pass


@pytest.fixture
def bridge(monkeypatch):
    b = WebTransportBridge(SessionConfig(host=HOST, username="admin", password="x"),
                           admission=_verifier(), linger_s=0)
    started = []
    monkeypatch.setattr(b, "_start_session_thread", lambda: started.append(1))
    b._started = started

    def end(v):
        v.ended = True
        b.remove_viewer(v)
    monkeypatch.setattr(b, "_end", end)
    return b


def _auth(b, v, **over):
    b.register_pending(v)
    b.handle_input_event({"type": "auth",
                          "ticket": hpg.sign_ticket(KEY, _payload(**over))}, v)


def test_no_mac_login_without_valid_ticket(bridge):
    v = _V(1)
    bridge.register_pending(v)
    bridge.handle_input_event({"type": "mouse", "x": 1, "y": 1}, v)
    assert v.ended and not bridge.viewers and not bridge._started
    assert v.sent[0]["type"] == "auth_failed"


def test_valid_ticket_starts_session(bridge):
    v = _V(1)
    _auth(bridge, v)
    assert bridge.viewers == [v] and bridge._started
    assert v.sent[-1] == {"type": "auth_ok", "read_only": False, "source_url": "",
                         "clipboard": False}


def test_one_controller_second_is_view_only(bridge):
    a, b = _V(1), _V(2)
    _auth(bridge, a, n="n1")
    _auth(bridge, b, n="n2")
    assert a.read_only is False and b.read_only is True


def test_ro_ticket_is_view_only_and_input_dropped(bridge, monkeypatch):
    v = _V(1)
    _auth(bridge, v, ro=True)
    assert v.read_only is True
    calls = []
    monkeypatch.setattr(bridge, "_note_input", lambda viewer: calls.append(viewer))
    bridge.handle_input_event({"type": "key", "down": True, "keysym": 65}, v)
    bridge.handle_input_datagram(v, b"\x10" + b"\x00" * 12)
    assert calls == []


def test_owner_leaving_cuts_joiners(bridge):
    owner, joiner = _V(1), _V(2)
    _auth(bridge, owner, n="n1")
    _auth(bridge, joiner, n="n2", sid="c" + "a" * 32 + "~helper", ro=True)
    bridge.remove_viewer(owner)
    assert joiner.ended and not bridge.viewers


def test_late_joiner_does_not_deadlock(bridge):
    # A running session with a cached config + keyframe: add_viewer replays
    # them through _broadcast_frame, which takes the viewer lock again.
    import threading

    class _Sess:
        def request_fir(self, _):
            pass

    class _Loop:
        def call_soon_threadsafe(self, fn, *a):
            pass

    bridge._session = _Sess()
    bridge._loop = _Loop()
    bridge._last_config_env = b"cfg"
    bridge._last_keyframe_env = {0: b"kf"}
    t = threading.Thread(target=bridge.add_viewer, args=(_V(9),), daemon=True)
    t.start()
    t.join(2.0)
    assert not t.is_alive(), "add_viewer deadlocked"
