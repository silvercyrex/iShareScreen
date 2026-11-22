"""HPG fork: the native (desktop) viewer for the installed app."""
from __future__ import annotations

import io

import pytest

from isharescreen.cli import _build_session_config, _make_parser
from isharescreen.proxy.session import Session, SessionConfig


class _Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append(name)


def test_view_only_session_drops_all_input():
    s = Session(SessionConfig(host="mac", username="u", password="p", view_only=True))
    real = s._input = _Recorder()
    s.input.pointer_event(1, 10, 10)
    s.input.key_event(True, 0x61)
    s.input.scroll_event(1, 1, 0, 1)
    s.input.send_clipboard_text("secret")
    assert real.calls == []


def test_control_session_passes_input():
    s = Session(SessionConfig(host="mac", username="u", password="p"))
    real = s._input = _Recorder()
    s.input.pointer_event(1, 10, 10)
    assert real.calls == ["pointer_event"]


def _config(monkeypatch, argv, stdin=""):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return _build_session_config(_make_parser().parse_args(argv))


def test_ask_password_and_view_only_reach_the_config(monkeypatch):
    cfg = _config(monkeypatch, ["--frontend", "desktop", "--mac-relay", "127.0.0.1:15900",
                                "-u", "admin", "--ask-password", "--view-only"])
    assert cfg.password == "" and cfg.view_only
    with pytest.raises(SystemExit):           # no password, no prompt: refused
        _config(monkeypatch, ["--frontend", "desktop", "--host", "mac", "-u", "admin"])


def test_password_prompt_sorts_errors():
    from isharescreen.frontend.desktop.password import _classify
    from isharescreen.proxy.protocol.auth import AuthError
    assert _classify(AuthError("result=1")) == ("Wrong user name or password.", 2, True)
    text, code, retry = _classify(RuntimeError(
        "session-select: the Mac did not offer a separate session; nothing was shared"))
    assert code == 3 and not retry and text.startswith("the Mac did not offer")
    assert _classify(OSError("timed out"))[1:] == (1, False)
