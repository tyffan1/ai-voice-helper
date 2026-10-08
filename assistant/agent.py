"""Агентный цикл ReAct: думать -> действие -> наблюдать -> ... -> ответить.

Одно действие — один ответ сразу (быстро). Цепочка из нескольких шагов —
только если в просьбе есть слова-связки («потом», «затем»...).
Опасные действия модель подтвердить сама себе НЕ может: флаг confirm
из её ответа выкидывается, вопрос задаётся пользователю.
"""

from assistant import actions, llm, models_router, safety
from assistant.config import AGENT_MAX_STEPS
from assistant.i18n import L

import re
import time

# Слова-связки: только тогда крутим несколько шагов.
_CHAIN_WORDS = ("потом", "затем", "после этого", "а потом", "и потом",
                "then", "after that", "and then")

_CHAIN_SPLIT = re.compile(
    r"\s*,?\s*(?:а\s+потом|и\s+потом|потом|затем|после\s+этого|"
    r"and\s+then|after\s+that|then)\s*,?\s*",
    re.IGNORECASE,
)

# После этих инструментов окну нужно время появиться перед следующим шагом.
_SLOW_TOOLS = frozenset({"open_app", "open_game", "open_url", "open_folder"})


def _is_chain(user_text):
    t = (user_text or "").lower()
    return any(w in t for w in _CHAIN_WORDS)


def run(user_text, lang=None, emit_log=None):
    """Выполнить задачу. Вернуть (final_text, stopped_for_confirm)."""
    from assistant import i18n
    lang = lang or i18n.get_language()
    emit_log = emit_log or (lambda t: None)
    chain = _is_chain(user_text)
    max_steps = AGENT_MAX_STEPS if chain else 1

    history = []  # [(tool, params, result)]

    # Цепочка «сделай А, потом Б»: режем на подзадачи САМИ, модели не доверяем —
    # слабая локалка иначе пихает всё предложение в один параметр.
    parts = [p.strip() for p in _CHAIN_SPLIT.split(user_text) if p and p.strip()]
    if len(parts) > 1:
        return _run_chain(parts[:3], lang, emit_log)

    for step in range(max_steps):
        try:
            if models_router.should_use_cloud(user_text, step):
                decision = _cloud_step(user_text, history, lang)
            else:
                decision = llm.ask_with_history(user_text, history, lang=lang)
        except Exception as exc:
            if step == 0 and not history:
                return L(f"Ошибка модели: {exc}", f"Model error: {exc}"), None
            break

        if "reply" in decision:
            return decision["reply"], None

        tool = decision.get("tool") or ""
        params = dict(decision.get("params") or {})
        if tool not in actions.REGISTRY:
            return L(
                "Не понял команду, попробуйте сформулировать иначе",
                "Did not understand, try rephrasing",
            ), None

        # модель не может сама подтверждать опасное — только пользователь
        if tool in safety.DANGEROUS_TOOLS:
            params.pop("confirm", None)

        emit_log(L("Действие:", "Action:") + f" {tool} {params} (шаг {step + 1})")
        result = actions.execute(tool, params)

        if isinstance(result, str) and result.startswith(safety.NEED_CONFIRM):
            question = result[len(safety.NEED_CONFIRM):]
            emit_log(f"{L('Атом:', 'Atom:')} {question}")
            return question, {"tool": tool, "params": params}

        history.append((tool, params, str(result)[:1500]))

        if step >= max_steps - 1:
            # последний шаг: результат и есть ответ
            return str(result), None
        # цепочка продолжается — следующий виток спросит модель с историей

    if history:
        return history[-1][2], None
    return L("Не смог выполнить задачу", "Could not complete the task"), None


def _run_chain(parts, lang, emit_log):
    """Выполнить подзадачи по очереди. Вернуть (общий итог, pending)."""
    from assistant import i18n
    lang = lang or i18n.get_language()
    done = []
    history = []
    for i, part in enumerate(parts):
        try:
            if models_router.should_use_cloud(part, 0):
                decision = _cloud_step(part, history, lang)
            else:
                decision = llm.ask_with_history(part, history[-2:], lang=lang)
        except Exception as exc:
            done.append(L(f"Шаг {i + 1} не вышел: {exc}", f"Step {i + 1} failed: {exc}"))
            continue
        if "reply" in decision:
            done.append(decision["reply"])
            continue
        tool = decision.get("tool") or ""
        params = dict(decision.get("params") or {})
        if tool not in actions.REGISTRY:
            done.append(L(f"Шаг {i + 1}: не понял", f"Step {i + 1}: did not understand"))
            continue
        if tool in safety.DANGEROUS_TOOLS:
            params.pop("confirm", None)
        emit_log(L("Действие:", "Action:") + f" {tool} {params} (шаг {i + 1})")
        result = actions.execute(tool, params)
        if isinstance(result, str) and result.startswith(safety.NEED_CONFIRM):
            question = result[len(safety.NEED_CONFIRM):]
            emit_log(f"{L('Атом:', 'Atom:')} {question}")
            rest = parts[i + 1:]
            pending = {"tool": tool, "params": params}
            if rest:
                pending["rest"] = rest
            if done:
                return " ".join(done) + " " + question, pending
            return question, pending
        done.append(str(result))
        history.append((tool, params, str(result)[:800]))
        if tool in _SLOW_TOOLS and i < len(parts) - 1:
            time.sleep(2.5)  # дать окну открыться перед следующим шагом
    return " ".join(d for d in done if d) or L("Готово", "Done"), None


def _cloud_step(user_text, history, lang):
    from assistant import i18n
    lang = lang or i18n.get_language()
    messages = [{"role": "system", "content": llm.system_prompt(lang)}]
    messages.append({"role": "user", "content": user_text})
    for tool, params, result in history[-4:]:
        messages.append({"role": "assistant", "content": f"[{tool} {params}]"})
        messages.append({"role": "user", "content": f"Результат: {result}"})
    tools = llm.tools_for(lang, user_text)
    name, params, reply = models_router.cloud_ask(messages, tools)
    if name:
        return {"tool": name, "params": params}
    return {"reply": reply}
