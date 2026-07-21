import os
import socket
import sys
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
        try:
            text = self.transcriber(self.wav_path, self.model, self.config.language)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, don't crash
            print(f"dictate: transcription failed: {exc}", file=sys.stderr)
            self.notifier("Dictation: transcription failed", str(exc))
            return "idle"
        if not text:
            self.notifier("No speech detected", "")
            return "idle"
        try:
            method = self.injector(text, self.config.inject_method)
        except RuntimeError as exc:
            print(f"dictate: injection failed: {exc}", file=sys.stderr)
            self.notifier("Dictation: could not insert text", text)
            return "idle"
        self.notifier("✍️ Inserted", f"({method}) {text[:60]}")
        return "idle"


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
                data = read_request(conn)
                if data is None:
                    continue
                reply, should_break = process_request(daemon, data, notify)
                if reply is not None:
                    conn.sendall((reply + "\n").encode())
                if should_break:
                    break
    finally:
        server.close()
        if path.exists():
            path.unlink()
