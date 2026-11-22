"""HPG fork: viewer admission (tickets / local token) and launcher events.

Added by the HPG fork (https://github.com/silvercyrex/iShareScreen), 2026-11.
Not part of upstream iShareScreen.

Admission. Every WebTransport viewer must present a credential as the FIRST
line on its bidirectional input stream before the bridge counts it as a
viewer (and so before anything can make the bridge log in to the Mac):

  {"type": "auth", "ticket": "<payload_b64url>.<sig_b64url>"}   # launcher mode
  {"type": "auth", "token": "<random token>"}                   # local mode

Ticket format (same shape as the HPG Mac-viewer relay ticket, own key and
signing prefix so a relay ticket is never accepted here):

  key     = the bridge's derived key (raw bytes from --ticket-key-file),
            e.g. HMAC-SHA256(gateway key, "hpg-iss-bridge-v1")
  sig     = HMAC-SHA256(key, b"hpg-iss-ticket-v1\\0" + payload_b64url)
  payload = {"v":1, "iat":int, "exp":int, "host":str, "port":int,
             "sid":str, "ro":bool, "user":str, "n":str}

Checks: signature, v == 1, not expired, valid for at most 60 s, issued after
the bridge started (minus clock skew), host/port match the Mac this bridge
serves, one-time (nonce `n` remembered).

Events. With --events the bridge writes one JSON object per line on stdout
for the launcher (ready / mac_connected / viewer_joined / viewer_left /
session_log / ended). `session_log` lines carry text in the same shape as
the relay's session log so the gateway's session log reader can use them.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

TICKET_PREFIX = b"hpg-iss-ticket-v1\x00"
TICKET_MAX_LIFETIME_S = 60
CLOCK_SKEW_S = 5
NONCE_MEMORY_S = 300


class AdmissionError(Exception):
    """Credential refused. The message is safe to show the viewer."""


@dataclass(frozen=True)
class Admission:
    user: str
    sid: str
    read_only: bool

    @property
    def is_joiner(self) -> bool:
        # The status app marks a joiner (someone added to an existing session)
        # with "~<name>" after the session id.
        return "~" in self.sid


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign_ticket(key: bytes, payload: dict) -> str:
    """Make a ticket. Used by tests and the lab; HPG's status app signs real ones."""
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(key, TICKET_PREFIX + p.encode(), hashlib.sha256).digest()
    return f"{p}.{_b64url_encode(sig)}"


class TicketVerifier:
    def __init__(self, key: bytes, host: str, port: int,
                 started_at: Optional[float] = None) -> None:
        if len(key) < 16:
            raise ValueError("ticket key too short (need at least 16 bytes)")
        self._key = key
        self._host = host
        self._port = port
        self._started_at = time.time() if started_at is None else started_at
        self._used: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, ticket: str, now: Optional[float] = None) -> Admission:
        now = time.time() if now is None else now
        try:
            p, s = ticket.split(".")
            sig = _b64url_decode(s)
        except Exception:
            raise AdmissionError("malformed ticket") from None
        want = hmac.new(self._key, TICKET_PREFIX + p.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig, want):
            raise AdmissionError("bad ticket signature")
        try:
            pl = json.loads(_b64url_decode(p))
            iat, exp = int(pl["iat"]), int(pl["exp"])
            host, port = str(pl["host"]), int(pl["port"])
            nonce = str(pl["n"])
        except Exception:
            raise AdmissionError("malformed ticket payload") from None
        if pl.get("v") != 1:
            raise AdmissionError("unsupported ticket version")
        if now > exp:
            raise AdmissionError("ticket expired")
        if exp - iat > TICKET_MAX_LIFETIME_S:
            raise AdmissionError("ticket lifetime too long")
        if iat < self._started_at - CLOCK_SKEW_S or iat > now + CLOCK_SKEW_S:
            raise AdmissionError("ticket not issued for this bridge")
        if host != self._host or port != self._port:
            raise AdmissionError("ticket is for a different Mac")
        if not nonce:
            raise AdmissionError("ticket has no nonce")
        with self._lock:
            for n, t in list(self._used.items()):
                if now - t > NONCE_MEMORY_S:
                    del self._used[n]
            if nonce in self._used:
                raise AdmissionError("ticket already used")
            self._used[nonce] = now
        return Admission(
            user=str(pl.get("user", "")),
            sid=str(pl.get("sid", "")),
            read_only=bool(pl.get("ro", True)),
        )


class TokenVerifier:
    """Local (non-launcher) mode: one random token, printed at start-up."""

    def __init__(self, token: Optional[str] = None, read_only: bool = False) -> None:
        self.token = token or secrets.token_urlsafe(24)
        self._read_only = read_only

    def check(self, token: str) -> Admission:
        if not isinstance(token, str) or not hmac.compare_digest(
                token.encode(), self.token.encode()):
            raise AdmissionError("bad token")
        return Admission(user="local", sid="local", read_only=self._read_only)


class EventSink:
    """One JSON object per line on stdout for the launcher. No-op when disabled."""

    def __init__(self, enabled: bool, connection_name: str = "") -> None:
        self.enabled = enabled
        self.connection_name = connection_name or "mac"
        self._lock = threading.Lock()
        self._last_active: dict[str, float] = {}

    def emit(self, event: str, **fields) -> None:
        if not self.enabled:
            return
        line = json.dumps({"event": event, "t": round(time.time(), 3), **fields},
                          separators=(",", ":"))
        with self._lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def session_log(self, text: str) -> None:
        self.emit("session_log", line=text)

    def user_connected(self, user: str) -> None:
        self.session_log(f'User "{user}" connected to connection "{self.connection_name}".')

    def user_disconnected(self, user: str, duration_ms: int, reason: str) -> None:
        self.session_log(
            f'User "{user}" disconnected from connection "{self.connection_name}". '
            f"Duration: {duration_ms} milliseconds. Reason: {reason}")

    def user_active(self, user: str) -> None:
        """At most once every 5 s per user, on input."""
        now = time.monotonic()
        with self._lock:
            last = self._last_active.get(user, 0.0)
            if now - last < 5.0:
                return
            self._last_active[user] = now
        self.session_log(f'User "{user}" active on connection "{self.connection_name}".')


def clean_log_text(text: object, limit: int = 300) -> str:
    """Browser-supplied text going into our log: one line, bounded."""
    s = str(text)[:limit]
    return "".join(ch if ch.isprintable() else " " for ch in s)
