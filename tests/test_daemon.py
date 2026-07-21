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
    events = {"injected": [], "keys": [], "notes": []}
    rec = FakeRecorder()
    daemon = DictationDaemon(
        config=Config(),
        model=object(),
        recorder=rec,
        transcriber=lambda wav, model, language: transcript,
        injector=lambda text, method: events["injected"].append(text) or "wtype",
        key_injector=lambda key, method: events["keys"].append(key) or "wtype",
        notifier=lambda summary, body="": events["notes"].append(summary),
        wav_path="/tmp/cap.wav",
    )
    return daemon, rec, events


def make_seq_daemon(transcripts, config=None, clock=None, injector=None):
    """Daemon whose transcriber returns each item of `transcripts` in turn."""
    events = {"injected": [], "keys": [], "notes": []}
    rec = FakeRecorder()
    seq = iter(transcripts)
    if injector is None:
        def injector(text, method):
            events["injected"].append(text)
            return "wtype"
    daemon = DictationDaemon(
        config=config or Config(),
        model=object(),
        recorder=rec,
        transcriber=lambda wav, model, language: next(seq),
        injector=injector,
        key_injector=lambda key, method: events["keys"].append(key) or "wtype",
        notifier=lambda summary, body="": events["notes"].append(summary),
        wav_path="/tmp/cap.wav",
        clock=clock or (lambda: 0.0),
    )
    return daemon, rec, events


def _dictate_once(daemon):
    daemon.handle("toggle")  # start
    daemon.handle("toggle")  # stop + transcribe + inject


def test_smart_spacing_adds_space_between_sequential_dictations():
    daemon, rec, events = make_seq_daemon(["hello world", "next chunk"])
    _dictate_once(daemon)
    _dictate_once(daemon)
    assert events["injected"] == ["hello world", " next chunk"]


def test_smart_spacing_capitalizes_after_sentence():
    daemon, rec, events = make_seq_daemon(["first sentence.", "next one"])
    _dictate_once(daemon)
    _dictate_once(daemon)
    assert events["injected"] == ["first sentence.", " Next one"]


def test_smart_spacing_resets_after_idle_window():
    now = [1000.0]
    daemon, rec, events = make_seq_daemon(["first.", "second"], clock=lambda: now[0])
    _dictate_once(daemon)
    now[0] += 31  # exceed the 30s reset window
    _dictate_once(daemon)
    # fresh start: no leading space, no forced capital
    assert events["injected"] == ["first.", "second"]


def test_smart_spacing_disabled_injects_raw():
    daemon, rec, events = make_seq_daemon(
        ["hello", "world"], config=Config(smart_spacing=False)
    )
    _dictate_once(daemon)
    _dictate_once(daemon)
    assert events["injected"] == ["hello", "world"]


def test_empty_transcript_does_not_update_boundary_state():
    daemon, rec, events = make_seq_daemon(["hello", "", "world"])
    _dictate_once(daemon)  # "hello"
    _dictate_once(daemon)  # empty -> no injection, state unchanged
    _dictate_once(daemon)  # "world" spaced off "hello"
    assert events["injected"] == ["hello", " world"]


def test_injection_failure_does_not_update_boundary_state():
    calls = [0]
    events = {"injected": []}

    def injector(text, method):
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("boom")
        events["injected"].append(text)
        return "wtype"

    daemon, rec, _ = make_seq_daemon(["first.", "second"], injector=injector)
    _dictate_once(daemon)  # injection fails, state stays empty
    _dictate_once(daemon)  # fresh start -> no leading space
    assert events["injected"] == ["second"]


def test_voice_command_injects_text_and_keys_in_order():
    order = []
    events = {"notes": []}
    rec = FakeRecorder()
    daemon = DictationDaemon(
        config=Config(),
        model=object(),
        recorder=rec,
        transcriber=lambda wav, model, language: "line one new line line two",
        injector=lambda text, method: order.append(("text", text)) or "wtype",
        key_injector=lambda key, method: order.append(("key", key)) or "wtype",
        notifier=lambda summary, body="": events["notes"].append(summary),
        wav_path="/tmp/cap.wav",
    )
    _dictate_once(daemon)
    assert order == [
        ("text", "line one"),
        ("key", "shift_enter"),
        ("text", "line two"),
    ]


def test_voice_command_trailing_enter_submits():
    daemon, rec, events = make_seq_daemon(["send this press enter"])
    _dictate_once(daemon)
    assert events["injected"] == ["send this"]
    assert events["keys"] == ["enter"]


def test_smart_spacing_applies_only_to_first_text_chunk():
    daemon, rec, events = make_seq_daemon(["a.", "b new line c"])
    _dictate_once(daemon)          # "a."
    _dictate_once(daemon)          # boundary + voice command
    # first chunk of 2nd utterance gets space+capital off "a."; chunk after the
    # newline injects verbatim (no forced leading space).
    assert events["injected"] == ["a.", " B", "c"]
    assert events["keys"] == ["shift_enter"]


def test_boundary_state_resets_after_trailing_key():
    daemon, rec, events = make_seq_daemon(["done. enter", "fresh"])
    _dictate_once(daemon)          # "done." + Enter -> submit, state reset
    _dictate_once(daemon)          # should start fresh: no leading space
    assert events["injected"] == ["done.", "fresh"]
    assert events["keys"] == ["enter"]


def test_voice_commands_disabled_injects_transcript_verbatim():
    daemon, rec, events = make_seq_daemon(
        ["say new line literally"], config=Config(voice_commands=False)
    )
    _dictate_once(daemon)
    assert events["injected"] == ["say new line literally"]
    assert events["keys"] == []


def test_key_injection_failure_aborts_and_keeps_state():
    events = {"injected": [], "notes": []}
    rec = FakeRecorder()

    def key_injector(key, method):
        raise RuntimeError("no key backend")

    daemon = DictationDaemon(
        config=Config(),
        model=object(),
        recorder=rec,
        transcriber=lambda wav, model, language: "hello new line world",
        injector=lambda text, method: events["injected"].append(text) or "wtype",
        key_injector=key_injector,
        notifier=lambda summary, body="": events["notes"].append((summary, body)),
        wav_path="/tmp/cap.wav",
    )
    _dictate_once(daemon)
    # first text chunk injected, then key fails -> abort, state left empty
    assert events["injected"] == ["hello"]
    assert daemon._last_text == ""


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


def test_start_begins_recording_and_is_idempotent():
    daemon, rec, events = make_daemon()
    assert daemon.handle("start") == "recording"
    assert rec.started == ["/tmp/cap.wav"]
    # second start must not start a second recording
    assert daemon.handle("start") == "recording"
    assert rec.started == ["/tmp/cap.wav"]


def test_stop_transcribes_and_injects():
    daemon, rec, events = make_daemon()
    daemon.handle("start")
    assert daemon.handle("stop") == "idle"
    assert rec.stopped == 1
    assert events["injected"] == ["hello world"]


def test_stop_when_idle_is_noop():
    daemon, rec, events = make_daemon()
    assert daemon.handle("stop") == "idle"
    assert rec.stopped == 0
    assert events["injected"] == []


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
