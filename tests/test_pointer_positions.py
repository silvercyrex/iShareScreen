"""HPG fork: every mouse position the page sends comes from one event type
and one mapping (a dragged window jumped when two event types disagreed)."""
from __future__ import annotations

import re
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1]
        / "src/isharescreen/frontend/wt/static/index.html").read_text()


def _handler(event: str) -> str:
    m = re.search(r'canvas\.addEventListener\("%s", \(e\) => \{(.*?)\n  \}\);' % event,
                  PAGE, re.S)
    assert m, event
    return m.group(1)


def test_raw_pointer_updates_never_send_a_position():
    m = re.search(r'addEventListener\("pointerrawupdate", \(e\) => \{(.*?)\}\);', PAGE, re.S)
    assert m
    body = m.group(1)
    assert "pendingMove" not in body and "send" not in body.lower()


def test_moves_and_buttons_map_through_one_function():
    for event in ("mousemove", "mousedown", "mouseup"):
        assert "inWindowToCanvas(e)" in _handler(event), event
    for name in ("offsetX", "offsetY", "pageX", "pageY", "layerX", "layerY", "screenX"):
        assert name not in PAGE, name
    m = re.search(r"function inWindowToCanvas\(ev\) \{(.*?)\n  \}", PAGE, re.S)
    body = m.group(1)
    assert "canvas.getBoundingClientRect()" in body        # current rect, every event
    assert "ev.clientX - rect.left" in body and "ev.clientY - rect.top" in body


def test_stats_report_raw_dy_and_the_bridge_logs_only_a_number():
    from isharescreen.frontend.wt.server import _int_or_dash
    assert "raw_dy: rawDy" in PAGE
    assert _int_or_dash(54) == "54" and _int_or_dash("x<script>") == "-"
    assert _int_or_dash(None) == "-"


def test_pixel_check_reads_a_copy_not_the_video_canvas():
    m = re.search(r"if \(probeCtx\) \{(.*?)\n        \}", PAGE, re.S)
    assert m, "probe path"
    body = m.group(1)
    assert "probeCtx.drawImage(canvas," in body and ", 1, 1, gx, gy, 1, 1)" in body
    assert "probeCtx.getImageData(0, 0, 8, 8)" in body
    assert "ctx.getImageData" not in body.replace("probeCtx.getImageData", "")
