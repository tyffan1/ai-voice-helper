import inspect
import json
import os
import threading

from llama_cpp import Llama

from assistant.actions import REGISTRY
from assistant.config import CITY, LLM_MODEL_PATH

_model = None
_lock = threading.Lock()

_SYSTEM = (
    "Ты — голосовой ассистент на русском языке, работающий на компьютере пользователя. "
    "Ты умеешь выполнять действия на компьютере через инструменты: запускать приложения, "
    "открывать сайты и поиск в браузере, ставить таймеры, сообщать время и состояние системы. "
    "Выбирай инструмент, если он нужен; иначе отвечай кратко и дружелюбно. "
    "Про время, дату и систему всегда используй инструменты, не отвечай по памяти. "
    f"Любой вопрос про погоду — открывай поиск, например: \"погода в {CITY}\". "
    "Выключение компьютера — только по явной просьбе пользователя."
)


def _build_tools():
    tools = []
    for name, (fn, desc) in REGISTRY.items():
        sig = inspect.signature(fn)
        props = {}
        required = []
        for pname, p in sig.parameters.items():
            ann = p.annotation
            ptype = "string"
            if ann is int:
                ptype = "integer"
            elif ann is bool:
                ptype = "boolean"
            elif ann is float:
                ptype = "number"
            props[pname] = {"type": ptype}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
        )
    return tools


_TOOLS = _build_tools()


def load():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                n_threads = max(2, (os.cpu_count() or 4) - 1)
                _model = Llama(
                    model_path=LLM_MODEL_PATH,
                    n_ctx=2048,
                    n_threads=n_threads,
                    n_batch=256,
                    verbose=False,
                )
    return _model


def _extract_tool_call(content):
    start = content.find("<tool_call>")
    if start == -1:
        return None
    end = content.find("</tool_call>", start)
    if end == -1:
        end = len(content)
    inner = content[start + len("<tool_call>") : end]
    for i, ch in enumerate(inner):
        if ch == "{":
            for j in range(len(inner) - 1, i, -1):
                if inner[j] != "}":
                    continue
                try:
                    data = json.loads(inner[i : j + 1])
                    if isinstance(data, dict) and "name" in data:
                        return {
                            "tool": data.get("name") or "",
                            "params": data.get("arguments") or {},
                        }
                except Exception:
                    continue
    return None


def ask(user_text):
    out = load().create_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_text},
        ],
        temperature=0.1,
        max_tokens=128,
        tools=_TOOLS,
    )
    msg = out["choices"][0]["message"]
    if msg.get("tool_calls"):
        call = msg["tool_calls"][0]["function"]
        try:
            params = json.loads(call.get("arguments") or "{}")
        except Exception:
            params = {}
        return {"tool": call.get("name") or "", "params": params}
    content = msg.get("content") or ""
    call = _extract_tool_call(content)
    if call:
        return call
    return {"reply": content}