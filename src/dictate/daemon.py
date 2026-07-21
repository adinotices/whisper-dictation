import os
import signal
import socket
import sys
import time
from pathlib import Path

from .audio import Recorder
from .commands import parse_utterance
from .config import load_config
from .inject import inject, inject_key
from .notify import notify
from .textproc import format_segment
from .transcribe import load_model, transcribe_wav


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "dictate.sock"
    return Path(f"/tmp/dictate-{os.getuid()}.sock")


class DictationDaemon:
    def __init__(self, config, model, recorder, transcriber, injector,
                 notifier, wav_path, key_injector=inject_key,
                 clock=time.monotonic):
        self.config = config
        self.model = model
        self.recorder = recorder
        self.transcriber = transcriber
        self.injector = injector
        self.key_injector = key_injector
        self.notifier = notifier
        self.wav_path = wav_path
        self._clock = clock
        self._last_text = ""
        self._last_time = 0.0

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

    def _stop_and_transcribe(self) -> str:
        self.recorder.stop()
        try:
            text = self.transcriber(self.wav_path, self.model, self.config.language)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, don't crash
            print(f"dictate: transcription failed: {exc}", file=sys.stderr)
            self.notifier("Dictation: transcription failed", str(exc))
            return "idle"
        if not text:
            self.notifier("No speech detected", "")
            return "idle"

        actions = self._plan_actions(text)
        last_kind = None
        last_text = ""
        first_text_done = False
        try:
            for kind, value in actions:
                if kind == "text":
                    to_inject = value
                    if not first_text_done:
                        to_inject = self._apply_spacing(value)
                        first_text_done = True
                    self.injector(to_inject, self.config.inject_method)
                    last_text = to_inject
                else:  # key
                    self.key_injector(value, self.config.inject_method)
                last_kind = kind
        except RuntimeError as exc:
            print(f"dictate: injection failed: {exc}", file=sys.stderr)
            self.notifier("Dictation: could not insert text", text)
            return "idle"

        # Remember what we typed (and when) so the next dictation can
        # space/capitalize off it. A trailing key (Enter/Shift+Enter) means the
        # next dictation lands on a new line or a fresh field, so reset the state.
        self._last_text = last_text if last_kind == "text" else ""
        self._last_time = self._clock()
        self.notifier("✍️ Inserted", text[:60])
        return "idle"

    def _plan_actions(self, text):
        if not self.config.voice_commands:
            return [("text", text)]
        return parse_utterance(text)

    def _apply_spacing(self, text: str) -> str:
        if not self.config.smart_spacing:
            return text
        prev = self._last_text
        if prev and (self._clock() - self._last_time) > \
                self.config.smart_spacing_reset_seconds:
            prev = ""  # idle too long: treat this dictation as a fresh start
        return format_segment(text, prev)


def read_request(conn, timeout=5):
    """Read one command from conn. Returns the stripped string, or None if the
    client sends nothing within `timeout` seconds, so a single silent client
    can't hang the single-threaded serve loop.
    """
    conn.settimeout(timeout)
    try:
        return conn.recv(1024).decode().strip()
    except (socket.timeout, TimeoutError):
        return None


def process_request(daemon, data, notifier):
    """Handle one request. Returns (reply, should_break).

    Contains errors from daemon.handle: on failure, notify and return
    (None, False) so the serve loop keeps running and sends no reply.
    """
    try:
        reply = daemon.handle(data)
    except Exception as exc:  # noqa: BLE001 - keep serving on any handler error
        print(f"dictate: request handling failed: {exc}", file=sys.stderr)
        notifier("dictate error", str(exc))
        return None, False
    return reply, reply == "bye"


def send_reply(conn, reply) -> None:
    """Send a reply line, tolerating a client that already disconnected (a
    vanished client must never crash the serve loop).
    """
    try:
        conn.sendall((reply + "\n").encode())
    except OSError as exc:
        print(f"dictate: could not send reply: {exc}", file=sys.stderr)


def create_server(path) -> socket.socket:
    """Bind and listen on the Unix socket at `path`, clearing any stale file
    left by a previous daemon. Returns the listening socket.
    """
    if path.exists():
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    return server


def main() -> None:
    # Turn SIGTERM (what systemd sends on stop/restart) into a normal exit so
    # the finally block runs and the socket file is unlinked — no stale socket.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    config = load_config()
    path = socket_path()
    # Bind before loading the model so the socket's presence reliably means
    # "daemon is up"; connections during model load queue in the listen backlog
    # instead of being refused.
    server = create_server(path)
    try:
        model = load_model(config.model)
        wav_path = str(path.with_name("dictate-capture.wav"))
        recorder = Recorder(mic_source=config.mic_source)
        daemon = DictationDaemon(
            config=config, model=model, recorder=recorder,
            transcriber=transcribe_wav, injector=inject, notifier=notify,
            wav_path=wav_path,
        )
        notify("dictate ready", f"model: {config.model}")
        while True:
            conn, _ = server.accept()
            with conn:
                data = read_request(conn)
                if data is None:
                    continue
                reply, should_break = process_request(daemon, data, notify)
                if reply is not None:
                    send_reply(conn, reply)
                if should_break:
                    break
    finally:
        server.close()
        if path.exists():
            path.unlink()
