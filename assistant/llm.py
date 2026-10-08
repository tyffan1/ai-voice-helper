import inspect
import json
import os
import re
import threading

from llama_cpp import Llama

from assistant import i18n, memory
from assistant.actions import REGISTRY
from assistant.config import LLM_MODEL_PATH

_model = None
_lock = threading.Lock()
_tools_cache = {}

# Иероглифы и fullwidth-знаки: Qwen иногда протекает китайским.
_CJK_CLASS = "\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002a6df\uff00-\uffef"
_CJK_ANY = re.compile("[" + _CJK_CLASS + "]")
_CJK_SPLIT = re.compile("[" + _CJK_CLASS + "]")

# Болтающиеся хвосты после обрезки: «спасибо за» -> «спасибо».
_DANGLE = frozenset({
    "за", "на", "в", "во", "с", "со", "к", "о", "об", "от", "до", "из", "у",
    "и", "а", "но", "что", "как", "это", "так", "вот", "же", "ли", "бы", "не",
    "for", "in", "on", "at", "to", "of", "from", "and", "or", "the", "a", "an",
})


def clean_reply(text, lang=None):
    """Обрезать ответ по первому иероглифу и подчистить хвост."""
    lang = lang or i18n.get_language()
    text = (text or "").strip()
    if _CJK_ANY.search(text):
        head = _CJK_SPLIT.split(text, maxsplit=1)[0].strip()
        words = head.split()
        while words and words[-1].strip(".,;:!?—-«»\"'").lower() in _DANGLE:
            words.pop()
        text = " ".join(words).strip(" .,;:!?—-«»\"'")
    else:
        text = re.sub(r"\s{2,}", " ", text).strip()
    if text:
        return text
    if lang == "en":
        return "I'm not sure, please rephrase."
    return "Затрудняюсь ответить, спросите иначе."

_SYSTEM = {
    "ru": (
        "Ты — голосовой ассистент Атом, работающий на компьютере пользователя. "
        "Отвечай СТРОГО на русском языке, никогда не используй китайские иероглифы. "
        "Ты полноценный ИИ-агент: можешь выполнять цепочки действий за несколько шагов. "
        "После каждого действия тебе покажут его результат — используй его для следующего шага, "
        "а в конце дай короткий итог голосом. "
        "Выбирай инструмент, если он нужен; иначе отвечай кратко и дружелюбно. "
        "Говори живо и по-человечески: короткие фразы, разнообразь формулировки. "
        "Перед кликами мышью ВСЕГДА сначала вызови screen_info, чтобы узнать размер экрана. "
        "Клик по НАЗВАННОМУ элементу (кнопка, закладка, вкладка) — это click_element, "
        "а не координаты. mouse_click — только когда знаешь точные x, y. "
        "Опасные действия (delete_file, run_shell, run_python) вызывай ТОЛЬКО с confirm=true "
        "и только после явного согласия пользователя — иначе просто спроси подтверждение текстом. "
        "НИКОГДА не ставь confirm=true сам: подтверждение даёт только пользователь. "
        "run_shell — только для команд, которые сами завершаются и печатают вывод "
        "(dir, echo, git status...). Голый cmd.exe или powershell без команды запрещён. "
        "«Открой терминал/консоль» — это open_app, а не run_shell. "
        "Про время, дату и систему всегда используй инструменты, не отвечай по памяти. "
        "Погоду всегда получай инструментом get_weather и озвучивай её, никогда не открывай сайты с погодой. "
        "Если пользователь назвал город — передай его в get_weather. "
        "Выключение компьютера — только по явной просьбе пользователя. "
        "«Запусти/открой/включи + название» — всегда вызывай open_app или open_game, не отвечай просто текстом. "
        'Пример: на «Какая погода в Киеве?» ответь {"tool": "get_weather", "arguments": {"city": "Киев"}}.'
    ),
    "en": (
        "You are Atom, a voice assistant running on the user's computer. "
        "Answer STRICTLY in English, never use Chinese characters. "
        "You are a full AI agent: you can do multi-step chains of actions. "
        "After each action you will see its result — use it for the next step, "
        "then give a short spoken summary. "
        "Pick a tool when needed; otherwise reply briefly and friendly. "
        "Before any mouse click ALWAYS call screen_info first to learn the screen size. "
        "Clicking a NAMED element (button, bookmark, tab) means click_element, "
        "not coordinates. mouse_click is only for exact known x, y. "
        "Dangerous actions (delete_file, run_shell, run_python) ONLY with confirm=true "
        "and only after explicit user approval — otherwise just ask for confirmation in text. "
        "NEVER set confirm=true yourself: only the user confirms. "
        "run_shell is only for commands that finish by themselves and print output "
        "(dir, echo, git status...). Bare cmd.exe or powershell without a command is forbidden. "
        "'Open terminal/console' means open_app, not run_shell. "
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
    "screen_info": ("узнать размер экрана и активное окно перед кликами, params: нет",
                    "get screen size and the active window before clicking, params: none"),
    "mouse_move": ("переместить курсор мыши в точку экрана, params: x, y (пиксели)",
                   "move the mouse cursor to a screen point, params: x, y (pixels)"),
    "mouse_click": ("кликнуть мышью в точке экрана, params: x, y, button (left/right/middle)",
                    "click at a screen point, params: x, y, button (left/right/middle)"),
    "double_click": ("двойной клик в точке экрана, params: x, y",
                     "double-click at a screen point, params: x, y"),
    "right_click": ("правый клик в точке экрана (контекстное меню), params: x, y",
                    "right-click at a screen point (context menu), params: x, y"),
    "mouse_drag": ("перетащить мышью из одной точки в другую, params: x1, y1, x2, y2",
                   "drag the mouse from one point to another, params: x1, y1, x2, y2"),
    "list_windows": ("показать список открытых окон с заголовками, params: нет",
                     "list open windows with titles, params: none"),
    "focus_window": ("показать и активировать окно по части заголовка, params: title",
                     "bring a window to front by part of its title, params: title"),
    "active_window": ("назвать активное окно, params: нет",
                      "name the active window, params: none"),
    "read_file": ("прочитать текстовый файл, params: path",
                  "read a text file, params: path"),
    "write_file": ("записать текст в файл (перезапись или дописать), params: path, content, mode (overwrite/append)",
                   "write text to a file, params: path, content, mode (overwrite/append)"),
    "list_dir": ("показать содержимое папки, params: path",
                 "list a folder's contents, params: path"),
    "delete_file": ("удалить файл или папку — ТОЛЬКО с confirm=true и после вопроса пользователю, params: path, confirm",
                    "delete a file or folder — ONLY with confirm=true after asking the user, params: path, confirm"),
    "run_shell": ("выполнить команду CMD/PowerShell и вернуть вывод — опасные команды ТОЛЬКО с confirm=true, params: command, confirm",
                  "run a CMD/PowerShell command and return output — dangerous ones ONLY with confirm=true, params: command, confirm"),
    "run_python": ("выполнить Python-код и вернуть вывод — ТОЛЬКО с confirm=true, params: code, confirm",
                   "run Python code and return output — ONLY with confirm=true, params: code, confirm"),
    "describe_screen": ("описать, что сейчас на экране (окна; с облаком — картинка), params: нет",
                        "describe what is on the screen now, params: none"),
    "click_element": ("кликнуть по элементу интерфейса с таким текстом — кнопка, закладка, вкладка, params: name",
                      "click an interface element with this text — button, bookmark, tab, params: name"),
    "system_setting": ("изменить настройку системы, params: setting и value. Доступные настройки: volume (громкость 0-100, up, down, mute), brightness (яркость 0-100), wifi (вкл/выкл), bluetooth (вкл/выкл), theme (тёмная/светлая тема), accent (цвет акцента: красный, синий и т.д. или hex), wallpaper (обои: путь к картинке или имя файла в Картинках), resolution (разрешение экрана, например 1920x1080 или max), display (погасить экран), sleep (сон сейчас), power_plan (план питания: сбалансированный, производительность, энергосбережение), sleep_timeout/monitor_timeout/hibernate_timeout (таймаут в минутах), hidden (показывать скрытые файлы), extensions (показывать расширения файлов), taskbar_autohide (автопрятие панели задач), mouse_speed (1-20), keyboard_delay (0-3), keyboard_speed (0-31), time_format (24 или 12 часов), time (установить время на компьютере, value например '16:53' или '16 часов 53 минуты'), date (установить дату, value например '20 августа 2026'), screensaver (заставка: выключить или имя/путь), game_mode (режим игры), clock_seconds (секунды на часах), autostart (автозагрузка приложения: название и вкл/выкл), restart (перезагрузка, value=confirm)",
                       "change a system setting, params: setting and value. Available settings: volume (0-100, up, down, mute), brightness (0-100), wifi (on/off), bluetooth (on/off), theme (dark/light), accent (accent color: red, blue etc. or hex), wallpaper (path or file name in Pictures), resolution (e.g. 1920x1080 or max), display (turn off screen), sleep (sleep now), power_plan (balanced, performance, saver), sleep_timeout/monitor_timeout/hibernate_timeout (timeout in minutes), hidden (show hidden files), extensions (show file extensions), taskbar_autohide (on/off), mouse_speed (1-20), keyboard_delay (0-3), keyboard_speed (0-31), time_format (24 or 12 hours), time (set the system clock, value e.g. '16:53'), date (set the system date, value e.g. '20 August 2026'), screensaver (off or name/path), game_mode (on/off), clock_seconds (on/off), autostart (app autostart: name and on/off), restart (value=confirm)"),
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
     "exit_assistant", "web_query", "web_search", "close_app",
     "screen_info", "list_windows", "list_dir", "read_file"}
)

_KEYWORDS = {
    "get_weather": ["погод", "град", "дожд", "температур", "солнц", "ветер", "снег", "weather", "rain", "snow", "temperature"],
    "get_currency": ["курс", "доллар", "евро", "гривн", "рубл", "юан", "валюта", "биткоин", "bitcoin", "currency", "exchange", "rate"],
    "set_timer": ["таймер", "напомн", "timer", "remind", "через"],
    "screenshot": ["скриншот", "скрин", "экран", "снимок", "screenshot", "capture"],
    "screen_info": ["экран", "разрешение", "screen", "клик", "кликни", "нажми", "кнопк", "click"],
    "mouse_click": ["клик", "кликни", "нажми", "щёлкни", "click", "на кнопку"],
    "mouse_move": ["курсор", "наведи", "мышь", "mouse", "cursor"],
    "mouse_drag": ["перетащи", "drag", "потяни"],
    "list_windows": ["окна", "окно", "windows", "покажи окна", "какие окна"],
    "focus_window": ["покажи окно", "активируй окно", "focus", "переключись на"],
    "active_window": ["активно", "какое окно", "active window"],
    "read_file": ["прочитай файл", "покажи файл", "read file", "открой файл", "содержимое файла"],
    "write_file": ["запиши", "сохрани в файл", "write file", "создай файл"],
    "list_dir": ["папки", "содержимое", "list", "файлы в", "что в папке"],
    "delete_file": ["удали", "удалить", "delete", "сотри"],
    "run_shell": ["команду", "терминал", "консоль", "запусти команду", "run command", "shell", "cmd", "powershell"],
    "run_python": ["питон", "python", "скрипт", "выполни код", "запусти скрипт"],
    "describe_screen": ["на экране", "что там", "что открыто", "опиши экран", "посмотри на экран",
                        "on screen", "describe screen", "what is open"],
    "click_element": ["нажми кнопку", "нажми на", "кликни по", "на элемент", "закладк", "вкладку",
                      "click the", "press the", "bookmark", "tab"],
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
    "system_setting": ["громк", "volume", "звук", "громче", "тише", "яркост", "brightness", "вайфай", "wi-fi", "wifi", "блютуз", "bluetooth", "тема", "тёмн", "темн", "светл", "theme", "экран", "монитор", "дисплей", "сон", "спать", "sleep", "перезагруз", "restart", "настройк", "settings", "разрешени", "resolution", "обои", "wallpaper", "фон", "план питания", "power plan", "питание", "таймаут", "засыпа", "гаснет", "скрыт", "hidden", "расширен", "панель задач", "taskbar", "автопрят", "мыш", "mouse", "клавиатур", "keyboard", "повтор клавиш", "акцент", "accent", "формат времени", "время 24", "24 часа", "12 часов", "заставка", "screensaver", "режим игры", "игровой режим", "game mode", "gamemode", "секунды на часах", "автозагруз", "автозапуск", "startup", "установи время", "поменяй время", "поставь время", "смени время", "измени время", "переведи время", "исправь время", "выставь время", "время на компьютере", "переведи часы", "поставь часы", "установи дату", "поменяй дату", "поставь дату", "смени дату", "set the time", "change the time", "set time", "change time", "set date", "change date", "set the date"],
    "web_query": ["найди", "поищи", "поиск", "узнай", "в интернете", "google", "гугл", "search", "что такое", "как сделать", "как приготовить", "рецепт", "новости", "переведи", "интернет", "web"],
    "remember": ["запомн", "сохран", "запиш", "не забудь", "памят", "remember", "save", "note", "запомнишь"],
    "forget": ["забудь", "забыт", "забывай", "forget", "забыла"],
}


def _tools(lang, user_text="", history=None):
    wanted = set(_DEFAULT_TOOLS)
    texts = [(user_text or "").lower()]
    for _t, _p, _r in (history or [])[-3:]:
        texts.append(f"{_t} {_p} {_r}".lower()[:500])
    text = " ".join(texts)
    for tool, kws in _KEYWORDS.items():
        if any(kw in text for kw in kws):
            wanted.add(tool)
    # раз агент в multi-step — на 2+ шаге даём все инструменты чтения/экрана
    if history:
        wanted.update({"screen_info", "list_windows", "read_file", "list_dir",
                       "mouse_click", "focus_window", "active_window"})
    key = (lang, frozenset(wanted))
    if key not in _tools_cache:
        _tools_cache[key] = _build_tools(lang, wanted)
    return _tools_cache[key]


def system_prompt(lang=None):
    lang = lang or i18n.get_language()
    system = _SYSTEM[lang]
    extra = memory.profile_text(lang)
    if extra:
        system = system + "\n" + extra
    return system


def tools_for(lang=None, user_text="", history=None):
    lang = lang or i18n.get_language()
    return _tools(lang, user_text, history)


def load():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                n_threads = max(2, (os.cpu_count() or 4) - 1)
                _model = Llama(
                    model_path=LLM_MODEL_PATH,
                    n_ctx=4096,
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
            return clean_reply(
                (out["choices"][0]["message"].get("content") or "").strip() or text[:300],
                lang,
            )
        except ValueError:
            chunk = chunk[: len(chunk) // 2]
    return text[:300]


def ask(user_text, lang=None):
    return ask_with_history(user_text, [], lang=lang)


def ask_with_history(user_text, history=None, lang=None):
    lang = lang or i18n.get_language()
    system = system_prompt(lang)
    messages = [{"role": "system", "content": system}]
    messages.append({"role": "user", "content": user_text})
    for tool, params, result in (history or [])[-4:]:
        messages.append({
            "role": "assistant",
            "content": f"<tool_call>{json.dumps({'name': tool, 'arguments': params}, ensure_ascii=False)}</tool_call>",
        })
        messages.append({
            "role": "user",
            "content": f"Результат {tool}: {str(result)[:1200]}",
        })
    out = load().create_chat_completion(
        messages=messages,
        temperature=0.1,
        max_tokens=256,
        tools=_tools(lang, user_text, history),
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
    return {"reply": clean_reply(content, lang)}
