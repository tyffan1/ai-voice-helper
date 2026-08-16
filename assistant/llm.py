import inspect
import json
import os
import threading

from llama_cpp import Llama

from assistant import i18n
from assistant.actions import REGISTRY
from assistant.config import LLM_MODEL_PATH

_model = None
_lock = threading.Lock()
_tools_cache = {}

_SYSTEM = {
    "ru": (
        "Ты — голосовой ассистент на русском языке, работающий на компьютере пользователя. "
        "Ты умеешь выполнять действия на компьютере через инструменты: запускать приложения, "
        "открывать сайты и поиск в браузере, печатать текст, нажимать клавиши, закрывать вкладки, "
        "делать скриншоты, ставить таймеры, сообщать время и состояние системы. "
        "Выбирай инструмент, если он нужен; иначе отвечай кратко и дружелюбно. "
        "Про время, дату и систему всегда используй инструменты, не отвечай по памяти. "
        "Погоду всегда получай инструментом get_weather и озвучивай её, никогда не открывай сайты с погодой. "
        "Если пользователь назвал город — передай его в get_weather. "
        "Печать в поле ввода — type_text, нажатие клавиш и комбинаций — press_key, "
        "закрытие вкладки — close_tab, прокрутка — scroll. "
        "Выключение компьютера — только по явной просьбе пользователя. "
        'Пример: на «Какая погода в Киеве?» ответь {"tool": "get_weather", "arguments": {"city": "Киев"}}.'
    ),
    "en": (
        "You are a voice assistant answering in English, running on the user's computer. "
        "You can perform actions via tools: launch apps, open sites and search, type text, "
        "press keys, close tabs, take screenshots, set timers, report time and system state. "
        "Pick a tool when needed; otherwise reply briefly and friendly. "
        "Always use tools for time, date and system state, never answer from memory. "
        "Always fetch weather with the get_weather tool and speak it, never open weather sites. "
        "If the user named a city, pass it to get_weather. "
        "Typing into an input field - type_text, keys and shortcuts - press_key, "
        "closing a tab - close_tab, scrolling - scroll. "
        "Shutdown only on explicit user request. "
        'Example: for "What is the weather in Kyiv?" answer {"tool": "get_weather", "arguments": {"city": "Kyiv"}}.'
    ),
}

_DESC = {
    "open_app": ("запустить приложение или программу по имени или пути, params: name",
                 "launch an app or program by name or path, params: name"),
    "open_url": ("открыть сайт или поисковый запрос в браузере, params: query",
                 "open a website or a search query in the browser, params: query"),
    "type_text": ("напечатать текст в активном текстовом поле с клавиатуры, params: text",
                  "type text into the active text field using the keyboard, params: text"),
    "press_key": ("нажать клавишу или комбинацию клавиш, например: enter, esc, tab, ctrl+s, win+d, ctrl+w, params: keys",
                  "press a key or a key combination, e.g.: enter, esc, tab, ctrl+s, win+d, ctrl+w, params: keys"),
    "close_tab": ("закрыть активную вкладку в браузере, params: нет",
                  "close the active browser tab, params: none"),
    "new_tab": ("открыть новую вкладку в браузере, params: нет",
                "open a new browser tab, params: none"),
    "refresh_page": ("обновить страницу в браузере, params: нет",
                     "refresh the page in the browser, params: none"),
    "show_desktop": ("свернуть все окна и показать рабочий стол, params: нет",
                     "minimize all windows and show the desktop, params: none"),
    "scroll": ("прокрутить страницу, params: direction (вверх или вниз)",
               "scroll the page, params: direction (up or down)"),
    "screenshot": ("сделать скриншот экрана и сохранить его, params: нет",
                   "take a screenshot of the screen and save it, params: none"),
    "get_weather": ("узнать текущую погоду в городе и озвучить её, params: city (если город не назван — город пользователя)",
                    "get the current weather in a city and speak it, params: city (if no city given - the user's city)"),
    "set_timer": ("поставить таймер, params: minutes (число) и message (что напомнить)",
                  "set a timer, params: minutes (number) and message (what to remind)"),
    "get_time": ("сообщить текущее время и дату, params: нет",
                 "tell the current time and date, params: none"),
    "system_info": ("сообщить нагрузку на процессор, память и заряд батареи, params: нет",
                    "report CPU load, memory and battery level, params: none"),
    "open_folder": ("открыть папку в проводнике, params: path",
                    "open a folder in the file explorer, params: path"),
    "lock_screen": ("заблокировать экран, params: нет",
                    "lock the screen, params: none"),
    "shutdown": ("выключить компьютер (только по явной просьбе с подтверждением), params: confirm",
                 "shut down the computer (only on explicit request with confirmation), params: confirm"),
    "cancel_shutdown": ("отменить выключение компьютера, params: нет",
                        "cancel the computer shutdown, params: none"),
    "exit_assistant": ("завершить работу ассистента, params: нет",
                       "quit the assistant, params: none"),
}


def _build_tools(lang):
    tools = []
    for name, (fn, _desc) in REGISTRY.items():
        desc = _DESC.get(name, (_desc, _desc))[0 if lang == "ru" else 1]
        sig = inspect.signature(fn)
        props = {}
        required = []
        for pname, p in sig.parameters.items():
            ann = p.annotation
            ptype = "string"
            if ann is int:
                ptype = "integer"
            elif ann is bool:
                ptype = "boolean"
            elif ann is float:
                ptype = "number"
            props[pname] = {"type": ptype}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
        )
    return tools


def _tools(lang):
    if lang not in _tools_cache:
        _tools_cache[lang] = _build_tools(lang)
    return _tools_cache[lang]


def load():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                n_threads = max(2, (os.cpu_count() or 4) - 1)
                _model = Llama(
                    model_path=LLM_MODEL_PATH,
                    n_ctx=2048,
                    n_threads=n_threads,
                    n_batch=256,
                    verbose=False,
                )
    return _model


def _extract_tool_call(content):
    start = content.find("<tool_call>")
    if start == -1:
        return None
    end = content.find("</tool_call>", start)
    if end == -1:
        end = len(content)
    inner = content[start + len("<tool_call>") : end]
    for i, ch in enumerate(inner):
        if ch == "{":
            for j in range(len(inner) - 1, i, -1):
                if inner[j] != "}":
                    continue
                try:
                    data = json.loads(inner[i : j + 1])
                    if isinstance(data, dict) and "name" in data:
                        return {
                            "tool": data.get("name") or "",
                            "params": data.get("arguments") or {},
                        }
                except Exception:
                    continue
    return None


def ask(user_text, lang=None):
    lang = lang or i18n.get_language()
    out = load().create_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM[lang]},
            {"role": "user", "content": user_text},
        ],
        temperature=0.1,
        max_tokens=128,
        tools=_tools(lang),
    )
    msg = out["choices"][0]["message"]
    if msg.get("tool_calls"):
        call = msg["tool_calls"][0]["function"]
        try:
            params = json.loads(call.get("arguments") or "{}")
        except Exception:
            params = {}
        return {"tool": call.get("name") or "", "params": params}
    content = msg.get("content") or ""
    call = _extract_tool_call(content)
    if call:
        return call
    return {"reply": content}