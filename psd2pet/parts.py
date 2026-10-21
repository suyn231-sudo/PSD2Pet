"""一张部件图 = 预乘 BGRA 数组 + 它在画布上的位置 + 这一层怎么动。"""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap


class Layer:
    def __init__(self, meta, spec, parts_dir, factor, pad):
        self.pid = meta["id"]
        self.x, self.y, self.w, self.h = meta["x"], meta["y"], meta["w"], meta["h"]
        self.blend = meta.get("blend", "normal")
        path = parts_dir / f"{self.pid}.png"
        img = QImage(str(path))
        if img.isNull():
            raise FileNotFoundError(f"缺部件图：{path}")
        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        sw, sh = max(1, round(self.w * factor)), max(1, round(self.h * factor))
        img = img.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation) \
            .convertToFormat(QImage.Format_ARGB32_Premultiplied)
        a = np.frombuffer(img.constBits(), np.uint8).reshape(sh, img.bytesPerLine() // 4, 4)[:, :sw]
        self.src = np.zeros((sh + 2 * pad, sw + 2 * pad, 4), np.uint8)
        self.src[pad:pad + sh, pad:pad + sw] = a
        self.fx, self.fy = sw / self.w, sh / self.h

        self.group = spec["group"]
        self.zx, self.zy = spec["z"]
        self.cx, self.cy = spec["bulge"]
        self.field = spec["field"]
        self.hang = spec.get("hang")
        self.hlen = self.y + self.h - self.hang["root"] if self.hang else 1
        self.tassel = spec.get("tassel")
        self.bend = spec.get("bend")
        self.anchor = spec.get("anchor")
        self.clip = tuple(spec.get("clip") or ())


def desk_pixmap(pid, parts_dir, factor):
    """桌垫、手、鼠标这些不参与变形的部件：直接缩放成一张 QPixmap。"""
    path = parts_dir / f"{pid}.png"
    img = QImage(str(path))
    if img.isNull():
        raise FileNotFoundError(f"缺部件图：{path}")
    w, h = max(1, round(img.width() * factor)), max(1, round(img.height() * factor))
    pm = QPixmap.fromImage(img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    pm.setDevicePixelRatio(factor)
    return pm
