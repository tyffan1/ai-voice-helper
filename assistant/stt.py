import re
import threading

from faster_whisper import WhisperModel

from assistant import i18n, memory
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


def _context_prompt():
    parts = []
    try:
        name = memory.get_name()
        if name:
            parts.append(name)
        city = memory.get_city()
        if city:
            parts.append(city)
        for c in memory.get_commands()[-10:]:
            parts.append(c["trigger"])
            parts.append(c["action"])
        for f in memory.get_facts()[-10:]:
            parts.append(f)
    except Exception:
        pass
    seen, out = set(), []
    for p in parts:
        p = re.sub(r"[^а-яА-ЯёЁa-zA-Z0-9 ]", " ", p).strip()
        low = p.lower()
        if p and low not in seen:
            seen.add(low)
            out.append(p)
    return ", ".join(out)


def transcribe(wav_path, lang=None, wake=False, hint=None):
    lang = lang or i18n.stt_language()
    model = load()
    kwargs = dict(
        language=lang,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    prompts = []
    if hint:
        prompts.append(hint)
    ctx = _context_prompt()
    if ctx:
        prompts.append(ctx)
    if wake:
        name = i18n.wake_name()
        prompts.append(f"{name}, {name}, {name}.")
        kwargs["vad_parameters"] = {
            "min_speech_duration_ms": 100,
            "speech_pad_ms": 200,
        }
        kwargs["no_speech_threshold"] = None
    if prompts:
        kwargs["initial_prompt"] = " ".join(prompts)
    segments, _info = model.transcribe(str(wav_path), **kwargs)
    return " ".join(s.text.strip() for s in segments).strip()