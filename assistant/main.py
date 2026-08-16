import threading

from pynput import keyboard

from assistant import i18n, llm, stt, tts
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
        log("Models loaded")
        print("Models loaded")
    except Exception as exc:
        log(f"Model preload error: {exc}")
        print(f"Model preload error: {exc}")


def main():
    i18n.load_settings()
    log(f"Atom assistant started. Models: {MODELS_DIR}")
    print("Starting Atom assistant...")
    controller = Controller()
    app = App(controller)
    controller.emit_status = app.emit_status
    controller.emit_log = app.emit_log
    controller.on_exit = lambda: app.after(0, app.exit_app)

    threading.Thread(target=warmup, daemon=True).start()

    wake = WakeListener(controller)
    wake.start()
    log("Wake listener started")

    listener = keyboard.GlobalHotKeys({HOTKEY: controller.record_and_handle})
    listener.start()

    try:
        app.mainloop()
    finally:
        wake.stop()
        listener.stop()
        log("Assistant stopped")
        print("Assistant stopped")


if __name__ == "__main__":
    main()