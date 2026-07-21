from dictate.config import Config
from dictate.daemon import DictationDaemon


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
