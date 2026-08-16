import os
import threading
import wave

import numpy as np
import sounddevice as sd
from piper import PiperVoice

from assistant import i18n
from assistant.config import PIPER_VOICES

_voices = {}
_lock = threading.Lock()
_speaking = False


def is_speaking():
    return _speaking


def load(lang=None):
    lang = lang or i18n.get_language()
    with _lock:
        if lang not in _voices:
            path = PIPER_VOICES[lang]
            if not os.path.exists(path):
                path = PIPER_VOICES["ru"]
            _voices[lang] = PiperVoice.load(path)
    return _voices[lang]


def synth_to_wav(text, path, lang=None):
    with wave.open(str(path), "wb") as wf:
        load(lang).synthesize_wav(text, wf)


def speak(text, lang=None):
    import tempfile

    global _speaking
    _speaking = True
    try:
        f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        f.close()
        synth_to_wav(text, f.name, lang)
        wf = wave.open(f.name, "rb")
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
        audio = (data.astype(np.float32) / 32768.0).reshape(-1)
        sd.play(audio, wf.getframerate())
        sd.wait()
        wf.close()
    finally:
        _speaking = False