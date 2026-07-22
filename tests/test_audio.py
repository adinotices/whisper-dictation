import queue
import wave

from dictate.audio import Recorder, build_stream_cmd


def test_stream_cmd_without_source():
    cmd = build_stream_cmd(None)
    assert cmd == [
        "pw-record", "--rate", "16000", "--channels", "1",
        "--format", "s16", "--raw", "-",
    ]


def test_stream_cmd_with_source():
    cmd = build_stream_cmd("Anker")
    assert "--target" in cmd and "Anker" in cmd
    assert cmd[-1] == "-"


class FakeStdout:
    """A controllable pipe: feed() queues a chunk, read() blocks for the next
    one. Feeding b"" simulates the process dying (EOF)."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()

    def feed(self, data: bytes) -> None:
        self._q.put(data)

    def read(self, _n=-1) -> bytes:
        return self._q.get()


class FakeStreamProc:
    def __init__(self):
        self.stdout = FakeStdout()
        self.terminated = False

    def terminate(self):
        self.terminated = True


def make_recorder():
    procs = []

    def spawn(cmd):
        p = FakeStreamProc()
        procs.append(p)
        return p

    return Recorder(spawn=spawn), procs


def read_wav(path):
    with wave.open(path, "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000
        return wav.readframes(wav.getnframes())


def test_recorder_spawns_stream_lazily_on_first_start(tmp_path):
    rec, procs = make_recorder()
    assert procs == []
    rec.start(str(tmp_path / "a.wav"))
    assert len(procs) == 1
    assert rec.is_recording is True


def test_recorder_reuses_warm_stream_across_cycles(tmp_path):
    rec, procs = make_recorder()
    proc = None
    for _ in range(3):
        rec.start(str(tmp_path / "a.wav"))
        proc = procs[-1]
        proc.stdout.feed(b"\x00\x01" * 4)
        rec.stop()
    assert len(procs) == 1  # never respawned
    assert proc.terminated is False


def test_stop_writes_only_bytes_captured_while_recording(tmp_path):
    rec, procs = make_recorder()
    out = str(tmp_path / "a.wav")

    # Route chunks directly (bypassing the background thread) so the test is
    # deterministic: is_recording is toggled by start()/stop(), and _route_chunk
    # is the same method the reader thread calls per chunk.
    rec._route_chunk(b"before-start")  # nothing is recording yet: dropped
    rec.start(out)
    rec._route_chunk(b"AB")
    rec._route_chunk(b"CD")
    rec.stop()
    rec._route_chunk(b"after-stop")  # recording stopped again: dropped

    assert read_wav(out) == b"ABCD"


def test_second_recording_does_not_see_previous_buffer(tmp_path):
    rec, procs = make_recorder()
    out1 = str(tmp_path / "a.wav")
    out2 = str(tmp_path / "b.wav")

    rec.start(out1)
    rec._route_chunk(b"first")
    rec.stop()

    rec.start(out2)
    rec._route_chunk(b"second")
    rec.stop()

    assert read_wav(out2) == b"second"


def test_dead_stream_is_respawned_on_next_start(tmp_path):
    rec, procs = make_recorder()
    rec.start(str(tmp_path / "a.wav"))
    first_proc = procs[-1]
    first_proc.stdout.feed(b"")  # EOF: process died
    rec._reader_thread.join(timeout=2)
    assert rec._proc is None
    rec.stop()

    rec.start(str(tmp_path / "b.wav"))
    assert len(procs) == 2  # respawned
    assert procs[-1] is not first_proc


def test_close_terminates_the_stream(tmp_path):
    rec, procs = make_recorder()
    rec.start(str(tmp_path / "a.wav"))
    proc = procs[-1]
    rec.close()
    assert proc.terminated is True


def test_close_before_any_start_does_not_raise():
    rec, _ = make_recorder()
    rec.close()  # no stream ever spawned; must be a no-op
