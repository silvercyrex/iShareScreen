"""Native Mac password prompt for the desktop viewer. New file, HPG fork,
2026-11.

`connect_with_prompt` shows a small window asking for the Mac password,
connects while showing "Connecting to …", asks again after a wrong password
(each wrong one is a failed login on the Mac, so 3 tries), and reports a
refusal (no right to share, no separate session offered) in the same window.
Only a connected session comes back; the video window opens after that.
"""
from __future__ import annotations

import gc
import logging
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)

MAX_TRIES = 3


def _classify(exc: BaseException) -> "tuple[str, int, bool]":
    """(message for the user, exit code, may the user try again)."""
    from ...proxy.protocol.auth import AuthError
    if isinstance(exc, AuthError):
        return "Wrong user name or password.", 2, True
    text = str(exc)
    if "session-select" in text:
        return text.split(":", 1)[-1].strip().rstrip(".") + ".", 3, False
    return f"Could not connect: {text}", 1, False


def connect_with_prompt(
    user: str,
    name: str,
    connect: Callable[[str], object],
    max_tries: int = MAX_TRIES,
) -> "tuple[Optional[object], int, str]":
    """Ask for the password and run `connect(password)` (which returns a
    connected session or raises). Returns (session or None, exit code, reason).
    Without a usable GUI toolkit it returns (None, 1, reason)."""
    result = _prompt(user, name, connect, max_tries)
    # The window's callbacks refer to themselves and to the Tk root, so the
    # Tk objects are only freed by the garbage collector, and Tcl aborts the
    # process if that happens on another thread ("Tcl_AsyncDelete: async
    # handler deleted by the wrong thread", seen on Windows once the session's
    # threads ran). Collect them here, on the thread that created them.
    gc.collect()
    return result


def _prompt(user, name, connect, max_tries):
    try:
        import tkinter as tk
    except ImportError:
        return None, 1, "no window toolkit (tkinter) for the password prompt"
    try:
        root = tk.Tk()
    except tk.TclError as e:          # no display
        return None, 1, f"cannot open the password window: {e}"

    state = {"session": None, "code": 0, "reason": "cancelled", "tries": max_tries,
             "busy": False, "result": None}
    root.title("HPG Mac viewer")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    frame = tk.Frame(root, padx=18, pady=14)
    frame.pack()
    tk.Label(frame, text=f"Password for {user} on {name}", anchor="w",
             font=("TkDefaultFont", 11, "bold")).pack(fill="x")
    entry = tk.Entry(frame, show="●", width=34)
    entry.pack(fill="x", pady=(10, 4))
    msg = tk.Label(frame, text="", fg="#b00020", anchor="w", justify="left",
                   wraplength=300)
    msg.pack(fill="x")
    buttons = tk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    cancel_btn = tk.Button(buttons, text="Cancel", width=10)
    cancel_btn.pack(side="right")
    ok_btn = tk.Button(buttons, text="Connect", width=10, default="active")
    ok_btn.pack(side="right", padx=(0, 6))

    def finish(code: int, reason: str) -> None:
        state["code"], state["reason"] = code, reason
        root.destroy()

    def worker(password: str) -> None:
        try:
            state["result"] = ("ok", connect(password))
        except Exception as e:  # noqa: BLE001 - shown to the user
            state["result"] = ("error", e)

    def poll() -> None:
        res = state["result"]
        if res is None:
            root.after(100, poll)
            return
        state["result"], state["busy"] = None, False
        kind, value = res
        if kind == "ok":
            state["session"] = value
            finish(0, "connected")
            return
        text, code, retry = _classify(value)
        log.info("Mac login: %s", text)
        msg.config(fg="#b00020")
        if retry:
            state["tries"] -= 1
            if state["tries"] <= 0:
                retry = False
                text = f"{text} No tries left."
        if retry:
            left = state["tries"]
            msg.config(text=f"{text} {left} {'try' if left == 1 else 'tries'} left.")
            entry.config(state="normal")
            ok_btn.config(state="normal")
            entry.delete(0, "end")
            entry.focus_set()
            return
        # Not something a new password fixes: show it, then only Close.
        state["code"], state["reason"] = code, text
        msg.config(text=text)
        ok_btn.pack_forget()
        cancel_btn.config(text="Close", command=root.destroy)

    def submit(_event=None) -> None:
        if state["busy"]:
            return
        password = entry.get()
        if not password:
            return
        entry.delete(0, "end")
        state["busy"] = True
        entry.config(state="disabled")
        ok_btn.config(state="disabled")
        msg.config(text=f"Connecting to {name}…", fg="#444444")
        threading.Thread(target=worker, args=(password,), name="mac-login",
                         daemon=True).start()
        root.after(100, poll)

    def cancel(_event=None) -> None:
        if not state["busy"]:
            finish(0, "cancelled")

    ok_btn.config(command=submit)
    cancel_btn.config(command=cancel)
    root.bind("<Return>", submit)
    root.bind("<Escape>", cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)
    entry.focus_set()
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry(f"+{(root.winfo_screenwidth() - w) // 2}+{(root.winfo_screenheight() - h) // 3}")
    root.mainloop()
    if state["session"] is None and state["code"] == 0 and state["reason"] == "connected":
        state["code"], state["reason"] = 1, "no session"
    return state["session"], state["code"], state["reason"]


__all__ = ["connect_with_prompt", "MAX_TRIES"]
