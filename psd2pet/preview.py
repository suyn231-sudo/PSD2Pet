"""离屏预览：把几种状态画成一张图，调参数的时候不用一直盯着桌面。

    python -m psd2pet --model models/my_pet --preview out/preview.png
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

import random  # noqa: E402
from pathlib import Path  # noqa: E402

from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from .config import Config  # noqa: E402
from .rig import Rig  # noqa: E402


def preview(model, out, scale=None, seconds=3.0, sheet=True):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    for f in ("msyh.ttc", "msyhbd.ttc"):
        p = os.path.join(os.environ.get("QT_QPA_FONTDIR", ""), f)
        if os.path.exists(p):
            QFontDatabase.addApplicationFont(p)
    cfg = Config(model)
    S = scale or cfg.scale_default
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def fresh(amp=0.0):
        r = Rig(cfg)
        r.idle_amp = amp
        r.build(S, 1.0)
        return r

    def sim(r, fn, secs):
        for _ in range(int(secs * 60)):
            fn(r)
            r.update(1 / 60)

    def idle(r):
        r.next_blink = 1e9

    def look(x, y):
        def f(r):
            idle(r)
            r.look_active, r.tx, r.ty = True, x, y
        return f

    def sleep(r):
        r.sleeping = True

    def typing(r):
        idle(r)
        r.hand_down, r.typing = True, True

    def blink_at(ph):
        def f(r):
            r.blink()
            for _ in range(int(ph * 240)):
                r.update(1 / 240)
        return f

    def poke(r):
        r.poke()
        sim(r, idle, 0.25)

    def speak(r):
        idle(r)
        r.voice_in = 1.0

    states = [("待机", idle, None), ("看左", look(-1, 0), None), ("看右", look(1, 0), None),
              ("看上", look(0, -1), None), ("看下", look(0, 1), None),
              ("看左上", look(-1, -1), None), ("看右下", look(1, 1), None),
              ("眨眼·压扁", idle, blink_at(0.04)), ("眨眼·闭上", idle, blink_at(0.09)),
              ("眨眼·弹开", idle, blink_at(0.17)), ("点她", idle, poke),
              ("睡觉", sleep, None), ("打字", typing, lambda r: r.on_key()), ("说话", speak, None)]
    if not sheet:
        return

    random.seed(7)
    w, h = int(cfg.canvas.width() * S), int(cfg.canvas.height() * S)
    cols, lab = 7, 26
    rows = (len(states) + cols - 1) // cols
    img = QImage(w * cols, (h + lab) * rows, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(200, 200, 200))
    p = QPainter(img)
    font = QFont("Microsoft YaHei")
    font.setPixelSize(15)
    for i, (name, fn, post) in enumerate(states):
        random.seed(7)
        r = fresh()
        sim(r, fn, seconds)
        if post:
            post(r)
        r.render()
        x0, y0 = i % cols * w, i // cols * (h + lab)
        p.drawImage(x0, y0 + lab, r.snapshot(QColor(0, 0, 0, 0)))
        p.setFont(font)
        p.setPen(QColor(0, 0, 0))
        p.drawText(QPointF(x0 + 6, y0 + 18), name)
    p.end()
    img.save(str(out))

    # 转头扫一遍，看弧面变形有没有裂
    imgs = []
    for x, y in ((-1, 0), (-0.5, 0), (0, 0), (0.5, 0), (1, 0), (0, -1), (0, 1), (-1, 1), (1, 1)):
        random.seed(7)
        r = fresh()
        sim(r, look(x, y), seconds)
        r.render()
        imgs.append(r.snapshot().copy())
    strip = QImage(w * len(imgs), h, QImage.Format_ARGB32_Premultiplied)
    strip.fill(QColor(225, 225, 225))
    ps = QPainter(strip)
    for k, im in enumerate(imgs):
        ps.drawImage(k * w, 0, im)
    ps.end()
    strip.save(str(out.with_name(out.stem + "_turn.png")))
    print(f"[预览] {out}")
