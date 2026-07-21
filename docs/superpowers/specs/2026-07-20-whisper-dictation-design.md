# Local Whisper Toggle-Dictation for COSMIC — Design

**Date:** 2026-07-20
**Status:** Approved (design), pending implementation plan

## Goal

A fully-local, offline speech-to-text dictation tool for a Pop!_OS / COSMIC
(Wayland) system. A keyboard shortcut toggles dictation on and off; on stop, the
spoken audio is transcribed with Whisper and the resulting text is typed into
whatever field currently has focus.

## Constraints & environment

- **Desktop:** COSMIC on Wayland (not GNOME/X11). Synthetic keystroke injection
  is restricted; must use a Wayland-compatible method.
- **Hardware:** Intel i7-13700H (20 threads), 16 GB RAM, Iris Xe integrated GPU
  (no usable CUDA). Transcription runs on CPU.
- **Audio:** PipeWire. Default mic is the built-in array; the Anker PowerConf
  C200 is also available and is the preferred dictation mic.
- **Privacy:** Fully local. No audio leaves the machine; no API keys; no per-use
  cost.

## Non-goals (YAGNI)

- No always-listening / wake-word mode.
- No cloud transcription backends.
- No GUI application; this is a headless daemon + hotkey.
- No multi-language UI (English-only model to start; model is swappable).

## Architecture

A resident **user daemon** keeps a Whisper model warm in RAM. A tiny **toggle
client**, bound to a COSMIC keyboard shortcut, flips the daemon between idle and
recording. They communicate over a Unix domain socket in `$XDG_RUNTIME_DIR`.

```
[COSMIC hotkey] → dictate-toggle (client) → unix socket → dictate-daemon
                                                             ├─ start: capture mic (PipeWire)
                                                             └─ stop:  transcribe → inject text
```

Keeping the model resident is the reason for the daemon/client split: model load
happens once at login, so a dictation cycle returns text ~1–2s after the user
stops speaking rather than paying model-load latency every time.

## Components

Each component has one purpose and a defined interface.

### 1. `dictate-daemon`
- **Does:** Owns all state. Loads `faster-whisper` (`small.en`, int8) once.
  Listens on the Unix socket for `toggle` commands. When toggled on, captures
  microphone audio into an in-memory buffer via PipeWire. When toggled off,
  runs transcription, post-processes text, and hands it to the injection layer.
- **Interface:** Unix socket accepting simple line commands (`toggle`, `status`,
  `quit`). Returns a short status string.
- **Depends on:** `faster-whisper`, a PipeWire capture source (`pw-record` or a
  Python audio lib), the injection layer, config.
- **Lifecycle:** Started at login by a `systemd --user` service with
  `Restart=on-failure`.

### 2. `dictate-toggle`
- **Does:** One-shot CLI. Connects to the daemon socket and sends `toggle`. If
  the daemon isn't running, starts it (or reports a clear error) and retries.
- **Interface:** No args for the common case; exit code reflects success.
- **Depends on:** the daemon socket path.

### 3. Text injection layer
- **Does:** Inserts a string into the focused field.
- **Strategy:** Try `wtype` (Wayland virtual-keyboard protocol, no root). On
  failure, fall back to `ydotool` (uinput). If both fail, copy the text to the
  clipboard via `wl-copy` and notify the user to paste manually — so text is
  never lost.
- **Interface:** `inject(text) -> method_used`.
- **Setup note:** During installation, detect which method actually works on
  this COSMIC build and record the winner in config to avoid retrying a broken
  method every cycle.

### 4. Feedback
- **Does:** Desktop notifications via `notify-send`: "🎙 Listening…" on start,
  "✍️ Inserted" (or the injection method) on success, "No speech detected" when
  the capture is empty/silent. Optional short beep on start/stop.

## Data flow

1. User presses the hotkey → COSMIC runs `dictate-toggle`.
2. Daemon (idle → recording): opens a PipeWire capture stream, buffers audio,
   shows "Listening".
3. User presses the hotkey again → `dictate-toggle` sends `toggle`.
4. Daemon (recording → idle): stops capture, runs the buffer through Whisper,
   trims/cleans the text.
5. Injection layer types the text into the focused field.
6. Notification confirms the result.

## Configuration

`~/.config/dictate/config.toml`, all keys optional with sensible defaults:

- `model` — default `small.en`. `medium.en` for higher accuracy at a few extra
  seconds per transcription.
- `language` — default `en`.
- `mic_source` — default = PipeWire default source; overridable to the Anker
  PowerConf C200.
- `inject_method` — auto-detected at install; `wtype` | `ydotool` | `clipboard`.
- `beep` — on/off.

## Error handling

- **Empty / near-silent capture:** no injection; "No speech detected"
  notification.
- **All injection methods fail:** text copied to clipboard + notification, so
  nothing is lost.
- **Daemon crash:** systemd `Restart=on-failure` brings it back; the client
  can also cold-start it.
- **Model missing on first run:** downloaded/cached by faster-whisper on first
  load; a one-time delay, surfaced via notification.

## Testing

- **Unit:** transcription function against a bundled sample WAV (asserts
  expected text); injection layer with a mocked backend to verify fallback
  order.
- **Manual acceptance:** hotkey → dictate a sentence into (a) a text editor,
  (b) a browser text field, (c) a terminal. Verify text appears and clipboard
  is untouched when `wtype`/`ydotool` is used.

## Install locations

- Scripts: `~/.local/bin/dictate-daemon`, `~/.local/bin/dictate-toggle`
- Config: `~/.config/dictate/config.toml`
- systemd unit: `~/.config/systemd/user/dictate.service`
- Project + this spec: `~/repos/whisper-dictation/` (git-versioned)
- COSMIC keybinding: bound to `dictate-toggle` via COSMIC Settings (documented
  in the repo README, since COSMIC shortcuts are configured through its own
  settings store).
