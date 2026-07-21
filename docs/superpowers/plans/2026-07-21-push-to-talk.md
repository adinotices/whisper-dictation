# Push-to-Talk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hold-to-talk dictation: hold Right Ctrl to record, release to transcribe, via an evdev listener that drives the existing daemon.

**Architecture:** A new resident listener (`dictate-ptt`) reads keyboard events from `/dev/input` (evdev) and sends idempotent `start`/`stop` commands to the existing daemon over its Unix socket. The daemon's recording/transcription/injection path is unchanged; only new command verbs and a new trigger front-end are added. The Super+D `toggle` shortcut keeps working.

**Tech Stack:** Python 3.11+, evdev, faster-whisper (unchanged), Unix domain sockets, systemd --user.

## Global Constraints

- `requires-python = ">=3.11"` (uses stdlib `tomllib`).
- PTT key default: Right Ctrl (`evdev.ecodes.KEY_RIGHTCTRL`). No `EVIOCGRAB` — the key is never swallowed.
- Listener acts only on the PTT key: value `1` → `start`, `0` → `stop`, `2` (auto-repeat) → ignore.
- `start`/`stop` on the daemon must be idempotent (safe to send twice).
- All new logic dependency-injected (event source, socket sender, device opener) so it is unit-testable without real `/dev/input`.
- Keep the existing 28 tests green. Run the full suite with `.venv/bin/pytest -q` from the repo root.
- Commit messages end with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.

---

### Task 1: Daemon `start` / `stop` commands

**Files:**
- Modify: `src/dictate/daemon.py` (the `DictationDaemon.handle` method, ~lines 32-44)
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: existing `DictationDaemon` (config, recorder, transcriber, injector, notifier, wav_path), existing `_stop_and_transcribe()`.
- Produces: `DictationDaemon.handle("start") -> "recording"` and `handle("stop") -> "idle"`, both idempotent. `toggle`/`status`/`quit` unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_daemon.py` (reuse the existing `make_daemon` helper):

```python
def test_start_begins_recording_and_is_idempotent():
    daemon, rec, events = make_daemon()
    assert daemon.handle("start") == "recording"
    assert rec.started == ["/tmp/cap.wav"]
    # second start must not start a second recording
    assert daemon.handle("start") == "recording"
    assert rec.started == ["/tmp/cap.wav"]


def test_stop_transcribes_and_injects():
    daemon, rec, events = make_daemon()
    daemon.handle("start")
    assert daemon.handle("stop") == "idle"
    assert rec.stopped == 1
    assert events["injected"] == ["hello world"]


def test_stop_when_idle_is_noop():
    daemon, rec, events = make_daemon()
    assert daemon.handle("stop") == "idle"
    assert rec.stopped == 0
    assert events["injected"] == []
```

Note: `FakeRecorder.start` appends unconditionally, but the daemon must guard on `is_recording`, so the idempotency assertion checks the daemon guards correctly.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_daemon.py -k "start or stop_transcribes or stop_when_idle" -v`
Expected: FAIL (handle returns `"unknown"` for `start`/`stop`).

- [ ] **Step 3: Implement `start`/`stop` in `handle`**

In `src/dictate/daemon.py`, edit `handle` to add the two verbs before the final `return "unknown"`:

```python
    def handle(self, command: str) -> str:
        command = command.strip()
        if command == "status":
            return "recording" if self.recorder.is_recording else "idle"
        if command == "quit":
            return "bye"
        if command == "toggle":
            if self.recorder.is_recording:
                return self._stop_and_transcribe()
            self.recorder.start(self.wav_path)
            self.notifier("🎙 Listening…", "")
            return "recording"
        if command == "start":
            if not self.recorder.is_recording:
                self.recorder.start(self.wav_path)
                self.notifier("🎙 Listening…", "")
            return "recording"
        if command == "stop":
            if self.recorder.is_recording:
                return self._stop_and_transcribe()
            return "idle"
        return "unknown"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_daemon.py -v`
Expected: PASS (all daemon tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add src/dictate/daemon.py tests/test_daemon.py
git commit -m "feat: add idempotent start/stop daemon commands for push-to-talk

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `ptt_key` config field

**Files:**
- Modify: `src/dictate/config.py` (the `Config` dataclass, ~lines 8-14)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.ptt_key: str` defaulting to `"rightctrl"`; `load_config` reads it from TOML and ignores unknown keys (existing behavior).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_ptt_key_defaults_and_loads(tmp_path):
    from dictate.config import Config, load_config
    assert Config().ptt_key == "rightctrl"
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('ptt_key = "rightalt"\n')
    assert load_config(cfg_file).ptt_key == "rightalt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::test_ptt_key_defaults_and_loads -v`
Expected: FAIL (`Config` has no attribute `ptt_key`).

- [ ] **Step 3: Add the field**

In `src/dictate/config.py`, add one line to the dataclass:

```python
@dataclass
class Config:
    model: str = "small.en"
    language: str = "en"
    mic_source: str | None = None
    inject_method: str | None = None
    beep: bool = False
    ptt_key: str = "rightctrl"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dictate/config.py tests/test_config.py
git commit -m "feat: add ptt_key config field (default rightctrl)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: PTT core logic — dependency, sender, event mapping, key lookup

**Files:**
- Modify: `pyproject.toml` (add `evdev` dependency)
- Modify: `src/dictate/client.py` (add `send_command`, refactor `send_toggle`)
- Create: `src/dictate/ptt.py`
- Test: `tests/test_client.py`, `tests/test_ptt.py` (new)

**Interfaces:**
- Consumes: `dictate.client.socket_connect` (existing).
- Produces:
  - `dictate.client.send_command(command: str, connect=socket_connect) -> str`
  - `dictate.ptt.event_to_command(code: int, value: int, ptt_code: int) -> str | None`
  - `dictate.ptt.key_name_to_code(name: str) -> int`

- [ ] **Step 1: Add the evdev dependency and install it**

In `pyproject.toml`, change the `dependencies` list to:

```toml
dependencies = [
    "faster-whisper>=1.0.0",
    "evdev>=1.6.0",
]
```

Then install into the venv:

Run: `.venv/bin/pip install -e .`
Expected: installs `evdev`; `.venv/bin/python -c "import evdev; print(evdev.ecodes.KEY_RIGHTCTRL)"` prints `97`.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_client.py`:

```python
def test_send_command_sends_and_reads_reply():
    from dictate.client import send_command

    class FakeConn:
        def __init__(self):
            self.sent = b""
        def sendall(self, data):
            self.sent += data
        def recv(self, n):
            return b"recording\n"
        def close(self):
            pass

    conn = FakeConn()
    reply = send_command("start", connect=lambda: conn)
    assert conn.sent == b"start"
    assert reply == "recording"
```

Create `tests/test_ptt.py`:

```python
import evdev

from dictate.ptt import event_to_command, key_name_to_code


def test_event_to_command_maps_down_up_repeat():
    code = evdev.ecodes.KEY_RIGHTCTRL
    assert event_to_command(code, 1, code) == "start"
    assert event_to_command(code, 0, code) == "stop"
    assert event_to_command(code, 2, code) is None  # auto-repeat ignored


def test_event_to_command_ignores_other_keys():
    ptt = evdev.ecodes.KEY_RIGHTCTRL
    other = evdev.ecodes.KEY_A
    assert event_to_command(other, 1, ptt) is None
    assert event_to_command(other, 0, ptt) is None


def test_key_name_to_code_known_and_unknown():
    assert key_name_to_code("rightctrl") == evdev.ecodes.KEY_RIGHTCTRL
    assert key_name_to_code("RightAlt") == evdev.ecodes.KEY_RIGHTALT
    # unknown falls back to right ctrl
    assert key_name_to_code("nonsense") == evdev.ecodes.KEY_RIGHTCTRL
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ptt.py tests/test_client.py::test_send_command_sends_and_reads_reply -v`
Expected: FAIL (`dictate.ptt` and `send_command` do not exist yet).

- [ ] **Step 4: Add `send_command` and refactor `send_toggle`**

In `src/dictate/client.py`, replace the `send_toggle` function with:

```python
def send_command(command, connect=socket_connect) -> str:
    conn = connect()
    try:
        conn.sendall(command.encode())
        return conn.recv(1024).decode().strip()
    finally:
        conn.close()


def send_toggle(connect=socket_connect) -> str:
    return send_command("toggle", connect=connect)
```

- [ ] **Step 5: Create `src/dictate/ptt.py` with the pure logic**

```python
import sys

import evdev


def event_to_command(code: int, value: int, ptt_code: int) -> str | None:
    """Map a key event to a daemon command. Only the PTT key matters:
    down (1) -> start, up (0) -> stop, auto-repeat (2) / anything else -> None.
    """
    if code != ptt_code:
        return None
    if value == 1:
        return "start"
    if value == 0:
        return "stop"
    return None


def key_name_to_code(name: str) -> int:
    """Resolve a config key name like 'rightctrl' to an evdev key code.
    Unknown names fall back to Right Ctrl with a warning.
    """
    attr = "KEY_" + name.strip().upper()
    code = getattr(evdev.ecodes, attr, None)
    if code is None:
        print(
            f"dictate-ptt: unknown ptt_key {name!r}, using rightctrl",
            file=sys.stderr,
        )
        return evdev.ecodes.KEY_RIGHTCTRL
    return code
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ptt.py tests/test_client.py -v`
Expected: PASS (new tests plus the existing client tests still green).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/dictate/client.py src/dictate/ptt.py tests/test_ptt.py tests/test_client.py
git commit -m "feat: add PTT core logic (evdev dep, send_command, event mapping, key lookup)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: PTT listener — dispatch, device selection, main, console script

**Files:**
- Modify: `src/dictate/ptt.py` (add `dispatch_events`, `select_keyboards`, `event_stream`, `main`)
- Modify: `pyproject.toml` (add `dictate-ptt` console script)
- Test: `tests/test_ptt.py`

**Interfaces:**
- Consumes: `event_to_command`, `key_name_to_code` (Task 3); `dictate.client.send_command`; `dictate.config.load_config`.
- Produces:
  - `dispatch_events(events, ptt_code, sender) -> None` — iterates events, calls `sender(cmd)` for mapped commands, swallowing `OSError` from the sender.
  - `select_keyboards(ptt_code, paths, opener) -> list` — devices whose `EV_KEY` capabilities include `ptt_code`.
  - `main() -> None` — console entry point `dictate-ptt`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ptt.py`:

```python
import collections

from dictate.ptt import dispatch_events, select_keyboards

FakeEvent = collections.namedtuple("FakeEvent", "type code value")


def test_dispatch_events_sends_mapped_commands():
    ptt = evdev.ecodes.KEY_RIGHTCTRL
    syn = evdev.ecodes.EV_SYN
    key = evdev.ecodes.EV_KEY
    events = [
        FakeEvent(key, ptt, 1),          # down -> start
        FakeEvent(key, ptt, 2),          # repeat -> nothing
        FakeEvent(syn, 0, 0),            # non-key -> nothing
        FakeEvent(key, evdev.ecodes.KEY_A, 1),  # other key -> nothing
        FakeEvent(key, ptt, 0),          # up -> stop
    ]
    sent = []
    dispatch_events(events, ptt, sent.append)
    assert sent == ["start", "stop"]


def test_dispatch_events_swallows_sender_oserror():
    ptt = evdev.ecodes.KEY_RIGHTCTRL
    events = [FakeEvent(evdev.ecodes.EV_KEY, ptt, 1)]

    def boom(cmd):
        raise OSError("daemon down")

    dispatch_events(events, ptt, boom)  # must not raise


class FakeDev:
    def __init__(self, keys):
        self._keys = keys
    def capabilities(self):
        return {evdev.ecodes.EV_KEY: self._keys}


def test_select_keyboards_picks_devices_with_ptt_key():
    ptt = evdev.ecodes.KEY_RIGHTCTRL
    devs = {
        "/dev/input/event0": FakeDev([ptt, evdev.ecodes.KEY_A]),  # keyboard
        "/dev/input/event1": FakeDev([evdev.ecodes.BTN_LEFT]),    # mouse
    }
    result = select_keyboards(ptt, list(devs), opener=lambda p: devs[p])
    assert len(result) == 1
    assert result[0] is devs["/dev/input/event0"]


def test_select_keyboards_skips_unopenable_devices():
    ptt = evdev.ecodes.KEY_RIGHTCTRL

    def opener(path):
        raise PermissionError("no access")

    assert select_keyboards(ptt, ["/dev/input/event0"], opener=opener) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ptt.py -k "dispatch or select_keyboards" -v`
Expected: FAIL (functions not defined).

- [ ] **Step 3: Implement dispatch + device selection + main**

Append to `src/dictate/ptt.py` (and add `import select` and the extra imports at the top):

```python
import select as _select

from .client import send_command
from .config import load_config


def dispatch_events(events, ptt_code, sender) -> None:
    """Feed an iterable of evdev events; send the mapped command for each PTT
    key edge. A sender OSError (daemon momentarily down) is logged, not raised.
    """
    for event in events:
        if event.type != evdev.ecodes.EV_KEY:
            continue
        command = event_to_command(event.code, event.value, ptt_code)
        if command is None:
            continue
        try:
            sender(command)
        except OSError as exc:
            print(f"dictate-ptt: {command} failed: {exc}", file=sys.stderr)


def select_keyboards(ptt_code, paths, opener=evdev.InputDevice):
    """Return opened devices whose EV_KEY capabilities include the PTT key.
    Devices that cannot be opened (permissions/hotplug races) are skipped.
    """
    keyboards = []
    for path in paths:
        try:
            device = opener(path)
        except (PermissionError, OSError):
            continue
        keys = device.capabilities().get(evdev.ecodes.EV_KEY, [])
        if ptt_code in keys:
            keyboards.append(device)
    return keyboards


def event_stream(devices):
    """Yield events from several devices at once via select()."""
    fd_to_device = {device.fd: device for device in devices}
    while True:
        readable, _, _ = _select.select(fd_to_device, [], [])
        for fd in readable:
            yield from fd_to_device[fd].read()


def main() -> None:
    config = load_config()
    ptt_code = key_name_to_code(config.ptt_key)
    devices = select_keyboards(ptt_code, evdev.list_devices())
    if not devices:
        print(
            "dictate-ptt: no keyboard exposing the PTT key found "
            "(is your user in the 'input' group?)",
            file=sys.stderr,
        )
        sys.exit(1)
    # Clear any stale recording state left by a previous run.
    try:
        send_command("stop")
    except OSError:
        pass
    names = ", ".join(d.name for d in devices)
    print(f"dictate-ptt: listening on {names}", file=sys.stderr)
    dispatch_events(event_stream(devices), ptt_code, send_command)
```

- [ ] **Step 4: Add the console script**

In `pyproject.toml`, under `[project.scripts]`, add the `dictate-ptt` line:

```toml
[project.scripts]
dictate-daemon = "dictate.daemon:main"
dictate-toggle = "dictate.client:main"
dictate-ptt = "dictate.ptt:main"
```

Then re-install so the entry point is generated:

Run: `.venv/bin/pip install -e .`
Expected: `.venv/bin/dictate-ptt` now exists.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest -q`
Expected: PASS — full suite (existing 28 + new PTT/daemon/config/client tests).

- [ ] **Step 6: Commit**

```bash
git add src/dictate/ptt.py pyproject.toml tests/test_ptt.py
git commit -m "feat: add PTT listener loop, device selection, and dictate-ptt entry point

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: systemd service + README

**Files:**
- Create: `systemd/dictate-ptt.service`
- Modify: `README.md`

**Interfaces:**
- Consumes: `dictate-ptt` console script (Task 4), existing `dictate.service`.
- Produces: an enable-able `--user` unit and user-facing setup docs.

- [ ] **Step 1: Create the service unit**

Create `systemd/dictate-ptt.service` (mirrors `dictate.service`, but ordered after and requiring the daemon; installed under `default.target` because it needs `/dev/input` and the daemon socket, not the Wayland session):

```ini
[Unit]
Description=Push-to-talk listener for Whisper dictation
After=dictate.service
Requires=dictate.service

[Service]
Type=simple
ExecStart=%h/repos/whisper-dictation/.venv/bin/dictate-ptt
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Document setup in the README**

Add a "Push-to-talk (hold to dictate)" section to `README.md` covering:

````markdown
## Push-to-talk (hold to dictate)

In addition to the Super+D tap-toggle, you can hold a key to talk and release to
transcribe. This needs a listener that reads keyboard events from `/dev/input`.

**One-time setup:**

```bash
# 1. Grant your user read access to input devices, then LOG OUT and back in.
sudo usermod -aG input "$USER"

# 2. Install the two user services and enable them.
mkdir -p ~/.config/systemd/user
cp systemd/dictate.service systemd/dictate-ptt.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dictate.service dictate-ptt.service
```

Hold **Right Ctrl** to record, release to transcribe into the focused field.

**Change the key:** set `ptt_key` in `~/.config/dictate/config.toml` (e.g.
`ptt_key = "rightalt"`) — any evdev key name minus the `KEY_` prefix, lower-case —
then `systemctl --user restart dictate-ptt.service`.

**Notes:**
- A keyboard plugged in *after* the listener starts is picked up only on
  `systemctl --user restart dictate-ptt.service`.
- The listener does not grab the key, so Right Ctrl still works as a normal
  modifier.
````

- [ ] **Step 3: Commit**

```bash
git add systemd/dictate-ptt.service README.md
git commit -m "docs: add dictate-ptt service unit and push-to-talk setup guide

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Live setup and end-to-end verification

**Files:** none (system configuration + manual verification).

This task has no automated tests — it installs the OS-level pieces and verifies the feature works end-to-end on the live machine. Do NOT mark the feature complete until Step 5 passes.

- [ ] **Step 1: Add user to the `input` group**

Run: `sudo usermod -aG input "$USER"`
Then confirm the group is listed for future logins: `id -nG "$USER" | tr ' ' '\n' | grep -x input` (may only show after re-login).

- [ ] **Step 2: Activate group membership**

The `input` group takes effect on next login. To verify without a full logout, run the listener in a shell that has the group: `newgrp input` then `.venv/bin/dictate-ptt` — it should print `dictate-ptt: listening on <keyboards>` and not exit. (For the systemd service to inherit the group, a real log out/in is required.)

- [ ] **Step 3: Install and enable the services**

```bash
mkdir -p ~/.config/systemd/user
cp systemd/dictate.service systemd/dictate-ptt.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dictate.service dictate-ptt.service
```

Run: `systemctl --user status dictate-ptt.service --no-pager`
Expected: `active (running)`, log line `listening on ...`. (If it logged the "no keyboard / input group" error, the re-login has not happened yet.)

- [ ] **Step 4: Confirm the daemon sees start/stop**

Run: `.venv/bin/python -c "from dictate.client import send_command; print(send_command('status'))"`
Expected: `idle`.

- [ ] **Step 5: End-to-end hold-to-talk test**

Focus a text field. Hold **Right Ctrl**, say a sentence, release. Confirm the transcript is typed into the field. Then verify Super+D tap-toggle still works independently.
Expected: both PTT and toggle produce transcribed text; `systemctl --user show -p NRestarts --value dictate-ptt.service` stays `0`.

- [ ] **Step 6: Final commit (if any tracked files changed)**

Only source/docs are tracked; system config lives outside the repo. If nothing tracked changed in this task, skip. Otherwise commit as appropriate.

---

## Notes for the executor

- Run all `pytest`/`pip` commands from the repo root with the venv at `.venv`.
- The full regression command is `.venv/bin/pytest -q`; it must stay green after every task.
- Tasks 1-5 are pure software and fully testable in this session. Task 6 requires `sudo` and a re-login and should be run interactively with the user.
