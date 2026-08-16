import threading

from faster_whisper import WhisperModel

from assistant.config import WHISPER_MODEL

_model = None
_lock = threading.Lock()


def load():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(wav_path):
    model = load()
    segments, _info = model.transcribe(
        str(wav_path),
        language="ru",
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()