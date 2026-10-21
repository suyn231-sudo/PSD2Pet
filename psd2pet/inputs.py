"""全局键盘/鼠标钩子。按键名字只留在内存里给气泡显示，不写盘、不记日志；关掉显示后连名字都不取。"""
import time

MODS = ("Ctrl", "Shift", "Alt", "Win")
KEY_NAMES = {"ctrl": "Ctrl", "ctrl_l": "Ctrl", "ctrl_r": "Ctrl", "shift": "Shift", "shift_l": "Shift",
             "shift_r": "Shift", "alt": "Alt", "alt_l": "Alt", "alt_r": "Alt", "alt_gr": "Alt",
             "cmd": "Win", "cmd_l": "Win", "cmd_r": "Win", "space": "Space", "enter": "Enter",
             "backspace": "Back", "tab": "Tab", "esc": "Esc", "caps_lock": "Caps", "delete": "Del",
             "insert": "Ins", "home": "Home", "end": "End", "page_up": "PgUp", "page_down": "PgDn",
             "up": "↑", "down": "↓", "left": "←", "right": "→", "menu": "Menu",
             "print_screen": "PrtSc", "num_lock": "NumLk", "scroll_lock": "ScrLk", "pause": "Pause"}
VK_NAMES = {0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.", 0x6F: "Num/",
            0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
            0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}


def key_id(key):
    name = getattr(key, "name", None)
    if name:
        return name
    return key.vk if getattr(key, "vk", None) is not None else key.char


def key_label(key):
    name = getattr(key, "name", None)
    if name:
        if name in KEY_NAMES:
            return KEY_NAMES[name]
        if name[0] == "f" and name[1:].isdigit():
            return name.upper()
        return name.replace("_", " ").title()
    vk = getattr(key, "vk", None)
    if vk is not None:
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            return chr(vk)
        if 0x60 <= vk <= 0x69:
            return f"Num{vk - 0x60}"
        if vk in VK_NAMES:
            return VK_NAMES[vk]
    ch = getattr(key, "char", None)
    if ch and ch.isprintable():
        return ch.upper()
    return "?"


class Inputs:
    """pynput 的全局监听。没装 pynput 或系统不让监听时，自动退化成「只有鼠标位置」也能用。"""

    def __init__(self):
        self.pressed = {}
        self.seq = 0
        self.key_count = 0
        self.last_key = -99.0
        self.last_input = time.monotonic()
        self.mouse_down = False
        self.show_names = True
        self.key_text, self.key_t, self.key_pop = "", -99.0, -99.0
        self.ok = False

    def start(self):
        try:
            from pynput import keyboard, mouse
        except ImportError:
            return False
        try:
            self.kb = keyboard.Listener(on_press=self._kp, on_release=self._kr)
            self.ms = mouse.Listener(on_click=self._click)
            for lis in (self.kb, self.ms):
                lis.daemon = True
                lis.start()
            self.ok = True
        except Exception:
            self.ok = False
        return self.ok

    def stop(self):
        for name in ("kb", "ms"):
            lis = getattr(self, name, None)
            if lis is not None:
                try:
                    lis.stop()
                except Exception:
                    pass

    def _kp(self, key):
        now = time.monotonic()
        kid = key_id(key)
        if kid not in self.pressed:              # 长按的自动重复不算新按键
            self.seq += 1
            self.key_count += 1
            self.pressed[kid] = (self.seq, key_label(key) if self.show_names else "")
            self.key_pop = now
        self.last_key = self.last_input = now
        if self.show_names:
            held = sorted(self.pressed.values(), key=lambda v: (v[1] not in MODS, v[0]))
            self.key_text = " + ".join(v[1] for v in held if v[1])
            self.key_t = now

    def _kr(self, key):
        self.pressed.pop(key_id(key), None)
        self.key_t = time.monotonic()

    def _click(self, _x, _y, _button, pressed):
        self.mouse_down = pressed
        self.last_input = time.monotonic()
