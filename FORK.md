# HPG fork of iShareScreen

This is HPG's fork of **iShareScreen** by renegadelink and contributors
(https://github.com/renegadelink/iShareScreen), forked at commit `9ab40d3`
(2026-07-26). All credit for the client, the protocol work and the browser
viewer goes to that project. This fork is licensed the same way:
**AGPL-3.0-or-later** (see [LICENSE](LICENSE)). Its source is public at
https://github.com/silvercyrex/iShareScreen on the `hpg/fork-fixes` branch
(`main` is kept as an unchanged copy of upstream).

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
- `--shared-udp-ports` (Linux): several bridges on one gateway address can
  stream from different Macs at once. The Mac always sends to the viewer's
  UDP 5900/5901; each process now connects its sockets to its own Mac so
  Linux hands each Mac's packets to the right process. Without it, a second
  session starting on the gateway took the first one's packets.

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

**Slow and lossy connections (2026-11-22)**
- A still screen (e.g. a login window) no longer makes the bridge ask the
  Mac for a full ~250 KB keyframe about every second; on a slow connection
  that alone froze the picture and delayed keys by 3-4 s.
- A viewer that falls behind is judged in time on its own connection
  (more than 0.5 s of video queued, not counting a keyframe on its way),
  frames are skipped until a fresh keyframe, which is requested again every
  1.5 s until it gets through. Same for the per-frame transport when a
  frame can't be sent.
- Media sockets ask for an 8 MB receive buffer and log what the kernel
  gave (the host's `net.core.rmem_max` caps it; 16 MB recommended). Kernel
  buffer drops are logged and shown on the page.
- Status line: "no change Ns" for a still screen, "catching up" only while
  a viewer waits for a keyframe, "skipped N", "buffer drops N".
- Lab (50 ms delay, 1% loss, 10 Mbit/s towards the browser): key to
  picture on a still screen 3.2 s -> 0.08 s; full-screen animation
  0.9 fps with 6 s freezes -> 4-9 fps.

**Key bar**
- Latching Command, Option, Control, Shift (held until the next key or
  click, a second click releases), Caps Lock, Esc, Tab, Return, arrows,
  F1-F12. Applies to the next mouse click too. Disabled for view-only
  viewers. An embedding page may send `{type: "iss-keys", action:
  "toggle"|"tap"|"combo"|"clear", keys: [...]}`.

**Session start and busy screens**
- The bridge no longer decodes the Mac's whole opening burst before showing
  anything: it never uses that decode (the browser decodes), and on
  full-motion content (an animated lock screen) software decoding took about
  12 s on a gateway without a GPU while the Mac's video went unread. Only the
  burst's first keyframe is decoded now (0.2 s).
- The media socket readers start right after the opening burst instead of
  after the rest of the set-up.
- The thread switch interval is 0.5 ms (`ISS_GIL_SWITCH_MS`). With Python's
  default 5 ms, a busy process let the socket reader take only ~500 packets
  per second, so the kernel dropped the Mac's start-up burst.
- Logs: kernel drops on this session's video socket each second ("video
  socket overflow"), their total in the `mac_disconnected` event
  (`video_drops`), and every 10 s "cpu by thread".

**Display delay in the browser**
- The H.264 stream sent to browsers now says it never reorders frames
  (High profile `constraint_set3_flag`). Without that, the browser's decoder
  held back up to 16 frames before showing one: in the lab (Chrome on
  macOS) 282 ms from decode to output. Motion-to-photon on the LAN (mouse
  move in the page to the Mac's reaction on screen in the page) went from
  357 ms to 74 ms. `ISS_BROWSER_NO_REORDER=0` turns it off.
- Every 10 s the log has "frame timing": time from a frame's first packet
  to its hand-off to the viewers, and from there into the QUIC stream.

**Separate session safety**
- `--alt-session` refuses when the Mac offers no session choice (its screen
  shows the login window). Upstream streamed the console instead, so keys
  meant for the user's own session went into the login window.

**Audio**
- Includes upstream pull request #32 by Vincent Janelle (not yet merged
  upstream): the Mac's audio is decoded with the bundled PyAV on Linux and
  Windows. Ubuntu's `libfdk-aac2` package lacks the part Apple's audio needs,
  so without this a Linux gateway had no audio. Browsers only start sound
  after the viewer clicks the speaker button.

**Bitrate feedback (optional)**
- Includes upstream pull request #34 by Charles Vestal (not yet merged
  upstream): Apple's RCTL receiver rate feedback. With `ISS_RCTL=1` the
  bridge caps it at 80% of the slowest viewer's connection rate. Off by
  default: in the lab (macOS 27, H.264) the Mac ignored it, sending 43-63
  Mbit/s while asked for 4-5.

**Settings (environment)**
- `ISS_UDP_RCVBUF` (bytes, default 8 MB), `ISS_WT_MAX_BEHIND_MS` (500),
  `ISS_WT_RESUME_BEHIND_MS` (150), `ISS_WT_KEYFRAME_RETRY_MS` (1500),
  `ISS_WT_CONGESTION` (`reno`; `cubic` was worse in the lab),
  `ISS_RCTL` (off), `ISS_WT_RCTL_SHARE` (0.8), `ISS_WT_RCTL_MIN_KBPS` (800),
  `ISS_GIL_SWITCH_MS` (0.5), `ISS_BROWSER_NO_REORDER` (on).

**Other**
- `requirements.lock`: the exact, hashed set of dependencies tested together.

Files changed by this fork carry a "Modified by the HPG fork" note with the
date. `src/isharescreen/frontend/wt/hpg.py` is new.

## Known issues

- The SRP server proof (M2) is still not checked; none of HPG's test Macs
  offer SRP, so a check could not be tested.
- Two sessions to the SAME Mac from one gateway address at the same time
  are not possible (the Mac always streams to UDP 5900/5901). Different Macs
  at the same time work with `--shared-udp-ports`; tested with one real Mac
  plus a second process holding the ports (only one test Mac exists).
- An animated lock screen (macOS aerial wallpaper) makes the Mac send about
  44 Mbit/s at 1080p, which the bridge can't fully receive (about half is
  dropped in the lab) and no outside connection could carry; nothing the
  viewer can request lowers it (rate feedback, a smaller screen). Use a still
  lock screen picture on managed Macs.
- The viewer's status bar shows "frozen" whenever the Mac's screen is still
  (upstream behaviour): a still screen is not a fault.

## Running it for a launcher (example)

```sh
printf '%s\n' "$MAC_PASSWORD" | iss --host 100.64.0.4 -u admin --password-stdin \
    --auth nonsrp --share-without-asking --no-audio \
    --bind 100.64.0.6 --bridge-port 4433 --no-page \
    --ticket-key-file /etc/hpg-gateway/iss-bridge.key \
    --events --connection-name TJG7HR9K4C --exit-after-session --shared-udp-ports \
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
