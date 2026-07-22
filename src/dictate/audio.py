import subprocess
import threading
import wave


def build_stream_cmd(mic_source: str | None) -> list[str]:
    cmd = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", "--raw"]
    if mic_source:
        cmd += ["--target", mic_source]
    cmd.append("-")
    return cmd


def _write_wav(out_path: str, data: bytes) -> None:
    with wave.open(out_path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(data)


def _default_spawn(cmd: list[str]):
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


class Recorder:
    """Keeps one `pw-record` stream open for the daemon's lifetime instead of
    spawning a fresh process per recording. Spawning costs ~50-100ms of PipeWire
    stream-negotiation latency, during which audio is silently dropped -- fatal
    for push-to-talk, where speech starts the instant the key goes down. By
    staying warm across start()/stop() cycles, only the very first press after a
    (re)start can be clipped; every press after that has zero startup latency.
    """

    def __init__(self, mic_source: str | None = None, spawn=_default_spawn,
                 chunk_size: int = 4096):
        self._mic_source = mic_source
        self._spawn = spawn
        self._chunk_size = chunk_size
        self._proc = None
        self._reader_thread = None
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._recording = False
        self._out_path = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self, out_path: str) -> None:
        if self._recording:
            return
        if self._proc is None:
            self._spawn_stream()
        self._out_path = out_path
        with self._lock:
            self._buffer = bytearray()
            self._recording = True

    def stop(self) -> None:
        if not self._recording:
            return
        with self._lock:
            self._recording = False
            data = bytes(self._buffer)
            self._buffer = bytearray()
        _write_wav(self._out_path, data)

    def close(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None

    def _spawn_stream(self) -> None:
        proc = self._spawn(build_stream_cmd(self._mic_source))
        self._proc = proc
        self._reader_thread = threading.Thread(
            target=self._read_loop, args=(proc,), daemon=True,
        )
        self._reader_thread.start()

    def _read_loop(self, proc) -> None:
        stdout = proc.stdout
        while True:
            chunk = stdout.read(self._chunk_size)
            if not chunk:
                if self._proc is proc:
                    self._proc = None
                return
            self._route_chunk(chunk)

    def _route_chunk(self, chunk: bytes) -> None:
        with self._lock:
            if self._recording:
                self._buffer.extend(chunk)
