import json
import os
import re
import threading
from pathlib import Path

from assistant.i18n import L

_DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "AtomAssistant"
_PATH = _DATA_DIR / "profile.json"
_lock = threading.Lock()
_profile = None
_MAX_FACTS = 50


def _load():
    global _profile
    if _profile is None:
        with _lock:
            if _profile is None:
                try:
                    _profile = json.loads(_PATH.read_text(encoding="utf-8"))
                except Exception:
                    _profile = {}
                if not isinstance(_profile, dict):
                    _profile = {}
                if not isinstance(_profile.get("facts"), list):
                    _profile["facts"] = []
                if not isinstance(_profile.get("commands"), list):
                    _profile["commands"] = []
    return _profile


def _save():
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(_load(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _clean(value):
    return re.sub(r"[.?!,;\"']+$", "", (value or "").strip())


def get_name():
    return _clean(_load().get("name"))


def set_name(name):
    name = _clean(name)[:40]
    if not name:
        return False
    _load()["name"] = name
    _save()
    return True


def get_city():
    return _clean(_load().get("city"))


_CITY_NOMINATIVE = {
    "москве": "Москва", "казани": "Казань", "твери": "Тверь", "самаре": "Самара",
    "уфе": "Уфа", "одессе": "Одесса", "ростове": "Ростов-на-Дону",
    "петербурге": "Санкт-Петербург", "питере": "Санкт-Петербург",
    "новосибирске": "Новосибирск", "екатеринбурге": "Екатеринбург",
    "нижнем новгороде": "Нижний Новгород", "краснодаре": "Краснодар",
    "калининграде": "Калининград", "минске": "Минск", "киеве": "Киев",
    "львове": "Львов", "харькове": "Харьков", "варшаве": "Варшава",
    "берлине": "Берлин", "париже": "Париж", "лондоне": "Лондон",
    "кишиневе": "Кишинёв", "астане": "Астана", "шымкенте": "Шымкент",
}


def normalize_city(city):
    c = _clean(city)
    low = c.lower()
    if low in _CITY_NOMINATIVE:
        return _CITY_NOMINATIVE[low]
    if low.endswith("е") and len(low) > 4:
        c = c[:-1]
    return c[:1].upper() + c[1:] if c else c


def set_city(city):
    city = normalize_city(city)[:60]
    if not city:
        return False
    _load()["city"] = city
    _save()
    return True


def get_facts():
    return [f for f in (_load().get("facts") or []) if isinstance(f, str) and f.strip()]


def add_fact(fact):
    fact = _clean(fact)
    if not fact:
        return False
    facts = _load().setdefault("facts", [])
    low = fact.lower()
    for f in facts:
        if f.lower() == low:
            return True
    facts.append(fact)
    if len(facts) > _MAX_FACTS:
        del facts[: len(facts) - _MAX_FACTS]
    _save()
    return True


def forget_fact(keyword):
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    facts = _load().setdefault("facts", [])
    kept = [f for f in facts if kw not in f.lower()]
    removed = len(kept) != len(facts)
    if removed:
        _load()["facts"] = kept
        _save()
    return removed


def _norm_words(value):
    return re.findall(r"[a-zа-яё0-9]+", (value or "").lower())


def get_commands():
    return [
        c
        for c in (_load().get("commands") or [])
        if isinstance(c, dict) and c.get("trigger") and c.get("action")
    ]


def add_command(trigger, action):
    trigger = _clean(trigger)
    action = _clean(action)
    if not trigger or not action:
        return False
    cmds = _load().setdefault("commands", [])
    low = trigger.lower()
    for c in cmds:
        if c["trigger"].lower() == low:
            c["action"] = action
            _save()
            return True
    cmds.append({"trigger": trigger, "action": action})
    if len(cmds) > 30:
        del cmds[: len(cmds) - 30]
    _save()
    return True


def _match_words(a, b):
    if len(a) < 3 or len(b) < 3:
        return a == b
    return a == b or a.startswith(b) or b.startswith(a)


def find_command(text):
    tw = _norm_words(text)
    if not tw:
        return None
    tj = " ".join(tw)
    for cmd in get_commands():
        cw = _norm_words(cmd["trigger"])
        if not cw:
            continue
        if len(cw) >= 2:
            if all(any(_match_words(w, t) for t in tw) for w in cw):
                return cmd
        elif any(_match_words(cw[0], t) for t in tw):
            return cmd
        if " ".join(cw) in tj:
            return cmd
    return None


def forget_command(keyword):
    kw = _norm_words(keyword)
    if not kw:
        return False
    cmds = _load().setdefault("commands", [])
    kept = [c for c in cmds if not any(w in _norm_words(c["trigger"]) for w in kw)]
    removed = len(kept) != len(cmds)
    if removed:
        _load()["commands"] = kept
        _save()
    return removed


def profile_text(lang="ru"):
    parts = []
    name = get_name()
    if name:
        if lang == "en":
            parts.append(f"Address the user by their name «{name}». If asked what their name is, say this name.")
        else:
            parts.append(f"Обращайся к пользователю по имени «{name}». Если спросят, как зовут пользователя, назови это имя.")
    city = get_city()
    if city:
        if lang == "en":
            parts.append(f"The user's city is {city}.")
        else:
            parts.append(f"Город пользователя: {city}.")
    facts = get_facts()
    if facts:
        shown = "; ".join(facts[-20:])
        if lang == "en":
            parts.append(f"What you know about the user: {shown}.")
        else:
            parts.append(f"Что ты знаешь о пользователе: {shown}.")
    cmds = get_commands()
    if cmds:
        shown = "; ".join(f"«{c['trigger']}» -> {c['action']}" for c in cmds[-15:])
        if lang == "en":
            parts.append(f"User-defined commands: {shown}.")
        else:
            parts.append(f"Пользовательские команды: {shown}.")
    return "\n".join(parts)


def describe(lang="ru"):
    parts = []
    name = get_name()
    city = get_city()
    facts = get_facts()
    if name:
        parts.append(L(f"Тебя зовут {name}", f"Your name is {name}"))
    if city:
        parts.append(L(f"Твой город — {city}", f"Your city is {city}"))
    if facts:
        if lang == "en":
            parts.append(f"I remember: {'; '.join(facts)}")
        else:
            parts.append(f"Помню, что {'; '.join(facts)}")
    cmds = get_commands()
    if cmds:
        shown = "; ".join(
            f"когда «{c['trigger']}» — {c['action']}" for c in cmds
        )
        if lang == "en":
            parts.append(f"I follow these commands: {shown}")
        else:
            parts.append(f"Выполняю: {shown}")
    return parts