from faster_whisper import WhisperModel

from assistant.config import WHISPER_MODEL

_model = None


def transcribe(wav_path):
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    segments, _info = _model.transcribe(str(wav_path), language="ru", beam_size=5)
    return " ".join(s.text.strip() for s in segments).strip()
