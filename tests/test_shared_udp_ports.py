"""HPG fork: several processes share UDP 5900/5901, one Mac each (Linux)."""
from __future__ import annotations

import socket
import sys

import pytest

from isharescreen.proxy.session import Session

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux socket semantics")


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_connected_sockets_share_a_port_and_demux_by_peer():
    port = _free_port()
    mac_a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mac_b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mac_a.bind(("127.0.0.2", 0))
    mac_b.bind(("127.0.0.3", 0))
    sess_a = Session._bind_udp("127.0.0.1", port, mac_a.getsockname())
    sess_b = Session._bind_udp("127.0.0.1", port, mac_b.getsockname())
    try:
        for s in (sess_a, sess_b):
            s.settimeout(1.0)
        mac_a.sendto(b"from-a", ("127.0.0.1", port))
        mac_b.sendto(b"from-b", ("127.0.0.1", port))
        assert sess_a.recvfrom(100)[0] == b"from-a"
        assert sess_b.recvfrom(100)[0] == b"from-b"
        # sending with an explicit address still works on a connected socket
        sess_a.sendto(b"to-a", mac_a.getsockname())
        mac_a.settimeout(1.0)
        assert mac_a.recvfrom(100)[0] == b"to-a"
    finally:
        for s in (sess_a, sess_b, mac_a, mac_b):
            s.close()


def test_cli_flag_reaches_config(monkeypatch):
    import io
    from isharescreen.cli import _build_session_config, _make_parser
    monkeypatch.setattr("sys.stdin", io.StringIO("x\n"))
    args = _make_parser().parse_args(
        ["--host", "mac", "-u", "a", "--password-stdin", "--shared-udp-ports"])
    assert _build_session_config(args).udp_connect is True
