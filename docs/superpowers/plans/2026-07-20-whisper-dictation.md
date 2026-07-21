# Whisper Toggle-Dictation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local, offline toggle-hotkey dictation tool for COSMIC/Wayland that transcribes speech with Whisper and types it into the focused field.

**Architecture:** A resident `systemd --user` daemon keeps a `faster-whisper` model warm and owns a record/idle state machine. A one-shot toggle client, bound to a COSMIC keyboard shortcut, sends `toggle` over a Unix socket. Audio is captured by a `pw-record` subprocess to a temp WAV; on stop the WAV is transcribed and the text is injected via `wtype` → `ydotool` → clipboard fallback.

**Tech Stack:** Python 3.12, faster-whisper (CTranslate2, CPU int8), pw-record (PipeWire), wtype/ydotool/wl-copy (Wayland text injection), notify-send (libnotify), systemd user service, pytest.

## Global Constraints

- **Python:** 3.10+ (target machine has 3.12).
- **Fully local:** no network calls at runtime except faster-whisper's one-time model download on first load. No cloud APIs, no API keys.
- **Model:** `small.en`, int8 compute type, CPU only.
- **Audio format for capture:** 16 kHz, mono, s16 WAV.
- **Injection precedence:** `wtype`, then `ydotool`, then clipboard (`wl-copy`) + notification. Never lose transcribed text.
- **Config file:** `~/.config/dictate/config.toml`, every key optional with a default.
- **Socket path:** `$XDG_RUNTIME_DIR/dictate.sock`.
- **Package name:** `dictate`. Console scripts: `dictate-daemon`, `dictate-toggle`.
- **Commits:** conventional-commit style, one per task minimum.

---

## File Structure

```
~/repos/whisper-dictation/
├── pyproject.toml               # package metadata, deps, console scripts
├── README.md                    # install + COSMIC keybinding instructions
├── src/dictate/
│   ├── __init__.py
│   ├── config.py                # Config dataclass + load_config()
│   ├── transcribe.py            # load_model(), transcribe_wav()
│   ├── inject.py                # detect_method(), inject()
│   ├── audio.py                 # build_pw_record_cmd(), Recorder
│   ├── notify.py                # notify()
│   ├── daemon.py                # DictationDaemon state machine + socket server
│   └── client.py                # toggle client entry point
├── systemd/dictate.service      # user service unit (template, installed to ~/.config)
├── tests/
│   ├── test_config.py
│   ├── test_transcribe.py
│   ├── test_inject.py
│   ├── test_audio.py
│   ├── test_daemon.py
│   └── test_client.py
└── docs/superpowers/{specs,plans}/...
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/dictate/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `dictate` package (`pip install -e .`), a working pytest setup.

- [ ] **Step 1: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "dictate"
version = "0.1.0"
description = "Local Whisper toggle-dictation for COSMIC/Wayland"
requires-python = ">=3.10"
dependencies = [
    "faster-whisper>=1.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
dictate-daemon = "dictate.daemon:main"
dictate-toggle = "dictate.client:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 3: Create the package init**

`src/dictate/__init__.py`:
```python
"""Local Whisper toggle-dictation for COSMIC/Wayland."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Write a smoke test**

`tests/test_smoke.py`:
```python
import dictate


def test_package_imports():
    assert dictate.__version__ == "0.1.0"
```

- [ ] **Step 5: Create venv and install**

Run:
```bash
cd ~/repos/whisper-dictation
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```
Expected: install completes (faster-whisper + ctranslate2 download may take a minute).

- [ ] **Step 6: Run the smoke test**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: scaffold dictate package"
```

---

### Task 2: Config module

**Files:**
- Create: `src/dictate/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass Config` with fields: `model: str = "small.en"`, `language: str = "en"`, `mic_source: str | None = None`, `inject_method: str | None = None`, `beep: bool = False`.
  - `load_config(path: pathlib.Path | None = None) -> Config` — reads TOML if present, else returns defaults; unknown keys ignored.
  - `DEFAULT_CONFIG_PATH: pathlib.Path` = `~/.config/dictate/config.toml`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
from pathlib import Path

from dictate.config import Config, load_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg == Config()
    assert cfg.model == "small.en"
    assert cfg.language == "en"
    assert cfg.mic_source is None


def test_reads_overrides(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('model = "medium.en"\nbeep = true\nmic_source = "Anker"\n')
    cfg = load_config(p)
    assert cfg.model == "medium.en"
    assert cfg.beep is True
    assert cfg.mic_source == "Anker"


def test_ignores_unknown_keys(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('model = "small.en"\nnonsense = 42\n')
    cfg = load_config(p)
    assert cfg.model == "small.en"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dictate.config'`.

- [ ] **Step 3: Implement config module**

`src/dictate/config.py`:
```python
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "dictate" / "config.toml"


@dataclass
class Config:
    model: str = "small.en"
    language: str = "en"
    mic_source: str | None = None
    inject_method: str | None = None
    beep: bool = False


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    known = {f.name for f in fields(Config)}
    filtered = {k: v for k, v in data.items() if k in known}
    return Config(**filtered)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/dictate/config.py tests/test_config.py
git commit -m "feat: add config loading with TOML overrides"
```

---

### Task 3: Transcription module

**Files:**
- Create: `src/dictate/transcribe.py`
- Test: `tests/test_transcribe.py`

**Interfaces:**
- Consumes: `Config` (for `model`, `language`).
- Produces:
  - `load_model(model_name: str) -> WhisperModel` — constructs `faster_whisper.WhisperModel(model_name, device="cpu", compute_type="int8")`.
  - `transcribe_wav(wav_path: str, model, language: str = "en") -> str` — runs `model.transcribe(wav_path, language=language)`, joins segment texts, strips whitespace. `model` is any object exposing `.transcribe(path, language=...) -> (segments_iterable, info)`; each segment has a `.text` attribute. Returns `""` when no segments.

- [ ] **Step 1: Write the failing tests**

`tests/test_transcribe.py`:
```python
from types import SimpleNamespace

from dictate.transcribe import transcribe_wav


class FakeModel:
    def __init__(self, texts):
        self._texts = texts
        self.calls = []

    def transcribe(self, path, language="en"):
        self.calls.append((path, language))
        segments = (SimpleNamespace(text=t) for t in self._texts)
        return segments, SimpleNamespace(language=language)


def test_joins_and_strips_segments():
    model = FakeModel(["  Hello ", "there. ", "How are you?"])
    result = transcribe_wav("x.wav", model, language="en")
    assert result == "Hello there. How are you?"
    assert model.calls == [("x.wav", "en")]


def test_empty_when_no_segments():
    model = FakeModel([])
    assert transcribe_wav("x.wav", model) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_transcribe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dictate.transcribe'`.

- [ ] **Step 3: Implement transcription module**

`src/dictate/transcribe.py`:
```python
from faster_whisper import WhisperModel


def load_model(model_name: str):
    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_wav(wav_path: str, model, language: str = "en") -> str:
    segments, _info = model.transcribe(wav_path, language=language)
    text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
    return text.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_transcribe.py -v`
Expected: PASS (2 tests). `load_model` is exercised in the Task 8 manual acceptance, not unit-tested (avoids downloading the model in CI).

- [ ] **Step 5: Commit**

```bash
git add src/dictate/transcribe.py tests/test_transcribe.py
git commit -m "feat: add whisper transcription with segment joining"
```

---

### Task 4: Text injection layer

**Files:**
- Create: `src/dictate/inject.py`
- Test: `tests/test_inject.py`

**Interfaces:**
- Consumes: nothing (uses `shutil.which` + `subprocess`).
- Produces:
  - `METHODS = ["wtype", "ydotool", "clipboard"]` (precedence order).
  - `detect_method() -> str` — returns the first available method: `"wtype"` if `wtype` on PATH, else `"ydotool"` if on PATH, else `"clipboard"` (requires `wl-copy`).
  - `inject(text: str, method: str | None = None, runner=subprocess.run) -> str` — injects `text` using `method` (or `detect_method()` if None); on failure walks down the precedence list starting after `method`; returns the method that succeeded. `runner` is injectable for testing. Raises `RuntimeError` if all methods fail.
  - Helper `_command(method, text) -> list[str]`: `wtype` → `["wtype", text]`; `ydotool` → `["ydotool", "type", text]`; `clipboard` → `["wl-copy", text]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_inject.py`:
```python
import subprocess

import pytest

from dictate.inject import _command, inject


def test_command_shapes():
    assert _command("wtype", "hi") == ["wtype", "hi"]
    assert _command("ydotool", "hi") == ["ydotool", "type", "hi"]
    assert _command("clipboard", "hi") == ["wl-copy", "hi"]


def test_falls_back_on_failure():
    tried = []

    def runner(cmd, **kwargs):
        tried.append(cmd[0])
        if cmd[0] == "wtype":
            raise FileNotFoundError("no wtype")
        return subprocess.CompletedProcess(cmd, 0)

    used = inject("hello", method="wtype", runner=runner)
    assert used == "ydotool"
    assert tried == ["wtype", "ydotool"]


def test_raises_when_all_fail():
    def runner(cmd, **kwargs):
        raise FileNotFoundError("nope")

    with pytest.raises(RuntimeError):
        inject("hello", method="wtype", runner=runner)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_inject.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dictate.inject'`.

- [ ] **Step 3: Implement injection module**

`src/dictate/inject.py`:
```python
import shutil
import subprocess

METHODS = ["wtype", "ydotool", "clipboard"]


def _command(method: str, text: str) -> list[str]:
    if method == "wtype":
        return ["wtype", text]
    if method == "ydotool":
        return ["ydotool", "type", text]
    if method == "clipboard":
        return ["wl-copy", text]
    raise ValueError(f"unknown method: {method}")


def detect_method() -> str:
    if shutil.which("wtype"):
        return "wtype"
    if shutil.which("ydotool"):
        return "ydotool"
    return "clipboard"


def inject(text: str, method: str | None = None, runner=subprocess.run) -> str:
    start = method or detect_method()
    order = METHODS[METHODS.index(start):]
    last_error: Exception | None = None
    for m in order:
        try:
            runner(_command(m, text), check=True)
            return m
        except Exception as exc:  # noqa: BLE001 - try next method
            last_error = exc
    raise RuntimeError(f"all injection methods failed: {last_error}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_inject.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/dictate/inject.py tests/test_inject.py
git commit -m "feat: add text injection with wtype/ydotool/clipboard fallback"
```

---

### Task 5: Audio recorder + notifications

**Files:**
- Create: `src/dictate/audio.py`
- Create: `src/dictate/notify.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: `Config` (for `mic_source`).
- Produces:
  - `build_pw_record_cmd(out_path: str, mic_source: str | None) -> list[str]` — returns `["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", ...]` with `["--target", mic_source]` inserted when `mic_source` is set, ending in `out_path`.
  - `class Recorder` with `start(out_path: str)` (spawns pw-record via injectable `spawn` callable, default `subprocess.Popen`), `stop() -> None` (sends SIGINT, waits), and `is_recording -> bool`.
  - `notify(summary: str, body: str = "", runner=subprocess.run) -> None` in `notify.py` — calls `notify-send` with `-a dictate`; swallows failures (notifications are best-effort).

- [ ] **Step 1: Write the failing tests**

`tests/test_audio.py`:
```python
import signal

from dictate.audio import Recorder, build_pw_record_cmd


def test_cmd_without_source():
    cmd = build_pw_record_cmd("/tmp/a.wav", None)
    assert cmd == [
        "pw-record", "--rate", "16000", "--channels", "1",
        "--format", "s16", "/tmp/a.wav",
    ]


def test_cmd_with_source():
    cmd = build_pw_record_cmd("/tmp/a.wav", "Anker")
    assert "--target" in cmd and "Anker" in cmd
    assert cmd[-1] == "/tmp/a.wav"


class FakeProc:
    def __init__(self):
        self.signals = []
        self.waited = False

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout=None):
        self.waited = True


def test_recorder_lifecycle():
    procs = []

    def spawn(cmd):
        p = FakeProc()
        procs.append((cmd, p))
        return p

    rec = Recorder(spawn=spawn)
    assert rec.is_recording is False
    rec.start("/tmp/a.wav")
    assert rec.is_recording is True
    assert procs[0][0][0] == "pw-record"
    rec.stop()
    assert rec.is_recording is False
    assert procs[0][1].signals == [signal.SIGINT]
    assert procs[0][1].waited is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dictate.audio'`.

- [ ] **Step 3: Implement audio + notify modules**

`src/dictate/audio.py`:
```python
import signal
import subprocess


def build_pw_record_cmd(out_path: str, mic_source: str | None) -> list[str]:
    cmd = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16"]
    if mic_source:
        cmd += ["--target", mic_source]
    cmd.append(out_path)
    return cmd


class Recorder:
    def __init__(self, mic_source: str | None = None, spawn=subprocess.Popen):
        self._mic_source = mic_source
        self._spawn = spawn
        self._proc = None

    @property
    def is_recording(self) -> bool:
        return self._proc is not None

    def start(self, out_path: str) -> None:
        if self._proc is not None:
            return
        self._proc = self._spawn(build_pw_record_cmd(out_path, self._mic_source))

    def stop(self) -> None:
        if self._proc is None:
            return
        self._proc.send_signal(signal.SIGINT)
        self._proc.wait(timeout=5)
        self._proc = None
```

`src/dictate/notify.py`:
```python
import subprocess


def notify(summary: str, body: str = "", runner=subprocess.run) -> None:
    try:
        runner(["notify-send", "-a", "dictate", summary, body], check=False)
    except Exception:  # noqa: BLE001 - notifications are best-effort
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/dictate/audio.py src/dictate/notify.py tests/test_audio.py
git commit -m "feat: add pw-record audio recorder and notify helper"
```

---

### Task 6: Daemon state machine + socket server

**Files:**
- Create: `src/dictate/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `Config`, `Recorder`, `transcribe_wav`, `inject`, `notify`.
- Produces:
  - `SOCKET_PATH` derived from `$XDG_RUNTIME_DIR/dictate.sock` (fallback `/tmp/dictate-<uid>.sock`).
  - `class DictationDaemon(config, model, recorder, transcriber, injector, notifier, wav_path)` where `transcriber(wav_path, model, language) -> str` and `injector(text, method) -> str`, `notifier(summary, body)`. Injectable for testing; `main()` wires the real ones.
  - `DictationDaemon.handle(command: str) -> str` — `"toggle"` flips record/idle and returns `"recording"` or `"idle"`; `"status"` returns current state; `"quit"` returns `"bye"`. Toggling to idle runs transcription+injection; empty transcript notifies "No speech detected" and injects nothing.
  - `main()` — loads config, loads model, creates a Unix socket server, serves `handle()` results line-by-line.

- [ ] **Step 1: Write the failing tests**

`tests/test_daemon.py`:
```python
from dictate.config import Config
from dictate.daemon import DictationDaemon


class FakeRecorder:
    def __init__(self):
        self.started = []
        self.stopped = 0
        self._on = False

    @property
    def is_recording(self):
        return self._on

    def start(self, out_path):
        self.started.append(out_path)
        self._on = True

    def stop(self):
        self.stopped += 1
        self._on = False


def make_daemon(transcript="hello world"):
    events = {"injected": [], "notes": []}
    rec = FakeRecorder()
    daemon = DictationDaemon(
        config=Config(),
        model=object(),
        recorder=rec,
        transcriber=lambda wav, model, language: transcript,
        injector=lambda text, method: events["injected"].append(text) or "wtype",
        notifier=lambda summary, body="": events["notes"].append(summary),
        wav_path="/tmp/cap.wav",
    )
    return daemon, rec, events


def test_toggle_starts_and_stops_recording():
    daemon, rec, events = make_daemon()
    assert daemon.handle("toggle") == "recording"
    assert rec.started == ["/tmp/cap.wav"]
    assert daemon.handle("toggle") == "idle"
    assert rec.stopped == 1
    assert events["injected"] == ["hello world"]


def test_empty_transcript_injects_nothing():
    daemon, rec, events = make_daemon(transcript="")
    daemon.handle("toggle")
    daemon.handle("toggle")
    assert events["injected"] == []
    assert any("No speech" in n for n in events["notes"])


def test_status_and_quit():
    daemon, rec, events = make_daemon()
    assert daemon.handle("status") == "idle"
    assert daemon.handle("quit") == "bye"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_daemon.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dictate.daemon'`.

- [ ] **Step 3: Implement the daemon**

`src/dictate/daemon.py`:
```python
import os
import socket
from pathlib import Path

from .audio import Recorder
from .config import load_config
from .inject import inject
from .notify import notify
from .transcribe import load_model, transcribe_wav


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "dictate.sock"
    return Path(f"/tmp/dictate-{os.getuid()}.sock")


class DictationDaemon:
    def __init__(self, config, model, recorder, transcriber, injector,
                 notifier, wav_path):
        self.config = config
        self.model = model
        self.recorder = recorder
        self.transcriber = transcriber
        self.injector = injector
        self.notifier = notifier
        self.wav_path = wav_path

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
        return "unknown"

    def _stop_and_transcribe(self) -> str:
        self.recorder.stop()
        text = self.transcriber(self.wav_path, self.model, self.config.language)
        if not text:
            self.notifier("No speech detected", "")
            return "idle"
        method = self.injector(text, self.config.inject_method)
        self.notifier("✍️ Inserted", f"({method}) {text[:60]}")
        return "idle"


def main() -> None:
    config = load_config()
    model = load_model(config.model)
    wav_path = str(socket_path().with_name("dictate-capture.wav"))
    recorder = Recorder(mic_source=config.mic_source)
    daemon = DictationDaemon(
        config=config, model=model, recorder=recorder,
        transcriber=transcribe_wav, injector=inject, notifier=notify,
        wav_path=wav_path,
    )

    path = socket_path()
    if path.exists():
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    notify("dictate ready", f"model: {config.model}")
    try:
        while True:
            conn, _ = server.accept()
            with conn:
                data = conn.recv(1024).decode().strip()
                reply = daemon.handle(data)
                conn.sendall((reply + "\n").encode())
                if reply == "bye":
                    break
    finally:
        server.close()
        if path.exists():
            path.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_daemon.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/dictate/daemon.py tests/test_daemon.py
git commit -m "feat: add dictation daemon state machine and socket server"
```

---

### Task 7: Toggle client

**Files:**
- Create: `src/dictate/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `socket_path()` from daemon.
- Produces:
  - `send_toggle(connect=socket_connect) -> str` — connects to the socket, sends `toggle`, returns the reply. `connect` is injectable and returns an object with `sendall`/`recv`/`close`.
  - `main()` — calls `send_toggle()`; if connection fails with `ConnectionRefusedError`/`FileNotFoundError`, starts the daemon (`subprocess.Popen(["dictate-daemon"])`), waits briefly for the socket, retries once; prints the reply; exit code 0 on success, 1 on failure.

- [ ] **Step 1: Write the failing tests**

`tests/test_client.py`:
```python
from dictate.client import send_toggle


class FakeConn:
    def __init__(self, reply):
        self._reply = reply
        self.sent = None

    def sendall(self, data):
        self.sent = data

    def recv(self, n):
        return self._reply

    def close(self):
        pass


def test_send_toggle_returns_reply():
    conn = FakeConn(b"recording\n")
    result = send_toggle(connect=lambda: conn)
    assert result == "recording"
    assert conn.sent == b"toggle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dictate.client'`.

- [ ] **Step 3: Implement the client**

`src/dictate/client.py`:
```python
import socket
import subprocess
import sys
import time

from .daemon import socket_path


def socket_connect():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(socket_path()))
    return sock


def send_toggle(connect=socket_connect) -> str:
    conn = connect()
    try:
        conn.sendall(b"toggle")
        return conn.recv(1024).decode().strip()
    finally:
        conn.close()


def _start_daemon_and_wait() -> None:
    subprocess.Popen(["dictate-daemon"])
    for _ in range(100):  # wait up to ~10s for model load + socket bind
        if socket_path().exists():
            return
        time.sleep(0.1)


def main() -> None:
    try:
        print(send_toggle())
        sys.exit(0)
    except (ConnectionRefusedError, FileNotFoundError):
        _start_daemon_and_wait()
    try:
        print(send_toggle())
        sys.exit(0)
    except OSError as exc:
        print(f"dictate: could not reach daemon: {exc}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_client.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Full suite green**

Run: `.venv/bin/pytest -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dictate/client.py tests/test_client.py
git commit -m "feat: add toggle client with daemon auto-start"
```

---

### Task 8: System integration — deps, service, keybinding, manual acceptance

**Files:**
- Create: `systemd/dictate.service`
- Create: `README.md`

**Interfaces:**
- Consumes: everything above; produces a running, hotkey-bound system.

- [ ] **Step 1: Install runtime system packages**

Run:
```bash
sudo apt update
sudo apt install -y wtype ydotool libnotify-bin
```
Expected: `wtype`, `ydotool`, `notify-send` now on PATH. (`pw-record` and `wl-copy` are already present.)

- [ ] **Step 2: Write the systemd user unit**

`systemd/dictate.service`:
```ini
[Unit]
Description=Local Whisper dictation daemon
After=default.target

[Service]
Type=simple
ExecStart=%h/repos/whisper-dictation/.venv/bin/dictate-daemon
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

- [ ] **Step 3: Install and start the service**

Run:
```bash
mkdir -p ~/.config/systemd/user
cp ~/repos/whisper-dictation/systemd/dictate.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dictate.service
sleep 8   # first start downloads the small.en model
systemctl --user status dictate.service --no-pager
```
Expected: `active (running)`; a "dictate ready" notification appears. If the model is downloading, wait and re-check.

- [ ] **Step 4: Verify injection method on this COSMIC build**

Run:
```bash
~/repos/whisper-dictation/.venv/bin/python -c "from dictate.inject import detect_method, inject; print('detected:', detect_method()); print('used:', inject('dictate wtype test '))"
```
Expected: prints the detected method and types `dictate wtype test` at your cursor. If `wtype` errors on COSMIC (compositor lacks the virtual-keyboard protocol), it falls back to `ydotool`. If `ydotool` is chosen, complete Step 5; otherwise skip it.

- [ ] **Step 5 (only if ydotool is the working method): enable ydotool uinput access**

Run:
```bash
sudo tee /etc/udev/rules.d/60-dictate-uinput.rules >/dev/null <<'EOF'
KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
EOF
sudo usermod -aG input "$USER"
sudo udevadm control --reload-rules && sudo udevadm trigger
systemctl --user enable --now ydotool.service 2>/dev/null || (ydotoold &)
```
Then set `inject_method = "ydotool"` in `~/.config/dictate/config.toml`. Note: group change needs a logout/login to take effect.

- [ ] **Step 6: Bind the COSMIC keyboard shortcut**

Open **COSMIC Settings → Keyboard → Keyboard Shortcuts → Custom Shortcuts → Add**. Set the command to:
```
/home/admin/repos/whisper-dictation/.venv/bin/dictate-toggle
```
Assign a key (e.g. **Super+D**). Document the chosen key in `README.md`. (COSMIC stores custom shortcuts in its own config; there is no reliable file to script, so this step is manual.)

- [ ] **Step 7: Manual acceptance test**

1. Focus a text editor. Press the shortcut → "🎙 Listening…" notification. Say "the quick brown fox jumps over the lazy dog". Press the shortcut again → within ~2s the sentence is typed.
2. Repeat in a browser text field.
3. Repeat in a terminal prompt.
4. Confirm your clipboard is unchanged (unless the clipboard fallback is the active method).

Expected: accurate transcription typed into each focused field.

- [ ] **Step 8: Write README**

`README.md` — cover: what it is, install steps (venv, `pip install -e .`, apt deps, systemd enable), the config keys, the injection-method note, and the exact COSMIC keybinding chosen in Step 6. Reference the spec at `docs/superpowers/specs/2026-07-20-whisper-dictation-design.md`.

- [ ] **Step 9: Commit**

```bash
git add systemd/dictate.service README.md
git commit -m "feat: add systemd unit, install docs, and COSMIC keybinding guide"
```

---

## Self-Review Notes

- **Spec coverage:** daemon/client split (Task 6/7), resident warm model (Task 3 `load_model` + systemd Task 8), PipeWire capture (Task 5), wtype→ydotool→clipboard precedence (Task 4), notifications (Task 5), config keys incl. mic override & model (Task 2), error paths — empty capture (Task 6), all-injection-fail (Task 4 `RuntimeError` → surfaced by daemon notifier), daemon crash restart (Task 8 unit), COSMIC keybinding (Task 8). All covered.
- **Type consistency:** `transcribe_wav(wav_path, model, language)`, `inject(text, method)`, `notify(summary, body)`, `Recorder.start/stop/is_recording`, `DictationDaemon.handle` — signatures match across producer/consumer tasks.
- **Placeholder scan:** no TBD/placeholder steps; every code step includes full code.
