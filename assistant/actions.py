import csv
import ctypes
import datetime
import inspect
import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from html.parser import HTMLParser
from pathlib import Path

import psutil
from pynput import mouse
from pynput.keyboard import Controller, Key

from assistant import i18n, tts
from assistant.config import BASE_DIR, CITY
from assistant.i18n import L

_exit_event = threading.Event()

_shell = None


def _get_shell():
    global _shell
    if _shell is None:
        import comtypes.client

        _shell = comtypes.client.Dispatch("WScript.Shell")
    return _shell


def _lnk_target(path):
    try:
        return _get_shell().CreateShortcut(str(path)).TargetPath or ""
    except Exception:
        return ""


def _iter_lnk_dirs():
    dirs = [
        Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.path.expanduser("~")) / "Desktop",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
    ]
    for d in dirs:
        if d.is_dir():
            yield d


def _rank(stem, name_l):
    if stem == name_l:
        return 3
    if stem.startswith(name_l):
        return 2
    return 1


def _search_lnk(name):
    name_l = name.lower()
    best = None
    for base in _iter_lnk_dirs():
        for lnk in base.rglob("*.lnk"):
            stem = lnk.stem.lower()
            if name_l not in stem:
                continue
            target = _lnk_target(lnk).lower()
            if target.startswith(("http://", "https://", "steam:", "minecraft:")):
                continue
            if best is None or _rank(stem, name_l) > _rank(best[1], name_l):
                best = (str(lnk), stem)
    return best[0] if best else None


def _find_exe(name):
    where = subprocess.run(
        ["where.exe", name], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
    )
    if where.returncode == 0:
        return where.stdout.strip().splitlines()[0]
    return None


_uwp_cache = None


def _uwp_apps():
    global _uwp_cache
    if _uwp_cache is None:
        try:
            out = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Csv -NoTypeInformation"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
            rows = []
            for line in csv.reader(out.splitlines()):
                if len(line) >= 2 and line[0] and line[1] and line[0] != "Name":
                    rows.append((line[0], line[1]))
            _uwp_cache = rows
        except Exception:
            _uwp_cache = []
    return _uwp_cache


def _search_uwp(name):
    name_l = name.lower()
    name_t = _translit(name)
    best = None
    for n, appid in _uwp_apps():
        nl = n.lower()
        if name_l in nl or (name_t and name_t in nl):
            if best is None or _rank(nl, name_l) > _rank(best[1], name_l):
                best = (appid, nl)
    return best


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ы": "y", "ь": "", "ъ": "", "э": "e", "ю": "yu", "я": "ya",
}


def _translit(text):
    return "".join(_TRANSLIT.get(ch, ch) for ch in text.lower())


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[len(b)]


def _fuzzy_hit(query, candidate):
    if query in candidate:
        return True
    q = query
    if len(q) < 4:
        return False
    limit = max(1, len(q) // 3)
    if len(candidate) >= len(q):
        for i in range(len(candidate) - len(q) + 1):
            if _edit_distance(q, candidate[i : i + len(q)]) <= limit:
                return True
    return False


def _search_steam(name):
    name_l = _translit(name)
    try:
        vdf = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam" / "steamapps" / "libraryfolders.vdf"
        libs = [vdf.parent]
        if vdf.is_file():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                p = Path(m.group(1)) / "steamapps"
                if p.is_dir():
                    libs.append(p)
        best = None
        for lib in libs:
            if not lib.is_dir():
                continue
            for acf in lib.glob("appmanifest_*.acf"):
                try:
                    t = acf.read_text(encoding="utf-8", errors="ignore")
                    m = re.search(r'"name"\s+"([^"]+)"', t)
                    mid = re.search(r'"appid"\s+"(\d+)"', t)
                    if not (m and mid):
                        continue
                    nm = m.group(1).strip()
                    if _fuzzy_hit(name_l, nm.lower()):
                        if best is None or _rank(nm.lower(), name_l) > _rank(best[1], name_l):
                            best = (mid.group(1), nm)
                except Exception:
                    continue
        return best
    except Exception:
        return None


def _ps_run(script):
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
    )


_NAME_MAP = {
    "блокнот": "notepad",
    "калькулятор": "calculator",
    "проводник": "explorer",
    "файловый менеджер": "explorer",
    "стим": "steam",
    "телеграм": "telegram",
    "дискорд": "discord",
    "спотифай": "spotify",
    "ворд": "winword",
    "эксель": "excel",
    "пейнт": "mspaint",
    "фотошоп": "photoshop",
}


def close_app(name):
    import ctypes
    from ctypes import wintypes

    name = (name or "").strip().strip('"').lower()
    if not name:
        return L("Какое приложение закрыть?", "Which app should I close?")
    name_l = name.removesuffix(".exe")
    if name_l in _NAME_MAP:
        name_l = _NAME_MAP[name_l]
    user32 = ctypes.windll.user32

    def close_by_title():
        closed = 0
        titles = []

        def _enum(hwnd, _):
            nonlocal closed
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if not title:
                return True
            titles.append(title)
            if name_l in title.lower():
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
                closed += 1
            return True

        user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(_enum), 0)
        return closed, titles

    closed, titles = close_by_title()
    if closed:
        return L(f"Закрываю {name}", f"Closing {name}")
    found = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            pn = (p.info["name"] or "").lower().removesuffix(".exe")
            if name_l == pn or (len(name_l) >= 4 and name_l in pn):
                found.append(p.info["pid"])
        except Exception:
            pass
    if not found:
        if titles:
            return L(
                f"Не нашёл приложение {name}. Открыты: {', '.join(titles[:5])}",
                f"Could not find {name}. Open windows: {', '.join(titles[:5])}",
            )
        return L(f"Не нашёл запущенное приложение {name}", f"Could not find a running app {name}")
    for pid in found:
        try:
            psutil.Process(pid).terminate()
        except Exception:
            pass
    return L(f"Закрываю {name}", f"Closing {name}")


def _set_volume(value):
    try:
        from pycaw.pycaw import AudioUtilities

        dev = AudioUtilities.GetSpeakers()
        if dev is None:
            return L("Нет аудиоустройства", "No audio device")
        v = dev.EndpointVolume
        cur = v.GetMasterVolumeLevelScalar() * 100.0
        if value == "up":
            value = min(100, cur + 10)
        elif value == "down":
            value = max(0, cur - 10)
        elif value == "mute":
            v.SetMute(1, None)
            return L("Звук выключен", "Sound muted")
        elif value == "unmute":
            v.SetMute(0, None)
            return L("Звук включён", "Sound unmuted")
        pct = max(0, min(100, float(value)))
        v.SetMasterVolumeLevelScalar(pct / 100.0, None)
        return L(f"Громкость {pct:.0f} процентов", f"Volume set to {pct:.0f} percent")
    except Exception as exc:
        return L(f"Не удалось изменить громкость: {exc}", f"Could not change volume: {exc}")


def _set_brightness(value):
    try:
        pct = max(0, min(100, int(float(value))))
        r = _ps_run(
            f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {pct})"
        )
        if r.returncode != 0 or r.stderr.strip():
            return L("Не удалось изменить яркость (не поддерживается)", "Could not change brightness (not supported)")
        return L(f"Яркость {pct} процентов", f"Brightness set to {pct} percent")
    except Exception:
        return L("Не удалось изменить яркость", "Could not change brightness")


def _net_adapter(desc_re):
    r = _ps_run(f"(Get-NetAdapter -Physical | Where-Object {{$_.InterfaceDescription -match '{desc_re}'}} | Select-Object -First 1).Name")
    return r.stdout.strip() if r.returncode == 0 else ""


def _set_wifi(value):
    if value in ("on", "вкл", "включи", "включить", "1"):
        want = "enabled"
    elif value in ("off", "выкл", "выключи", "выключить", "0"):
        want = "disabled"
    else:
        return L("Скажите: включить или выключить вайфай", "Say: turn wifi on or off")
    name = _net_adapter("Wireless|WiFi|802.11|WLAN")
    if not name:
        return L("Не нашёл Wi-Fi адаптер", "Could not find a Wi-Fi adapter")
    r = subprocess.run(["netsh", "interface", "set", "interface", f"name={name}", f"admin={want}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode != 0:
        return L("Нужны права администратора для управления вайфаем",
                 "Administrator rights are required to control Wi-Fi")
    return L(f"Вайфай {'включён' if want == 'enabled' else 'выключен'}",
             f"Wi-Fi turned {'on' if want == 'enabled' else 'off'}")


def _set_bluetooth(value):
    if value in ("on", "вкл", "включи", "включить", "1"):
        want = "Enabled"
    elif value in ("off", "выкл", "выключи", "выключить", "0"):
        want = "Disabled"
    else:
        return L("Скажите: включить или выключить блютуз", "Say: turn bluetooth on or off")
    r = _ps_run(
        "$bt = Get-PnpDevice -Class Bluetooth -PresentOnly | Where-Object {$_.FriendlyName -match 'Radio'} | Select-Object -First 1;"
        f"if ($bt) {{ Set-PnpDevice -InstanceId $bt.InstanceId -Status {want} }} else {{ 'NOT_FOUND' }}"
    )
    out = (r.stdout + r.stderr).strip()
    if "NOT_FOUND" in out:
        return L("Не нашёл блютуз-адаптер", "Could not find a Bluetooth adapter")
    if "Access" in out or "отказано" in out or (r.returncode != 0 and not out):
        return L("Нужны права администратора для управления блютузом",
                 "Administrator rights are required to control Bluetooth")
    return L(f"Блютуз {'включён' if want == 'Enabled' else 'выключен'}",
             f"Bluetooth turned {'on' if want == 'Enabled' else 'off'}")


def _set_theme(value):
    if value in ("dark", "тёмн", "темн", "тёмная", "темная", "чёрн", "0"):
        v = 0
        label = L("тёмную тему", "dark theme")
    elif value in ("light", "светл", "бел", "светлая", "1"):
        v = 1
        label = L("светлую тему", "light theme")
    else:
        return L("Скажите: тёмная или светлая тема", "Say: dark or light theme")
    _ps_run(
        f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name AppsUseLightTheme -Value {v};"
        f"Set-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name SystemUsesLightTheme -Value {v}"
    )
    return L(f"Включил {label}", f"Enabled {label}")


def _display_off():
    try:
        import ctypes

        HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER = 0xFFFF, 0x0112, 0xF170
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2, SMTO_ABORTIFHUNG, 3000, ctypes.byref(ctypes.c_long())
        )
        return L("Экран погас", "Screen turned off")
    except Exception:
        return L("Не удалось погасить экран", "Could not turn off the screen")


class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort),
        ("dmSize", ctypes.c_ushort),
        ("dmDriverExtra", ctypes.c_ushort),
        ("dmFields", ctypes.c_uint),
        ("dmPosition_x", ctypes.c_long),
        ("dmPosition_y", ctypes.c_long),
        ("dmDisplayOrientation", ctypes.c_uint),
        ("dmDisplayFixedOutput", ctypes.c_uint),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", ctypes.c_ushort),
        ("dmBitsPerPel", ctypes.c_uint),
        ("dmPelsWidth", ctypes.c_uint),
        ("dmPelsHeight", ctypes.c_uint),
        ("dmDisplayFlags", ctypes.c_uint),
        ("dmDisplayFrequency", ctypes.c_uint),
        ("dmICMMethod", ctypes.c_uint),
        ("dmICMIntent", ctypes.c_uint),
        ("dmMediaType", ctypes.c_uint),
        ("dmDitherType", ctypes.c_uint),
        ("dmReserved1", ctypes.c_uint),
        ("dmReserved2", ctypes.c_uint),
        ("dmPanningWidth", ctypes.c_uint),
        ("dmPanningHeight", ctypes.c_uint),
    ]


def _list_modes():
    import ctypes

    user32 = ctypes.windll.user32
    modes = []
    seen = set()
    for i in range(512):
        dm = _DEVMODEW()
        dm.dmSize = ctypes.sizeof(_DEVMODEW)
        if not user32.EnumDisplaySettingsW(None, i, ctypes.byref(dm)):
            break
        key = (dm.dmPelsWidth, dm.dmPelsHeight)
        if key[0] and key not in seen:
            seen.add(key)
            modes.append(key)
    modes.sort(key=lambda k: k[0] * k[1], reverse=True)
    return modes


def _parse_res(value):
    v = value.strip().lower().replace("*", "x").replace("х", "x")
    m = re.match(r"^(\d+)\s*x\s*(\d+)$", v)
    if m:
        return int(m.group(1)), int(m.group(2))
    common = {"1080p": (1920, 1080), "1440p": (2560, 1440), "2160p": (3840, 2160), "4k": (3840, 2160)}
    return common.get(v, (None, None))


_res_prev = None


def _set_resolution(value):
    global _res_prev
    import ctypes

    ENUM_CURRENT = -1
    CDS_TEST = 0x0002
    CDS_UPDATEREGISTRY = 0x0001
    DM_PELSWIDTH = 0x00080000
    DM_PELSHEIGHT = 0x00100000
    DISP_CHANGE_SUCCESSFUL = 0
    user32 = ctypes.windll.user32

    def cur():
        dm = _DEVMODEW()
        dm.dmSize = ctypes.sizeof(_DEVMODEW)
        if user32.EnumDisplaySettingsW(None, ENUM_CURRENT, ctypes.byref(dm)):
            return dm
        return None

    try:
        now = cur()
        if now is None:
            return L("Не удалось получить текущее разрешение", "Could not read the current resolution")
        now_w, now_h = now.dmPelsWidth, now.dmPelsHeight
        value = (value or "").strip().lower()
        if not value or value in ("сейчас", "какое", "current"):
            return L(f"Сейчас разрешение {now_w}x{now_h}", f"Current resolution is {now_w}x{now_h}")
        if value in ("верни", "восстанови", "назад", "default", "обратно"):
            if _res_prev:
                w, h = _res_prev
            else:
                return L(f"Я не меняла разрешение. Сейчас {now_w}x{now_h}", f"I did not change the resolution. It is {now_w}x{now_h}")
        else:
            w, h = _parse_res(value)
            if not w or not h:
                modes = _list_modes()
                listed = ", ".join(f"{a}x{b}" for a, b in modes[:8])
                return L(
                    f"Не понял разрешение {value}. Доступные: {listed}",
                    f"Unknown resolution {value}. Available: {listed}",
                )
        dm = _DEVMODEW()
        dm.dmSize = ctypes.sizeof(_DEVMODEW)
        dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT
        dm.dmPelsWidth = w
        dm.dmPelsHeight = h
        res = user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, CDS_TEST, None)
        if res != DISP_CHANGE_SUCCESSFUL:
            modes = _list_modes()
            listed = ", ".join(f"{a}x{b}" for a, b in modes[:8])
            return L(
                f"Разрешение {w}x{h} не поддерживается. Доступные: {listed}",
                f"Resolution {w}x{h} is not supported. Available: {listed}",
            )
        if value not in ("верни", "восстанови", "назад", "default", "обратно"):
            _res_prev = (now_w, now_h)
        user32.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None)
        return L(f"Разрешение {w}x{h}", f"Resolution set to {w}x{h}")
    except Exception:
        return L("Не удалось изменить разрешение", "Could not change the resolution")


def _sleep_now():
    try:
        import ctypes

        ctypes.windll.powrprof.SetSuspendState(0, 1, 0)
        return L("Усыпляю компьютер", "Putting the computer to sleep")
    except Exception:
        return L("Не удалось усыпить компьютер", "Could not put the computer to sleep")


def system_setting(setting, value=None):
    s = (setting or "").strip().lower()
    v = (value or "").strip().lower()
    if s in ("volume", "громкость", "звук", "sound"):
        return _set_volume(v or "50")
    if s in ("громче", "louder", "громкость выше"):
        return _set_volume("up")
    if s in ("тише", "quieter", "громкость ниже"):
        return _set_volume("down")
    if s in ("brightness", "яркость", "яркост"):
        return _set_brightness(v or "50")
    if s in ("wifi", "вайфай", "wi-fi"):
        return _set_wifi(v)
    if s in ("bluetooth", "блютуз", "блuetooth", "bt"):
        return _set_bluetooth(v)
    if s in ("theme", "тема"):
        return _set_theme(v)
    if "resolution" in s or "разрешени" in s:
        return _set_resolution(v)
    if s in ("display", "экран", "монитор", "дисплей"):
        return _display_off()
    if s in ("sleep", "сон", "спать"):
        return _sleep_now()
    if s in ("restart", "перезагруз", "перезагрузка", "reboot"):
        if v in ("confirm", "да", "подтверждаю", "yes", "ага"):
            subprocess.Popen(["shutdown", "/r", "/t", "30"])
            return L("Компьютер перезагрузится через тридцать секунд",
                     "The computer will restart in thirty seconds")
        return L("Точно перезагрузить компьютер? Скажите: подтверждаю",
                 "Restart the computer? Say: confirm")
    return L(
        f"Не знаю настройку {setting}. Можно: громкость, яркость, вайфай, блютуз, тема, разрешение экрана, экран, сон, перезагрузка",
        f"Unknown setting {setting}. Try: volume, brightness, wifi, bluetooth, theme, resolution, display, sleep, restart",
    )


def _decode(raw, headers=None):
    charset = None
    if headers:
        ctype = headers.get("Content-Type") or ""
        m = re.search(r"charset=([\w-]+)", ctype, re.I)
        if m:
            charset = m.group(1).lower()
    try:
        s = raw.decode("utf-8")
        if any(c in s for c in ("\u00c3", "\u00d0", "\u00d1", "\u00d2")):
            raise UnicodeDecodeError("utf-8", raw, 0, 1, "mojibake")
        return s
    except UnicodeDecodeError:
        for enc in (charset or "", "windows-1251", "cp1251"):
            if not enc:
                continue
            try:
                return raw.decode(enc, errors="replace")
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")


def _fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
    })
    with urllib.request.urlopen(req, timeout=12) as r:
        return r.read(600000), dict(r.headers)


class _TextExtract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def _html_to_text(html):
    p = _TextExtract()
    p.feed(html)
    lines = [" ".join(line.split()) for line in "".join(p.parts).split("\n")]
    return "\n".join(line for line in lines if line)


def _ddg_search(query):
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)
    raw, headers = _fetch(url)
    html = _decode(raw, headers)
    links = re.findall(r'<a rel="nofollow" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    snippets = re.findall(r"<td class='result-snippet'>(.*?)</td>", html, re.S)
    results = []
    seen = set()
    for i, (href, title) in enumerate(links):
        real = None
        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            if qs.get("uddg"):
                real = qs["uddg"][0]
        href = real or href.strip()
        if not href.startswith("http") or "duckduckgo.com" in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        title = re.sub(r"<[^>]+>", "", title).strip()
        snip = ""
        if i < len(snippets):
            snip = re.sub(r"<[^>]+>", "", snippets[i]).strip()
        results.append((title or href, href, snip))
        if len(results) >= 5:
            break
    return results


def _bing_search(query):
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
    raw, headers = _fetch(url)
    html = _decode(raw, headers)
    results = []
    for m in re.finditer(r'<li class="b_algo".*?<h2><a href="([^"]+)"[^>]*>(.*?)</a></h2>\s*<p[^>]*>(.*?)</p>', html, re.S):
        href, title, snip = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip(), re.sub(r"<[^>]+>", "", m.group(3)).strip()
        if href.startswith("http"):
            results.append((title or href, href, snip))
        if len(results) >= 5:
            break
    return results


def _search(query):
    try:
        res = _ddg_search(query)
        if res:
            return res
    except Exception:
        pass
    try:
        return _bing_search(query)
    except Exception:
        return []


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "AtomAssistant"


def _autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}"'
    return f'"{os.path.abspath(sys.executable)}" "{BASE_DIR / "run_app.py"}"'


def is_autostart():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _AUTOSTART_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled):
    import winreg

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        if enabled:
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def _my_ip():
    try:
        import urllib.request

        with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
            ip = r.read().decode().strip()
        if ip:
            return ip
    except Exception:
        pass
    return None


_CURRENCY_NAMES = {
    "usd": ("доллар", ("доллар", "доллара", "долларов")),
    "eur": ("евро", ("евро", "евро", "евро")),
    "uah": ("гривна", ("гривна", "гривны", "гривен")),
    "rub": ("рубль", ("рубль", "рубля", "рублей")),
    "cny": ("юань", ("юань", "юаня", "юаней")),
    "gbp": ("фунт", ("фунт", "фунта", "фунтов")),
    "jpy": ("иена", ("иена", "иены", "иен")),
    "chf": ("франк", ("франк", "франка", "франков")),
    "try": ("лира", ("лира", "лиры", "лир")),
    "pln": ("злотый", ("злотый", "злотых", "злотых")),
    "kzt": ("тенге", ("тенге", "тенге", "тенге")),
    "byn": ("белорусский рубль", ("белорусский рубль", "белорусских рубля", "белорусских рублей")),
    "btc": ("биткоин", ("биткоин", "биткоина", "биткоинов")),
}

_CURRENCY_ALIASES = {
    "доллар": "usd", "доллара": "usd", "долларов": "usd", "бакс": "usd", "баксов": "usd",
    "евро": "eur",
    "гривн": "uah", "гривен": "uah",
    "рубл": "rub", "рублей": "rub",
    "юан": "cny",
    "фунт": "gbp",
    "иен": "jpy",
    "франк": "chf",
    "лир": "try",
    "злот": "pln",
    "тенге": "kzt",
    "биткоин": "btc", "bitcoin": "btc",
    "dollar": "usd", "euro": "eur", "hryvnia": "uah", "ruble": "rub",
    "yuan": "cny", "pound": "gbp", "yen": "jpy", "franc": "chf", "lira": "try", "zloty": "pln",
}

_CURRENCY_CODES = frozenset(_CURRENCY_NAMES) - {"btc"}


def _find_currency(text):
    t = (text or "").lower()
    found = []
    for code in _CURRENCY_CODES:
        if f" {code} " in f" {t} ":
            found.append(code)
    for alias, code in _CURRENCY_ALIASES.items():
        if alias in t and code not in found:
            found.append(code)
    return found


def _fetch_rate(base, quote):
    for url in (f"https://open.er-api.com/v6/latest/{base}",
                f"https://api.frankfurter.app/latest?from={base}"):
        try:
            raw, headers = _fetch(url)
            data = json.loads(_decode(raw, headers))
            r = data.get("rates", {})
            if quote in r:
                return float(r[quote])
        except Exception:
            continue
    return None


def _fetch_btc(quote):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies={quote.lower()}"
    try:
        raw, headers = _fetch(url)
        data = json.loads(_decode(raw, headers))
        v = data.get("bitcoin", {}).get(quote.lower())
        if v is not None:
            return float(v)
    except Exception:
        pass
    return None


def _plural(n, forms):
    i = int(n)
    if i != n:
        return forms[1]
    if i % 100 in (11, 12, 13, 14):
        return forms[2]
    if i % 10 == 1:
        return forms[0]
    if i % 10 in (2, 3, 4):
        return forms[1]
    return forms[2]


def get_currency(base="", quote="", value=""):
    texts = " ".join(x for x in (base, quote, value) if x)
    found = _find_currency(texts)
    if not found:
        return L("Какую валюту? Например: курс доллара к евро",
                 "Which currency? For example: dollar to euro rate")
    if len(found) == 1:
        base_c, quote_c = found[0], "rub"
    else:
        base_c, quote_c = found[0], found[1]
    if base_c == "rub" and quote_c != "rub":
        base_c, quote_c = quote_c, "rub"
    rate = _fetch_btc(quote_c) if base_c == "btc" else _fetch_rate(base_c.upper(), quote_c.upper())
    if rate is None:
        return L("Не удалось получить курс валют", "Could not fetch the currency rate")
    if rate >= 1000:
        rate = round(rate)
    name_b = _CURRENCY_NAMES[base_c][0]
    name_q = _CURRENCY_NAMES[quote_c][0]
    if i18n.get_language() == "en":
        plural_q = name_q if name_q in ("yen", "yuan", "tenge") else name_q + "s"
        return f"1 {name_b} = {rate:.2f} {plural_q}"
    form_q = _plural(rate, _CURRENCY_NAMES[quote_c][1])
    text = f"{rate:.2f}".replace(".", ",") if rate % 1 else str(int(rate))
    return f"1 {name_b} = {text} {form_q}"


def web_search(query):
    q = (query or "").strip()
    if not q:
        return L("Что найти?", "What should I search for?")
    results = _search(q)
    if not results:
        return L("Не удалось найти ничего в интернете", "Could not find anything on the internet")
    parts = []
    for i, (title, href, snip) in enumerate(results, 1):
        parts.append(f"{i}. {title} — {href}")
        if snip:
            parts.append(f"   {snip}")
    return "\n".join(parts)


def _web_lookup(query, page=0):
    results = _search(query)
    if not results:
        return None
    attempts = 0
    for i, (title, href, _snip) in enumerate(results):
        if i < page:
            continue
        attempts += 1
        if attempts > 3:
            break
        try:
            raw, headers = _fetch(href)
            text = _html_to_text(_decode(raw, headers))
        except Exception:
            continue
        text = re.sub(r"\n{2,}", "\n", text).strip()
        if len(text) < 500:
            continue
        low = text.lower()
        for marker in ("ингредиент", "состав", "ingredients"):
            idx = low.find(marker)
            if idx > 0:
                text = text[idx:]
                break
        if len(text) > 8000:
            text = text[:8000] + "\n..."
        return title, href, text
    return None


def web_query(query):
    q = (query or "").strip()
    if not q:
        return L("Что найти?", "What should I search for?")
    hit = _web_lookup(q, 0)
    if hit is None:
        return L("Не удалось найти ничего в интернете", "Could not find anything on the internet")
    title, href, text = hit
    return f"{title}\n{href}\n\n{text}"


def _launch_uwp(appid):
    os.startfile(f"shell:AppsFolder\\{appid}")


def open_app(name):
    name = name.strip().strip('"')
    if os.path.isfile(name):
        os.startfile(name)
        return L(f"Запускаю {name}", f"Launching {name}")
    lnk = _search_lnk(name)
    if lnk:
        os.startfile(lnk)
        return L(f"Запускаю {name}", f"Launching {name}")
    exe = _find_exe(name)
    if exe:
        subprocess.Popen([exe])
        return L(f"Запускаю {name}", f"Launching {name}")
    uwp = _search_uwp(name)
    if uwp:
        appid, nm = uwp
        _launch_uwp(appid)
        return L(f"Запускаю {nm}", f"Launching {nm}")
    return L(
        f"Не нашёл приложение {name}. Скажите название как в меню Пуск",
        f"Could not find the app {name}. Say its name as it appears in the Start menu",
    )


def open_game(name):
    name = name.strip().strip('"')
    if not name:
        return L("Назовите игру", "Name the game")
    hit = _search_steam(name)
    if hit:
        appid, nm = hit
        os.startfile(f"steam://rungameid/{appid}")
        return L(f"Запускаю игру {nm} через Steam", f"Launching the game {nm} via Steam")
    uwp = _search_uwp(name)
    if uwp:
        appid, nm = uwp
        _launch_uwp(appid)
        return L(f"Запускаю {nm}", f"Launching {nm}")
    lnk = _search_lnk(name)
    if lnk:
        os.startfile(lnk)
        return L(f"Запускаю {name}", f"Launching {name}")
    return L(
        f"Не нашёл игру {name}. Проверьте, что она установлена через Steam или Game Pass",
        f"Could not find the game {name}. Make sure it is installed via Steam or Game Pass",
    )


def open_url(query):
    q = query.strip()
    if not q:
        return L("Нечего открывать", "Nothing to open")
    if "://" not in q and " " in q:
        q = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    elif "." not in q:
        q = "https://www.google.com/search?q=" + urllib.parse.quote(q)
    elif "://" not in q:
        q = "https://" + q
    webbrowser.open(q)
    return L("Открыл в браузере", "Opened in the browser")


def type_text(text):
    kb = Controller()
    for ch in text:
        if ch == "\n":
            kb.press(Key.enter)
            kb.release(Key.enter)
        else:
            kb.type(ch)
    return L("Напечатал", "Typed")


_KEYS = {
    "enter": Key.enter, "return": Key.enter,
    "esc": Key.esc, "escape": Key.esc,
    "tab": Key.tab, "backspace": Key.backspace,
    "delete": Key.delete, "del": Key.delete,
    "space": Key.space,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "home": Key.home, "end": Key.end,
    "pageup": Key.page_up, "pagedown": Key.page_down,
    "ctrl": Key.ctrl, "control": Key.ctrl,
    "alt": Key.alt, "shift": Key.shift,
    "win": Key.cmd, "cmd": Key.cmd, "windows": Key.cmd,
}


def _press_combo(combo):
    kb = Controller()
    keys = []
    for part in combo.split("+"):
        p = part.strip().lower()
        if p in _KEYS:
            keys.append(_KEYS[p])
        elif len(p) == 1:
            keys.append(p)
        else:
            raise ValueError(f"unknown key: {p}")
    for k in keys:
        kb.press(k)
    for k in reversed(keys):
        kb.release(k)


def press_key(keys):
    try:
        _press_combo(keys)
    except Exception:
        return L(
            f"Не понимаю клавишу {keys}. Примеры: enter, esc, tab, ctrl+s, win+d",
            f"Cannot press {keys}. Examples: enter, esc, tab, ctrl+s, win+d",
        )
    return L(f"Нажал {keys}", f"Pressed {keys}")


def close_tab():
    _press_combo("ctrl+w")
    return L("Закрыл вкладку", "Closed the tab")


def new_tab():
    _press_combo("ctrl+t")
    return L("Открыл новую вкладку", "Opened a new tab")


def refresh_page():
    _press_combo("ctrl+r")
    return L("Обновил страницу", "Refreshed the page")


def show_desktop():
    _press_combo("win+d")
    return L("Свернул все окна", "Minimized all windows")


def scroll(direction):
    kb = mouse.Controller()
    d = (direction or "").lower()
    if "верх" in d or "up" in d:
        kb.scroll(0, 3)
        return L("Прокрутил вверх", "Scrolled up")
    kb.scroll(0, -3)
    return L("Прокрутил вниз", "Scrolled down")


def screenshot():
    from PIL import ImageGrab

    shots = Path(os.path.expanduser("~")) / "Pictures"
    shots.mkdir(exist_ok=True)
    path = shots / f"screenshot_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
    ImageGrab.grab().save(path)
    return L(f"Скриншот сохранён: {path}", f"Screenshot saved: {path}")


_WMO = {
    0: ("ясно", "clear"),
    1: ("преимущественно ясно", "mostly clear"),
    2: ("переменная облачность", "partly cloudy"),
    3: ("пасмурно", "overcast"),
    45: ("туман", "fog"),
    48: ("туман", "fog"),
    51: ("лёгкая морось", "light drizzle"),
    53: ("морось", "drizzle"),
    55: ("сильная морось", "heavy drizzle"),
    56: ("ледяная морось", "freezing drizzle"),
    57: ("сильная ледяная морось", "heavy freezing drizzle"),
    61: ("небольшой дождь", "light rain"),
    63: ("дождь", "rain"),
    65: ("сильный дождь", "heavy rain"),
    66: ("ледяной дождь", "freezing rain"),
    67: ("сильный ледяной дождь", "heavy freezing rain"),
    71: ("небольшой снег", "light snow"),
    73: ("снег", "snow"),
    75: ("сильный снег", "heavy snow"),
    77: ("снежная крупа", "snow grains"),
    80: ("небольшие ливни", "light showers"),
    81: ("ливни", "showers"),
    82: ("сильные ливни", "heavy showers"),
    85: ("снежные заряды", "snow showers"),
    86: ("сильные снежные заряды", "heavy snow showers"),
    95: ("гроза", "thunderstorm"),
    96: ("гроза с градом", "thunderstorm with hail"),
    99: ("сильная гроза с градом", "severe thunderstorm with hail"),
}

_MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def set_timer(minutes, message):
    minutes = max(0.1, float(minutes))
    threading.Timer(
        minutes * 60.0,
        lambda: tts.speak(message),
    ).start()
    return L(
        f"Поставил таймер на {minutes:g} минут",
        f"Timer set for {minutes:g} minutes",
    )


def get_time():
    now = datetime.datetime.now()
    if i18n.get_language() == "en":
        return f"It is {now.strftime('%H:%M')}, {now.day} {_MONTHS_EN[now.month - 1]} {now.year}"
    return f"Сейчас {now.strftime('%H:%M')}, {now.day} {_MONTHS_RU[now.month - 1]} {now.year} года"


def system_info():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    if i18n.get_language() == "en":
        parts = [f"CPU load is {cpu:.0f} percent", f"memory usage is {mem.percent:.0f} percent"]
    else:
        parts = [f"Загрузка процессора {cpu:.0f} процентов", f"память занята на {mem.percent:.0f} процентов"]
    try:
        batt = psutil.sensors_battery()
        if batt is not None:
            parts.append(L(
                f"заряд батареи {batt.percent:.0f} процентов",
                f"battery level is {batt.percent:.0f} percent",
            ))
    except Exception:
        pass
    return ", ".join(parts)


def open_folder(path):
    path = os.path.expandvars(os.path.expanduser(path))
    if os.path.isdir(path):
        os.startfile(path)
        return L(f"Открыл папку {path}", f"Opened folder {path}")
    return L(f"Папка не найдена: {path}", f"Folder not found: {path}")


def lock_screen():
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return L("Экран заблокирован", "Screen locked")


def shutdown(confirm=False):
    if not confirm:
        return L(
            "Точно выключить компьютер? Скажите: подтверждаю",
            "Shut down the computer? Say: confirm",
        )
    subprocess.Popen(["shutdown", "/s", "/t", "30"])
    return L(
        "Компьютер выключится через тридцать секунд",
        "The computer will shut down in thirty seconds",
    )


def cancel_shutdown():
    subprocess.Popen(["shutdown", "/a"])
    return L("Отменил выключение", "Shutdown cancelled")


def exit_assistant():
    _exit_event.set()
    return L("До встречи", "See you")


def get_weather(city=None):
    lang = i18n.get_language()
    city = (city or CITY).strip()
    try:
        geo = json.load(
            urllib.request.urlopen(
                "https://geocoding-api.open-meteo.com/v1/search"
                f"?name={urllib.parse.quote(city)}&count=1&language={lang}",
                timeout=10,
            )
        )
        results = geo.get("results") or []
        if not results:
            return L(f"Не нашёл город {city}", f"Could not find the city {city}")
        r = results[0]
        w = json.load(
            urllib.request.urlopen(
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={r['latitude']}&longitude={r['longitude']}"
                "&current=temperature_2m,apparent_temperature,wind_speed_10m,weather_code",
                timeout=10,
            )
        )
        cur = w["current"]
        name = r.get("name") or city
        desc = _WMO.get(cur["weather_code"], ("переменчивая погода", "changeable weather"))[0 if lang == "ru" else 1]
        if lang == "en":
            return (
                f"In {name} it is now {cur['temperature_2m']:.0f} degrees, {desc}, "
                f"feels like {cur['apparent_temperature']:.0f}, "
                f"wind {cur['wind_speed_10m']:.0f} meters per second"
            )
        return (
            f"В городе {name} сейчас {cur['temperature_2m']:.0f} градусов, {desc}, "
            f"ощущается как {cur['apparent_temperature']:.0f}, "
            f"ветер {cur['wind_speed_10m']:.0f} метров в секунду"
        )
    except Exception:
        return L(
            "Не удалось получить данные о погоде, проверьте интернет",
            "Could not get weather data, check your internet connection",
        )


REGISTRY = {
    "open_app": (open_app, "запустить приложение или программу по имени или пути, params: name"),
    "open_game": (open_game, "запустить игру (Steam, Game Pass или ярлык), params: name"),
    "close_app": (close_app, "закрыть запущенное приложение или программу по имени, params: name"),
    "system_setting": (system_setting, "изменить настройку системы: громкость, яркость, вайфай, блютуз, тема, экран, сон, перезагрузка, params: setting и value"),
    "web_search": (web_search, "найти информацию в интернете и вернуть ссылки, params: query"),
    "web_query": (web_query, "найти информацию в интернете, открыть лучший результат и вернуть его текст, params: query"),
    "open_url": (open_url, "открыть сайт или поисковый запрос в браузере, params: query"),
    "type_text": (type_text, "напечатать текст в активном текстовом поле с клавиатуры, params: text"),
    "press_key": (press_key, "нажать клавишу или комбинацию клавиш, например: enter, esc, tab, ctrl+s, win+d, ctrl+w, params: keys"),
    "close_tab": (close_tab, "закрыть активную вкладку в браузере, params: нет"),
    "new_tab": (new_tab, "открыть новую вкладку в браузере, params: нет"),
    "refresh_page": (refresh_page, "обновить страницу в браузере, params: нет"),
    "show_desktop": (show_desktop, "свернуть все окна и показать рабочий стол, params: нет"),
    "scroll": (scroll, "прокрутить страницу, params: direction (вверх или вниз)"),
    "screenshot": (screenshot, "сделать скриншот экрана и сохранить его, params: нет"),
    "get_weather": (get_weather, "узнать текущую погоду в городе и озвучить её, params: city (если город не назван — город пользователя)"),
    "get_currency": (get_currency, "узнать курс валют, params: base (код или название валюты), quote (валюта, к которой курс) или value (например 'доллар к гривне')"),
    "set_timer": (set_timer, "поставить таймер, params: minutes (число) и message (что напомнить)"),
    "get_time": (get_time, "сообщить текущее время и дату, params: нет"),
    "system_info": (system_info, "сообщить нагрузку на процессор, память и заряд батареи, params: нет"),
    "open_folder": (open_folder, "открыть папку в проводнике, params: path"),
    "lock_screen": (lock_screen, "заблокировать экран, params: нет"),
    "shutdown": (shutdown, "выключить компьютер (только по явной просьбе с подтверждением), params: confirm"),
    "cancel_shutdown": (cancel_shutdown, "отменить выключение компьютера, params: нет"),
    "exit_assistant": (exit_assistant, "завершить работу ассистента, params: нет"),
}


def execute(tool, params=None):
    fn = REGISTRY.get(tool)
    if fn is None:
        return L(f"Не знаю такого действия: {tool}", f"Unknown action: {tool}")
    params = params or {}
    sig = inspect.signature(fn[0])
    filtered = {k: v for k, v in params.items() if k in sig.parameters}
    return fn[0](**filtered)


def wait_exit(timeout=None):
    return _exit_event.wait(timeout)