import socket

from dictate.config import Config
from dictate.daemon import (
    DictationDaemon,
    create_server,
    process_request,
    read_request,
    send_reply,
)


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


def test_injection_failure_notifies_with_transcript_and_does_not_raise():
    events = {"injected": [], "notes": []}
    rec = FakeRecorder()

    def failing_injector(text, method):
        raise RuntimeError("all injection methods failed")

    daemon = DictationDaemon(
        config=Config(),
        model=object(),
        recorder=rec,
        transcriber=lambda wav, model, language: "hello world",
        injector=failing_injector,
        notifier=lambda summary, body="": events["notes"].append((summary, body)),
        wav_path="/tmp/cap.wav",
    )
    assert daemon.handle("toggle") == "recording"
    result = daemon.handle("toggle")
    assert result == "idle"
    assert rec.stopped == 1
    assert events["injected"] == []
    assert any(
        "could not insert" in summary and "hello world" in body
        for summary, body in events["notes"]
    )


def test_transcription_failure_notifies_and_does_not_raise():
    events = {"injected": [], "notes": []}
    rec = FakeRecorder()

    def failing_transcriber(wav, model, language):
        raise RuntimeError("bad wav")

    daemon = DictationDaemon(
        config=Config(),
        model=object(),
        recorder=rec,
        transcriber=failing_transcriber,
        injector=lambda text, method: events["injected"].append(text) or "wtype",
        notifier=lambda summary, body="": events["notes"].append((summary, body)),
        wav_path="/tmp/cap.wav",
    )
    assert daemon.handle("toggle") == "recording"
    result = daemon.handle("toggle")
    assert result == "idle"
    assert rec.stopped == 1
    assert events["injected"] == []
    assert any(
        "transcription failed" in summary.lower()
        for summary, body in events["notes"]
    )


def test_send_reply_writes_line():
    class RecordingConn:
        def __init__(self):
            self.sent = b""

        def sendall(self, data):
            self.sent += data

    conn = RecordingConn()
    send_reply(conn, "idle")
    assert conn.sent == b"idle\n"


def test_send_reply_tolerates_disconnected_client():
    class BrokenConn:
        def sendall(self, data):
            raise BrokenPipeError("client gone")

    send_reply(BrokenConn(), "idle")  # must not raise


def test_create_server_replaces_stale_socket_and_accepts(tmp_path):
    p = tmp_path / "dictate.sock"
    p.write_text("stale")  # leftover file from a daemon killed without cleanup
    server = create_server(p)
    try:
        assert p.is_socket()
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2)
        client.connect(str(p))  # succeeds: already bound + listening
        client.close()
    finally:
        server.close()
        if p.exists():
            p.unlink()


class FakeConn:
    def __init__(self, data=None, raise_timeout=False):
        self._data = data
        self._raise_timeout = raise_timeout
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv(self, bufsize):
        if self._raise_timeout:
            raise socket.timeout("timed out")
        return self._data


def test_read_request_returns_stripped_data():
    conn = FakeConn(data=b"  toggle\n")
    assert read_request(conn) == "toggle"
    assert conn.timeout is not None


def test_read_request_returns_none_on_timeout():
    conn = FakeConn(raise_timeout=True)
    assert read_request(conn) is None


class _StubDaemon:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def handle(self, data):
        if self._error is not None:
            raise self._error
        return self._result


def test_process_request_contains_handler_error():
    notes = []
    daemon = _StubDaemon(error=RuntimeError("boom"))

    reply, should_break = process_request(daemon, "toggle", lambda s, b="": notes.append((s, b)))

    assert (reply, should_break) == (None, False)
    assert any("boom" in summary or "boom" in body for summary, body in notes)


def test_process_request_returns_bye_and_breaks():
    daemon = _StubDaemon(result="bye")

    reply, should_break = process_request(daemon, "quit", lambda s, b="": None)

    assert (reply, should_break) == ("bye", True)


def test_process_request_returns_recording_and_does_not_break():
    daemon = _StubDaemon(result="recording")

    reply, should_break = process_request(daemon, "toggle", lambda s, b="": None)

    assert (reply, should_break) == ("recording", False)
