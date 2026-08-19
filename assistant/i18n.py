import json
import os
from pathlib import Path

_DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "AtomAssistant"
SETTINGS_PATH = _DATA_DIR / "settings.json"

_lang = "ru"

WAKE_NAMES = {"ru": "атом", "en": "atom"}
LANG_LABELS = {"ru": "Русский", "en": "English"}


def load_settings():
    global _lang
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("language") in ("ru", "en"):
            _lang = data["language"]
    except Exception:
        pass


def save_settings():
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"language": _lang}, f, ensure_ascii=False)
    except Exception:
        pass


def set_language(lang):
    global _lang
    if lang in ("ru", "en"):
        _lang = lang
        save_settings()


def get_language():
    return _lang


def L(ru, en):
    return en if _lang == "en" else ru


def wake_name():
    return WAKE_NAMES.get(_lang, "атом")


def stt_language():
    return "en" if _lang == "en" else "ru"