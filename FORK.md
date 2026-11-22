# HPG fork of iShareScreen

This is HPG's fork of **iShareScreen** by renegadelink and contributors
(https://github.com/renegadelink/iShareScreen), forked at commit `9ab40d3`
(2026-07-26). All credit for the client, the protocol work and the browser
viewer goes to that project. This fork is licensed the same way:
**AGPL-3.0-or-later** (see [LICENSE](LICENSE)). Its source is public at
https://github.com/silvercyrex/iShareScreen.

HPG runs the browser viewer (`iss --frontend browser`, the "bridge") on its
own remote-access gateway, one process per viewing session, started by HPG's
status system. The changes below make that safe and fit HPG's two uses:
helping a person in their own session, and IT working in a separate session.

## What this fork changes (2026-11)

**Logging in to the Mac**
- `--share-without-asking`: when someone else is at the Mac, share their
  screen without the "allow" pop-up (Apple's SessionSelect command 1). The
  Mac only offers this to an account with Remote Management rights, and shows
  the person "Your screen is being observed".
- No silent downgrade: `--auth srp` (the default) is SRP only. The older
  login runs only when chosen with `--auth nonsrp`. Upstream retried with the
  older login after any SRP failure.
- The bridge never retries a refused login (upstream retried every 1.5 s,
  each retry another failed login on the Mac).

**Browser bridge**
- A viewer must send a credential first: an HPG ticket (`--ticket-key-file`)
  or a one-time local token. Until then it gets nothing and the bridge does
  not log in to the Mac. Format and checks: `src/isharescreen/frontend/wt/hpg.py`.
- `--bind` (default `127.0.0.1`) instead of listening on every interface.
- View-only viewers (`ro` in the ticket, or `--view-only`), at most one viewer
  in control, and joiners are cut when the session owner leaves.
- The open `POST /log` and `GET /stats` addresses are gone; diagnostics and
  stats travel over the viewer's authenticated connection.
- `--events`: one JSON line per event on stdout for the launcher (`ready`,
  `mac_connected`, `viewer_joined`, `viewer_left`, `session_log`,
  `mac_disconnected`, `ended`). `session_log` lines have the same text as
  HPG's Mac-viewer relay session log.
- `--no-page`, `--linger`, `--idle-timeout`, `--exit-after-session`,
  `--source-url`; clean stop on SIGTERM; exit codes 0 (normal), 1 (stream
  failed), 2 (Mac login refused), 3 (session choice refused).
- Curtain (blanking the Mac's screen) and clipboard sync are off by default.
- The TLS key is written readable by its owner only.
- Fixed a deadlock when a viewer joined a session that was already running.

**Separate session (`--alt-session`)**
- Reconnecting to a user's existing session works. Upstream sent the
  "new login" display setup on every connection; on a reconnect that left the
  session with no picture until the user was logged out on the Mac. The Mac
  answers the session choice only after logging a new user in (about 4-5 s)
  but at once when the session exists (a few ms), so iss now skips that
  setup when the answer is quick.

**Viewer page**
- Can be embedded in HPG's HTTPS page: settings arrive by `postMessage` from
  the parent origin named in `?parent=`, so the ticket never sits in a URL.
- Shows "View only" when the viewer can't control, and a **Source code** link
  (AGPL section 13) set from `--source-url`.
- Decodes without asking for hardware (upstream's "prefer-hardware" showed a
  black screen on machines without a hardware H.264 decoder), and skips to
  the next full frame when the computer can't keep up instead of freezing.

**Other**
- `requirements.lock`: the exact, hashed set of dependencies tested together.

Files changed by this fork carry a "Modified by the HPG fork" note with the
date. `src/isharescreen/frontend/wt/hpg.py` is new.

## Known issues

- The SRP server proof (M2) is still not checked; none of HPG's test Macs
  offer SRP, so a check could not be tested.
- One bridge process per Mac session per address: the client always uses
  local UDP ports 5900/5901.
- The viewer's status bar shows "frozen" whenever the Mac's screen is still
  (upstream behaviour): a still screen is not a fault.

## Running it for a launcher (example)

```sh
printf '%s\n' "$MAC_PASSWORD" | iss --host 100.64.0.4 -u admin --password-stdin \
    --auth nonsrp --share-without-asking --no-audio \
    --bind 100.64.0.6 --bridge-port 4433 --no-page \
    --ticket-key-file /etc/hpg-gateway/iss-bridge.key \
    --events --connection-name TJG7HR9K4C --exit-after-session \
    --source-url https://github.com/silvercyrex/iShareScreen/tree/<commit>
```

The page (`src/isharescreen/frontend/wt/static/index.html`) is served by the
launcher's own HTTPS site and opened as
`index.html?embed=1&parent=<launcher origin>`; the parent page then sends:

```js
viewerFrame.contentWindow.postMessage({
  type: "iss-config",
  wt_url: "https://<bridge address>:<port>/wt",
  cert_sha256: "<cert_sha256 from the bridge's ready event>",
  ticket: "<one-time ticket>",
  source_url: "<same as --source-url>",
  dynamic: false,
}, "<bridge page origin>");
```
