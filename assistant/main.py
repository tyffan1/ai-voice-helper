import os
import threading
from pathlib import Path

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


def rotate_log(path, keep=3, max_bytes=1024 * 1024):
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        for i in range(keep - 1, 0, -1):
            src = Path(str(path) + f".{i}")
            dst = Path(str(path) + f".{i + 1}")
            if src.exists():
                os.replace(src, dst)
        os.replace(path, Path(str(path) + ".1"))
    except Exception:
        pass


def warmup():
    try:
        stt.load()
        threading.Thread(target=tts.warm_edge, daemon=True).start()
        log("Models loaded")
        print("Models loaded")
    except Exception as exc:
        log(f"Model preload error: {exc}")
        print(f"Model preload error: {exc}")


def main():
    i18n.load_settings()
    rotate_log(LOG_PATH)
    rotate_log(BASE_DIR / "wake.log")
    log(f"Atom assistant started. Models: {MODELS_DIR}")
    print("Starting Atom assistant...")
    controller = Controller()
    app = App(controller)
    orig_emit_log = app.emit_log

    def _emit_log(text):
        orig_emit_log(text)
        log(text)

    app.emit_log = _emit_log
    controller.emit_status = app.emit_status
    controller.emit_log = app.emit_log
    controller.on_exit = lambda: app.after(0, app.exit_app)

    threading.Thread(target=warmup, daemon=True).start()
    controller.greet()

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