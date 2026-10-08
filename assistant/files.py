"""Файлы и выполнение кода с уровнями риска.

SAFE:   list_dir, read_file
MEDIUM: write_file вне системных путей
DANGER: delete_file, run_shell, run_python — только с confirm=True
"""

import os
import subprocess
import tempfile
from pathlib import Path

from assistant import safety
from assistant.i18n import L

MAX_READ = 8000
SHELL_TIMEOUT = 30


def _resolve(path):
    p = os.path.expandvars(os.path.expanduser((path or "").strip().strip('"')))
    return os.path.abspath(p)


def list_dir(path=""):
    base = _resolve(path or ".")
    if not os.path.isdir(base):
        return L(f"Папка не найдена: {path}", f"Folder not found: {path}")
    try:
        items = []
        for f in sorted(os.listdir(base))[:100]:
            full = os.path.join(base, f)
            mark = "/" if os.path.isdir(full) else ""
            items.append(f + mark)
        if L("а", "b") == "а":
            return f"{base}:\n" + "\n".join(items)
        return f"{base}:\n" + "\n".join(items)
    except Exception as exc:
        return L(f"Не могу прочитать папку: {exc}", f"Cannot list folder: {exc}")


def read_file(path, limit=MAX_READ):
    base = _resolve(path)
    if not os.path.isfile(base):
        return L(f"Файл не найден: {path}", f"File not found: {path}")
    try:
        if os.path.getsize(base) > 2_000_000:
            return L("Файл слишком большой (>2 МБ)", "File too large (>2 MB)")
        text = Path(base).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return L(f"Не могу прочитать файл: {exc}", f"Cannot read file: {exc}")
    if len(text) > limit:
        text = text[:limit] + "\n…[обрезано]"
    return text or L("(пустой файл)", "(empty file)")


def write_file(path, content="", mode="overwrite", confirm=False):
    base = _resolve(path)
    if not base or base.endswith(os.sep):
        return L("Куда записать? Укажите путь к файлу", "Where to write? Give a file path")
    level, _ = safety.classify("write_file", {"path": base})
    if level == "danger" and not confirm:
        return safety.NEED_CONFIRM + safety.confirm_question(
            "write_file", {"path": base}
        )
    try:
        os.makedirs(os.path.dirname(base) or ".", exist_ok=True)
        if mode == "append" and os.path.exists(base):
            with open(base, "a", encoding="utf-8") as f:
                f.write(content or "")
        else:
            with open(base, "w", encoding="utf-8") as f:
                f.write(content or "")
        return L(f"Записал в {base}", f"Wrote to {base}")
    except Exception as exc:
        return L(f"Не удалось записать: {exc}", f"Cannot write: {exc}")


def delete_file(path, confirm=False):
    base = _resolve(path)
    if not confirm:
        return safety.NEED_CONFIRM + safety.confirm_question(
            "delete_file", {"path": base}
        )
    try:
        if os.path.isdir(base):
            import shutil
            shutil.rmtree(base)
        else:
            os.remove(base)
        return L(f"Удалил {base}", f"Deleted {base}")
    except FileNotFoundError:
        return L(f"Не найдено: {base}", f"Not found: {base}")
    except Exception as exc:
        return L(f"Не удалось удалить: {exc}", f"Cannot delete: {exc}")


_INTERACTIVE_SHELLS = frozenset({
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "python", "python.exe", "wsl", "wsl.exe", "bash", "sh", "farmanager",
})


def run_shell(command, confirm=False):
    cmd = (command or "").strip()
    if not cmd:
        return L("Какую команду выполнить?", "Which command should I run?")
    low = cmd.lower()
    # голая интерактивная оболочка без команды — сразу отказ, иначе виснет
    first = low.split()[0].strip('"') if low.split() else ""
    if first in _INTERACTIVE_SHELLS and len(low.split()) == 1:
        return L(
            "Интерактивную оболочку так не запускаю — скажите конкретную команду, "
            "например: список файлов, или «открой терминал» чтобы открыть окно",
            "I can't run an interactive shell like that — give a specific command, "
            "e.g. list files, or say 'open terminal' to open a window",
        )
    dangerous = any(p in low for p in safety.DANGEROUS_SHELL_RE)
    if not confirm and (dangerous or True):
        # shell всегда через подтверждение при голосовом вызове без флага:
        # но чтобы не мучить на dir/echo, разрешаем безопасный список сразу
        safe_prefix = ("dir ", "echo ", "where ", "whoami", "ipconfig",
                       "ping ", "tasklist", "git status", "git diff", "ls", "pwd")
        if not low.startswith(safe_prefix):
            return safety.NEED_CONFIRM + safety.confirm_question(
                "run_shell", {"command": cmd[:120]}
            )
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=SHELL_TIMEOUT, stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        out = out.strip()[:4000] or f"(код {r.returncode}, без вывода)"
        return f"[exit {r.returncode}]\n{out}"
    except subprocess.TimeoutExpired:
        return L("Команда зависла и остановлена по таймауту", "Command timed out")
    except Exception as exc:
        return L(f"Не удалось выполнить: {exc}", f"Cannot execute: {exc}")


def run_python(code, confirm=False):
    if not (code or "").strip():
        return L("Какой код выполнить?", "Which code should I run?")
    if not confirm:
        return safety.NEED_CONFIRM + safety.confirm_question(
            "run_python", {"code": code[:120]}
        )
    with tempfile.NamedTemporaryFile(
        suffix=".py", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(code)
        name = f.name
    try:
        import sys
        r = subprocess.run(
            [sys.executable, name], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=SHELL_TIMEOUT,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = ((r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")).strip()
        return f"[exit {r.returncode}]\n{(out[:4000] or '(без вывода)')}"
    except subprocess.TimeoutExpired:
        return L("Код завис и остановлен", "Code timed out")
    finally:
        try:
            os.remove(name)
        except Exception:
            pass
