import threading

from faster_whisper import WhisperModel

from assistant import i18n
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


def transcribe(wav_path, lang=None, wake=False):
    lang = lang or i18n.stt_language()
    model = load()
    kwargs = dict(
        language=lang,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    if wake:
        name = i18n.wake_name()
        kwargs["initial_prompt"] = f"{name}, {name}, {name}."
        kwargs["vad_parameters"] = {
            "min_speech_duration_ms": 100,
            "speech_pad_ms": 200,
        }
        kwargs["no_speech_threshold"] = None
    segments, _info = model.transcribe(str(wav_path), **kwargs)
    return " ".join(s.text.strip() for s in segments).strip()