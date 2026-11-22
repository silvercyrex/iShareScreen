"""Local app mode (`iss --app`). New file, HPG fork, 2026-11.

The viewer page is served on 127.0.0.1 and opened in a window of its own:
Edge or Chrome/Chromium in app mode with a throw-away profile, so the window
is its own browser process and closing it ends iss. Without such a browser
the default browser opens the page, and iss ends when the page disconnects.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from typing import Callable, Optional

log = logging.getLogger(__name__)


def free_port(host: str = "127.0.0.1") -> int:
    """A port free for both TCP (the page) and UDP (WebTransport) on host."""
    for _ in range(50):
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            tcp.bind((host, 0))
            port = tcp.getsockname()[1]
            udp.bind((host, port))
            return port
        except OSError:
            continue
        finally:
            tcp.close()
            udp.close()
    raise OSError(f"no port free for both TCP and UDP on {host}")


def _windows_candidates() -> list:
    out = []
    for app in (("Microsoft", "Edge", "Application", "msedge.exe"),
                ("Google", "Chrome", "Application", "chrome.exe")):
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                out.append(os.path.join(base, *app))
    return out


_MAC_CANDIDATES = (
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)
_LINUX_NAMES = ("google-chrome", "google-chrome-stable", "chromium",
                "chromium-browser", "microsoft-edge", "microsoft-edge-stable")


def find_browser(override: str = "") -> Optional[str]:
    """Path of a Chromium-family browser to open the app window with, or
    None. `override` (--app-browser) is a path or a command name."""
    if override:
        if os.path.isfile(override):
            return override
        return shutil.which(override)
    if sys.platform == "win32":
        cands = _windows_candidates()
    elif sys.platform == "darwin":
        cands = list(_MAC_CANDIDATES)
    else:
        cands = [p for p in (shutil.which(n) for n in _LINUX_NAMES) if p]
    return next((c for c in cands if os.path.isfile(c)), None)


class AppWindow:
    """One browser window (and process) showing the viewer page."""

    def __init__(self, url: str, browser: str,
                 on_closed: Callable[[], None]) -> None:
        self.profile = tempfile.mkdtemp(prefix="hpg-macviewer-")
        # A fresh profile must not keep its browser running in the background
        # once the window is closed (Edge enables that by default).
        with open(os.path.join(self.profile, "Local State"), "w") as f:
            json.dump({"background_mode": {"enabled": False}}, f)
        args = [browser, f"--app={url}", f"--user-data-dir={self.profile}",
                "--no-first-run", "--no-default-browser-check",
                "--window-size=1440,900"]
        self.proc = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        self._on_closed = on_closed
        threading.Thread(target=self._watch, name="app-window", daemon=True).start()
        log.info("app window opened (%s)", os.path.basename(browser))

    def _watch(self) -> None:
        self.proc.wait()
        self._on_closed()

    def finish(self, wait_s: float = 0.0) -> None:
        """Wait up to `wait_s` for the user to close the window (so a message
        on the page stays readable), then close it and delete its profile."""
        if wait_s > 0:
            try:
                self.proc.wait(timeout=wait_s)
            except subprocess.TimeoutExpired:
                pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        for _ in range(10):          # Windows keeps files locked for a moment
            shutil.rmtree(self.profile, ignore_errors=True)
            if not os.path.exists(self.profile):
                break
            time.sleep(0.3)


def open_app_window(url: str, browser_override: str,
                    on_closed: Callable[[], None]) -> Optional[AppWindow]:
    """Open `url` in its own window; None when only the default browser
    could be used (then the page's disconnect ends iss)."""
    browser = find_browser(browser_override)
    if browser:
        try:
            return AppWindow(url, browser, on_closed)
        except OSError as e:
            log.warning("could not start %s: %s", browser, e)
    log.info("no Edge/Chrome found; opening the default browser")
    webbrowser.open(url)
    return None


__all__ = ["AppWindow", "find_browser", "free_port", "open_app_window"]
