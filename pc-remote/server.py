#!/usr/bin/env python3
"""
PC Remote — управление компьютером с телефона.

Запуск:  python server.py
Затем откройте на телефоне адрес, который напечатается в консоли
(телефон и компьютер должны быть в одной сети, либо в одной сети Tailscale).

Только стандартная библиотека Python 3.8+. Windows — полная поддержка,
Linux — через стандартные утилиты (xdotool, pactl, playerctl, loginctl).
"""
import ctypes
import hmac
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
IS_WIN = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


# ----------------------------------------------------------------- config ---
def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    changed = False
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(16)
        changed = True
    if not cfg.get("port"):
        cfg["port"] = 8765
        changed = True
    if not isinstance(cfg.get("deck"), list):
        cfg["deck"] = default_deck()
        changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def default_deck():
    win = platform.system() == "Windows"
    b = lambda icon, label, color, type_, value: {
        "id": secrets.token_hex(4), "icon": icon, "label": label,
        "color": color, "type": type_, "value": value}
    return [
        b("📁", "Проводник", "#4f8cff", "hotkey", "win+e"),
        b("🧮", "Калькулятор", "#7b61ff", "launch", "calc" if win else "gnome-calculator"),
        b("📝", "Блокнот", "#3ecf8e", "launch", "notepad" if win else "gedit"),
        b("📊", "Диспетчер", "#f5a623", "hotkey", "ctrl+shift+esc"),
        b("✂️", "Скриншот", "#ff5a5f", "hotkey", "win+shift+s"),
        b("🖥", "Рабочий стол", "#20242d", "hotkey", "win+d"),
        b("▶️", "YouTube", "#ff0033", "url", "https://youtube.com"),
        b("🎵", "Пауза", "#20242d", "hotkey", "play"),
        b("🔇", "Без звука", "#20242d", "hotkey", "vol_mute"),
    ]


CFG = load_config()
TOKEN = CFG["token"]
PORT = int(CFG["port"])


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def mac_address():
    n = uuid.getnode()
    return ":".join(f"{(n >> s) & 0xFF:02X}" for s in range(40, -1, -8))


def run(cmd):
    try:
        subprocess.Popen(cmd, shell=isinstance(cmd, str),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


# --------------------------------------------------------- Windows input ---
if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
    MOUSEEVENTF_MOVE = 0x0001
    MOUSE_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010),
                   "middle": (0x0020, 0x0040)}
    MOUSEEVENTF_WHEEL = 0x0800

    def _send(*inputs):
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))

    def _mouse(flags, dx=0, dy=0, data=0):
        i = INPUT(type=INPUT_MOUSE)
        i.u.mi = MOUSEINPUT(dx, dy, ctypes.c_ulong(data & 0xFFFFFFFF).value, flags, 0, 0)
        return i

    def _key(vk, up=False):
        i = INPUT(type=INPUT_KEYBOARD)
        i.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
        return i

    def _uni(code, up=False):
        i = INPUT(type=INPUT_KEYBOARD)
        i.u.ki = KEYBDINPUT(0, code, KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0), 0, 0)
        return i

    def mouse_move(dx, dy):
        _send(_mouse(MOUSEEVENTF_MOVE, int(dx), int(dy)))

    def mouse_click(button="left"):
        down, up = MOUSE_FLAGS.get(button, MOUSE_FLAGS["left"])
        _send(_mouse(down), _mouse(up))

    def mouse_scroll(amount):
        _send(_mouse(MOUSEEVENTF_WHEEL, data=int(amount) * 40))

    def press_combo(vks):
        _send(*[_key(v) for v in vks], *[_key(v, True) for v in reversed(vks)])

    def type_text(text):
        seq = []
        for ch in text:
            if ch == "\n":
                seq += [_key(0x0D), _key(0x0D, True)]
                continue
            b = ch.encode("utf-16-le")
            for k in range(0, len(b), 2):
                code = int.from_bytes(b[k:k + 2], "little")
                seq += [_uni(code), _uni(code, True)]
        if seq:
            _send(*seq)

    VK = {"enter": 0x0D, "backspace": 0x08, "esc": 0x1B, "escape": 0x1B, "tab": 0x09,
          "space": 0x20, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
          "win": 0x5B, "alt": 0x12, "ctrl": 0x11, "control": 0x11, "shift": 0x10,
          "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
          "pageup": 0x21, "pagedown": 0x22, "printscreen": 0x2C, "prtsc": 0x2C,
          "capslock": 0x14, "menu": 0x5D, "pause": 0x13,
          "vol_mute": 0xAD, "vol_down": 0xAE, "vol_up": 0xAF,
          "next": 0xB0, "prev": 0xB1, "stop": 0xB2, "play": 0xB3,
          "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
          ",": 0xBC, ".": 0xBE, "/": 0xBF, "`": 0xC0, "\\": 0xDC}

    def _vk(name):
        name = name.strip().lower()
        if name in VK:
            return VK[name]
        if len(name) == 1 and name.isascii() and name.isalnum():
            return ord(name.upper())
        if name.startswith("f") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
            return 0x70 + int(name[1:]) - 1
        if name.startswith("num") and name[3:].isdigit() and len(name) == 4:
            return 0x60 + int(name[3:])
        raise ValueError(f"Неизвестная клавиша: {name}")

    def key(name):
        parts = [_vk(p) for p in name.split("+") if p.strip()]
        if parts:
            press_combo(parts)

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    def _filetime():
        idle, kern, usr = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(usr))
        f = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
        return f(idle), f(kern) + f(usr)

    def cpu_percent():
        i1, t1 = _filetime()
        time.sleep(0.25)
        i2, t2 = _filetime()
        dt = t2 - t1
        return round(100 * (1 - (i2 - i1) / dt), 1) if dt else 0.0

    def mem_info():
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.dwMemoryLoad, m.ullTotalPhys

    def uptime_seconds():
        kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        return kernel32.GetTickCount64() // 1000


# ----------------------------------------------------------- Linux input ---
elif IS_LINUX:
    def _xdo(*args):
        return run(["xdotool", *args])

    def mouse_move(dx, dy):
        _xdo("mousemove_relative", "--", str(int(dx)), str(int(dy)))

    def mouse_click(button="left"):
        _xdo("click", {"left": "1", "middle": "2", "right": "3"}.get(button, "1"))

    def mouse_scroll(amount):
        amount = int(amount)
        btn = "4" if amount > 0 else "5"
        _xdo("click", "--repeat", str(max(1, abs(amount) // 3)), btn)

    def type_text(text):
        _xdo("type", "--", text)

    XKEYS = {"enter": "Return", "backspace": "BackSpace", "esc": "Escape", "tab": "Tab",
             "space": "space", "left": "Left", "up": "Up", "right": "Right", "down": "Down",
             "win": "super", "alt": "alt", "ctrl": "ctrl", "shift": "shift", "f4": "F4",
             "f5": "F5", "f11": "F11", "delete": "Delete", "d": "d"}

    def key(name):
        if name == "vol_up":
            return run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"])
        if name == "vol_down":
            return run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"])
        if name == "vol_mute":
            return run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        if name in ("play", "next", "prev"):
            return run(["playerctl", {"play": "play-pause", "next": "next", "prev": "previous"}[name]])
        combo = "+".join(XKEYS.get(p.strip().lower(), p.strip()) for p in name.split("+"))
        _xdo("key", combo)

    def _cpu_times():
        with open("/proc/stat") as f:
            vals = list(map(int, f.readline().split()[1:]))
        return vals[3] + vals[4], sum(vals)

    def cpu_percent():
        i1, t1 = _cpu_times()
        time.sleep(0.25)
        i2, t2 = _cpu_times()
        dt = t2 - t1
        return round(100 * (1 - (i2 - i1) / dt), 1) if dt else 0.0

    def mem_info():
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        total = info.get("MemTotal", 1)
        avail = info.get("MemAvailable", 0)
        return round(100 * (1 - avail / total)), total

    def uptime_seconds():
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))

else:
    def _unsupported(*a, **k):
        raise RuntimeError("Эта ОС пока не поддерживается для ввода")
    mouse_move = mouse_click = mouse_scroll = type_text = key = _unsupported
    cpu_percent = lambda: 0.0
    mem_info = lambda: (0, 0)
    uptime_seconds = lambda: 0


# ---------------------------------------------------------------- power ---
def power(action, minutes=0):
    secs = max(0, int(float(minutes) * 60))
    if IS_WIN:
        cmds = {
            "shutdown": f"shutdown /s /t {max(secs, 3)}",
            "reboot": f"shutdown /r /t {max(secs, 3)}",
            "cancel": "shutdown /a",
            "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
            "hibernate": "shutdown /h",
            "lock": None,
            "logoff": "shutdown /l",
            "monitor_off": None,
        }
        if action == "lock":
            return bool(user32.LockWorkStation())
        if action == "monitor_off":
            # WM_SYSCOMMAND / SC_MONITORPOWER / 2 = выключить
            user32.PostMessageW(0xFFFF, 0x0112, 0xF170, 2)
            return True
        cmd = cmds.get(action)
        return run(cmd) if cmd else False
    if IS_LINUX:
        m = max(1, (secs + 59) // 60) if secs else 0
        cmds = {
            "shutdown": ["shutdown", "-h", f"+{m}"] if m else ["systemctl", "poweroff"],
            "reboot": ["shutdown", "-r", f"+{m}"] if m else ["systemctl", "reboot"],
            "cancel": ["shutdown", "-c"],
            "sleep": ["systemctl", "suspend"],
            "hibernate": ["systemctl", "hibernate"],
            "lock": ["loginctl", "lock-session"],
            "logoff": ["loginctl", "terminate-user", os.environ.get("USER", "")],
            "monitor_off": ["xset", "dpms", "force", "off"],
        }
        cmd = cmds.get(action)
        return run(cmd) if cmd else False
    return False


DECK_TYPES = {"hotkey", "launch", "url", "text", "command", "power"}


def run_deck_button(btn):
    t, v = btn.get("type"), str(btn.get("value", "")).strip()
    if not v:
        raise ValueError("У кнопки не задано действие")
    if t == "hotkey":
        for step in v.split(","):          # "ctrl+c, alt+tab, ctrl+v"
            if step.strip():
                key(step.strip())
                time.sleep(0.05)
    elif t == "launch":
        if IS_WIN:
            os.startfile(v)
        else:
            import shlex
            subprocess.Popen(shlex.split(v), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    elif t == "url":
        webbrowser.open(v if "://" in v else "https://" + v)
    elif t == "text":
        type_text(v.replace("\\n", "\n"))
    elif t == "command":
        subprocess.Popen(v, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif t == "power":
        if not power(v):
            raise ValueError("Неизвестное действие питания")
    else:
        raise ValueError("Неизвестный тип кнопки")


def clean_deck(items):
    if not isinstance(items, list) or len(items) > 120:
        raise ValueError("Некорректный список кнопок")
    out = []
    for it in items:
        if not isinstance(it, dict) or it.get("type") not in DECK_TYPES:
            raise ValueError("Некорректная кнопка")
        out.append({
            "id": str(it.get("id") or secrets.token_hex(4))[:16],
            "icon": str(it.get("icon", ""))[:8],
            "label": str(it.get("label", ""))[:40],
            "color": str(it.get("color", "#20242d"))[:9],
            "type": it["type"],
            "value": str(it.get("value", ""))[:1000],
        })
    return out


def screenshot_png():
    try:
        from PIL import ImageGrab  # pip install pillow (необязательно)
    except ImportError:
        return None
    import io
    img = ImageGrab.grab()
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def status():
    load, total = mem_info()
    return {
        "host": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": cpu_percent(),
        "ram": load,
        "ram_total_gb": round(total / 1024 ** 3, 1),
        "uptime": uptime_seconds(),
        "mac": mac_address(),
        "ip": local_ip(),
    }


# ------------------------------------------------------------------ http ---
with open(os.path.join(HERE, "app.html"), encoding="utf-8") as _f:
    APP_HTML = _f.read()

MANIFEST = json.dumps({
    "name": "PC Remote", "short_name": "PC Remote", "start_url": "./",
    "display": "standalone", "background_color": "#0f1115", "theme_color": "#0f1115",
    "icons": [{"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"}],
})

ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<rect width="100" height="100" rx="22" fill="#0f1115"/>'
        '<path d="M50 22v26" stroke="#4f8cff" stroke-width="9" stroke-linecap="round"/>'
        '<path d="M33 32a26 26 0 1 0 34 0" fill="none" stroke="#4f8cff" stroke-width="9" '
        'stroke-linecap="round"/></svg>')


class Handler(BaseHTTPRequestHandler):
    server_version = "PCRemote/1.0"

    def log_message(self, fmt, *args):
        if "/api/mouse" not in (self.path or ""):
            sys.stderr.write("%s  %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        token = self.headers.get("X-Token", "")
        if not token:
            token = parse_qs(urlparse(self.path).query).get("t", [""])[0]
        return hmac.compare_digest(token.encode(), TOKEN.encode())

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, APP_HTML, "text/html; charset=utf-8")
        if path == "/manifest.json":
            return self._send(200, MANIFEST, "application/manifest+json")
        if path == "/icon.svg":
            return self._send(200, ICON, "image/svg+xml")
        if not self._authorized():
            return self._send(403, {"error": "Неверный ключ"})
        if path == "/api/deck":
            return self._send(200, CFG["deck"])
        if path == "/api/status":
            return self._send(200, status())
        if path == "/api/screenshot":
            try:
                img = screenshot_png()
            except Exception as e:
                return self._send(500, {"error": f"Не удалось сделать снимок: {e}"})
            if img is None:
                return self._send(501, {"error": "Установите Pillow: pip install pillow"})
            return self._send(200, img, "image/jpeg")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized():
            return self._send(403, {"error": "Неверный ключ"})
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            data = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except Exception:
            return self._send(400, {"error": "bad json"})
        try:
            if path == "/api/power":
                ok = power(data.get("action", ""), data.get("minutes", 0))
                return self._send(200 if ok else 400, {"ok": ok})
            if path == "/api/mouse/move":
                mouse_move(data.get("dx", 0), data.get("dy", 0))
            elif path == "/api/mouse/click":
                mouse_click(data.get("button", "left"))
            elif path == "/api/mouse/scroll":
                mouse_scroll(data.get("amount", 0))
            elif path == "/api/key":
                key(str(data.get("key", "")))
            elif path == "/api/type":
                type_text(str(data.get("text", ""))[:2000])
            elif path == "/api/deck":
                CFG["deck"] = clean_deck(data.get("deck"))
                save_config(CFG)
                return self._send(200, CFG["deck"])
            elif path == "/api/deck/run":
                btn = next((b for b in CFG["deck"] if b["id"] == data.get("id")), None)
                if not btn:
                    return self._send(404, {"error": "Кнопка не найдена"})
                run_deck_button(btn)
            elif path == "/api/open":
                url = str(data.get("url", "")).strip()
                if not url:
                    return self._send(400, {"error": "empty"})
                if "://" not in url:
                    url = "https://" + url
                if not url.lower().startswith(("http://", "https://")):
                    return self._send(400, {"error": "only http(s)"})
                webbrowser.open(url)
            else:
                return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        self._send(200, {"ok": True})


def main():
    ip = local_ip()
    url = f"http://{ip}:{PORT}/?t={TOKEN}"
    print("=" * 60)
    print(" PC Remote запущен")
    print(f" Откройте на телефоне:  {url}")
    print(f" MAC-адрес (для Wake-on-LAN):  {mac_address()}")
    print(" Ключ хранится в config.json — не показывайте его посторонним.")
    print("=" * 60)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
