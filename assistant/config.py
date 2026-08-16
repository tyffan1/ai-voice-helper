import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

_LLM_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
_LLM_ALT = "qwen2.5-3b-instruct-q4_k_m.gguf"


def _resolve_models_dir():
    if not getattr(sys, "frozen", False):
        return BASE_DIR / "models"
    for candidate in (BASE_DIR / "models", Path.cwd() / "models", BASE_DIR.parent / "models"):
        if (candidate / _LLM_FILE).exists() or (candidate / _LLM_ALT).exists():
            return candidate
    return BASE_DIR / "models"


MODELS_DIR = _resolve_models_dir()
MODELS_DIR.mkdir(exist_ok=True)

WHISPER_MODEL = os.environ.get("ASSISTANT_WHISPER", "small")
LLM_MODEL_PATH = os.environ.get(
    "ASSISTANT_LLM", str(MODELS_DIR / "qwen2.5-1.5b-instruct-q4_k_m.gguf")
)
TTS_ENGINE = os.environ.get("ASSISTANT_TTS_ENGINE", "auto")  # auto | edge | sapi | piper
EDGE_VOICES = {
    "ru": os.environ.get("ASSISTANT_EDGE_RU", "ru-RU-SvetlanaNeural"),
    "en": os.environ.get("ASSISTANT_EDGE_EN", "en-US-AriaNeural"),
}
PIPER_VOICES = {
    "ru": os.environ.get("ASSISTANT_PIPER_RU", str(MODELS_DIR / "ru_RU-irina-medium.onnx")),
    "en": os.environ.get("ASSISTANT_PIPER_EN", str(MODELS_DIR / "en_US-lessac-medium.onnx")),
}

HOTKEY = os.environ.get("ASSISTANT_HOTKEY", "<ctrl>+<shift>+<space>")
CITY = os.environ.get("ASSISTANT_CITY", "Москва")
WAKE_NAME = os.environ.get("ASSISTANT_WAKE_NAME", "атом")
WAKE_VOLUME_THRESHOLD = 500
SAMPLE_RATE = 16000
SILENCE_MS = 1200
VOLUME_THRESHOLD = 300
MAX_RECORD_SEC = 30
