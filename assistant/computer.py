"""Низкоуровневое управление компьютером: мышь, окна, экран.

Без новых зависимостей: pynput (уже есть) + ctypes + PIL.
Координаты — в пикселях от левого верхнего угла основного экрана.
LLM всегда должен сначала вызвать screen_info, чтобы узнать размер.
"""

import ctypes
from ctypes import wintypes

from pynput.mouse import Button, Controller

from assistant.i18n import L

_mouse = None


def _m():
    global _mouse
    if _mouse is None:
        _mouse = Controller()
    return _mouse


def screen_info():
    """Размер экрана + активное окно. Всегда safe, агент вызывает первым."""
    try:
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
    except Exception:
        w, h = 1920, 1080
    title = active_window()
    if L("", "") == "" and False:
        pass
    from assistant.i18n import get_language
    if get_language() == "en":
        return f"Screen: {w}x{h}. Active window: {title or 'unknown'}"
    return f"Экран: {w}x{h}. Активное окно: {title or 'неизвестно'}"


def _clamp(x, y):
    try:
        user32 = ctypes.windll.user32
        w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return max(0, min(int(x), w - 1)), max(0, min(int(y), h - 1))
    except Exception:
        return int(x), int(y)


def mouse_move(x, y):
    x, y = _clamp(x, y)
    _m().position = (x, y)
    return L(f"Курсор на {x}, {y}", f"Cursor moved to {x}, {y}")


def mouse_click(x, y, button="left"):
    x, y = _clamp(x, y)
    m = _m()
    m.position = (x, y)
    btn = {"left": Button.left, "right": Button.right, "middle": Button.middle}.get(
        str(button).lower(), Button.left
    )
    m.click(btn, 1)
    return L(f"Клик {button} на {x}, {y}", f"{button} click at {x}, {y}")


def double_click(x, y):
    x, y = _clamp(x, y)
    m = _m()
    m.position = (x, y)
    m.click(Button.left, 2)
    return L(f"Двойной клик на {x}, {y}", f"Double click at {x}, {y}")


def right_click(x, y):
    return mouse_click(x, y, "right")


def mouse_drag(x1, y1, x2, y2):
    x1, y1 = _clamp(x1, y1)
    x2, y2 = _clamp(x2, y2)
    m = _m()
    m.position = (x1, y1)
    m.press(Button.left)
    m.position = (x2, y2)
    m.release(Button.left)
    return L(f"Перетащил с {x1},{y1} на {x2},{y2}", f"Dragged from {x1},{y1} to {x2},{y2}")


def _window_text(hwnd):
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or ""


def active_window():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        return _window_text(hwnd)
    except Exception:
        return ""


def list_windows():
    user32 = ctypes.windll.user32
    titles = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = _window_text(hwnd)
            if title and len(title.strip()) >= 2:
                titles.append(title.strip())
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_enum, 0)
    except Exception:
        pass
    seen, out = set(), []
    for t in titles:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= 20:
            break
    if not out:
        return L("Нет видимых окон", "No visible windows")
    if L("а", "b") == "а":
        return "Окна:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(out))
    return "Windows:\n" + "\n".join(f"{i + 1}. {t}" for i, t in enumerate(out))


def focus_window(title):
    title = (title or "").strip().lower()
    if not title:
        return L("Какое окно показать?", "Which window should I focus?")
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _):
        try:
            t = _window_text(hwnd)
            if t and title in t.lower():
                found.append((hwnd, t))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_enum, 0)
    except Exception:
        pass
    if not found:
        return L(f"Не нашёл окно {title}", f"Could not find window {title}")
    hwnd, name = found[0]
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    return L(f"Показал окно {name}", f"Focused window {name}")
