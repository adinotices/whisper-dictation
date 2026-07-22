# Push-to-Talk Hotplug — Design

**Date:** 2026-07-22
**Status:** Approved (design)

## Problem

`dictate-ptt` enumerates keyboards **once at startup** (`select_keyboards` over
`evdev.list_devices()`). On a docked machine (USB-C hub, external keyboards like the
Logitech K860 that come and go) any keyboard connected *after* the listener starts is
never watched, so holding Right Ctrl on it does nothing until a manual
`systemctl --user restart dictate-ptt.service`. Observed live: the service was
listening only on the two built-in keyboards while the user pressed Right Ctrl on the
externally-docked K860.

## Approach

Re-scan the device set periodically and on device loss, with **no new dependency**.
The existing `select()` loop gains a timeout; each time it wakes (whether from a key
event or the timeout) it reconciles the open device set against the current
`/dev/input` contents — opening newly-appeared keyboards, closing removed ones. A
device that vanishes mid-read raises `OSError`, which drops it immediately.

## Components (`src/dictate/ptt.py`)

### 1. `reconcile_devices(current, ptt_code, list_devices, opener) -> (added, removed)`

Mutates `current` (a `{path: device}` dict) in place to match reality:
- **Removed:** for each tracked path no longer in `list_devices()`, `close()` and drop
  it. Collect its name for the return.
- **Added:** for each present path not already tracked, open it; keep it only if its
  `EV_KEY` capabilities include `ptt_code` (else close immediately); skip devices that
  can't be opened (`PermissionError`/`OSError` — permission or hotplug race).
- Returns the lists of added/removed device names so the caller can log changes.

Pure of global state and fully unit-testable with fake openers/listers.

### 2. `run_listener(ptt_code, sender, ...)` — the loop

- Maintain `devices: {path: device}`; seed it via `reconcile_devices`.
- Loop: `select.select(fds, [], [], POLL_INTERVAL)`.
  - For each readable fd, `read()` its events through `dispatch_events`; on `OSError`
    (device yanked) drop that fd/device.
  - After handling (or on timeout), call `reconcile_devices` again; log any
    added/removed device names to stderr.
- `POLL_INTERVAL = 1.0` s — a docked keyboard becomes live within ~1 s, no busy-wait.

`select_keyboards` is kept (still used/tested) but `main()` now drives `run_listener`.
`event_stream` (the fixed-device generator) is superseded by the loop.

### 3. `main()`

Resolve `ptt_code`, build the initial device set via `reconcile_devices`; if empty,
print the "in the 'input' group?" hint and exit 1 (unchanged). Send a startup `stop`
to clear stale state, log the initial device names, then `run_listener`.

## Behaviour

```
dock K860   → within ~1s reconcile opens it → Right Ctrl works, no restart
undock K860 → device removed cleanly, others keep working
daemon down → sender OSError still swallowed (unchanged)
```

## Testing (TDD; keep the suite green)

- `reconcile_devices`: opens a newly-present keyboard; closes a removed one (and its
  `.close()` is called); ignores a present non-keyboard (no PTT key); skips an
  unopenable path; returns added/removed names; is idempotent when nothing changed.
- Existing `select_keyboards` / `event_to_command` / `dispatch_events` tests stay green.
- Loop wiring (`run_listener`, `select`) stays thin and is exercised via the reconcile
  unit tests + a live smoke test (dock the K860, confirm PTT works without restart).

## Out of scope

- udev/pyudev netlink monitoring (a dependency; the 1 s poll is enough for keyboards).
- Desktop notifications on device change (stderr log only).
