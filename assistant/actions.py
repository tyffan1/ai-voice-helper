import datetime
import inspect
import os
import subprocess
import threading
import urllib.parse
import webbrowser

import psutil
from pynput.keyboard import Controller, Key

from assistant import tts

_exit_event = threading.Event()


def open_app(name):
    try:
        if os.path.isfile(name):
            os.startfile(name)
        else:
            subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
    except Exception:
        return f"Не получилось запустить {name}"
    return f"Запускаю {name}"


def open_url(query):
    q = query.strip()
    if not q:
        return "Нечего открывать"
    if "://" not in q and " " in q:
        q = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    elif "." not in q:
        q = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    elif "://" not in q:
        q = "https://" + q
    webbrowser.open(q)
    return "Открыл в браузере"


def type_text(text):
    kb = Controller()
    for ch in text:
        if ch == "\n":
            kb.press(Key.enter)
            kb.release(Key.enter)
        else:
            kb.type(ch)
    return "Напечатал"


def set_timer(minutes, message):
    minutes = max(0.1, float(minutes))
    threading.Timer(
        minutes * 60.0,
        lambda: tts.speak(f"Напоминание: {message}"),
    ).start()
    return f"Поставил таймер на {minutes:g} минут"


_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def get_time():
    now = datetime.datetime.now()
    return f"Сейчас {now.strftime('%H:%M')}, {now.day} {_MONTHS[now.month - 1]} {now.year} года"


def system_info():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    parts = [f"Загрузка процессора {cpu:.0f} процентов", f"память занята на {mem.percent:.0f} процентов"]
    try:
        batt = psutil.sensors_battery()
        if batt is not None:
            parts.append(f"заряд батареи {batt.percent:.0f} процентов")
    except Exception:
        pass
    return ", ".join(parts)


def open_folder(path):
    path = os.path.expandvars(os.path.expanduser(path))
    if os.path.isdir(path):
        os.startfile(path)
        return f"Открыл папку {path}"
    return f"Папка не найдена: {path}"


def lock_screen():
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "Экран заблокирован"


def shutdown(confirm=False):
    if not confirm:
        return "Точно выключить компьютер? Скажите: подтверждаю"
    subprocess.Popen(["shutdown", "/s", "/t", "30"])
    return "Компьютер выключится через тридцать секунд"


def cancel_shutdown():
    subprocess.Popen(["shutdown", "/a"])
    return "Отменил выключение"


def exit_assistant():
    _exit_event.set()
    return "До встречи"


REGISTRY = {
    "open_app": (open_app, "запустить приложение или программу по имени или пути, params: name"),
    "open_url": (open_url, "открыть сайт или поисковый запрос в браузере, params: query"),
    "type_text": (type_text, "напечатать текст с клавиатуры, params: text"),
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
        return f"Не знаю такого действия: {tool}"
    params = params or {}
    sig = inspect.signature(fn[0])
    filtered = {k: v for k, v in params.items() if k in sig.parameters}
    return fn[0](**filtered)


def wait_exit(timeout=None):
    return _exit_event.wait(timeout)
