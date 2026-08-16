import wave

import numpy as np
import sounddevice as sd
from piper import PiperVoice

from assistant.config import PIPER_VOICE

_voice = None


def _load():
    global _voice
    if _voice is None:
        _voice = PiperVoice.load(PIPER_VOICE)
    return _voice


def synth_to_wav(text, path):
    with wave.open(str(path), "wb") as wf:
        _load().synthesize_wav(text, wf)


def speak(text):
    import tempfile

    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    synth_to_wav(text, f.name)
    wf = wave.open(f.name, "rb")
    data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = (data.astype(np.float32) / 32768.0).reshape(-1)
    sd.play(audio, wf.getframerate())
    sd.wait()
    wf.close()
