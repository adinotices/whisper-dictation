# dictate — local Whisper toggle-dictation for COSMIC/Wayland

A fully-local, offline speech-to-text dictation tool. Press a keyboard shortcut
to start listening, press it again to stop; your speech is transcribed with
Whisper (running on CPU) and typed into whatever field currently has focus. No
audio ever leaves your machine.

Built for **Pop!_OS / COSMIC on Wayland**. See the design spec in
[`docs/superpowers/specs/2026-07-20-whisper-dictation-design.md`](docs/superpowers/specs/2026-07-20-whisper-dictation-design.md).

## How it works

A resident user daemon (`dictate-daemon`) keeps a `faster-whisper` model warm in
RAM. A one-shot client (`dictate-toggle`), bound to a COSMIC keyboard shortcut,
flips the daemon between recording and idle over a Unix socket. On stop, the
captured audio is transcribed and the text is injected into the focused window.

```
[COSMIC hotkey] → dictate-toggle → unix socket → dictate-daemon
                                                    ├─ start: pw-record (PipeWire)
                                                    └─ stop:  faster-whisper → inject text
```

Text injection tries `wtype` (Wayland virtual-keyboard, no root) first, falls
back to `ydotool` (uinput), and finally to the clipboard (`wl-copy`) so text is
never lost.

## Install

### 1. Python package + model

```bash
cd ~/repos/whisper-dictation
python3 -m venv .venv
.venv/bin/pip install -e .
```

The `small.en` Whisper model (~460 MB) is downloaded automatically the first
time the daemon starts.

### 2. System dependencies

```bash
sudo apt update
sudo apt install -y wtype ydotool libnotify-bin
```

`pw-record` (PipeWire) and `wl-copy` (wl-clipboard) are already present on a
standard COSMIC install.

### 3. Run the daemon at login

```bash
mkdir -p ~/.config/systemd/user
cp ~/repos/whisper-dictation/systemd/dictate.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dictate.service
systemctl --user status dictate.service --no-pager
```

You should see a "dictate ready" desktop notification once the model has loaded.

### 4. Confirm the text-injection method

```bash
~/repos/whisper-dictation/.venv/bin/python -c \
  "from dictate.inject import detect_method, inject; print('detected:', detect_method()); print('used:', inject('dictate wtype test '))"
```

This types `dictate wtype test` at your cursor. If COSMIC's compositor supports
the virtual-keyboard protocol, `wtype` is used (no further setup). If it falls
back to `ydotool`, complete the ydotool step below.

#### ydotool setup (only if wtype does not work)

```bash
sudo tee /etc/udev/rules.d/60-dictate-uinput.rules >/dev/null <<'EOF'
KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
EOF
sudo usermod -aG input "$USER"
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then set `inject_method = "ydotool"` in your config (below), make sure the
`ydotoold` daemon is running, and log out/in once so the `input` group
membership takes effect.

### 5. Bind the COSMIC keyboard shortcut

COSMIC stores custom shortcuts in its own settings, so this step is manual:

**Settings → Keyboard → Keyboard Shortcuts → Custom Shortcuts → Add**, with the
command:

```
/home/admin/repos/whisper-dictation/.venv/bin/dictate-toggle
```

Assigned key: **Super+D** _(update this line if you choose a different key)._

## Usage

1. Focus any text field.
2. Press the shortcut → "🎙 Listening…" notification. Speak.
3. Press the shortcut again → within ~1–2 s the transcribed text is typed in.

If no speech is detected you get a "No speech detected" notification and nothing
is inserted. If every injection method fails, the transcript is shown in a
notification so you can copy it manually.

## Configuration

Optional, at `~/.config/dictate/config.toml`. Every key has a default:

```toml
model = "small.en"        # or "medium.en" for higher accuracy, a bit slower
language = "en"
mic_source = ""           # PipeWire node name; empty = default source
inject_method = ""        # "wtype" | "ydotool" | "clipboard"; empty = auto-detect
beep = false
```

To find your microphone's node name for `mic_source`, run `wpctl status` and use
the source's name (e.g. the Anker PowerConf C200).

After changing config, restart the daemon:

```bash
systemctl --user restart dictate.service
```

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```
