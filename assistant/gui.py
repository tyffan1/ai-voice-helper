import queue
import threading

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw

from assistant import actions, i18n
from assistant.config import HOTKEY
from assistant.i18n import L

GREEN = "#4caf50"
GRAY = "#9e9e9e"
ORANGE = "#ff9800"
BLUE = "#2196f3"
RED = "#f44336"


def _make_tray_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((22, 22, 42, 42), fill=(76, 175, 80))
    d.ellipse((5, 9, 59, 55), outline=(33, 150, 243), width=4)
    d.ellipse((9, 5, 55, 59), outline=(33, 150, 243), width=4)
    for cx, cy in ((5, 32), (59, 32), (32, 5), (32, 59)):
        d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(255, 255, 255))
    return img


class App(ctk.CTk):
    def __init__(self, controller):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(L("Атом — голосовой ассистент", "Atom - voice assistant"))
        self.geometry("460x640")
        self.minsize(400, 560)
        self.controller = controller
        self._queue = queue.Queue()
        self._tray = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll)
        threading.Thread(target=self._init_tray, daemon=True).start()

    def _init_tray(self):
        icon = pystray.Icon(
            "atom_assistant",
            _make_tray_image(),
            L("Атом — голосовой ассистент", "Atom - voice assistant"),
            self._tray_menu(),
        )
        self._tray = icon
        icon.run()

    def _tray_menu(self):
        return pystray.Menu(
            pystray.MenuItem(L("Показать окно", "Show window"), self._show_from_tray, default=True),
            pystray.MenuItem(L("Выход", "Exit"), self._quit_from_tray),
        )

    def _rebuild_tray(self):
        def _do():
            try:
                old = self._tray
                if old:
                    old.stop()
            except Exception:
                pass
            icon = pystray.Icon(
                "atom_assistant",
                _make_tray_image(),
                L("Атом — голосовой ассистент", "Atom - voice assistant"),
                self._tray_menu(),
            )
            self._tray = icon
            icon.run()

        threading.Thread(target=_do, daemon=True).start()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.status_frame = ctk.CTkFrame(self, corner_radius=12)
        self.status_frame.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        self.status_dot = ctk.CTkLabel(self.status_frame, text="●", text_color=GRAY, font=ctk.CTkFont(size=22))
        self.status_dot.pack(side="left", padx=(16, 8), pady=12)
        self.status_label = ctk.CTkLabel(
            self.status_frame, text=L("Слушаю...", "Listening..."), font=ctk.CTkFont(size=15, weight="bold")
        )
        self.status_label.pack(side="left", pady=12)

        self.tabs = ctk.CTkTabview(self, corner_radius=12)
        self.tabs.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        self._build_tabs()

        self.hint = ctk.CTkLabel(
            self,
            text=self._hint_text(),
            text_color=GRAY,
            font=ctk.CTkFont(size=12),
        )
        self.hint.grid(row=2, column=0, padx=16, pady=(0, 12))

    def _build_tabs(self):
        self.tabs.add(L("Ассистент", "Assistant"))
        self.tabs.add(L("Настройки", "Settings"))
        main_tab = self.tabs.tab(L("Ассистент", "Assistant"))
        settings_tab = self.tabs.tab(L("Настройки", "Settings"))

        main_tab.grid_columnconfigure(0, weight=1)
        main_tab.grid_rowconfigure(1, weight=1)
        self.talk_button = ctk.CTkButton(
            main_tab,
            text=L("Говорить", "Talk"),
            height=52,
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._on_talk,
        )
        self.talk_button.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")

        self.log_box = ctk.CTkTextbox(main_tab, corner_radius=12, state="disabled", wrap="word")
        self.log_box.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")

        self.wake_switch = ctk.CTkSwitch(
            settings_tab, text=self._wake_switch_text(), command=self._toggle_wake
        )
        self.wake_switch.pack(anchor="w", padx=20, pady=(20, 12))
        if self.controller.wake_enabled:
            self.wake_switch.select()

        lang_frame = ctk.CTkFrame(settings_tab, corner_radius=10)
        lang_frame.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(lang_frame, text=L("Язык:", "Language:"), font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(16, 8), pady=10
        )
        self.lang_menu = ctk.CTkOptionMenu(
            lang_frame,
            values=["Русский", "English"],
            width=140,
            command=self._on_language,
        )
        self.lang_menu.pack(side="left", padx=8, pady=10)
        self.lang_menu.set("Русский" if i18n.get_language() == "ru" else "English")

        start_frame = ctk.CTkFrame(settings_tab, corner_radius=10)
        start_frame.pack(fill="x", padx=16, pady=6)
        self.autostart_switch = ctk.CTkSwitch(
            start_frame, text=L("Запускать при старте Windows", "Launch at Windows startup"), command=self._toggle_autostart
        )
        self.autostart_switch.pack(anchor="w", padx=16, pady=12)
        if actions.is_autostart():
            self.autostart_switch.select()

    def _restore_tab_states(self):
        self.wake_switch.configure(text=self._wake_switch_text())
        if self.controller.wake_enabled:
            self.wake_switch.select()
        else:
            self.wake_switch.deselect()
        self.lang_menu.set("Русский" if i18n.get_language() == "ru" else "English")
        if actions.is_autostart():
            self.autostart_switch.select()
        else:
            self.autostart_switch.deselect()

    def _wake_switch_text(self):
        return L(f"Откликаться на «{self.controller.wake_name}»", f'Respond to "{self.controller.wake_name}"')

    def _hint_text(self):
        return L(f"Горячая клавиша: {HOTKEY}", f"Hotkey: {HOTKEY}")

    def _on_language(self, choice):
        lang = "ru" if choice == "Русский" else "en"
        if lang == i18n.get_language():
            return
        i18n.set_language(lang)
        self.title(L("Атом — голосовой ассистент", "Atom - voice assistant"))
        self.hint.configure(text=self._hint_text())
        self.status_label.configure(text=L("Слушаю...", "Listening..."))
        log_text = self.log_box.get("1.0", "end-1c")
        self.tabs.destroy()
        self.tabs = ctk.CTkTabview(self, corner_radius=12)
        self.tabs.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        self._build_tabs()
        self._restore_tab_states()
        if log_text:
            self.log_box.configure(state="normal")
            self.log_box.insert("1.0", log_text)
            self.log_box.configure(state="disabled")
        self._rebuild_tray()

    def _toggle_wake(self):
        self.controller.set_wake_enabled(bool(self.wake_switch.get()))

    def _toggle_autostart(self):
        actions.set_autostart(bool(self.autostart_switch.get()))

    def _on_talk(self):
        threading.Thread(target=self.controller.record_and_handle, args=("кнопка",), daemon=True).start()

    def _on_close(self):
        self._hide_to_tray()

    def _hide_to_tray(self):
        self.withdraw()
        if self._tray:
            self._tray.notify(L("Атом продолжает работать в фоне", "Atom keeps working in the background"), "Атом")

    def _show_from_tray(self, icon=None, item=None):
        self.after(0, self._restore)

    def _restore(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_from_tray(self, icon=None, item=None):
        self.after(0, self.exit_app)

    def exit_app(self):
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
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