"""HPG fork: drop-to-keyframe resync for a viewer that falls behind."""
from __future__ import annotations

import pytest

from isharescreen.frontend.wt import server as srv


class _Sender:
    def __init__(self):
        self._buffer_start = 0
        self._buffer_stop = 0


class _Stream:
    def __init__(self):
        self.sender = _Sender()
        self.receiver = type("R", (), {"is_finished": False})()


class _Loss:
    def __init__(self, rtt=0.05, cwnd=62_500):
        # 62.5 KB per 50 ms RTT = 1.25 MB/s (10 Mbit/s)
        self._rtt_smoothed = rtt
        self.congestion_window = cwnd


class _Quic:
    def __init__(self):
        self._streams = {}
        self._loss = _Loss()
        self.sent = []
        self.fail_new_streams = False

    def send_stream_data(self, stream_id, data, end_stream):
        self.sent.append((stream_id, data))
        st = self._streams.get(stream_id)
        if st is not None:
            st.sender._buffer_stop += len(data)


class _H3:
    def __init__(self, quic):
        self._quic = quic
        self._next = 3

    def create_webtransport_stream(self, session_id, is_unidirectional):
        if self._quic.fail_new_streams:
            raise RuntimeError("stream credit exhausted")
        sid = self._next
        self._next += 4
        self._quic._streams[sid] = _Stream()
        return sid


def _viewer(single=True):
    quic = _Quic()
    requests = []
    v = srv._ViewerSession(
        session_id=0, stream_id=0, h3=_H3(quic), loop=None,
        transmit=lambda: None, input_callback=None,
        use_single_stream=single,
        request_keyframe=lambda force=False: requests.append(force),
    )
    return v, quic, requests


KEY = bytes([srv._TYPE_VIDEO_KEY]) + b"k" * 100
DELTA = bytes([srv._TYPE_VIDEO_DELTA]) + b"d" * 100


def _queue(quic, v, nbytes):
    st = quic._streams[v.video_stream_id]
    st.sender._buffer_stop = st.sender._buffer_start + nbytes


@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(srv.time, "monotonic", lambda: t[0])
    return t


def test_in_sync_frames_flow(clock):
    v, quic, req = _viewer()
    v.send_frame(KEY)
    v.send_frame(DELTA)
    assert len(quic.sent) == 2 and v.frames_dropped == 0 and not v.resync_since


def test_behind_enters_resync_and_waits_for_drain(clock):
    v, quic, req = _viewer()
    v.send_frame(KEY)
    _queue(quic, v, 1_000_000)            # 0.8 s at 10 Mbit/s
    v.send_frame(DELTA)
    assert v.resync_since and v.frames_dropped == 1 and v.resyncs == 1
    assert req == []                      # still full: no keyframe on top of it
    v.send_frame(DELTA)                   # dropped while resyncing
    assert v.frames_dropped == 2 and len(quic.sent) == 1


def test_drained_requests_keyframe_and_retries(clock):
    v, quic, req = _viewer()
    v.send_frame(KEY)
    _queue(quic, v, 1_000_000)
    v.send_frame(DELTA)
    _queue(quic, v, 0)                    # drained
    v.resync_tick()
    assert req == [True]
    clock[0] += 1.0
    v.resync_tick()
    assert req == [True]                  # paced
    clock[0] += 0.6
    v.resync_tick()
    assert req == [True, True]            # retried: the Mac may ignore one


def test_keyframe_ends_resync_only_when_deliverable(clock):
    v, quic, req = _viewer()
    v.send_frame(KEY)
    _queue(quic, v, 1_000_000)
    v.send_frame(DELTA)
    v.send_frame(KEY)                     # still 0.8 s behind: not deliverable
    assert v.resync_since
    _queue(quic, v, 0)
    v.send_frame(KEY)
    assert not v.resync_since
    n = len(quic.sent)
    v.send_frame(DELTA)
    assert len(quic.sent) == n + 1


def test_keyframe_alone_does_not_trip_a_drop(clock):
    # 250 KB (one 1080p keyframe) is 0.2 s at 10 Mbit/s: under the limit.
    v, quic, req = _viewer()
    v.send_frame(KEY)
    _queue(quic, v, 250_000)
    v.send_frame(DELTA)
    assert not v.resync_since and v.frames_dropped == 0


def test_still_screen_timer_alone_drives_retries(clock):
    v, quic, req = _viewer()
    v.send_frame(KEY)
    _queue(quic, v, 1_000_000)
    v.send_frame(DELTA)
    _queue(quic, v, 0)
    for _ in range(4):                    # no frames arrive, only the timer
        v.resync_tick()
        clock[0] += 1.0
    assert len(req) >= 2


def test_per_frame_send_failure_resyncs(clock):
    v, quic, req = _viewer(single=False)
    v.send_frame(KEY)
    quic.fail_new_streams = True
    v.send_frame(DELTA)
    assert v.resync_since and v.frames_dropped == 1
    assert req == [True]                  # per-frame: nothing queued to drain
    quic.fail_new_streams = False
    n = len(quic.sent)
    v.send_frame(DELTA)                   # would reference the lost frame
    assert len(quic.sent) == n and v.frames_dropped == 2
    v.send_frame(KEY)
    assert not v.resync_since
    v.send_frame(DELTA)
    assert len(quic.sent) == n + 2


def test_keyframe_in_flight_is_not_counted(clock):
    # On a slow path a big keyframe takes ~1 s to deliver; deltas queued behind
    # it must still flow, or every keyframe trips the next drop.
    v, quic, req = _viewer()
    big_key = bytes([srv._TYPE_VIDEO_KEY]) + b"k" * 1_000_000   # 0.8 s at 10 Mbit/s
    v.send_frame(big_key)
    for _ in range(5):
        v.send_frame(DELTA)
    assert not v.resync_since and v.frames_dropped == 0
    # ...but deltas piling up behind it beyond the limit still trigger a drop.
    many = bytes([srv._TYPE_VIDEO_DELTA]) + b"d" * 700_000
    v.send_frame(many)
    v.send_frame(DELTA)
    assert v.resync_since and v.frames_dropped == 1
