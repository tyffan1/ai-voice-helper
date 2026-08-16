import json
import os

from llama_cpp import Llama

from assistant.config import LLM_MODEL_PATH
from assistant.actions import REGISTRY

_model = None

_TOOLS = "\n".join(f"- {name}: {desc}" for name, (fn, desc) in REGISTRY.items())

_SYSTEM = (
    "Ты — голосовой ассистент на русском языке, работающий на компьютере пользователя.\n"
    "Ты умеешь выполнять действия на компьютере через инструменты.\n"
    "Сначала думай, какое действие нужно выполнить, затем ОТВЕЧАЙ СТРОГО ОДНИМ JSON-ОБЪЕКТОМ без пояснений.\n\n"
    'Если нужно действие, верни: {"tool": "название_инструмента", "params": {"имя_параметра": "значение"}}\n'
    'Если действие не требуется и достаточно ответить, верни: {"reply": "текст ответа"}\n\n'
    "Доступные инструменты:\n"
    + _TOOLS
    + "\n\nПримеры:\n"
    'Пользователь: "Который час?" → {"tool": "get_time", "params": {}}\n'
    'Пользователь: "Открой сайт youtube.com" → {"tool": "open_url", "params": {"query": "youtube.com"}}\n'
    'Пользователь: "Запусти калькулятор" → {"tool": "open_app", "params": {"name": "calc"}}\n'
    'Пользователь: "Привет" → {"reply": "Привет! Чем могу помочь?"}\n'
    "\nПравила:\n"
    "- Параметры называй точно так же, как в описании.\n"
    "- На простые вопросы (кто ты, как дела) отвечай в поле reply, кратко и дружелюбно.\n"
    "- Про время, дату и состояние системы НИКОГДА не отвечай по памяти: всегда вызывай соответствующий инструмент (get_time, system_info).\n"
    "- Если просят открыть сайт, передавай только адрес сайта без лишних слов.\n"
    "- Если просьба не связана с компьютером, отвечай в reply, но предлагай, чем можешь помочь.\n"
    "- Не выдумывай инструменты, которых нет в списке."
)


def _load():
    global _model
    if _model is None:
        n_threads = max(2, (os.cpu_count() or 4) - 1)
        _model = Llama(
            model_path=LLM_MODEL_PATH,
            n_ctx=4096,
            n_threads=n_threads,
            n_batch=256,
            verbose=False,
        )
    return _model


def ask(user_text):
    out = _load().create_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_text},
        ],
        temperature=0.2,
        max_tokens=256,
    )
    content = out["choices"][0]["message"]["content"].strip()
    return parse(content, user_text)


def parse(content, user_text):
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(content[start : end + 1])
            if isinstance(data, dict):
                if "tool" in data:
                    return data
                for name in REGISTRY:
                    if name in data:
                        return {"tool": name, "params": data[name]}
                return data
        except Exception:
            pass
    return {"reply": content if content else f"Не понял запрос: {user_text}"}
