import os
import threading
import time
import wave

import numpy as np
import sounddevice as sd
from piper import PiperVoice

from assistant import i18n
from assistant.config import EDGE_VOICES, PIPER_VOICES, TTS_ENGINE

_voices = {}
_sapi = None
_lock = threading.Lock()
_speaking = False
_edge_cooldown = 0.0


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


def _sapi_voice():
    global _sapi
    if _sapi is None:
        try:
            import comtypes.client

            _sapi = comtypes.client.CreateObject("SAPI.SpVoice")
            try:
                _sapi.Rate = -1
            except Exception:
                pass
        except Exception:
            _sapi = False
    return _sapi or None


def _engine_for(lang):
    engine = TTS_ENGINE.strip().lower()
    if engine == "piper":
        return "piper"
    if engine == "sapi":
        return "sapi" if _sapi_voice() else "piper"
    if engine == "edge":
        return "edge"
    if time.time() > _edge_cooldown:
        return "edge"
    if lang == "ru" and _sapi_voice():
        return "sapi"
    return "piper"


def _edge_synth(text, path, lang):
    import asyncio

    import edge_tts
    import miniaudio

    mp3 = path + ".mp3"

    async def _run():
        await asyncio.wait_for(
            edge_tts.Communicate(text, EDGE_VOICES.get(lang, EDGE_VOICES["ru"]), rate="-5%").save(mp3),
            timeout=10,
        )

    for _ in range(2):
        try:
            asyncio.run(_run())
            break
        except Exception:
            continue
    else:
        return False
    try:
        dec = miniaudio.decode_file(mp3)
        data = np.frombuffer(dec.samples, dtype=np.int16)
        if dec.nchannels > 1:
            data = data.reshape(-1, dec.nchannels).mean(axis=1).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(dec.sample_rate)
            wf.writeframes(data.tobytes())
        return True
    except Exception:
        return False
    finally:
        try:
            os.remove(mp3)
        except Exception:
            pass


def warm_edge():
    import tempfile

    try:
        f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        f.close()
        _edge_synth("Атом", f.name, "ru")
        os.remove(f.name)
    except Exception:
        pass


def _sapi_synth(text, path):
    import comtypes.client

    voice = _sapi_voice()
    stream = comtypes.client.CreateObject("SAPI.SpFileStream")
    stream.Open(str(path), 3)
    voice.AudioOutputStream = stream
    voice.Speak(text, 0)
    stream.Close()


def synth_to_wav(text, path, lang=None):
    lang = lang or i18n.get_language()
    global _edge_cooldown
    if _engine_for(lang) == "edge":
        if _edge_synth(text, path, lang):
            return
        _edge_cooldown = time.time() + 60
    if lang == "ru" and _sapi_voice():
        try:
            _sapi_synth(text, path)
            return
        except Exception:
            pass
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