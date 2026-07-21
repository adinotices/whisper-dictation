# Push-to-Talk (hold-to-dictate) — Design

**Date:** 2026-07-21
**Status:** Approved (design)

## Problem

The current trigger is a COSMIC custom keyboard shortcut (Super+D) running
`dictate-toggle`: tap to start, tap again to stop. The user wants **hold-to-talk**:
press and hold a key, speak, release to transcribe.

COSMIC (like every Wayland DE shortcut system) fires a shortcut command **only on
key press** — there is no release event to bind to. So hold-to-talk cannot be built
on the COSMIC shortcut mechanism. It requires a process that reads raw keyboard
events (`/dev/input` via evdev) so it can observe both key-down and key-up.

## Approach

A small resident listener, `dictate-ptt`, reads keyboard events and drives the
existing daemon over its Unix socket: key-down → `start`, key-up → `stop`. Nothing
about recording, transcription, or injection changes — only a new trigger front-end
is added. The existing Super+D `toggle` shortcut keeps working, so the user has both
modes.

**PTT key:** Right Ctrl (harmless when held or tapped alone, so no keyboard grab).
**Permissions:** user added to the `input` group for `/dev/input` read access.
**Dependency:** `evdev` added to the existing venv; `dictate-ptt` ships in the package.

## Components

### 1. Daemon: `start` / `stop` commands (`src/dictate/daemon.py`)

`DictationDaemon.handle()` gains two idempotent commands alongside `toggle`:

- `start` → if idle, begin recording (recorder.start + "Listening" notify); if
  already recording, no-op. Returns `recording`.
- `stop` → if recording, run the existing `_stop_and_transcribe` path (stop,
  transcribe, inject, notify); if idle, no-op. Returns `idle`.

Idempotency makes the listener robust to duplicate or missed edges. `toggle`,
`status`, and `quit` are unchanged.

### 2. Listener (`src/dictate/ptt.py`, console script `dictate-ptt`)

- On start, enumerate `/dev/input` via evdev and select every device whose
  capabilities include the PTT key code (i.e. all keyboards — internal and any
  docked external keyboard both work).
- Read key events from all selected devices concurrently. Act **only** on the PTT
  key: value `1` (down) → send `start`; value `0` (up) → send `stop`; value `2`
  (auto-repeat) → ignore.
- **No `EVIOCGRAB`** — the key is not swallowed, so Right Ctrl still works normally
  as a modifier; held alone during speech it does nothing.
- Send commands over the same Unix socket the client uses. A send that fails
  (daemon momentarily down) is logged and does not crash the listener.
- Safety: send one `stop` on startup to clear any stale recording state.

The event→command decision is a pure function
`event_to_command(code, value, ptt_code) -> "start" | "stop" | None`, so the core
logic is unit-testable without real devices. Device enumeration and the socket
sender are injected.

### 3. Config (`src/dictate/config.py`)

New field `ptt_key: str = "rightctrl"`. Mapped to an evdev key code at listener
startup, so the key can be rebound without code changes. Unknown keys fall back to
Right Ctrl with a logged warning.

### 4. systemd `--user` service (`systemd/dictate-ptt.service`)

`After=dictate.service`, `Requires=dictate.service`, `Restart=on-failure`, resident.
Inherits the user's `input` group membership. `WantedBy=default.target` (it needs
`/dev/input` and the daemon socket, not the Wayland session).

### 5. One-time setup (README)

- `sudo usermod -aG input <user>` — then **log out/in once** for the group to apply.
- Install `evdev` into the venv (already handled by `pip install -e .` after the
  dep is added to `pyproject.toml`).
- `systemctl --user enable --now dictate-ptt.service`.

## Data flow

```
Right Ctrl down ──▶ dictate-ptt ──"start"──▶ daemon ──▶ recorder.start()
Right Ctrl up   ──▶ dictate-ptt ──"stop"───▶ daemon ──▶ stop + transcribe + inject
```

## Error handling

- Listener can't reach the daemon socket: log, skip that command, keep running.
  (The service `Requires=dictate.service`, so the daemon is normally up.)
- Listener crash while key is held: daemon stays recording. Mitigation: user taps
  Super+D to toggle off; `Restart=on-failure` revives the listener. No max-record
  timer in v1.
- Key already held when the listener starts: the eventual key-up sends `stop`,
  which is a harmless no-op if idle.
- Duplicate down/up or repeats: absorbed by idempotent `start`/`stop` + repeat
  filtering.

## Testing (TDD; keep the existing 28 green)

- Daemon: `start` when idle → recording + started; `start` when recording → no
  second start; `stop` when recording → transcribes + injects; `stop` when idle →
  no-op.
- PTT: `event_to_command` returns `start`/`stop`/`None` for down/up/repeat and
  ignores other key codes; listener sends the mapped command through a fake sender.
- Existing daemon/audio/inject/config/client tests remain green.

## Out of scope (v1)

- Live hotplug of keyboards added after listener start (needs pyudev). Documented
  limitation; the service can be restarted to pick up a new keyboard.
- Max-recording safety timeout.
- Rebinding via GUI (config edit only).
