from faster_whisper import WhisperModel


def load_model(model_name: str):
    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_wav(wav_path: str, model, language: str = "en") -> str:
    segments, _info = model.transcribe(wav_path, language=language)
    text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
    return text.strip()
