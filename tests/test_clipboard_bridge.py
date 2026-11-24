"""HPG fork: --clipboard text swaps clipboard text between the Mac and the
controlling viewer's browser; never view-only, never logged."""
from __future__ import annotations

import logging

from isharescreen.frontend.wt import server as srv
from isharescreen.frontend.wt.server import WebTransportBridge
from isharescreen.proxy.session import SessionConfig


class _Input:
    def __init__(self):
        self.sent = []

    def cut_text(self, text):
        self.sent.append(text)


class _Session:
    def __init__(self):
        self.input = _Input()


class _Viewer:
    def __init__(self, read_only=False):
        self.read_only = read_only
        self.session_id = 7
        self.controls = []

    def send_control(self, obj):
        self.controls.append(obj)


class _Loop:
    def call_soon_threadsafe(self, fn, *args):
        fn(*args)

    def call_later(self, delay, fn, *args):
        fn(*args)          # run the coalescing flush at once


def _bridge(clipboard=True):
    b = WebTransportBridge.__new__(WebTransportBridge)
    b._clipboard = clipboard
    b._session = _Session()
    b._loop = _Loop()
    b._controller = _Viewer()
    b.viewers = {b._controller}
    return b


def test_flag_reaches_the_session_config_and_not_for_view_only():
    cfg = SessionConfig(host="mac", username="u", password="p")
    on = WebTransportBridge(cfg, clipboard=True)
    assert on._clipboard and on._config.clipboard_sync
    ro = WebTransportBridge(cfg, clipboard=True, view_only=True)
    assert not ro._clipboard and not ro._config.clipboard_sync
    off = WebTransportBridge(cfg)
    assert not off._clipboard and not off._config.clipboard_sync


def test_viewer_text_goes_to_the_mac_and_is_not_logged(caplog):
    b = _bridge()
    caplog.set_level(logging.INFO)
    b._clipboard_to_mac("secret 123")
    assert b._session.input.sent == ["secret 123"]
    assert "secret" not in caplog.text and "10 chars" in caplog.text


def test_nothing_goes_to_the_mac_when_off_or_too_long():
    b = _bridge(clipboard=False)
    b._clipboard_to_mac("x")
    assert b._session.input.sent == []
    b = _bridge()
    b._clipboard_to_mac("x" * (srv._CLIPBOARD_MAX_CHARS + 1))
    b._clipboard_to_mac("")
    b._clipboard_to_mac(123)
    assert b._session.input.sent == []


def test_mac_text_goes_to_the_controller_only():
    b = _bridge()
    b._on_mac_clipboard("from the mac")
    assert b._controller.controls == [{"type": "clipboard", "text": "from the mac"}]
    b._controller.read_only = True
    b._on_mac_clipboard("again")
    assert len(b._controller.controls) == 1


def test_a_copy_spamming_mac_sends_only_the_newest_text():
    b = _bridge()

    class _Held(_Loop):
        def __init__(self):
            self.pending = []

        def call_later(self, delay, fn, *args):
            self.pending.append(fn)
            return object()
    b._loop = _Held()
    for i in range(50):
        b._on_mac_clipboard(f"copy {i}")
    assert len(b._loop.pending) == 1
    b._loop.pending[0]()
    assert b._controller.controls == [{"type": "clipboard", "text": "copy 49"}]


def test_our_own_paste_coming_back_is_not_echoed():
    b = _bridge()
    b._clipboard_to_mac("pasted")
    b._on_mac_clipboard("pasted")
    assert b._controller.controls == []


def test_view_only_viewers_cannot_send_clipboard_text():
    b = _bridge()
    b._view_only = False
    b._events = srv.EventSink(False)
    v = _Viewer(read_only=True)
    v.admission = object()
    b.handle_input_event({"type": "clipboard", "text": "x"}, v)
    assert b._session.input.sent == []


def test_session_hands_mac_text_to_the_page_not_the_gateway_clipboard(monkeypatch):
    from isharescreen.proxy import local_clipboard
    from isharescreen.proxy.protocol.clipboard import build_clipboard_send
    from isharescreen.proxy.session import Session
    pushed = []
    monkeypatch.setattr(local_clipboard, "push_text", pushed.append)
    monkeypatch.delenv("ISS_CLIP", raising=False)
    s = Session(SessionConfig(host="mac", username="u", password="p", clipboard_sync=True))
    got = []
    s.set_clipboard_text_callback(got.append)
    s._handle_clipboard_send(build_clipboard_send("hello"))
    assert got == ["hello"] and pushed == []
    monkeypatch.setenv("ISS_CLIP", "1")
    s._handle_clipboard_send(build_clipboard_send("again"))
    assert pushed == ["again"]


def test_a_later_mac_copy_of_text_we_pasted_still_arrives():
    b = _bridge()
    b._clipboard_to_mac("A")
    b._on_mac_clipboard("A")                      # our echo: skipped
    b._on_mac_clipboard("B")
    b._on_mac_clipboard("A")                      # a real copy on the Mac
    assert b._controller.controls == [{"type": "clipboard", "text": "B"},
                                      {"type": "clipboard", "text": "A"}]


def test_other_mac_text_ends_the_echo_wait():
    b = _bridge()
    b._clipboard_to_mac("A")
    b._on_mac_clipboard("B")                      # the echo never came
    b._on_mac_clipboard("A")
    assert [c["text"] for c in b._controller.controls] == ["B", "A"]
