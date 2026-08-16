import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)

WHISPER_MODEL = os.environ.get("ASSISTANT_WHISPER", "small")
LLM_MODEL_PATH = os.environ.get(
    "ASSISTANT_LLM", str(MODELS_DIR / "qwen2.5-3b-instruct-q4_k_m.gguf")
)
PIPER_VOICE = os.environ.get(
    "ASSISTANT_PIPER", str(MODELS_DIR / "ru_RU-irina-medium.onnx")
)

HOTKEY = os.environ.get("ASSISTANT_HOTKEY", "<ctrl>+<shift>+<space>")
SAMPLE_RATE = 16000
SILENCE_MS = 1200
VOLUME_THRESHOLD = 300
MAX_RECORD_SEC = 30
