from pynput import keyboard

from assistant import audio, actions, llm, stt, tts
from assistant.config import HOTKEY


def handle(text):
    if not text or len(text) < 3:
        tts.speak("Не расслышал, повторите")
        return
    print(f"  распознано: {text}")
    decision = llm.ask(text)
    if "reply" in decision:
        print(f"  ответ: {decision['reply']}")
        tts.speak(decision["reply"])
        return
    tool = decision.get("tool")
    params = decision.get("params") or {}
    if not tool:
        print(f"  не JSON: {decision}")
        tts.speak(decision.get("reply") or "Не понял запрос")
        return
    print(f"  действие: {tool} {params}")
    result = actions.execute(tool, params)
    if result:
        tts.speak(result)


def on_trigger():
    audio.beep(880.0, 0.12)
    print("\nСлушаю...")
    try:
        recording = audio.record_until_silence()
        rms = float((recording.astype(float) ** 2).mean() ** 0.5)
        if rms < 8.0:
            print("  (тихо — не распознаю)")
            tts.speak("Не расслышал, повторите")
            return
        wav = audio.temp_wav(recording)
        text = stt.transcribe(wav)
        audio.beep(440.0, 0.08)
        handle(text)
    except Exception as exc:
        print(f"  ошибка: {exc}")
        try:
            tts.speak("Произошла ошибка, попробуйте ещё раз")
        except Exception:
            pass


def main():
    print(f"Ассистент запущен. Нажмите {HOTKEY} для команды. Для выхода скажите: выключи ассистента.")
    listener = keyboard.GlobalHotKeys({HOTKEY: on_trigger})
    listener.start()
    try:
        while not actions.wait_exit(1.0):
            pass
    finally:
        listener.stop()
        print("Ассистент остановлен")


if __name__ == "__main__":
    main()
