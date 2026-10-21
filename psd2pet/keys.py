"""左上角的按键气泡：白底、圆角、顶上两只耳朵、尾巴指向角色。颜色和位置都在 config 的 keys 里。"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPainterPath, QPen

_key_font = None


def key_font():
    global _key_font
    if _key_font is None:
        fams = set(QFontDatabase.families())
        name = next((f for f in ("Arial Rounded MT Bold", "Microsoft YaHei UI") if f in fams), "Microsoft YaHei")
        _key_font = QFont(name)
        _key_font.setPixelSize(62)
        _key_font.setBold(name != "Arial Rounded MT Bold")   # 圆体本身就是粗的
    return _key_font


def ear_path(cx, base_y, ew, top_y, s):
    """一只圆尖的耳朵。s = -1 左耳 / 1 右耳，尖往外歪。"""
    tip = QPointF(cx + s * ew * 0.25, top_y)
    h = base_y - top_y
    path = QPainterPath(QPointF(cx - ew / 2, base_y))
    path.quadTo(QPointF(cx - ew * 0.42 + s * ew * 0.12, top_y + h * 0.35),
                QPointF(tip.x() - ew * 0.09, tip.y() + h * 0.1))
    path.quadTo(tip, QPointF(tip.x() + ew * 0.09, tip.y() + h * 0.1))
    path.quadTo(QPointF(cx + ew * 0.42 + s * ew * 0.12, top_y + h * 0.35), QPointF(cx + ew / 2, base_y))
    path.closeSubpath()
    return path


def paint_keys(p, text, alpha, pop, cfg, bob=0.0):
    """坐标是画布坐标，调用前已经 scale + translate 到画布空间。"""
    k = cfg.keys
    if not text or alpha <= 0 or not k:
        return
    col = k.get("colors", {})
    line_c = QColor(*col.get("line", [104, 182, 152]))
    text_c = QColor(*col.get("text", [56, 146, 112]))
    inner_c = QColor(*col.get("inner", [178, 228, 210]))
    shadow_c = QColor(*col.get("shadow", [40, 70, 60, 45]))
    font = key_font()
    fm = QFontMetricsF(font)
    max_w = k.get("max_w", 820)
    if fm.horizontalAdvance(text) > max_w:
        text = fm.elidedText(text, Qt.ElideRight, max_w)
    tw = fm.horizontalAdvance(text)
    H = fm.height() + 46
    W = max(tw + H * 0.9, H * 1.4)
    x, y = k.get("pos", [0, 0])
    y += bob
    body = QRectF(x, y, W, H)

    outline = QPainterPath()
    outline.addRoundedRect(body, H * 0.42, H * 0.42)
    bx = x + min(W * 0.62, W - H * 0.55)                   # 尾巴：从底边伸向右下
    tail = QPainterPath(QPointF(bx - 26, y + H - 10))
    tail.quadTo(bx + 6, y + H + 22, bx + 52, y + H + 46)
    tail.quadTo(bx + 24, y + H + 12, bx + 30, y + H - 10)
    tail.closeSubpath()
    outline = outline.united(tail)
    ew, eh = H * 0.8, H * 0.46
    ex = min(W * 0.27, H * 0.6)                            # 耳朵靠两侧，长气泡也不会分太开
    inner = []
    for cx, s in ((x + ex, -1), (x + W - ex, 1)):
        outline = outline.united(ear_path(cx, y + H * 0.35, ew, y - eh, s))
        inner.append(ear_path(cx + s * ew * 0.08, y + 8, ew * 0.46, y - eh * 0.55, s))

    tip = QPointF(bx + 52, y + H + 46)
    sc = 1 + 0.1 * pop
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setOpacity(alpha)
    p.translate(tip)
    p.scale(sc, sc)
    p.translate(-tip)
    p.setPen(Qt.NoPen)
    p.setBrush(shadow_c)                                   # 淡淡的投影，深色桌面上也看得清
    p.drawPath(outline.translated(0, 9))
    p.setBrush(QColor(255, 255, 255))
    p.drawPath(outline)
    p.setBrush(inner_c)
    for path in inner:
        p.drawPath(path)
    pen = QPen(line_c, 8)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(outline)
    p.setFont(font)
    p.setPen(text_c)
    p.drawText(body.adjusted(0, 3, 0, 3), Qt.AlignCenter, text)
    p.restore()
