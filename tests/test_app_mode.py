"""HPG fork: local viewer app (--app, --mac-relay, password typed in the page)."""
from __future__ import annotations

import io
import socket

import pytest

from isharescreen.cli import _build_session_config, _make_parser, _parse_relay
from isharescreen.frontend.wt.app import find_browser, free_port
from isharescreen.frontend.wt.hpg import AdmissionError, TokenVerifier


def _config(monkeypatch, argv, stdin=""):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return _build_session_config(_make_parser().parse_args(argv))


def test_parse_relay():
    assert _parse_relay("127.0.0.1:15900") == ("127.0.0.1", 15900)
    for bad in ("127.0.0.1", ":15900", "127.0.0.1:x", "127.0.0.1:65535"):
        with pytest.raises(SystemExit):
            _parse_relay(bad)


def test_mac_relay_config(monkeypatch):
    cfg = _config(monkeypatch, ["--mac-relay", "127.0.0.1:15900", "-u", "admin",
                                "--password-stdin"], "pw\n")
    assert (cfg.host, cfg.port) == ("127.0.0.1", 15900)
    assert cfg.udp_bind_host == "127.0.0.1" and cfg.udp_local_any_port
    # the Mac's ports, seen through the relay: UDP P and P+1
    assert (cfg.udp_ctrl_port or cfg.port, cfg.udp_video_port or cfg.port + 1) == (15900, 15901)


def test_app_without_password_asks_in_the_page(monkeypatch):
    cfg = _config(monkeypatch, ["--app", "--mac-relay", "127.0.0.1:15900", "-u", "admin"])
    assert cfg.password == ""
    with pytest.raises(SystemExit):           # without --app a password is required
        _config(monkeypatch, ["--host", "mac", "-u", "admin"])


def test_password_not_in_config_repr(monkeypatch):
    cfg = _config(monkeypatch, ["--host", "mac", "-u", "admin", "--password-stdin"],
                  "s3cret-pw\n")
    assert "s3cret-pw" not in repr(cfg)


def test_one_time_token():
    tv = TokenVerifier(one_time=True)
    tv.check(tv.token)
    with pytest.raises(AdmissionError):
        tv.check(tv.token)
    reusable = TokenVerifier()
    reusable.check(reusable.token)
    reusable.check(reusable.token)


def test_free_port_is_free_for_tcp_and_udp():
    port = free_port("127.0.0.1")
    t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        t.bind(("127.0.0.1", port))
        u.bind(("127.0.0.1", port))
    finally:
        t.close()
        u.close()


def test_find_browser_override(tmp_path):
    exe = tmp_path / "my-browser"
    exe.write_text("")
    assert find_browser(str(exe)) == str(exe)
    assert find_browser(str(tmp_path / "missing")) is None


class _Viewer:
    def __init__(self):
        self.sent = []
        self.read_only = True
        self.admission = object()

    def send_control(self, msg):
        self.sent.append(msg)


def _bridge(**kw):
    from isharescreen.frontend.wt.server import WebTransportBridge
    from isharescreen.proxy.session import SessionConfig
    cfg = SessionConfig(host="127.0.0.1", username="admin", password="", port=15900)
    return WebTransportBridge(cfg, admission=TokenVerifier(), password_from_page=True,
                              mac_name="Lab Mac", **kw)


def test_page_password_starts_the_session(monkeypatch):
    b = _bridge()
    started = []
    monkeypatch.setattr(b, "_start_session", lambda: started.append(b._config.password))
    v = _Viewer()
    b.viewers.append(v)
    assert b._needs_password()
    b._ask_password(v)
    assert v.sent[-1]["type"] == "need_password" and v.sent[-1]["name"] == "Lab Mac"
    assert "password" not in v.sent[-1]
    b.handle_input_event({"type": "mac_password", "password": "pw"}, v)  # view-only ok
    assert started == ["pw"]
    b.handle_input_event({"type": "mac_password", "password": "again"}, v)
    assert started == ["pw"]                  # only while waiting for one
    b._password_refused("wrong user name or password")
    assert b._config.password == "" and v.sent[-1]["error"]


def test_page_password_rejects_junk(monkeypatch):
    b = _bridge()
    monkeypatch.setattr(b, "_start_session", lambda: pytest.fail("started"))
    v = _Viewer()
    for bad in (None, "", 5, "x" * 300):
        b.handle_input_event({"type": "mac_password", "password": bad}, v)


def test_entry_routes_app_flags_to_the_cli(monkeypatch):
    import isharescreen.cli as cli
    from isharescreen.tui import entry
    called = []
    monkeypatch.setattr(cli, "main", lambda: called.append(True) or 0)
    for argv in (["--app", "--mac-relay", "127.0.0.1:15900", "-u", "a"],
                 ["--mac-relay=127.0.0.1:15900", "-u", "a"]):
        monkeypatch.setattr("sys.argv", ["iss"] + argv)
        assert entry.main() == 0
    assert called == [True, True]


def test_stdin_close_stops():
    import io
    from isharescreen.frontend.wt.server import watch_stdin_close
    calls = []
    watch_stdin_close(io.BytesIO(b"anything\nmore"), lambda: calls.append(1))
    assert calls == [1]


def test_launcher_stop_closes_the_window_at_once():
    import inspect
    from isharescreen.frontend.wt.server import WebTransportBridge
    src = inspect.getsource(WebTransportBridge.run)
    for reason in ("window closed", "viewer left", "terminated", "launcher closed"):
        assert f'"{reason}"' in src
