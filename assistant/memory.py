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
    return parts