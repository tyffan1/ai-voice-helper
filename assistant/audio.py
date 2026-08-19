import tempfile
import wave

import numpy as np
import sounddevice as sd

from assistant.config import MAX_RECORD_SEC, SAMPLE_RATE, SILENCE_MS, VOLUME_THRESHOLD


def beep(freq=880.0, duration=0.12):
    t = np.linspace(0.0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    tone = (np.sin(2.0 * np.pi * freq * t) * 0.2).astype(np.float32)
    sd.play(tone, SAMPLE_RATE)


def play_wav(path):
    wf = wave.open(str(path), "rb")
    data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = (data.astype(np.float32) / 32768.0).reshape(-1)
    sd.play(audio, wf.getframerate())
    sd.wait()
    wf.close()


def record_until_silence(max_sec=MAX_RECORD_SEC, block_sec=0.2):
    frames = []
    silence = 0
    silence_needed = int(SAMPLE_RATE * SILENCE_MS / 1000)
    elapsed = 0.0
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
        while elapsed < max_sec:
            block, _ = stream.read(int(SAMPLE_RATE * block_sec))
            frames.append(block)
            elapsed += block_sec
            level = int(np.abs(block).max())
            if level < VOLUME_THRESHOLD:
                silence += len(block)
            else:
                silence = 0
            if len(frames) > 5 and silence > silence_needed:
                break
    return np.concatenate(frames).reshape(-1)


def save_wav(audio, path):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.astype(np.int16).tobytes())


def temp_wav(audio):
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    f.close()
    save_wav(audio, f.name)
    return f.name
