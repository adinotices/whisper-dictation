from types import SimpleNamespace

from dictate.transcribe import transcribe_wav


class FakeModel:
    def __init__(self, texts):
        self._texts = texts
        self.calls = []

    def transcribe(self, path, language="en"):
        self.calls.append((path, language))
        segments = (SimpleNamespace(text=t) for t in self._texts)
        return segments, SimpleNamespace(language=language)


def test_joins_and_strips_segments():
    model = FakeModel(["  Hello ", "there. ", "How are you?"])
    result = transcribe_wav("x.wav", model, language="en")
    assert result == "Hello there. How are you?"
    assert model.calls == [("x.wav", "en")]


def test_empty_when_no_segments():
    model = FakeModel([])
    assert transcribe_wav("x.wav", model) == ""
