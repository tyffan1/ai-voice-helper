import inspect
import json
import os
import threading

from llama_cpp import Llama

from assistant import i18n, memory
from assistant.actions import REGISTRY
from assistant.config import LLM_MODEL_PATH

_model = None
_lock = threading.Lock()
_tools_cache = {}

_SYSTEM = {
    "ru": (
        "Ты — голосовой ассистент на русском языке, работающий на компьютере пользователя. "
        "Выбирай инструмент, если он нужен; иначе отвечай кратко и дружелюбно. "
        "Говори живо и по-человечески: короткие фразы, разнообразь формулировки, "
        "не будь канцелярским, допустима лёгкая ирония, но без сарказма в адрес пользователя. "
        "Про время, дату и систему всегда используй инструменты, не отвечай по памяти. "
        "Погоду всегда получай инструментом get_weather и озвучивай её, никогда не открывай сайты с погодой. "
        "Если пользователь назвал город — передай его в get_weather. "
        "Выключение компьютера — только по явной просьбе пользователя. "
        "«Запусти/открой/включи + название» — всегда вызывай open_app или open_game, не отвечай просто текстом. "
        'Пример: на «Какая погода в Киеве?» ответь {"tool": "get_weather", "arguments": {"city": "Киев"}}.'
    ),
    "en": (
        "You are a voice assistant answering in English, running on the user's computer. "
        "Pick a tool when needed; otherwise reply briefly and friendly. "
        "Sound lively and human: short phrases, vary your wording, never sound robotic; "
        "light humor is fine, but no sarcasm toward the user. "
        "Always use tools for time, date and system state, never answer from memory. "
        "Always fetch weather with the get_weather tool and speak it, never open weather sites. "
        "If the user named a city, pass it to get_weather. "
        "Shutdown only on explicit user request. "
        "For 'open/launch/start <name>' always use the open_app or open_game tool, never reply with plain text. "
        'Example: for "What is the weather in Kyiv?" answer {"tool": "get_weather", "arguments": {"city": "Kyiv"}}.'
    ),
}

_DESC = {
    "open_app": ("запустить приложение или программу по имени или пути, params: name",
                 "launch an app or program by name or path, params: name"),
    "open_game": ("запустить игру (Steam, Game Pass или ярлык), params: name",
                  "launch a game (Steam, Game Pass or a shortcut), params: name"),
    "system_setting": ("изменить настройку системы: громкость, яркость, вайфай, блютуз, тема, разрешение экрана, экран, сон, перезагрузка, params: setting и value",
                       "change a system setting: volume, brightness, wifi, bluetooth, theme, screen resolution, display, sleep, restart, params: setting and value"),
    "web_search": ("найти информацию в интернете и вернуть ссылки, params: query",
                   "search the internet and return links, params: query"),
    "web_query": ("найти информацию в интернете, открыть лучший результат и вернуть его текст, params: query",
                  "search the internet, open the best result and return its text, params: query"),
    "open_url": ("открыть сайт или поисковый запрос в браузере, params: query",
                 "open a website or a search query in the browser, params: query"),
    "type_text": ("напечатать текст в активном текстовом поле с клавиатуры, params: text",
                  "type text into the active text field using the keyboard, params: text"),
    "press_key": ("нажать клавишу или комбинацию клавиш, например: enter, esc, tab, ctrl+s, win+d, ctrl+w, params: keys",
                  "press a key or a key combination, e.g.: enter, esc, tab, ctrl+s, win+d, ctrl+w, params: keys"),
    "close_tab": ("закрыть активную вкладку в браузере, params: нет",
                  "close the active browser tab, params: none"),
    "close_app": ("закрыть запущенное приложение или программу по имени, params: name",
                  "close a running application by name, params: name"),
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
    "get_currency": ("узнать курс валют, params: base (код или название валюты), quote (валюта, к которой курс) или value (например 'доллар к гривне')",
                     "get a currency exchange rate, params: base (currency code or name), quote (currency to compare) or value (e.g. 'dollar to hryvnia')"),
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
    "remember": ("запомнить факт о пользователе на будущее, params: fact (что запомнить)",
                 "remember a fact about the user for later, params: fact (what to remember)"),
    "forget": ("забыть ранее запомненный факт по ключевому слову, params: keyword",
               "forget a previously remembered fact by keyword, params: keyword"),
}


def _build_tools(lang, wanted=None):
    tools = []
    for name, (fn, _desc) in REGISTRY.items():
        if wanted is not None and name not in wanted:
            continue
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


_DEFAULT_TOOLS = frozenset(
    {"open_app", "open_game", "open_url", "type_text", "press_key", "get_time",
     "exit_assistant", "web_query", "web_search", "close_app"}
)

_KEYWORDS = {
    "get_weather": ["погод", "град", "дожд", "температур", "солнц", "ветер", "снег", "weather", "rain", "snow", "temperature"],
    "get_currency": ["курс", "доллар", "евро", "гривн", "рубл", "юан", "валюта", "биткоин", "bitcoin", "currency", "exchange", "rate"],
    "set_timer": ["таймер", "напомн", "timer", "remind", "через"],
    "screenshot": ["скриншот", "скрин", "экран", "снимок", "screenshot", "capture"],
    "system_info": ["процессор", "память", "батаре", "систем", "нагрузк", "cpu", "battery", "memory", "system", "заряд"],
    "shutdown": ["выключ", "выруб", "shutdown", "turn off"],
    "cancel_shutdown": ["отмен", "cancel", "не надо"],
    "lock_screen": ["блокировк", "заблокир", "lock"],
    "close_tab": ["вкладк", "закрой", "close", "tab"],
    "close_app": ["закрой", "закрыть", "закройте", "закрывай", "заверши", "выключи", "закройка", "приложени", "программ", "close", "quit", "exit"],
    "new_tab": ["новую вкладк", "new tab"],
    "refresh_page": ["обнов", "refresh", "reload"],
    "show_desktop": ["рабочий стол", "сверни", "desktop", "minimize"],
    "scroll": ["прокрут", "листа", "вниз", "вверх", "scroll"],
    "open_folder": ["папк", "проводник", "folder", "explorer"],
    "open_game": ["игр", "game", "steam", "поиграть", "гейм", "запусти", "запуск", "запускать", "стартуй", "launch", "start"],
    "system_setting": ["громк", "volume", "звук", "громче", "тише", "яркост", "brightness", "вайфай", "wi-fi", "wifi", "блютуз", "bluetooth", "тема", "тёмн", "темн", "светл", "theme", "экран", "монитор", "дисплей", "сон", "спать", "sleep", "перезагруз", "restart", "настройк", "settings", "разрешени", "resolution"],
    "web_query": ["найди", "поищи", "поиск", "узнай", "в интернете", "google", "гугл", "search", "что такое", "как сделать", "как приготовить", "рецепт", "новости", "переведи", "интернет", "web"],
    "remember": ["запомн", "сохран", "запиш", "не забудь", "памят", "remember", "save", "note", "запомнишь"],
    "forget": ["забудь", "забыт", "забывай", "forget", "забыла"],
}


def _tools(lang, user_text=""):
    wanted = set(_DEFAULT_TOOLS)
    text = (user_text or "").lower()
    for tool, kws in _KEYWORDS.items():
        if any(kw in text for kw in kws):
            wanted.add(tool)
    key = (lang, frozenset(wanted))
    if key not in _tools_cache:
        _tools_cache[key] = _build_tools(lang, wanted)
    return _tools_cache[key]


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
                    n_batch=512,
                    flash_attn=True,
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


def summarize(text, query, lang=None):
    lang = lang or i18n.get_language()
    if lang == "en":
        system = (
            "You are a voice assistant. Give a short, lively answer to the user's question "
            "based on the web text below: 1-3 sentences, meant to be read aloud. "
            "No headings or preamble — answer directly. "
            "If the text has the exact answer — give it with numbers and facts. "
            "If the request is about a recipe — list the main ingredients and briefly the cooking steps. "
            "If the text has no answer or is just a catalog/link list — "
            "honestly say the information is insufficient."
        )
        tmpl = "Question: {q}\n\nWeb text:\n{t}"
    else:
        system = (
            "Ты — голосовой ассистент. Дай короткий живой ответ на запрос пользователя "
            "на основе текста из интернета ниже: 1-3 предложения, для чтения вслух. "
            "Никаких заголовков и предисловий — сразу ответ. "
            "Если в тексте есть точный ответ — приведи его цифрами и фактами. "
            "Если запрос о рецепте — перечисли основные ингредиенты и кратко шаги приготовления. "
            "Если в тексте нет ответа или это только каталог/список ссылок — "
            "честно скажи, что информации недостаточно."
        )
        tmpl = "Запрос: {q}\n\nТекст из интернета:\n{t}"
    chunk = text[:2000]
    for _ in range(4):
        try:
            out = load().create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": tmpl.format(q=query, t=chunk)},
                ],
                temperature=0.3,
                max_tokens=160,
            )
            return (out["choices"][0]["message"].get("content") or "").strip() or text[:300]
        except ValueError:
            chunk = chunk[: len(chunk) // 2]
    return text[:300]


def ask(user_text, lang=None):
    lang = lang or i18n.get_language()
    system = _SYSTEM[lang]
    extra = memory.profile_text(lang)
    if extra:
        system = system + "\n" + extra
    out = load().create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        temperature=0.1,
        max_tokens=128,
        tools=_tools(lang, user_text),
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