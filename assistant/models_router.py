"""Роутер моделей: локальный Qwen по умолчанию, облако — опционально.

Если заданы переменные окружения:
  ASSISTANT_API_KEY  — ключ OpenAI-совместимого API
  ASSISTANT_API_BASE — например https://api.openai.com/v1 (по умолчанию)
  ASSISTANT_API_MODEL— например gpt-4o-mini
то сложные длинные задачи уходят в облако, простые — остаются локально.

Без ключа всё работает как раньше — полностью офлайн.
"""

import json
import os
import urllib.request

from assistant.config import (
    CLOUD_API_BASE, CLOUD_API_KEY, CLOUD_MODEL,
)


def cloud_enabled():
    return bool(CLOUD_API_KEY)


def _cloud_chat(messages, tools=None, temperature=0.2, max_tokens=400):
    url = CLOUD_API_BASE.rstrip("/") + "/chat/completions"
    payload = {
        "model": CLOUD_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CLOUD_API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def cloud_ask(messages, tools=None, temperature=0.2, max_tokens=400):
    """Вернуть (tool_name, params, reply). Бросает исключение при ошибке."""
    data = _cloud_chat(messages, tools, temperature, max_tokens)
    msg = data["choices"][0]["message"]
    if msg.get("tool_calls"):
        call = msg["tool_calls"][0]["function"]
        try:
            params = json.loads(call.get("arguments") or "{}")
        except Exception:
            params = {}
        return call.get("name") or "", params, ""
    return "", {}, (msg.get("content") or "").strip()


def should_use_cloud(user_text, step):
    """Эвристика: облако для длинных/сложных задач на 1-м шаге."""
    if not cloud_enabled():
        return False
    t = (user_text or "").lower()
    if step > 0:
        return False  # продолжение цепочки — тем же движком, что начал
    long_task = len(user_text or "") > 120
    code_words = ("напиши код", "скрипт", "программу", "разбери", "проанализируй",
                  "write code", "explain", "analyze", "plan")
    return long_task or any(w in t for w in code_words)


def env_status(lang="ru"):
    if cloud_enabled():
        base = CLOUD_API_BASE
        if lang == "en":
            return f"Cloud model {CLOUD_MODEL} via {base} is available."
        return f"Облачная модель {CLOUD_MODEL} доступна."
    if lang == "en":
        return "Working fully offline (local Qwen). Set ASSISTANT_API_KEY to enable cloud."
    return "Работаю полностью офлайн (локальный Qwen). Для облака задайте ASSISTANT_API_KEY."


def _shot_data_uri():
    """Скриншот -> data URI для vision-запроса."""
    import base64

    from assistant.vision import take_shot

    path, _size = take_shot()
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def vision_describe(lang="ru"):
    """Описать экран через облачную VLM. Бросает исключение при ошибке."""
    from assistant.i18n import get_language

    lang = get_language()
    prompt = (
        "Describe this screenshot in 2-3 short sentences for a voice assistant: "
        "active window, what is open, key elements. No preamble."
        if lang == "en" else
        "Опиши этот скриншот в 2-3 коротких предложениях для голосового ассистента: "
        "активное окно, что открыто, ключевые элементы. Без предисловий."
    )
    data = _cloud_chat(
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _shot_data_uri()}},
        ]}],
        temperature=0.2, max_tokens=300,
    )
    return (data["choices"][0]["message"].get("content") or "").strip()


def vision_locate(query):
    """Найти элемент на экране через VLM. Вернуть (x, y) в пикселях."""
    import re

    prompt = (
        f'Find the UI element the user means: "{query}". '
        'Answer with ONLY JSON like {{"x": 500, "y": 300}} '
        'where x,y are coordinates on a 0-1000 scale (0,0 = top-left). '
        'No other text.'
    )
    data = _cloud_chat(
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _shot_data_uri()}},
        ]}],
        temperature=0.1, max_tokens=60,
    )
    text = (data["choices"][0]["message"].get("content") or "").strip()
    m = re.search(r"\{[^}]*\}", text)
    if not m:
        raise ValueError(f"bad locate reply: {text[:80]}")
    import json as _json
    pt = _json.loads(m.group(0))
    from assistant import computer
    import ctypes

    try:
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        w, h = 1920, 1080
    return max(0, min(int(pt["x"]) * w // 1000, w - 1)), \
        max(0, min(int(pt["y"]) * h // 1000, h - 1))
