"""HPG fork: SessionSelect cmd=1 (share without asking) and no silent SRP downgrade."""
from __future__ import annotations

import struct

import pytest

from isharescreen.proxy.protocol import negotiation as neg
from isharescreen.proxy.protocol.auth import AuthError


class _FakeSock:
    def __init__(self, reply: bytes = b"\x00" * 82):
        self.sent = b""
        self.reply = reply
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def settimeout(self, _t) -> None:
        pass

    def recv(self, _n: int) -> bytes:
        return self.reply

    def close(self) -> None:
        self.closed = True


def test_share_body_cmd_byte():
    assert neg._build_ss_cmd0_body("Admin")[6] == 0
    body = neg._build_ss_cmd0_body("Admin", cmd=1)
    assert len(body) == 72
    assert body[6] == 1
    assert body[8:14] == b"Admin\x00"


def test_share_body_rejects_other_cmds():
    with pytest.raises(ValueError):
        neg._build_ss_cmd0_body("Admin", cmd=2)


def test_no_ask_sends_cmd1_when_offered(monkeypatch):
    monkeypatch.setattr(neg, "_read_ss_prompt", lambda s: (0x7, "Admin"))
    sock = _FakeSock()
    assert neg._phase_session_select(
        sock, mode="share_console_no_ask",
        username="u", password="p", ecb_key=b"\x00" * 16,
    ) is not None
    (length,) = struct.unpack(">H", sock.sent[:2])
    assert length == 72
    assert sock.sent[2 + 6] == 1


def test_no_ask_refuses_when_not_offered(monkeypatch):
    # flags=0x5: cmd 0 (ask) and cmd 2 (own session) only
    monkeypatch.setattr(neg, "_read_ss_prompt", lambda s: (0x5, "Admin"))
    sock = _FakeSock()
    with pytest.raises(RuntimeError, match="Remote Management"):
        neg._phase_session_select(
            sock, mode="share_console_no_ask",
            username="u", password="p", ecb_key=b"\x00" * 16,
        )
    assert sock.sent == b""  # never falls back to the asking popup


def test_cli_flag_reaches_config(monkeypatch):
    import io
    from isharescreen.cli import _build_session_config, _make_parser
    monkeypatch.setattr("sys.stdin", io.StringIO("secret\n"))
    args = _make_parser().parse_args(
        ["--host", "mac", "-u", "admin", "--password-stdin", "--share-without-asking"])
    cfg = _build_session_config(args)
    assert cfg.share_without_asking is True


def test_srp_failure_does_not_fall_back(monkeypatch):
    socks = []

    def fake_open(host, port, recorder):
        s = _FakeSock()
        socks.append(s)
        return s

    def srp_fails(sock, user, pw):
        raise AuthError("SRP challenge too short (22B)")

    def nonsrp_must_not_run(sock, user, pw):
        raise AssertionError("non-SRP login must not run when SRP was asked for")

    monkeypatch.setattr(neg, "_open_socket_and_handshake", fake_open)
    monkeypatch.setattr(neg, "do_srp_auth", srp_fails)
    monkeypatch.setattr(neg, "do_nonsrp_auth", nonsrp_must_not_run)
    with pytest.raises(AuthError, match="--auth nonsrp"):
        neg._phase_auth("mac", 5900, "u", "p", "srp")
    assert len(socks) == 1 and socks[0].closed


def test_nonsrp_only_when_asked(monkeypatch):
    monkeypatch.setattr(neg, "_open_socket_and_handshake", lambda h, p, r: _FakeSock())
    monkeypatch.setattr(neg, "do_nonsrp_auth", lambda s, u, p: b"k" * 16)

    def srp_must_not_run(sock, user, pw):
        raise AssertionError("SRP must not run when non-SRP was asked for")

    monkeypatch.setattr(neg, "do_srp_auth", srp_must_not_run)
    _sock, key = neg._phase_auth("mac", 5900, "u", "p", "nonsrp")
    assert key == b"k" * 16


def test_ack_delay_tells_existing_session(monkeypatch):
    # A quick ack on the own-session path means the user's session exists
    # (the daemon answers a first login only after logging the user in).
    monkeypatch.setattr(neg, "_read_ss_prompt", lambda s: (0x7, "Admin"))
    delay = neg._phase_session_select(
        _FakeSock(), mode="alt_session",
        username="rstest", password="p", ecb_key=b"\x00" * 16,
    )
    assert delay is not None and delay < neg._SS_EXISTING_SESSION_ACK_S


def test_no_prompt_returns_none(monkeypatch):
    monkeypatch.setattr(neg, "_read_ss_prompt", lambda s: None)
    assert neg._phase_session_select(
        _FakeSock(), mode="alt_session",
        username="u", password="p", ecb_key=b"\x00" * 16) is None


class _Stop(Exception):
    pass


def _negotiate_without_prompt(monkeypatch, **kw):
    monkeypatch.setattr(neg, "_phase_auth", lambda *a, **k: (_FakeSock(), b"\x00" * 16))
    monkeypatch.setattr(neg, "_phase_client_init", lambda s: (1920, 1080))
    monkeypatch.setattr(neg, "_peek_ss_prompt", lambda s, *a, **k: False)

    def handshake(*a, **k):
        raise _Stop()
    monkeypatch.setattr(neg, "_phase_handshake_plaintext", handshake)
    return neg.connect_and_negotiate("mac", 5900, "u", "p", audio_offer=b"a",
                                     video_offer=b"v", **kw)


def test_alt_session_never_falls_back_to_the_console(monkeypatch):
    # The Mac offers no session choice (its screen shows the login window):
    # streaming the console here would put "my own session" keys into it.
    with pytest.raises(RuntimeError, match="did not offer a separate session"):
        _negotiate_without_prompt(monkeypatch, alt_session=True)


def test_console_share_without_prompt_still_proceeds(monkeypatch):
    with pytest.raises(_Stop):
        _negotiate_without_prompt(monkeypatch, share_console=True)
