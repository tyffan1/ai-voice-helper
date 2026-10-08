"""Зрение Атома — два слоя.

Офлайн (всегда): accessibility-дерево Windows (UIA) — находит кнопки,
пункты меню, вкладки и закладки браузера ПО НАЗВАНИЮ и кликает в их центр.
Без новой модели, быстро, детерминированно.

Облако (если задан ASSISTANT_API_KEY): VLM смотрит на скриншот —
понимает «вон та красная кнопка» и возвращает координаты.
"""

import tempfile
from pathlib import Path

from assistant.i18n import L

_SHOT_NAME = "atom_screen.jpg"

# Мусорные слова вокруг сути: «кликни на ИКОНКУ ютуба» -> «ютуба».
_STOPWORDS = frozenset({
    "нажми", "нажать", "кликни", "кликнуть", "щёлкни", "на", "по", "в", "этот",
    "эту", "это", "иконку", "иконка", "иконке", "кнопку", "кнопка", "кнопке",
    "закладку", "закладка", "закладке", "вкладку", "вкладка", "вкладке",
    "пункт", "меню", "ссылку", "ссылка", "ярлык",
    "click", "press", "the", "a", "button", "icon", "bookmark", "tab", "link",
})

# Частые русские названия -> как подписано в интерфейсе.
_NAME_ALIASES = {
    "ютуб": "youtube", "ютуба": "youtube", "ютубе": "youtube", "ютубчик": "youtube",
    "гугл": "google", "гугле": "google",
    "телеграм": "telegram", "телегу": "telegram", "телега": "telegram",
    "дискорд": "discord", "дискорде": "discord",
    "почта": "mail", "почту": "mail",
    "карты": "maps", "карту": "maps",
}


def _candidates(name):
    """Варианты для подстрочного поиска: суть без мусора + алиасы + оригинал."""
    import re

    raw = (name or "").strip().strip('"').lower()
    if not raw:
        return []
    words = re.findall(r"[a-zа-яё0-9]+", raw)
    core_words = [w for w in words if w not in _STOPWORDS]
    cands = []
    if core_words:
        core = " ".join(core_words)
        mapped = " ".join(_NAME_ALIASES.get(w, w) for w in core_words)
        # ютуба -> youtube: сравнить основу без окончания
        stems = []
        for w in core_words:
            stems.append(_NAME_ALIASES.get(w, _NAME_ALIASES.get(w[:4], w)))
        stemmed = " ".join(stems)
        for c in (mapped, stemmed, core):
            if c and c not in cands:
                cands.append(c)
    if raw not in cands:
        cands.append(raw)
    return cands


def take_shot(max_w=1280):
    """Скриншот во временный файл (не захламляет Картинки). Вернуть (путь, (w, h))."""
    from PIL import ImageGrab

    img = ImageGrab.grab()
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)))
    path = Path(tempfile.gettempdir()) / _SHOT_NAME
    img.convert("RGB").save(path, "JPEG", quality=70)
    return path, img.size


def _uia_find(name, timeout=8):
    """Найти элемент по подстроке названия через UIA. Вернуть (x, y, title) или None."""
    try:
        from pywinauto import Desktop
    except Exception:
        return None
    queries = _candidates(name)
    if not queries:
        return None
    import time

    deadline = time.time() + timeout
    for query in queries:
        best = None
        try:
            desktop = Desktop(backend="uia")
            wins = desktop.windows(top_level_only=True, visible_only=True)
        except Exception:
            return None
        for win in wins:
            if time.time() > deadline:
                break
            try:
                title = (win.window_text() or "").strip()
            except Exception:
                continue
            if not title:
                continue
            # 1. само окно подходит
            if query in title.lower():
                try:
                    r = win.rectangle()
                    return (r.left + r.right) // 2, (r.top + r.bottom) // 2, title
                except Exception:
                    pass
            # 2. ищем внутри окна
            try:
                elems = win.descendants()
            except Exception:
                continue
            for el in elems:
                if time.time() > deadline:
                    break
                try:
                    t = (el.window_text() or "").strip()
                except Exception:
                    continue
                if t and query in t.lower():
                    try:
                        r = el.rectangle()
                        cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
                    except Exception:
                        continue
                    # мелкий и осмысленный элемент лучше огромного контейнера
                    score = len(t)
                    if best is None or score < best[3]:
                        best = (cx, cy, t, score)
            if best and best[3] <= max(8, len(query) + 4):
                break
        if best is not None:
            return best[0], best[1], best[2]
    return None


def describe_screen():
    """Что сейчас на экране. Cloud: смотрит VLM. Офлайн: активное окно + список окон."""
    from assistant import computer, models_router

    if models_router.cloud_enabled():
        try:
            return models_router.vision_describe()
        except Exception:
            pass
    info = computer.screen_info()
    wins = computer.list_windows()
    if L("а", "b") == "а":
        return (
            f"{info}\n{wins}\n"
            "Офлайн вижу только названия окон, а не картинку. "
            "Для понимания картинок задайте ASSISTANT_API_KEY — подключится облачное зрение."
        )
    return (
        f"{info}\n{wins}\n"
        "Offline I only see window titles, not the picture. "
        "Set ASSISTANT_API_KEY to enable cloud vision."
    )


def click_element(name):
    """Кликнуть по элементу с таким текстом: закладка, кнопка, вкладка..."""
    from assistant import computer, models_router

    name = (name or "").strip().strip('"')
    if not name:
        return L("Какой элемент нажать?", "Which element should I click?")
    hit = _uia_find(name)
    if hit:
        x, y, title = hit
        computer.mouse_click(x, y)
        return L(f"Нажал «{title}»", f"Clicked \"{title}\"")
    if models_router.cloud_enabled():
        try:
            x, y = models_router.vision_locate(name)
            computer.mouse_click(x, y)
            return L(f"Нажал по координатам {x}, {y}", f"Clicked at {x}, {y}")
        except Exception:
            pass
    if L("а", "b") == "а":
        return (
            f"Не нашёл элемент «{name}». Вижу только названия окон — "
            "назовите точнее (как подписано на экране) или задайте ASSISTANT_API_KEY для зрения по картинке."
        )
    return (
        f"Could not find \"{name}\". I only see window titles — "
        "name it exactly as labeled, or set ASSISTANT_API_KEY for image vision."
    )
