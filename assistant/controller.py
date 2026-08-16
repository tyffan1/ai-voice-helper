import threading
import time

import numpy as np

from assistant import audio, actions, i18n, llm, stt, tts
from assistant.i18n import L


def _idle():
    return L("Слушаю...", "Listening...")


def _recording():
    return L("Записываю...", "Recording...")


def _thinking():
    return L("Думаю...", "Thinking...")


def _speaking():
    return L("Говорю...", "Speaking...")


def _repeat():
    return L("Не расслышал, повторите", "Sorry, didn't catch that, say it again")


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[len(b)]


def _matches_wake(word, name):
    return _edit_distance(word, name) <= max(1, len(name) // 3)


def strip_wake(text, name=None):
    import re

    name = name or i18n.wake_name()
    words = re.sub(r"[^\w\s]", "", text.lower()).split()
    if words and _matches_wake(words[0], name):
        return " ".join(words[1:]).strip()
    return None


class Controller:
    def __init__(self, emit_status=None, emit_log=None):
        self.emit_status = emit_status or (lambda text, color=None: None)
        self.emit_log = emit_log or (lambda text: None)
        self.busy = threading.RLock()
        self.wake_enabled = True
        self.wake_awaiting = False
        self._wake_seen_at = 0.0
        self.on_exit = None

    @property
    def wake_name(self):
        return i18n.wake_name()

    def set_wake_enabled(self, enabled):
        self.wake_enabled = enabled
        print(L(f"Wake-отклик: {'включён' if enabled else 'выключен'}",
                f"Wake response: {'on' if enabled else 'off'}"))

    def _speak(self, text):
        if not text:
            return
        self.emit_status(_speaking(), "#4caf50")
        tts.speak(text)
        self.emit_status(_idle(), "#9e9e9e")

    def handle_text(self, text):
        text = text.strip()
        if not text or len(text) < 3:
            self._speak(_repeat())
            return
        with self.busy:
            you = L("Вы:", "You:")
            atom = L("Атом:", "Atom:")
            self.emit_log(f"{you} {text}")
            self.emit_status(_thinking(), "#ff9800")
            decision = llm.ask(text)
            if "reply" in decision:
                self.emit_log(f"{atom} {decision['reply']}")
                self._speak(decision["reply"])
                return
            tool = decision.get("tool")
            params = decision.get("params") or {}
            self.emit_log(L("Действие:", "Action:") + f" {tool} {params}")
            if tool == "exit_assistant":
                goodbye = L("До встречи", "See you")
                self.emit_log(f"{atom} {goodbye}")
                self._speak(goodbye)
                self.emit_status(L("Завершение...", "Shutting down..."), "#f44336")
                if self.on_exit:
                    self.on_exit()
                else:
                    import os

                    os._exit(0)
            result = actions.execute(tool, params)
            if result:
                self.emit_log(f"{atom} {result}")
                self._speak(result)
            else:
                self.emit_status(_idle(), "#9e9e9e")

    def record_and_handle(self, source=L("горячая клавиша", "hotkey")):
        with self.busy:
            self.emit_status(_recording(), "#2196f3")
            print(f"[{source}] recording...")
            recording = audio.record_until_silence()
            rms = float((recording.astype(np.float32) ** 2).mean() ** 0.5)
            if rms < 8.0:
                self.emit_status(_idle(), "#9e9e9e")
                self._speak(_repeat())
                return
            wav = audio.temp_wav(recording)
            text = stt.transcribe(wav)
            print(f"[{source}] recognized: {text}")
            self.handle_text(text)

    def wake_session(self, clip):
        with self.busy:
            wav = audio.temp_wav(clip)
            text = stt.transcribe(wav)
            print(f"[wake] {text}")
            rest = strip_wake(text)
            if self.wake_awaiting:
                self.wake_awaiting = False
                command = rest if rest is not None else text.strip()
                if command:
                    print("[wake] command accepted")
                    self.handle_text(command)
                else:
                    self._speak(_repeat())
                return
            if rest is None:
                return
            if rest:
                self.handle_text(rest)
            else:
                audio.beep(660.0, 0.08)
                self.wake_awaiting = True
                self._wake_seen_at = time.time()
                print("[wake] waiting for command...")