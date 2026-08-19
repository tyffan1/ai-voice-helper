import datetime
import re
import threading
import time

import numpy as np

from assistant import audio, actions, i18n, llm, memory, stt, tts
from assistant.i18n import L

_MEM_NAME_RE = re.compile(
    r"^(?:называй|зови|зовут)\s+меня\s+(.+)$"
    r"|^меня\s+зовут\s+(.+)$"
    r"|^запомни(?:,)?\s+что\s+меня\s+зовут\s+(.+)$"
    r"|^(?:my name is|call me|you can call me)\s+(.+)$",
    re.IGNORECASE,
)
_MEM_CITY_RE = re.compile(
    r"^(?:я\s+живу\s+в\s+|живу\s+в\s+|мой\s+город\s+"
    r"|запомни(?:,)?\s+мой\s+город\s+"
    r"|запомни(?:,)?\s+что\s+(?:мой\s+город|я\s+живу\s+в)\s+"
    r"|i live in\s+)(.+)$",
    re.IGNORECASE,
)
_MEM_FACT_RE = re.compile(r"^(?:запомни(?:,)?(?:\s+что)?|remember(?: that)?)\s+(.+)$", re.IGNORECASE)
_MEM_FORGET_RE = re.compile(r"^(?:забудь(?:,)?(?:\s+про)?|forget(?: about)?)\s+(.+)$", re.IGNORECASE)
_MEM_RECALL_RE = re.compile(
    r"^(?:что\s+ты\s+(?:знаешь|помнишь)(?:\s+обо\s+мне)?"
    r"|что\s+ты\s+обо\s+мне\s+(?:знаешь|помнишь)"
    r"|как\s+меня\s+зовут"
    r"|what do you (?:know|remember) about me)\s*\??$",
    re.IGNORECASE,
)

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


def _matches_wake(word, name):
    return actions._edit_distance(word, name) <= max(1, len(name) // 3)


def _extract_name(text):
    t = re.sub(r"[^\w\s]", "", (text or "")).strip().lower()
    if not t:
        return None
    if any(x in t for x in ("не знаю", "не скажу", "не помню", "не хочу")):
        return None
    for pat in (r"^(зови меня|называй меня|зовут меня|меня зовут|моё имя|меня звать|я)\s+",
                r"^(my name is|i am|i'm|call me|it's)\s+"):
        t = re.sub(pat, "", t, flags=re.I)
    t = t.strip()
    if not t or len(t) < 2:
        return None
    return " ".join(w.capitalize() for w in t.split()[:2])[:40]


def strip_wake(text, name=None):
    import re

    name = name or i18n.wake_name()
    words = re.sub(r"[^\w\s]", "", text.lower()).split()
    for i in range(min(3, len(words))):
        if _matches_wake(words[i], name):
            return " ".join(words[i + 1 :]).strip()
    return None


class Controller:
    def __init__(self, emit_status=None, emit_log=None):
        self.emit_status = emit_status or (lambda text, color=None: None)
        self.emit_log = emit_log or (lambda text: None)
        self.busy = threading.RLock()
        self.wake_enabled = True
        self.wake_awaiting = False
        self._wake_seen_at = 0.0
        self._beep_at = 0.0
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

    def _fallback_launch_close(self, text, atom):
        name = self._launch_fallback(text)
        if name:
            result = self._launch_or_app(name)
            self.emit_log(f"{atom} {result}")
            self._speak(result)
            return True
        name = self._close_fallback(text)
        if name:
            result = actions.execute("close_app", {"name": name})
            self.emit_log(f"{atom} {result}")
            self._speak(result)
            return True
        return False

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

    def _memory_handle(self, text):
        m = _MEM_NAME_RE.match(text)
        if m:
            name = next(g for g in m.groups() if g).strip().strip('"')
            if memory.set_name(name):
                return L(f"Отлично, буду называть тебя {name}", f"Great, I will call you {name}")
        m = _MEM_CITY_RE.match(text)
        if m:
            raw = m.group(1).strip().strip('"')
            if memory.set_city(raw):
                city = memory.get_city()
                return L(f"Запомнила, твой город — {city}", f"Got it, your city is {city}")
        m = _MEM_RECALL_RE.match(text)
        if m:
            parts = memory.describe(i18n.get_language())
            if parts:
                return " ".join(parts)
            return L(
                "Пока ничего о тебе не знаю. Скажи, например: меня зовут Макс",
                "I don't know anything about you yet. Say, for example: my name is Max",
            )
        m = _MEM_FACT_RE.match(text)
        if m:
            fact = m.group(1).strip().strip('"')
            if memory.add_fact(fact):
                name = memory.get_name()
                return L(f"Запомнила{', ' + name if name else ''}", f"Got it{', ' + name if name else ''}")
        m = _MEM_FORGET_RE.match(text)
        if m:
            kw = m.group(1).strip().strip('"')
            if memory.forget_fact(kw):
                return L(f"Забыла про {kw}", f"Forgot about {kw}")
            return L(f"Не помню ничего про {kw}", f"I don't remember anything about {kw}")
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
            memory_msg = self._memory_handle(text)
            if memory_msg:
                self.emit_log(f"{atom} {memory_msg}")
                self._speak(memory_msg)
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
                if self._fallback_launch_close(text, atom):
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
                if self._fallback_launch_close(text, atom):
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
            text = stt.transcribe(wav, hint=actions.app_hint())
            print(f"[{source}] recognized: {text}")
            self.handle_text(text)

    def wake_session(self, clip):
        with self.busy:
            if time.time() - self._beep_at < 0.6:
                print("[wake] ignoring beep echo")
                return
            rms = float((clip.astype(np.float32) ** 2).mean() ** 0.5)
            if rms < 8.0:
                print("[wake] ignoring noise clip")
                return
            wav = audio.temp_wav(clip)
            text = stt.transcribe(wav, wake=True, hint=actions.app_hint())
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
                self._beep_at = time.time()
                audio.beep(660.0, 0.08)
                self.wake_awaiting = True
                self._wake_seen_at = time.time()
                print("[wake] waiting for command...")

    def greet(self):
        def _run():
            stt.load()
            time.sleep(1.5)
            with self.busy:
                name = memory.get_name()
                if name:
                    hour = datetime.datetime.now().hour
                    if hour < 5:
                        part = L("Доброй ночи", "Good night")
                    elif hour < 12:
                        part = L("Доброе утро", "Good morning")
                    elif hour < 18:
                        part = L("Добрый день", "Good afternoon")
                    else:
                        part = L("Добрый вечер", "Good evening")
                    msg = f"{part}, {name}! {L('Чем могу помочь?', 'How can I help?')}"
                    atom = L("Атом:", "Atom:")
                    self.emit_log(f"{atom} {msg}")
                    self._speak(msg)
                else:
                    self._ask_name()

        threading.Thread(target=_run, daemon=True).start()

    def _ask_name(self):
        atom = L("Атом:", "Atom:")
        questions = [
            L("Привет! Я Атом. А как тебя зовут?", "Hi! I'm Atom. What's your name?"),
            L("Не расслышала. Скажи ещё раз, как тебя зовут?", "Sorry, didn't catch that. What's your name again?"),
        ]
        for question in questions:
            self.emit_log(f"{atom} {question}")
            self._speak(question)
            recording = audio.record_until_silence(max_sec=8)
            rms = float((recording.astype(np.float32) ** 2).mean() ** 0.5)
            if rms < 8.0:
                continue
            wav = audio.temp_wav(recording)
            text = stt.transcribe(wav, hint="меня зовут, зови меня, как тебя зовут, моё имя, my name is")
            name = _extract_name(text)
            if name and memory.set_name(name):
                msg = L(f"Приятно познакомиться, {name}!", f"Nice to meet you, {name}!")
                self.emit_log(f"{atom} {msg}")
                self._speak(msg)
                return
        msg = L(
            "Ладно, скажешь потом. Например: меня зовут Костя",
            "Alright, tell me later. For example: my name is Max",
        )
        self.emit_log(f"{atom} {msg}")
        self._speak(msg)