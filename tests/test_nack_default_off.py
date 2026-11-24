"""The Mac never retransmits, so iss sends no NACK by default and waits for a
missing H.264 packet only as long as a reorder takes; ISS_NACK=1 restores both."""
import os
import subprocess
import sys
import types
from collections import defaultdict

from isharescreen.proxy import session as sess


def test_defaults():
    assert sess._NACK_ENABLED is False
    assert sess._AVC_RTP_REPAIR_WAIT_S == 0.010


def test_drain_sends_nothing_and_clears_when_off():
    s = sess.Session.__new__(sess.Session)
    s._nack_pending = defaultdict(set, {0x1000: {11, 12}})
    s._video_rtcp_dest = lambda: (_ for _ in ()).throw(AssertionError("must not send"))
    s._drain_pending_nack()
    assert not s._nack_pending


def test_env_restores_nack_and_long_wait():
    # In a fresh interpreter: reloading the module here would swap the
    # classes other tests already imported.
    code = ("from isharescreen.proxy import session as s; "
            "print(s._NACK_ENABLED, s._AVC_RTP_REPAIR_WAIT_S)")
    env = dict(os.environ, ISS_NACK="1")
    env.pop("ISS_AVC_REPAIR_WAIT_MS", None)
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["True", "0.075"]
    env = dict(os.environ, ISS_AVC_REPAIR_WAIT_MS="30")
    env.pop("ISS_NACK", None)
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["False", "0.03"]
