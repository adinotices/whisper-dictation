import signal
import subprocess

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


class TimeoutProc:
    def __init__(self):
        self.signals = []
        self.killed = False
        self.waits = []

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if timeout is not None:
            # the SIGINT grace-period wait times out
            raise subprocess.TimeoutExpired("pw-record", timeout)
        # the post-kill reap succeeds
        return 0


def test_recorder_stop_kills_and_recovers_on_wait_timeout():
    proc = TimeoutProc()
    rec = Recorder(spawn=lambda cmd: proc)
    rec.start("/tmp/a.wav")
    assert rec.is_recording is True
    rec.stop()  # escalates SIGINT -> SIGKILL; must not raise
    assert proc.signals == [signal.SIGINT]
    assert proc.killed is True
    assert rec.is_recording is False
