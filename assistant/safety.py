"""Уровни риска действий Атома.

SAFE   — выполняется сразу, без спроса (чтение, справка, скриншот).
MEDIUM — выполняется сразу, но логируется (открыть app/url, печать, клик, громкость...).
DANGER — только с явным подтверждением пользователя (удаление, shell, выключение...).

Опасные инструменты работают в два шага, как shutdown сейчас:
первый вызов без confirm=True возвращает вопрос NEED_CONFIRM,
второй вызов (после «да / подтверждаю») — выполняет.
"""

NEED_CONFIRM = "NEED_CONFIRM:"

SAFE = frozenset({
    "get_time", "get_weather", "get_currency", "system_info",
    "web_search", "web_query", "screenshot", "screen_info",
    "list_windows", "active_window", "list_dir", "read_file",
    "remember",
})

DANGEROUS_TOOLS = frozenset({
    "shutdown", "delete_file", "run_shell", "run_python",
})

# Подстроки в shell-командах, которые всегда требуют подтверждения.
DANGEROUS_SHELL_RE = (
    "rm -rf", "mkfs", "dd if=", ":(){", "format ",
    "shutdown", "reboot", "poweroff", "halt",
    "del /f", "del /s", "rmdir /s", "rd /s",
    "remove-item", "rm -recurse", "diskpart",
    "reg delete", "reg add", "takeown", "icacls",
    ">nul 2>&1 del", "cipher /w",
)

# Пути, запись/удаление в которых всегда опасна.
SYSTEM_PATHS = (
    "c:\\windows", "c:\\program files", "c:\\programdata",
    "hkey_local_machine", "hkcu\\software\\microsoft\\windows\\currentversion\\run",
)

CONFIRM_WORDS_RU = frozenset({
    "да", "подтверждаю", "подтверди", "подтвердить", "точно",
    "ага", "давай", "выполняй", "согласен", "согласна",
})
CONFIRM_WORDS_EN = frozenset({"yes", "confirm", "confirmed", "do it", "go ahead", "ok"})


def is_confirm(text):
    t = (text or "").strip().lower().strip(".,!?")
    return t in CONFIRM_WORDS_RU or t in CONFIRM_WORDS_EN or t.startswith("да,")


def _path_is_system(path):
    p = (path or "").lower().replace("/", "\\")
    return any(p.startswith(s) for s in SYSTEM_PATHS)


def classify(tool, params=None):
    """Вернуть (level, reason): level in {"safe","medium","danger"}."""
    params = params or {}
    if tool in SAFE:
        return "safe", ""
    if tool in DANGEROUS_TOOLS:
        if tool in ("run_shell", "run_python"):
            cmd = str(params.get("command", params.get("code", "")))[:120]
            return "danger", f"выполнение кода: {cmd}"
        return "danger", tool
    if tool == "system_setting":
        setting = str(params.get("setting", "")).lower()
        if setting in ("restart", "sleep", "time", "date"):
            return "danger", f"системная настройка: {setting}"
        return "medium", ""
    if tool in ("write_file",):
        if _path_is_system(str(params.get("path", ""))):
            return "danger", "запись в системный путь"
        return "medium", ""
    if tool in ("close_app", "forget"):
        return "medium", ""
    # всё остальное, что меняет состояние (клики, печать, запуск) — medium
    return "medium", ""


def needs_confirm(tool, params=None):
    """True если нужен второй вызов с confirm=True."""
    level, _ = classify(tool, params)
    if level != "danger":
        return False
    if tool in ("shutdown",):
        return not params.get("confirm")
    return not params.get("confirm")


def confirm_question(tool, params=None, lang="ru"):
    """Текст вопроса пользователю перед опасным действием."""
    _, reason = classify(tool, params)
    detail = ""
    if params:
        bits = []
        for k in ("command", "code", "path", "name", "setting", "value"):
            if params.get(k):
                bits.append(f"{k}={str(params[k])[:100]}")
        if bits:
            detail = ": " + ", ".join(bits)
    if lang == "en":
        return f"Confirm a dangerous action: {tool}{detail} ({reason}). Say 'yes' to proceed."
    return f"Опасное действие: {tool}{detail} ({reason}). Скажите «да» или «подтверждаю», чтобы выполнить."
