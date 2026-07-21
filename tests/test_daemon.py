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
