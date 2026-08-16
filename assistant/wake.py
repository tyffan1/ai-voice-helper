import threading
import time

import numpy as np
import sounddevice as sd

from assistant import tts
from assistant.config import SAMPLE_RATE, WAKE_VOLUME_THRESHOLD


class WakeListener(threading.Thread):
    def __init__(self, controller):
        super().__init__(daemon=True, name="wake-listener")
        self.controller = controller
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _speech_blocks(self, stream):
        block = stream.read(int(SAMPLE_RATE * 0.4))[0]
        level = int(np.abs(block).max())
        if level < WAKE_VOLUME_THRESHOLD:
            return None
        blocks = [block]
        silence = 0
        while not self._stop.is_set():
            b = stream.read(int(SAMPLE_RATE * 0.4))[0]
            blocks.append(b)
            if int(np.abs(b).max()) < WAKE_VOLUME_THRESHOLD:
                silence += len(b)
            else:
                silence = 0
            if silence > int(SAMPLE_RATE * 0.8):
                break
            if len(blocks) * 0.4 > 12:
                break
        return np.concatenate(blocks).reshape(-1)

    def run(self):
        print("Wake-листенер запущен")
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
                while not self._stop.is_set():
                    if not self.controller.wake_enabled or self.controller.busy.locked() or tts.is_speaking():
                        time.sleep(0.15)
                        continue
                    if (
                        self.controller.wake_awaiting
                        and time.time() - self.controller._wake_seen_at > 8
                    ):
                        self.controller.wake_awaiting = False
                        print("[wake] таймаут ожидания команды")
                        continue
                    clip = self._speech_blocks(stream)
                    if clip is None or len(clip) < int(SAMPLE_RATE * 0.5):
                        continue
                    self.controller.wake_session(clip)
        except Exception as exc:
            print(f"Wake-листенер остановлен: {exc}")