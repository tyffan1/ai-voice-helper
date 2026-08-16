import queue
import threading

import customtkinter as ctk

from assistant.config import HOTKEY

GREEN = "#4caf50"
GRAY = "#9e9e9e"
ORANGE = "#ff9800"
BLUE = "#2196f3"
RED = "#f44336"


class App(ctk.CTk):
    def __init__(self, controller):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("Атом — голосовой ассистент")
        self.geometry("460x600")
        self.minsize(400, 500)
        self.controller = controller
        self._queue = queue.Queue()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.status_frame = ctk.CTkFrame(self, corner_radius=12)
        self.status_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        self.status_dot = ctk.CTkLabel(self.status_frame, text="●", text_color=GRAY, font=ctk.CTkFont(size=22))
        self.status_dot.pack(side="left", padx=(16, 8), pady=12)
        self.status_label = ctk.CTkLabel(self.status_frame, text="Слушаю...", font=ctk.CTkFont(size=15, weight="bold"))
        self.status_label.pack(side="left", pady=12)

        controls = ctk.CTkFrame(self, corner_radius=12)
        controls.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        self.wake_switch = ctk.CTkSwitch(
            controls, text=f"Откликаться на «{self.controller.wake_name}»", command=self._toggle_wake
        )
        self.wake_switch.pack(side="left", padx=16, pady=12)
        self.wake_switch.select()

        self.talk_button = ctk.CTkButton(
            self,
            text="Говорить",
            height=52,
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._on_talk,
        )
        self.talk_button.grid(row=2, column=0, padx=16, pady=8, sticky="ew")

        self.log_box = ctk.CTkTextbox(self, corner_radius=12, state="disabled", wrap="word")
        self.log_box.grid(row=3, column=0, padx=16, pady=8, sticky="nsew")

        self.hint = ctk.CTkLabel(
            self,
            text=f"Горячая клавиша: {HOTKEY}",
            text_color=GRAY,
            font=ctk.CTkFont(size=12),
        )
        self.hint.grid(row=4, column=0, padx=16, pady=(0, 12))

    def _toggle_wake(self):
        self.controller.set_wake_enabled(bool(self.wake_switch.get()))

    def _on_talk(self):
        threading.Thread(target=self.controller.record_and_handle, args=("кнопка",), daemon=True).start()

    def _on_close(self):
        self.destroy()

    def emit_status(self, text, color=None):
        self._queue.put(("status", text, color or GRAY))

    def emit_log(self, text):
        self._queue.put(("log", text))

    def _poll(self):
        try:
            while True:
                kind, *rest = self._queue.get_nowait()
                if kind == "status":
                    self.status_label.configure(text=rest[0])
                    self.status_dot.configure(text_color=rest[1])
                elif kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", rest[0] + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll)