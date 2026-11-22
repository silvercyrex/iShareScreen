"""HPG fork: media socket readers start early; per-thread CPU and drop counts."""
from __future__ import annotations

import time

from isharescreen.proxy.session import Session, SessionConfig


def _names(targets):
    return [n for n, _ in targets]


def test_drains_start_once_and_are_not_spawned_twice():
    s = Session(SessionConfig(host="mac", username="u", password="p"))
    assert "iss-video-drain" in _names(s._thread_targets())
    s._sock_video = None          # readers exit at once without a socket
    s._sock_ctrl = None
    s._start_drain_threads()
    names = _names(s._thread_targets())
    assert "iss-video-drain" not in names and "iss-ctrl-drain" not in names
    assert "iss-video-process" in names
    s._start_drain_threads()      # idempotent
    assert sum(t.name == "iss-video-drain" for t in s._threads) == 1


def test_teardown_lets_a_reconnect_start_them_again():
    s = Session(SessionConfig(host="mac", username="u", password="p"))
    s._sock_video = None
    s._sock_ctrl = None
    s._start_drain_threads()
    time.sleep(0.05)
    s._teardown()
    assert "iss-video-drain" in _names(s._thread_targets())


def test_video_socket_drops_reads_own_socket():
    import socket
    import sys
    s = Session(SessionConfig(host="mac", username="u", password="p"))
    assert s.video_socket_drops() is None          # no socket yet
    if sys.platform != "linux":
        return
    s._sock_video = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s._sock_video.bind(("127.0.0.1", 0))
    try:
        assert s.video_socket_drops() == 0
    finally:
        s._sock_video.close()


def test_thread_cpu_names_threads():
    import threading
    from isharescreen.frontend.wt.hpg import describe_thread_cpu, thread_cpu_ticks
    stop = threading.Event()

    def spin():
        while not stop.is_set():
            pass
    t = threading.Thread(target=spin, name="iss-spin-test", daemon=True)
    before = thread_cpu_ticks()
    t.start()
    time.sleep(0.5)
    after = thread_cpu_ticks()
    stop.set()
    t.join()
    assert "iss-spin-test" in describe_thread_cpu(before, after, 0.5)


def _slice(nal_type: int, slice_type: int) -> bytes:
    # NAL header + first_mb_in_slice=0 ("1") + slice_type ue(v), byte-padded
    bits = "1" + format(slice_type + 1, "b").zfill(2 * len(format(slice_type + 1, "b")) - 1)
    bits += "1" * (-len(bits) % 8)
    return bytes([0x60 | nal_type]) + int(bits, 2).to_bytes(len(bits) // 8, "big") + b"\x00" * 4


def test_leading_keyframes_stops_after_the_first_keyframe():
    from isharescreen.proxy.media.avc import _nal_is_keyframe
    from isharescreen.proxy.session import _leading_keyframes
    p, i = _slice(1, 0), _slice(1, 2)        # P slice, I slice
    assert _nal_is_keyframe(i) and not _nal_is_keyframe(p)
    burst = {0: [p, i, i, p, p, i]}
    assert _leading_keyframes(burst) == {0: [p, i, i]}
    assert _leading_keyframes({0: [p, p]}) == {0: [p, p]}


def test_bridge_config_asks_for_passthrough():
    import inspect
    from isharescreen.frontend.wt.server import WebTransportBridge
    assert "video_passthrough=True" in inspect.getsource(WebTransportBridge.__init__)


def test_forwarded_keyframe_stops_the_repeat_requests():
    from isharescreen.proxy.media.quality_gate import FrameQualityGate
    from isharescreen.proxy.session import _au_has_keyframe

    class Clock:
        t = 100.0

        def monotonic(self):
            return self.t
    gate = FrameQualityGate(1)
    gate._time = clock = Clock()
    gate.force_keyframe_all()
    asked = 0
    for _ in range(5):                  # nothing decodes here: it keeps asking
        clock.t += 1.1
        asked += len(gate.consume_fir_request())
    assert asked >= 3
    assert _au_has_keyframe([_slice(1, 2)]) and not _au_has_keyframe([_slice(1, 0)])
    gate.mark_keyframe_forwarded(0)
    clock.t += 5.0
    assert gate.consume_fir_request() == set()
    gate.mark_keyframe_forwarded(7)     # out of range: ignored
