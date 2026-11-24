"""HPG fork: on Windows/Linux, Alt is the Mac's Option key. screensharingd
reads Meta_L/R (0xffe7/0xffe8) as Option and Alt_L/R (0xffe9/0xffea) as
Command; the Win key stays Command (Super)."""
from __future__ import annotations

import importlib
import sys

import glfw

from isharescreen.frontend.desktop import keyboard_grab as grab
from isharescreen.frontend.desktop import keymap


def test_windows_grab_sends_option_for_alt_and_command_for_win():
    assert grab._vk_to_keysym(grab._VK_LMENU) == 0xffe7
    assert grab._vk_to_keysym(grab._VK_MENU) == 0xffe7
    assert grab._vk_to_keysym(grab._VK_RMENU) == 0xffe8
    assert grab._vk_to_keysym(grab._VK_LWIN) == 0xffeb
    # right Alt (AltGr on European layouts) is still left to the char path
    assert grab._VK_RMENU not in grab._MODIFIER_VKS


def test_desktop_keymap_alt_is_option_off_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    km = importlib.reload(keymap)
    try:
        assert km.GLFW_KEY_TO_X11[glfw.KEY_LEFT_ALT] == 0xffe7
        assert km.GLFW_KEY_TO_X11[glfw.KEY_RIGHT_ALT] == 0xffe8
        assert km.GLFW_KEY_TO_X11[glfw.KEY_LEFT_SUPER] == 0xffeb
    finally:
        monkeypatch.undo()
        importlib.reload(keymap)


def test_desktop_keymap_unchanged_on_a_mac_viewer(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    km = importlib.reload(keymap)
    try:
        assert km.GLFW_KEY_TO_X11[glfw.KEY_LEFT_ALT] == 0xffe9
    finally:
        monkeypatch.undo()
        importlib.reload(keymap)
