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
        try:
            self._proc.send_signal(signal.SIGINT)
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # pw-record ignored SIGINT; force it down so it can't orphan,
                # then let the caller transcribe whatever WAV was flushed.
                self._proc.kill()
                self._proc.wait()
        finally:
            self._proc = None
