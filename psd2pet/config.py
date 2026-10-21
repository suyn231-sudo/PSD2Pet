"""读配置：config.json 里有的用你的，没有的用这里的默认值。缺的字段不会崩，只会按默认来。"""
import copy
import json
from pathlib import Path

from PySide6.QtCore import QRectF

DEFAULTS = {
    "name": "桌宠",
    "slug": "pet",                       # 设置文件夹名：%APPDATA%\\PSD2Pet\\<slug>
    "mode": "sitting",                   # sitting 坐着（键盘/鼠标/手） | standing 站着（全身）
    "parts": "parts.json",
    "parts_dir": "parts",
    "canvas": [0, 0, 1000, 1200],        # 窗口里显示画布的哪一块（PSD 坐标）
    "scale": {"default": None, "min": 0.10, "max": 0.80, "step": 1.08},   # default = 第一次打开的大小
    "sleep_after": 90,                   # 多少秒没碰键鼠就睡觉
    "icon_box": None,                    # 托盘图标截哪块 [左, 上, 边长]；None = 整个画布
    "look": {"neck": [0, 0], "aim_y": 0, "yaw": 25, "pitch": 18, "tanh_x": 450, "tanh_y": 350},
    "fields": {"head": [0, 0, 1, 1], "body": [0, 0, 1, 1]},
    "head": {"shift": 20, "up": 15, "down": 20, "bang_up": 15, "bang_down": 25,
             "lag_max": 4.0, "roll_lag": 1.5, "pin": [0, 0, 150, 0.4]},      # pin = [钉住的 y, 过渡高度, 横向保留, 纵向保留]
    "body": {"desk": None},              # 身体压扁伸缩的支点；None = 画布底边中间
    "eyes": {"mid_x": 0, "brow_y": 0, "centers": [[0, 0], [0, 0]], "pupil": [8, 5],
             "foreshorten": [0.2, 0.05]},
    "mouth": {"center": [0, 0], "top": [0, 0]},
    "swing": {"hang_gravity": 0.7, "tassel_span": 220, "bend_span": 240},
    "layers": [],                        # 变形部件，顺序 = 从下往上画
    "faces": {"white": "eyewhite", "iris": "iris", "line": "eye", "brow": "brow",
              "closed": "eye_closed", "happy": "eye_alt",
              "mouths": ["mouth_a", "mouth_b"], "mouth": "mouth",
              "blink": "eye_closed", "sleep": "eye_closed", "happy_eye": "eye_alt"},
    "desk": {},                          # 坐着模式的桌垫、鼠标、手、小玩偶
    "keys": {"show": True, "pos": [0, 0], "max_w": 800},
    "zzz": {"at": [0, 0], "drift": [100, -200], "color": [110, 130, 190]},
    "blink": [0.055, 0.075],
    "voice": {"open": 0.12, "gates": {"高": 6, "中": 10, "低": 15}},
    "window": {"key_color": [255, 0, 255], "title": None},
    "shadow": {"on": True, "size": [380, 70], "color": [0, 0, 0, 60]},
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """配置目录（models/<名字>）里的 config.json + parts.json + parts/*.png。"""

    def __init__(self, path):
        path = Path(path)
        if path.is_dir():
            path = path / "config.json"
        self.file = path
        self.dir = path.parent
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.data = _merge(DEFAULTS, raw)
        d = self.data
        self.name = d["name"]
        self.slug = d["slug"]
        self.mode = d["mode"]
        self.sitting = self.mode == "sitting"
        self.canvas = QRectF(*d["canvas"])
        self.parts_json = self.dir / d["parts"]
        self.parts_dir = self.dir / d["parts_dir"]
        if not self.parts_json.exists():
            raise FileNotFoundError(f"找不到部件清单：{self.parts_json}")
        meta = json.loads(self.parts_json.read_text(encoding="utf-8"))
        self.meta = {p["id"]: p for p in meta["parts"]}
        self.canvas_full = tuple(meta.get("canvas") or ())
        self.layers = {}
        self.order = []
        for spec in d["layers"]:
            pid = spec["id"]
            if pid not in self.meta:
                continue                      # 这套图没有这个部件就跳过
            self.layers[pid] = spec
            self.order.append(pid)
        self.faces = dict(d["faces"])
        self.open_eyes = [self.faces[k] for k in ("white", "iris", "brow", "line")]
        self.expr = list(dict.fromkeys(self.open_eyes + [self.faces["closed"], self.faces["happy"]]
                                       + list(self.faces["mouths"]) + [self.faces["mouth"]]))
        self.desk = dict(d["desk"] or {}) if self.sitting else {}
        self.pix = [p for p in self.desk.get("parts", ()) if p in self.meta]
        self.keys = dict(d["keys"])
        self.keys_show = bool(self.keys.get("show", True)) and self.sitting
        self.zzz = dict(d["zzz"])
        self.blink = tuple(d["blink"])
        self.voice = dict(d["voice"])
        self.window = dict(d["window"])
        self.shadow = dict(d["shadow"])
        self.scale_min = float(d["scale"]["min"])
        self.scale_max = float(d["scale"]["max"])
        sizes = d.get("sizes") or {}                  # 老配置的小中大档位：拿「中」当默认大小
        default = d["scale"].get("default") or sizes.get("中") or (min(sizes.values()) if sizes else 0.30)
        self.scale_default = min(max(float(default), self.scale_min), self.scale_max)
        self.scale_step = float(d["scale"]["step"])
        self.sleep_after = float(d["sleep_after"])
        self.icon_box = d["icon_box"]
        self.neck = tuple(d["look"]["neck"])
        self.aim_y = d["look"]["aim_y"]
        self.yaw = d["look"]["yaw"]
        self.pitch = d["look"]["pitch"]
        self.tanh = (d["look"]["tanh_x"], d["look"]["tanh_y"])
        self.field = {k: tuple(v) for k, v in d["fields"].items()}
        self.head = dict(d["head"])
        self.body = dict(d["body"])
        self.desk_point = tuple(self.body["desk"]) if self.body.get("desk") else \
            (self.canvas.center().x(), self.canvas.bottom())
        self.eyes = dict(d["eyes"])
        self.mouth = dict(d["mouth"])
        self.swing = dict(d["swing"])
