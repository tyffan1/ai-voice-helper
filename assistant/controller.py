import re
import threading
import time

import numpy as np

from assistant import audio, actions, i18n, llm, stt, tts
from assistant.i18n import L

_LAUNCH_RE = re.compile(
    r"^(запусти|запустите|запускай|открой|откройте|включи|включите|open|launch|start|play)\s+(.+)$",
    re.IGNORECASE,
)
_LAUNCH_STOP = {"игру", "игра", "игрушку", "игры", "game", "games", "приложение", "программу", "программу"}

_CLOSE_RE = re.compile(
    r"^(закрой|закройте|закрыть|закрывай|заверши|закройка|close|quit)\s+(.+)$",
    re.IGNORECASE,
)
_CLOSE_STOP = {"вкладку", "вкладки", "вкладка", "окно", "окна", "tab"}

_FACT_RE = re.compile(
    r"^(какая|какой|какие|какое|кто|где|когда|сколько|почему|зачем|что такое|что за|"
    r"кто такой|какой город|как правильно|как называется|что означает|расскажи про|"
    r"what|who|where|when|why|how)\b",
    re.IGNORECASE,
)

_SEARCH_RE = re.compile(
    r"^(найди|найти|поищи|поиск|погугли|загугли|узнай|узнать|посмотри|покажи|в интернете|"
    r"search|find|google)\b",
    re.IGNORECASE,
)

_SEARCH_DIRECT_RE = re.compile(
    r"^(найди|найти|поищи|поиск|погугли|загугли|search|find|google)\b",
    re.IGNORECASE,
)

_NOT_FOUND_HINTS = (
    "не содержит", "не нашёл", "не удалось найти", "не смог", "не знаю", "нет ответа",
    "информации недостаточно", "можно найти", "на сайте", "нет информации",
    "not contain", "could not find", "no answer", "not found", "don't know", "do not know",
    "insufficient", "available at", "on the site",
    "извините", "в тексте нет", "нет конкретного", "нет рецепта", "не указан", "не указано",
    "нет данных", "ничего не найден", "нет упоминаний", "не удалось получить",
)

_PREAMBLE_RE = re.compile(
    r"^(вот ответ( на запрос)?:?|ответ:?|результат:?|по результатам поиска:?|"
    r"вот что удалось найти:?|вот информация:?|here is the answer:?|answer:?)\s*$",
    re.IGNORECASE,
)


def _clean_summary(summary):
    lines = (summary or "").split("\n")
    while lines and (_PREAMBLE_RE.match(lines[0].strip()) or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


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

    def _launch_fallback(self, text):
        m = _LAUNCH_RE.match(text.strip())
        if not m:
            return None
        name = m.group(2).strip().strip('"').strip(".")
        if not name or name.lower() in _LAUNCH_STOP:
            return None
        return name

    def _launch_or_app(self, name):
        res = actions.execute("open_game", {"name": name})
        fail = L("Не нашёл игру", "Could not find the game")
        if res.startswith(fail):
            res = actions.execute("open_app", {"name": name})
        return res

    def _close_fallback(self, text):
        m = _CLOSE_RE.match(text.strip())
        if not m:
            return None
        name = m.group(2).strip().strip('"').strip(".")
        if not name or name.lower() in _CLOSE_STOP:
            return None
        return name

    def _verify_fact(self, text):
        last = None
        try:
            results = actions._search(text)
            if results:
                snips = "\n".join(
                    f"{i}. {title}. {snip}" for i, (title, href, snip) in enumerate(results[:5], 1) if snip
                )
                if snips.strip():
                    summary = _clean_summary(llm.summarize(snips, text, lang=i18n.get_language()))
                    if summary:
                        last = summary
                        low = summary.lower()
                        weak = len(summary) < 60 and ":" not in summary and not re.search(r"\d", summary)
                        if not weak and not any(h in low for h in _NOT_FOUND_HINTS):
                            return summary
        except Exception:
            pass
        for page in range(2):
            try:
                hit = actions._web_lookup(text, page)
                if hit is None:
                    break
                summary = _clean_summary(llm.summarize(hit[2], text, lang=i18n.get_language()))
                if not summary:
                    continue
                last = summary
                if summary.strip()[:40] == hit[0][:40]:
                    continue
                low = summary.lower()
                weak = len(summary) < 60 and ":" not in summary and not re.search(r"\d", summary)
                if weak or any(h in low for h in _NOT_FOUND_HINTS):
                    tail = hit[2][-6000:]
                    summary = _clean_summary(llm.summarize(tail, text, lang=i18n.get_language()))
                    weak = bool(summary) and len(summary) < 60 and ":" not in summary and not re.search(r"\d", summary)
                    if summary and not weak and not any(h in summary.lower() for h in _NOT_FOUND_HINTS):
                        return summary
                    continue
                return summary
            except Exception:
                break
        if last and not any(h in last.lower() for h in _NOT_FOUND_HINTS):
            return last
        return None

    def handle_text(self, text):
        text = text.strip()
        if not text or len(text) < 3:
            self._speak(_repeat())
            return
        with self.busy:
            you = L("Вы:", "You:")
            atom = L("Атом:", "Atom:")
            self.emit_log(f"{you} {text}")
            if re.search(r"\b(ip|айпи)\b", text.lower()):
                ip = actions._my_ip()
                if ip:
                    msg = L(f"Ваш IP-адрес: {ip}", f"Your IP address is: {ip}")
                    self.emit_log(f"{atom} {msg}")
                    self._speak(msg)
                    return
            if _SEARCH_DIRECT_RE.match(text) and not _LAUNCH_RE.match(text):
                self.emit_status(_thinking(), "#ff9800")
                summary = self._verify_fact(text)
                if summary:
                    self.emit_log(f"{atom} {summary}")
                    self._speak(summary)
                    return
                msg = L("Не нашёл ответ в интернете", "I could not find an answer on the internet")
                self.emit_log(f"{atom} {msg}")
                self._speak(msg)
                return
            self.emit_status(_thinking(), "#ff9800")
            decision = llm.ask(text)
            if "reply" in decision:
                name = self._launch_fallback(text)
                if name:
                    result = self._launch_or_app(name)
                    self.emit_log(f"{atom} {result}")
                    self._speak(result)
                    return
                name = self._close_fallback(text)
                if name:
                    result = actions.execute("close_app", {"name": name})
                    self.emit_log(f"{atom} {result}")
                    self._speak(result)
                    return
                if _FACT_RE.match(text) or _SEARCH_RE.match(text):
                    summary = self._verify_fact(text)
                    if summary:
                        self.emit_log(f"{atom} {summary}")
                        self._speak(summary)
                        return
                self.emit_log(f"{atom} {decision['reply']}")
                self._speak(decision["reply"])
                return
            tool = decision.get("tool")
            params = decision.get("params") or {}
            if tool not in actions.REGISTRY:
                name = self._launch_fallback(text)
                if name:
                    result = self._launch_or_app(name)
                    self.emit_log(f"{atom} {result}")
                    self._speak(result)
                    return
                name = self._close_fallback(text)
                if name:
                    result = actions.execute("close_app", {"name": name})
                    self.emit_log(f"{atom} {result}")
                    self._speak(result)
                    return
                self.emit_log(f"{atom} {tool}")
                self._speak(
                    L("Не понял команду, попробуйте сформулировать иначе", "Did not understand, try rephrasing")
                )
                return
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
                if tool in ("web_query", "web_search"):
                    try:
                        summary = None
                        results = actions._search(text)
                        if results:
                            snips = "\n".join(
                                f"{i}. {title}. {snip}"
                                for i, (title, href, snip) in enumerate(results[:5], 1)
                                if snip
                            )
                            if snips.strip():
                                summary = llm.summarize(snips, text, lang=i18n.get_language())
                        if not summary or any(h in summary.lower() for h in _NOT_FOUND_HINTS):
                            summary = llm.summarize(result, text, lang=i18n.get_language())
                    except Exception:
                        summary = None
                    summary = _clean_summary(summary) if summary else None
                    if summary:
                        self.emit_log(f"{atom} {summary}")
                        self._speak(summary)
                        return
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
            text = stt.transcribe(wav, wake=True)
            print(f"[wake] {text}")
            try:
                from assistant.wake import _log

                _log(f"transcribed: {text!r}")
            except Exception:
                pass
            rest = strip_wake(text)
            try:
                from assistant.wake import _log

                _log(f"wake match ({self.wake_name}): rest={rest!r}")
            except Exception:
                pass
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