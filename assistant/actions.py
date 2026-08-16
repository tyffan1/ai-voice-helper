import datetime
import inspect
import json
import os
import subprocess
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import psutil
from pynput import mouse
from pynput.keyboard import Controller, Key

from assistant import i18n, tts
from assistant.config import CITY
from assistant.i18n import L

_exit_event = threading.Event()


def _find_app(name):
    base_dirs = [
        Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    name_l = name.lower()
    for base in base_dirs:
        if not base.is_dir():
            continue
        for lnk in base.rglob("*.lnk"):
            if name_l in lnk.stem.lower():
                return str(lnk)
    where = subprocess.run(
        ["where.exe", name], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
    )
    if where.returncode == 0:
        return where.stdout.strip().splitlines()[0]
    return None


def open_app(name):
    name = name.strip().strip('"')
    if os.path.isfile(name):
        os.startfile(name)
        return L(f"Запускаю {name}", f"Launching {name}")
    target = _find_app(name)
    if target:
        os.startfile(target)
        return L(f"Запускаю {name}", f"Launching {name}")
    return L(
        f"Не нашёл приложение {name}. Скажите название как в меню Пуск",
        f"Could not find the app {name}. Say its name as it appears in the Start menu",
    )


def open_url(query):
    q = query.strip()
    if not q:
        return L("Нечего открывать", "Nothing to open")
    if "://" not in q and " " in q:
        q = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    elif "." not in q:
        q = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    elif "://" not in q:
        q = "https://" + q
    webbrowser.open(q)
    return L("Открыл в браузере", "Opened in the browser")


def type_text(text):
    kb = Controller()
    for ch in text:
        if ch == "\n":
            kb.press(Key.enter)
            kb.release(Key.enter)
        else:
            kb.type(ch)
    return L("Напечатал", "Typed")


_KEYS = {
    "enter": Key.enter, "return": Key.enter,
    "esc": Key.esc, "escape": Key.esc,
    "tab": Key.tab, "backspace": Key.backspace,
    "delete": Key.delete, "del": Key.delete,
    "space": Key.space,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "home": Key.home, "end": Key.end,
    "pageup": Key.page_up, "pagedown": Key.page_down,
    "ctrl": Key.ctrl, "control": Key.ctrl,
    "alt": Key.alt, "shift": Key.shift,
    "win": Key.cmd, "cmd": Key.cmd, "windows": Key.cmd,
}


def _press_combo(combo):
    kb = Controller()
    keys = []
    for part in combo.split("+"):
        p = part.strip().lower()
        if p in _KEYS:
            keys.append(_KEYS[p])
        elif len(p) == 1:
            keys.append(p)
        else:
            raise ValueError(f"unknown key: {p}")
    for k in keys:
        kb.press(k)
    for k in reversed(keys):
        kb.release(k)


def press_key(keys):
    try:
        _press_combo(keys)
    except Exception:
        return L(
            f"Не понимаю клавишу {keys}. Примеры: enter, esc, tab, ctrl+s, win+d",
            f"Cannot press {keys}. Examples: enter, esc, tab, ctrl+s, win+d",
        )
    return L(f"Нажал {keys}", f"Pressed {keys}")


def close_tab():
    _press_combo("ctrl+w")
    return L("Закрыл вкладку", "Closed the tab")


def new_tab():
    _press_combo("ctrl+t")
    return L("Открыл новую вкладку", "Opened a new tab")


def refresh_page():
    _press_combo("ctrl+r")
    return L("Обновил страницу", "Refreshed the page")


def show_desktop():
    _press_combo("win+d")
    return L("Свернул все окна", "Minimized all windows")


def scroll(direction):
    kb = mouse.Controller()
    d = (direction or "").lower()
    if "верх" in d or "up" in d:
        kb.scroll(0, 3)
        return L("Прокрутил вверх", "Scrolled up")
    kb.scroll(0, -3)
    return L("Прокрутил вниз", "Scrolled down")


def screenshot():
    from PIL import ImageGrab

    shots = Path(os.path.expanduser("~")) / "Pictures"
    shots.mkdir(exist_ok=True)
    path = shots / f"screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
    ImageGrab.grab().save(path)
    return L(f"Скриншот сохранён: {path}", f"Screenshot saved: {path}")


_WMO = {
    0: ("ясно", "clear"),
    1: ("преимущественно ясно", "mostly clear"),
    2: ("переменная облачность", "partly cloudy"),
    3: ("пасмурно", "overcast"),
    45: ("туман", "fog"),
    48: ("туман", "fog"),
    51: ("лёгкая морось", "light drizzle"),
    53: ("морось", "drizzle"),
    55: ("сильная морось", "heavy drizzle"),
    56: ("ледяная морось", "freezing drizzle"),
    57: ("сильная ледяная морось", "heavy freezing drizzle"),
    61: ("небольшой дождь", "light rain"),
    63: ("дождь", "rain"),
    65: ("сильный дождь", "heavy rain"),
    66: ("ледяной дождь", "freezing rain"),
    67: ("сильный ледяной дождь", "heavy freezing rain"),
    71: ("небольшой снег", "light snow"),
    73: ("снег", "snow"),
    75: ("сильный снег", "heavy snow"),
    77: ("снежная крупа", "snow grains"),
    80: ("небольшие ливни", "light showers"),
    81: ("ливни", "showers"),
    82: ("сильные ливни", "heavy showers"),
    85: ("снежные заряды", "snow showers"),
    86: ("сильные снежные заряды", "heavy snow showers"),
    95: ("гроза", "thunderstorm"),
    96: ("гроза с градом", "thunderstorm with hail"),
    99: ("сильная гроза с градом", "severe thunderstorm with hail"),
}

_MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def set_timer(minutes, message):
    minutes = max(0.1, float(minutes))
    threading.Timer(
        minutes * 60.0,
        lambda: tts.speak(message),
    ).start()
    return L(
        f"Поставил таймер на {minutes:g} минут",
        f"Timer set for {minutes:g} minutes",
    )


def get_time():
    now = datetime.datetime.now()
    if i18n.get_language() == "en":
        return f"It is {now.strftime('%H:%M')}, {now.day} {_MONTHS_EN[now.month - 1]} {now.year}"
    return f"Сейчас {now.strftime('%H:%M')}, {now.day} {_MONTHS_RU[now.month - 1]} {now.year} года"


def system_info():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    if i18n.get_language() == "en":
        parts = [f"CPU load is {cpu:.0f} percent", f"memory usage is {mem.percent:.0f} percent"]
    else:
        parts = [f"Загрузка процессора {cpu:.0f} процентов", f"память занята на {mem.percent:.0f} процентов"]
    try:
        batt = psutil.sensors_battery()
        if batt is not None:
            parts.append(L(
                f"заряд батареи {batt.percent:.0f} процентов",
                f"battery level is {batt.percent:.0f} percent",
            ))
    except Exception:
        pass
    return ", ".join(parts)


def open_folder(path):
    path = os.path.expandvars(os.path.expanduser(path))
    if os.path.isdir(path):
        os.startfile(path)
        return L(f"Открыл папку {path}", f"Opened folder {path}")
    return L(f"Папка не найдена: {path}", f"Folder not found: {path}")


def lock_screen():
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return L("Экран заблокирован", "Screen locked")


def shutdown(confirm=False):
    if not confirm:
        return L(
            "Точно выключить компьютер? Скажите: подтверждаю",
            "Shut down the computer? Say: confirm",
        )
    subprocess.Popen(["shutdown", "/s", "/t", "30"])
    return L(
        "Компьютер выключится через тридцать секунд",
        "The computer will shut down in thirty seconds",
    )


def cancel_shutdown():
    subprocess.Popen(["shutdown", "/a"])
    return L("Отменил выключение", "Shutdown cancelled")


def exit_assistant():
    _exit_event.set()
    return L("До встречи", "See you")


def get_weather(city=None):
    lang = i18n.get_language()
    city = (city or CITY).strip()
    try:
        geo = json.load(
            urllib.request.urlopen(
                "https://geocoding-api.open-meteo.com/v1/search"
                f"?name={urllib.parse.quote(city)}&count=1&language={lang}",
                timeout=10,
            )
        )
        results = geo.get("results") or []
        if not results:
            return L(f"Не нашёл город {city}", f"Could not find the city {city}")
        r = results[0]
        w = json.load(
            urllib.request.urlopen(
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={r['latitude']}&longitude={r['longitude']}"
                "&current=temperature_2m,apparent_temperature,wind_speed_10m,weather_code",
                timeout=10,
            )
        )
        cur = w["current"]
        name = r.get("name") or city
        desc = _WMO.get(cur["weather_code"], ("переменчивая погода", "changeable weather"))[0 if lang == "ru" else 1]
        if lang == "en":
            return (
                f"In {name} it is now {cur['temperature_2m']:.0f} degrees, {desc}, "
                f"feels like {cur['apparent_temperature']:.0f}, "
                f"wind {cur['wind_speed_10m']:.0f} meters per second"
            )
        return (
            f"В городе {name} сейчас {cur['temperature_2m']:.0f} градусов, {desc}, "
            f"ощущается как {cur['apparent_temperature']:.0f}, "
            f"ветер {cur['wind_speed_10m']:.0f} метров в секунду"
        )
    except Exception:
        return L(
            "Не удалось получить данные о погоде, проверьте интернет",
            "Could not get weather data, check your internet connection",
        )


REGISTRY = {
    "open_app": (open_app, "запустить приложение или программу по имени или пути, params: name"),
    "open_url": (open_url, "открыть сайт или поисковый запрос в браузере, params: query"),
    "type_text": (type_text, "напечатать текст в активном текстовом поле с клавиатуры, params: text"),
    "press_key": (press_key, "нажать клавишу или комбинацию клавиш, например: enter, esc, tab, ctrl+s, win+d, ctrl+w, params: keys"),
    "close_tab": (close_tab, "закрыть активную вкладку в браузере, params: нет"),
    "new_tab": (new_tab, "открыть новую вкладку в браузере, params: нет"),
    "refresh_page": (refresh_page, "обновить страницу в браузере, params: нет"),
    "show_desktop": (show_desktop, "свернуть все окна и показать рабочий стол, params: нет"),
    "scroll": (scroll, "прокрутить страницу, params: direction (вверх или вниз)"),
    "screenshot": (screenshot, "сделать скриншот экрана и сохранить его, params: нет"),
    "get_weather": (get_weather, "узнать текущую погоду в городе и озвучить её, params: city (если город не назван — город пользователя)"),
    "set_timer": (set_timer, "поставить таймер, params: minutes (число) и message (что напомнить)"),
    "get_time": (get_time, "сообщить текущее время и дату, params: нет"),
    "system_info": (system_info, "сообщить нагрузку на процессор, память и заряд батареи, params: нет"),
    "open_folder": (open_folder, "открыть папку в проводнике, params: path"),
    "lock_screen": (lock_screen, "заблокировать экран, params: нет"),
    "shutdown": (shutdown, "выключить компьютер (только по явной просьбе с подтверждением), params: confirm"),
    "cancel_shutdown": (cancel_shutdown, "отменить выключение компьютера, params: нет"),
    "exit_assistant": (exit_assistant, "завершить работу ассистента, params: нет"),
}


def execute(tool, params=None):
    fn = REGISTRY.get(tool)
    if fn is None:
        return L(f"Не знаю такого действия: {tool}", f"Unknown action: {tool}")
    params = params or {}
    sig = inspect.signature(fn[0])
    filtered = {k: v for k, v in params.items() if k in sig.parameters}
    return fn[0](**filtered)


def wait_exit(timeout=None):
    return _exit_event.wait(timeout)