"""HPG fork: the viewer page's key bar latch (runs the page's own JS in node)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "src/isharescreen/frontend/wt/static/index.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

CMD, OPT, CTRL, SHIFT = 0xFFEB, 0xFFE7, 0xFFE3, 0xFFE1
RET, ESC, A = 0xFF0D, 0xFF1B, ord("a")


def _latch_source() -> str:
    m = re.search(r"// KEYLATCH-BEGIN.*?// KEYLATCH-END", PAGE.read_text(), re.S)
    assert m, "KEYLATCH block not found in index.html"
    return m.group(0)


def _run(steps: str) -> list:
    """Run `steps` against a fresh latch; returns the [keysym, down] events."""
    script = _latch_source() + """
const ev = [];
const L = makeKeyLatch((k, d) => ev.push([k, d]), null);
function real(k) { ev.push([k, true]); L.realKeyDown(k); ev.push([k, false]); L.realKeyUp(k); }
""" + steps + "\nprocess.stdout.write(JSON.stringify({ev, held: L.latched()}));\n"
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_option_return_from_own_keyboard():
    # Sina's case: latch Option, press Return on his own keyboard.
    r = _run(f"L.toggle({OPT}); real({RET});")
    assert r["ev"] == [[OPT, True], [RET, True], [RET, False], [OPT, False]]
    assert r["held"] == []


def test_click_latched_again_releases_without_sending_anything_else():
    r = _run(f"L.toggle({CMD}); L.toggle({CMD});")
    assert r["ev"] == [[CMD, True], [CMD, False]] and r["held"] == []


def test_modifiers_never_count_as_the_next_key():
    r = _run(f"L.toggle({CMD}); real({SHIFT}); real(0xffe2); real({A});")
    assert r["ev"][-2:] == [[A, False], [CMD, False]]
    assert [CMD, False] not in r["ev"][:-1]


def test_bar_tap_releases_latched_in_reverse_order():
    r = _run(f"L.toggle({CTRL}); L.toggle({OPT}); L.tap({ESC});")
    assert r["ev"] == [[CTRL, True], [OPT, True], [ESC, True], [ESC, False],
                       [OPT, False], [CTRL, False]]


def test_combo_releases_latched_first():
    r = _run(f"L.toggle({SHIFT}); L.combo([{CMD}, {OPT}, {ESC}]);")
    assert r["ev"] == [[SHIFT, True], [SHIFT, False],
                       [CMD, True], [OPT, True], [ESC, True],
                       [ESC, False], [OPT, False], [CMD, False]]


def test_next_mouse_click_releases():
    r = _run(f"L.toggle({OPT}); L.mouseUp();")
    assert r["ev"] == [[OPT, True], [OPT, False]] and r["held"] == []


def test_clear_forgets_without_sending():
    r = _run(f"L.toggle({OPT}); L.clear();")
    assert r["ev"] == [[OPT, True]] and r["held"] == []


def test_nothing_latched_keys_pass_through():
    r = _run(f"real({A}); L.mouseUp();")
    assert r["ev"] == [[A, True], [A, False]]


def test_keysyms_match_apple():
    r = subprocess.run([NODE, "-e", _latch_source() + """
process.stdout.write(JSON.stringify([KEYBAR_KEYSYM.cmd, KEYBAR_KEYSYM.opt, KEYBAR_KEYSYM.f1,
  KEYBAR_KEYSYM.f12, KEYBAR_KEYSYM.caps]));"""], capture_output=True, text=True, check=True)
    assert json.loads(r.stdout) == [0xFFEB, 0xFFE7, 0xFFBE, 0xFFC9, 0xFFE5]
