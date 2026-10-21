"""界面文字：中文 / English。默认跟着系统语言，菜单里能手动换。"""
import ctypes

TEXT = {
    "size":        ("大小 {p}%（在桌宠身上滚滚轮调）", "Size {p}% (scroll over the pet)"),
    "size_reset":  ("恢复默认大小", "Reset size"),
    "top":         ("置顶", "Always on top"),
    "through":     ("鼠标穿透（点不到桌宠，从托盘关）", "Click-through (turn off from the tray)"),
    "desktop":     ("桌面上显示", "Show on desktop"),
    "keys":        ("显示按键", "Show keys"),
    "wake":        ("叫醒", "Wake up"),
    "sleep":       ("睡觉", "Sleep"),
    "live":        ("直播窗口（OBS 窗口捕获用）", "Live window (for OBS window capture)"),
    "live_title":  ("直播捕获", "Live capture"),
    "voice":       ("声捕（说话就张嘴）", "Lip sync (mouth moves when you talk)"),
    "mic":         ("麦克风", "Microphone"),
    "mic_default": ("默认", "Default"),
    "gate":        ("灵敏度", "Sensitivity"),
    "admin":       ("管理员模式（游戏里也能抓按键）", "Admin mode (catch keys in games)"),
    "lang":        ("语言 Language", "Language 语言"),
    "lang_auto":   ("跟随系统", "System default"),
    "quit":        ("退出", "Quit"),
    "mic_fail":    ("打不开麦克风：", "Can't open the microphone: "),
    "no_model":    ("找不到模型：{p}\n把导入好的模型文件夹（里面有 config.json）改名叫 model，放在程序旁边；"
                    "或者启动时加 --model 指定。",
                    "Model not found: {p}\nRename the imported model folder (the one with config.json) to "
                    "\"model\" and put it next to the program, or start with --model <folder>."),
    "bad_model":   ("模型读不出来：\n", "Can't read the model:\n"),
}

# 声捕灵敏度档位：配置里的名字 → 显示的名字
GATES = {"高": ("高", "High"), "中": ("中", "Medium"), "低": ("低", "Low"),
         "high": ("高", "High"), "mid": ("中", "Medium"), "low": ("低", "Low")}

LANGS = (("zh", "中文"), ("en", "English"))


def system_lang():
    """Windows 界面语言是中文就用中文，其余英文。"""
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "zh" if lid & 0x3FF == 0x04 else "en"
    except Exception:
        return "zh"


def resolve(choice):
    return choice if choice in ("zh", "en") else system_lang()


def tr(lang, key, **kw):
    s = TEXT[key][0 if lang == "zh" else 1]
    return s.format(**kw) if kw else s


def gate_label(lang, name):
    pair = GATES.get(name)
    return pair[0 if lang == "zh" else 1] if pair else name
