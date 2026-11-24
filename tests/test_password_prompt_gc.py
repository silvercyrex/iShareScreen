"""HPG fork: the Tk password window's objects are collected on the thread
that made them (Tcl aborts the process when another thread frees them)."""
from __future__ import annotations

from isharescreen.frontend.desktop import password


def test_collects_right_after_the_window_on_the_same_thread(monkeypatch):
    import threading
    order = []
    monkeypatch.setattr(password, "_prompt",
                        lambda *a: order.append(("prompt", threading.get_ident()))
                        or ("session", 0, "connected"))
    monkeypatch.setattr(password.gc, "collect",
                        lambda: order.append(("gc", threading.get_ident())) or 0)
    out = password.connect_with_prompt("u", "Mac", lambda pw: None)
    assert out == ("session", 0, "connected")
    assert [o[0] for o in order] == ["prompt", "gc"]
    assert order[0][1] == order[1][1]
