import urllib.request
from pathlib import Path

from assistant.config import MODELS_DIR

FILES = {
    "ru_RU-irina-medium.onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
    "ru_RU-irina-medium.onnx.json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json",
    "qwen2.5-3b-instruct-q4_k_m.gguf": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
}


def download(name, url):
    dest = MODELS_DIR / name
    if dest.exists() and dest.stat().st_size > 1024 * 1024:
        print(f"есть: {name}")
        return
    print(f"скачиваю {name} ...")
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"  {done * 100 // total}%", end="\r")
    tmp.replace(dest)
    print(f"готово: {name} ({dest.stat().st_size // (1024*1024)} МБ)")


if __name__ == "__main__":
    for name, url in FILES.items():
        download(name, url)
