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
