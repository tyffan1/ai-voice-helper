import threading

from pynput import keyboard

from assistant import llm, stt, tts
from assistant.config import BASE_DIR, HOTKEY, MODELS_DIR
from assistant.controller import Controller
from assistant.gui import App
from assistant.wake import WakeListener

LOG_PATH = BASE_DIR / "deri.log"


def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def warmup():
    try:
        stt.load()
        llm.load()
        tts.load()
        log("Модели загружены")
        print("Модели загружены")
    except Exception as exc:
        log(f"Ошибка предзагрузки моделей: {exc}")
        print(f"Ошибка предзагрузки моделей: {exc}")


def main():
    log(f"Запуск ассистента Атом. Модели: {MODELS_DIR}")
    print("Запуск ассистента Атом...")
    controller = Controller()
    app = App(controller)
    controller.emit_status = app.emit_status
    controller.emit_log = app.emit_log
    controller.on_exit = lambda: app.after(0, app._on_close)

    threading.Thread(target=warmup, daemon=True).start()

    wake = WakeListener(controller)
    wake.start()
    log("Wake-листенер запущен")

    listener = keyboard.GlobalHotKeys({HOTKEY: controller.record_and_handle})
    listener.start()

    try:
        app.mainloop()
    finally:
        wake.stop()
        listener.stop()
        log("Ассистент остановлен")
        print("Ассистент остановлен")


if __name__ == "__main__":
    main()