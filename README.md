# ⚛️ Atom — Voice Assistant

**A fully local voice assistant for Windows.** Wakes on the word "Atom", understands spoken commands, performs actions on your PC and replies by voice — no internet, no cloud services, no API keys.

[![Release](https://img.shields.io/github/v/release/tyffan1/ai-voice-helper?color=4caf50&label=release)](https://github.com/tyffan1/ai-voice-helper/releases)
[![Platform](https://img.shields.io/badge/platform-Windows-2196f3)](https://github.com/tyffan1/ai-voice-helper)
[![Offline](https://img.shields.io/badge/offline-100%25-4caf50)](https://github.com/tyffan1/ai-voice-helper)

```
+------------------------------------------+
|  Atom - voice assistant                  |
|  * Listening...                          |
|  +------------------------------------+  |
|  | You: Atom, open Telegram           |  |
|  | Action: open_app (Telegram)        |  |
|  | Atom: Launching Telegram           |  |
|  +------------------------------------+  |
|  [ Talk ]  [x] Wake word: Atom           |
+------------------------------------------+
```

## How it works

```
   "Atom, what time is it?"
             |
             v
   +------------------+   +------------------+   +------------------+
   | wake word        |-->| Whisper (STT)    |-->| Qwen 2.5 3B      |
   | "Atom" + VAD     |   | recognition      |   | LLM decides,     |
   +------------------+   +------------------+   | what to do       |
                                                 +---------+--------+
                                                           |
                                                           v
   +------------------+   +------------------+   +------------------+
   | Piper (TTS)      |<--| reply / result   |<--| tools:           |
   | Russian voice    |   |                  |   | weather, tabs    |
   +------------------+   +------------------+   +------------------+
```

## Features

- 🌐 **Two languages** — switch between Russian and English in the app: the UI, speech recognition, the assistant's replies and the TTS voice all change instantly (the choice is saved)
- 🎙 **Wake word** — say "Atom" (or «Атом») at any moment; fuzzy matching tolerates slight mispronunciations, while random words don't trigger it
- ⌨️ **Hotkey** `Ctrl+Shift+Space` — force invocation
- 🖱 **"Talk" button** in the app window
- 🗣 **Speech fully on-device** — recognition and synthesis are local
- 🧠 **LLM with tools** — the model decides which action to run
- 🪟 **GUI app** — dark theme, status indicator, chat log, system tray
- 🌤 **Real weather** — fetches Open-Meteo and speaks it, instead of opening weather sites

### Commands out of the box

| Say... | What happens |
|---|---|
| «Атом, какая погода в Киеве?» / "Atom, what's the weather in Kyiv?" | Fetches and speaks the current weather (Open-Meteo, no key) |
| «Атом, запусти телеграм» / "Atom, open Telegram" | Finds the app in the Start menu and launches it |
| "Atom, open youtube.com" | Opens the site in the browser |
| "Atom, search for the best Python books" | Opens a web search |
| "Atom, close the tab" | Closes the active browser tab (Ctrl+W) |
| "Atom, refresh the page" | Refreshes the page |
| "Atom, scroll down" | Scrolls the page with the mouse wheel |
| "Atom, take a screenshot" | Saves a screenshot to `~/Pictures` |
| "Atom, set a timer for 5 minutes to remind me about tea" | Reminds you by voice in 5 minutes |
| "Atom, what time is it?" | Says the current time and date |
| "Atom, check the CPU load" | Reports CPU, memory and battery |
| "Atom, type the following text..." | Types with the keyboard into the active field |
| "Atom, press ctrl+s" | Presses any key or combination (enter, esc, win+d...) |
| "Atom, open the folder C:\..." | Opens the folder in Explorer |
| "Atom, lock the screen" | Locks the desktop |
| "Atom, shut down the computer" | Shuts down the PC (with confirmation) |
| "Atom, exit the assistant" | Closes the app |

## Quick start

### Option 1 — ready-made exe

1. Download [AtomAssistant.exe](https://github.com/tyffan1/ai-voice-helper/releases) from the latest release
2. Put the `models` folder next to it (see below)
3. Run `AtomAssistant.exe`

### Option 2 — from source

```powershell
# 1. Clone and install dependencies
git clone https://github.com/tyffan1/ai-voice-helper.git
cd ai-voice-helper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Download the models (~2.6 GB)
python download_models.py
#     - Qwen 2.5 3B (LLM, ~2 GB)
#     - ru_RU-irina-medium + en_US-lessac-medium (Piper voices, ~60 MB each)
#     - Whisper small is downloaded automatically on first run (~460 MB)

# 3. Run
run.bat
```

## Requirements

- Windows 10/11
- Python 3.10+ (source builds only)
- ~4 GB of free RAM
- ~3 GB of disk space for models
- Microphone and speakers

## Configuration

Everything is set via environment variables or by editing `assistant/config.py`:

| Variable | Default | Description |
|---|---|---|
| `ASSISTANT_WAKE_NAME` | `атом` | Wake word (RU); in English mode it's `atom` |
| `ASSISTANT_CITY` | `Москва` | City used for weather requests when none is named |
| `ASSISTANT_HOTKEY` | `<ctrl>+<shift>+<space>` | Hotkey |
| `ASSISTANT_WHISPER` | `small` | Whisper model (`tiny`/`base` — faster, `medium` — more accurate) |
| `ASSISTANT_LLM` | path in `models/` | LLM GGUF file |
| `ASSISTANT_PIPER_RU` | path in `models/` | Russian Piper voice |
| `ASSISTANT_PIPER_EN` | path in `models/` | English Piper voice |

The interface language can be switched in the app (stored in `settings.json` next to the executable).

## Building the exe

```powershell
python -m PyInstaller --noconfirm --onefile --windowed --name AtomAssistant `
  --collect-all llama_cpp --collect-all faster_whisper --collect-all ctranslate2 `
  --collect-all tokenizers --collect-all onnxruntime --collect-all av `
  --collect-all customtkinter --collect-all piper --collect-all sounddevice `
  --collect-all pystray --collect-all PIL `
  run_app.py
```

Result: `dist/AtomAssistant.exe` (~130 MB). If something fails, check `deri.log` next to the exe.

## Project structure

```
ai-voice-helper/
├── assistant/
│   ├── main.py        # entry point, model preloading
│   ├── gui.py         # app window (customtkinter), tray, language switch
│   ├── controller.py  # session logic: record -> LLM -> action -> reply
│   ├── wake.py        # background wake-word listener
│   ├── stt.py         # speech recognition (faster-whisper)
│   ├── llm.py         # local LLM with tools (llama.cpp)
│   ├── tts.py         # speech synthesis (Piper)
│   ├── actions.py     # actions on the computer
│   ├── i18n.py        # language switching (RU/EN), settings
│   ├── audio.py       # record/playback (sounddevice)
│   └── config.py      # settings
├── models/            # models (not in the repo, see download_models.py)
├── download_models.py # model download script
├── run_app.py         # entry point for PyInstaller
├── run.bat            # source launch
└── requirements.txt
```

## Tech stack

| Component | Technology |
|---|---|
| Speech recognition | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper small, int8) |
| Brain (LLM) | [Qwen 2.5 3B Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF) via [llama.cpp](https://github.com/ggerganov/llama.cpp) |
| Speech synthesis | [Piper](https://github.com/rhasspy/piper) — voices Irina (ru_RU) and Lessac (en_US) |
| GUI | [customtkinter](https://github.com/TomSchimansky/CustomTkinter) |
| System tray | [pystray](https://github.com/moses-palmer/pystray) |
| Sound | sounddevice + amplitude-based VAD |
| Weather | [Open-Meteo](https://open-meteo.com) (no API key) |