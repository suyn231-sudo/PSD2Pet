"""引擎本体：一套 2.5D 绑定。所有坐标、角度、弹簧都从 config 读，代码里没有一只具体的角色。

原理（只记这一句就够）：每个部件是一张图，每帧按「头转了多少」把它整体挪一点、再按中间鼓边缘不动
的弧面变形一次。模型没画成 3D，眼睛看到的立体感全来自 29 个部件挪的量各不相同。

    头（head）      脸、中发、后脑、五官、呆毛、侧发：跟着光标转
    刘海（bang）    慢半拍追着头（弹簧），上下多看/低头时多露或多盖一点
    后发（back）    双马尾、飘带、耳朵、丸子：反方向挪，像头转到前面把它们挡在后面
    松的（loose）   坠子、蝴蝶结：甩得比头还厉害
    身体（body）    跟头转 1/3，钉在桌沿上，呼吸时轻轻伸缩
可选部件（耳朵、呆毛、头花、双马尾、桌子）缺了自动跳过，不会报错。
"""
import json
import math
import random
import time

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap

from . import motion
from .motion import Spring, about, apply, clamp, m_r, m_s, m_t, piecewise, qt
from .parts import Layer, desk_pixmap

cv2.setNumThreads(2)


class Group:
    """一套跟着头走的角度：sin yaw / sin pitch、绕脖子的 tan roll、整体平移。"""

    def __init__(self):
        self.sx = self.sy = self.tan = self.ex = self.ey = 0.0
        self.rigid = np.eye(3)


class Rig:
    """表情、视线、待机节奏 → 每层的变形参数；render() 把每层 remap 成窗口像素，paint() 叠起来。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.scale, self.dpr, self.f = 0.3, 1.0, 0.3
        self.size = (1, 1)
        self.layers, self.pix, self.frame = {}, {}, []
        self.t = 0.0
        self.idle_amp = 1.0
        # 输入（窗口每帧写入）
        self.tx = self.ty = 0.0
        self.look_active = False
        self.typing = False
        self.mx_t = self.my_t = 0.0
        self.mouse_down = False
        self.hand_down = False
        self.sleeping = False
        # 视线
        self.wx = self.wy = 0.0
        self.next_wander = 1.0
        self.head_x, self.head_y = Spring(45, 8.0), Spring(45, 8.0)
        self.eye_x, self.eye_y = Spring(300, 34), Spring(300, 34)
        self.nod = Spring(120, 9)
        self.sx = self.sy = 0.0
        self.next_sacc = 0.5
        self.lag = {"bang": [Spring(170, 13), Spring(170, 13), Spring(170, 13)],
                    "back": [Spring(65, 6.5), Spring(65, 6.5), Spring(65, 6.5)],
                    "loose": [Spring(30, 3.0), Spring(30, 3.0), Spring(26, 3.0)]}
        self.body_yaw, self.body_pitch = Spring(60, 9), Spring(60, 9)
        self.groups = {g: Group() for g in ("head", "bang", "back", "loose", "body")}
        self.loose_v = Spring(60, 7)
        self.mxs, self.mys = Spring(150, 19), Spring(150, 19)
        self.press = self.tap = 0.0
        self.bob = Spring(170, 11)
        self.ahoge = Spring(90, 4.0)
        self.hair = Spring(22, 2.6)
        self.rib = Spring(14, 1.6)
        self.flw = Spring(110, 4.5)
        self.doll = {"a": Spring(260, 15), "h": Spring(500, 22)}
        self.prev_hx = None
        self.ear_t0, self.next_ear, self.ear_side = -9.0, 3.0, (1, 1)
        self.ear_l = self.ear_r = 0.0
        self.ear_d = 0.0
        self.ear_swing = Spring(110, 3.2)
        self.ear_sq = Spring(200, 8)
        self.head_vy = 0.0
        self.doll_t0, self.doll_hop, self.next_doll = -9.0, -9.0, 4.0
        self.lean = 0.0
        self.blink_t0, self.next_blink, self.reopened = -9.0, 2.0, True
        self.eye_sy = Spring(700, 21)
        self.eye_sy.x = 1.0
        self.jelly = Spring(380, 5)
        self.happy, self.happy_t0 = 0.0, -9.0
        self.voice_in = self.voice = 0.0
        self.voice_hi, self.voice_mouth = False, self._mouths()[0]
        self.happy_mouth = self._mouths()[0]
        self.pop = Spring(500, 12)
        self.sleep_k = 0.0
        self.bph = 0.0
        self.breath = 0.0
        self.noise = {c: [(f * random.uniform(0.8, 1.2), a, random.uniform(0, 2 * math.pi))
                          for f, a in ((0.11, 0.55), (0.23, 0.3), (0.41, 0.15))]
                      for c in ("yaw", "pitch", "roll", "body")}
        self.ax = self.ay = self.roll = 0.0
        self.ct = np.eye(3)
        self.has = {k: k in cfg.layers for k in ("ears", "ahoge", "flower")}
        self.ear_on = self.has["ears"] and cfg.layers["ears"].get("ear") is not None
        self.ear_cfg = cfg.layers.get("ears", {}).get("ear") or {}

    # ---------- 小工具 ----------
    def _mouths(self):
        m = list(self.cfg.faces["mouths"])
        return m or [self.cfg.faces["mouth"]]

    def _face(self, role):
        pid = self.cfg.faces.get(role)
        return pid if pid in self.layers else None

    # ---------- 准备 ----------
    def build(self, scale, dpr):
        cfg = self.cfg
        self.scale, self.dpr = scale, dpr
        f = self.f = scale * dpr
        c = cfg.canvas
        self.size = (max(1, round(c.width() * f)), max(1, round(c.height() * f)))
        self.layers = {pid: Layer(cfg.meta[pid], cfg.layers[pid], cfg.parts_dir, f, 2) for pid in cfg.order}
        self.pix = {pid: desk_pixmap(pid, cfg.parts_dir, f) for pid in cfg.pix}
        self.update(1 / 60)
        self.render()

    # ---------- 动作 ----------
    @property
    def blinking(self):
        ph = self.t - self.blink_t0
        return self.cfg.blink[0] <= ph < self.cfg.blink[0] + self.cfg.blink[1]

    def blink(self):
        self.blink_t0, self.reopened = self.t, False

    def n(self, ch):
        return sum(a * math.sin(2 * math.pi * f * self.t + ph) for f, a, ph in self.noise[ch]) * self.idle_amp

    def poke(self):
        self.happy, self.happy_t0 = 1.8, self.t
        self.happy_mouth = random.choice(self._mouths())
        self.pop.x, self.pop.v = 0.0, 9.0
        self.bob.v -= 240
        self.nod.v -= 70
        self.flw.v += random.choice((-1, 1)) * 3
        self.loose_v.v += random.choice((-1, 1)) * 3.5
        self.ear_d = 1.0
        self.doll_hop = self.t

    def on_key(self):
        self.tap = 1.0
        self.bob.v += 70

    def update(self, dt):
        cfg = self.cfg
        h, sw = cfg.head, cfg.swing
        dt = clamp(dt, 0.001, 0.05)
        self.t += dt
        t = self.t
        self.sleep_k += ((1.0 if self.sleeping else 0.0) - self.sleep_k) * min(1.0, dt * 1.5)
        sl = self.sleep_k
        calm = 1.0 - 0.75 * sl
        self.happy = max(0.0, self.happy - dt)
        hp = self.happy / 1.8
        self.press += ((1.0 if self.mouse_down else 0.0) - self.press) * min(1.0, dt * 25)
        self.tap = max(0.0, self.tap - dt * 8)

        if t >= self.next_wander:
            self.wx, self.wy = random.uniform(-1, 1), random.uniform(-1, 1)
            self.next_wander = t + random.uniform(1.5, 4.5)
        if sl > 0.5:
            gx, gy = 0.0, 0.5
        else:
            gx, gy = self.tx, self.ty + (0.3 if self.typing else 0.0)
        r = math.hypot(gx, gy)
        if r > 1:
            gx, gy = gx / r, gy / r
        self.eye_x.step(gx + 0.15 * self.wx * self.idle_amp, dt)
        self.eye_y.step(gy + 0.15 * self.wy * self.idle_amp, dt)
        self.head_x.step(gx * 0.9, dt)
        self.head_y.step(gy * 0.8, dt)
        self.nod.step(0.0, dt)
        if t >= self.next_sacc:
            self.sx, self.sy = random.uniform(-1, 1), random.uniform(-1, 1)
            self.next_sacc = t + random.uniform(0.3, 1.5)
            self.jelly.v += random.uniform(-0.6, 0.6)
        self.mxs.step(self.mx_t, dt)
        self.mys.step(self.my_t, dt)
        self.bob.step(0.0, dt)
        self.pop.step(0.0, dt)

        self.bph += dt * 2 * math.pi / (3.4 + 2.2 * sl)
        self.breath = math.sin(self.bph)
        br = self.breath * calm
        self.ax = clamp(self.head_x.x + 0.08 * self.n("yaw") * calm, -1.1, 1.1)
        self.ay = clamp(self.head_y.x + 0.06 * self.n("pitch") * calm - 0.07 * br, -1.1, 1.1)
        self.roll = 1.2 * self.n("roll") * calm + 1.0 * math.sin(self.bph * 0.5 + 0.8) * calm * self.idle_amp \
            + 3 * self.ax + 6 * sl + 3 * math.sin((t - self.happy_t0) * 10) * hp * hp
        self.lean = self.head_x.x * calm

        yaw = self.ax * cfg.yaw
        pitch = -self.ay * cfg.pitch - 8 * sl + self.nod.x
        roll = clamp(self.roll, -12, 12)
        angles = {"head": (yaw, pitch, roll)}
        for g, springs in self.lag.items():
            for s, target, lim in zip(springs, (yaw, pitch, roll), (h["lag_max"], h["lag_max"], h["roll_lag"])):
                s.step(target, dt)
                s.x = target + clamp(s.x - target, -lim, lim)
            angles[g] = tuple(s.x for s in springs)
        mx_span = cfg.desk.get("mouse", [cfg.canvas.width() / 30])[0] if cfg.desk else cfg.canvas.width() / 30
        self.body_yaw.step(yaw / 3 + 4 * self.mxs.x / (mx_span or 1) + 1 * self.n("body") * calm, dt)
        self.body_pitch.step(pitch / 4, dt)

        # 脖子钉在身体上（只跟着身体走）；头朝看的方向挪、随呼吸起伏都放进位移里，越靠下巴越小
        bg = self.groups["body"]
        bg.sx, bg.sy = math.sin(math.radians(self.body_yaw.x)), math.sin(math.radians(self.body_pitch.x))
        ndx, ndy = self.disp_at("body", cfg.neck[0], cfg.neck[1])
        for g in ("head", "bang", "back", "loose"):
            y_, p_, r_ = angles[g]
            gr = self.groups[g]
            gr.sx, gr.sy = math.sin(math.radians(y_)), math.sin(math.radians(p_))
            gr.tan = math.tan(math.radians(r_))
            gr.ex = h["shift"] * math.sin(math.radians(yaw))
            dy_ = -h["up"] * self.ay if self.ay < 0 else h["down"] * self.ay
            if g == "bang":
                dy_ += -h["bang_up"] * self.ay if self.ay < 0 else h["bang_down"] * self.ay
            elif g == "loose":
                dy_ *= 1.3
            gr.ey = -4 * br + 6 * self.ay + 6 * sl + dy_
            gr.rigid = m_t(ndx, ndy) @ about(cfg.neck, m_r(r_))

        # 呆毛、后面头发、头花：头往哪边动，梢就往反方向甩，停下再回摆
        hxv = self.ax * 30 + math.radians(self.roll) * 445 + self.lean * 14
        if self.prev_hx is None:
            self.prev_hx = hxv
        drive = clamp(-(hxv - self.prev_hx) / dt * 0.0012, -0.12, 0.12)
        self.prev_hx = hxv
        wind = (0.022 * math.sin(2 * math.pi * 0.16 * t) + 0.01 * math.sin(2 * math.pi * 0.41 * t + 1)) * calm
        self.ahoge.step(1.5 * wind + 1.3 * drive + 0.035 * math.sin(2 * math.pi * 0.7 * t) * calm, dt)
        self.hair.step(wind + drive, dt)
        self.rib.step(1.3 * wind + drive + 0.012 * math.sin(2 * math.pi * 0.33 * t) * calm, dt)
        self.flw.step(1.2 * drive, dt)
        self.loose_v.step(60 * drive + 1.2 * math.sin(2 * math.pi * 0.23 * t) * calm, dt)
        # 耳朵 duang：头动得越快甩得越狠，停下后自己晃两下
        dhy = (self.ay - getattr(self, "prev_ay", self.ay)) / dt
        self.prev_ay = self.ay
        dhx = (self.ax - getattr(self, "prev_ax", self.ax)) / dt
        self.prev_ax = self.ax
        self.ear_swing.step(clamp(-dhy * 10 - dhx * 4, -14, 14) + 3 * self.ax, dt)
        self.ear_sq.step(clamp(-dhy * 0.05, -0.16, 0.16), dt)
        # 桌上的小玩偶：待机小晃；隔几秒蹦一下、甩一下
        if "doll" in self.pix and t >= self.next_doll and sl < 0.5:
            self.doll_hop, self.next_doll = t, t + random.uniform(4, 8)
            self.doll["a"].v += random.choice((-1, 1)) * 2.2
        self.doll["a"].step(0.0, dt)
        self.doll["h"].step(0.0, dt)
        # 声捕：张嘴快、闭嘴慢一点；每个字起音时轻轻弹一下、点一下头，嘴型随机换
        vi = self.voice_in if sl < 0.5 else 0.0
        self.voice += (vi - self.voice) * min(1.0, dt * (35 if vi > self.voice else 10))
        if self.voice > 0.4 and not self.voice_hi:
            self.voice_hi = True
            self.voice_mouth = random.choice(self._mouths())
            self.bob.v -= 40 + 50 * self.voice
            self.nod.v -= 15
            self.ear_d = max(self.ear_d, 0.3)
        elif self.voice < 0.2:
            self.voice_hi = False

        # 耳朵：跟呼吸轻轻动，时不时抖一下；开心竖起、睡觉耷拉；头一动就被甩（duang）
        if self.ear_on and t >= self.next_ear and sl < 0.5:
            self.ear_t0, self.next_ear = t, t + random.uniform(3, 9)
            self.ear_side = random.choice(((1, 0), (0, 1), (1, 1)))
        if self.ear_on:
            e = (t - self.ear_t0) / 0.35
            flick = math.sin(e * 2 * math.pi) * (1 - e) if 0 <= e <= 1 else 0.0
            base = 2 * math.sin(self.bph + 0.6) * calm - 5 * hp + 12 * sl
            self.ear_l = base + 16 * flick * self.ear_side[0]
            self.ear_r = base + 16 * flick * self.ear_side[1]
        self.ear_d = max(0.0, self.ear_d - dt * 1.6)

        # 眨眼：打字的时候也照样眨
        if t >= self.next_blink and not self.sleeping:
            self.blink()
            self.next_blink = t + (0.35 if random.random() < 0.2 else random.uniform(2.0, 5.5))
        ph = t - self.blink_t0
        c0, c1 = cfg.blink
        if ph < c0:
            self.eye_sy.x, self.eye_sy.v = 1 - 0.7 * (ph / c0) ** 2, 0.0
        elif ph < c0 + c1:
            self.eye_sy.x, self.eye_sy.v = 0.45, 0.0
        else:
            if not self.reopened:
                self.reopened = True
                self.jelly.v += 2.6
            self.eye_sy.step(1.0, dt)
        self.jelly.step(0.0, dt)

    # ---------- 变形 ----------
    def disp_at(self, g, x, y, L=None):
        """弧面 + 深度位移（画布像素）。L 为 None 时按身体算。"""
        cfg = self.cfg
        h, sw = cfg.head, cfg.swing
        if L is None:
            spec = cfg.layers.get("body") or {"z": (0, 0), "bulge": (0, 0), "field": cfg.field["body"]}
            zx, zy = spec["z"]
            cx, cy = spec["bulge"]
            field = spec["field"]
            hang = None
            anchor = None
            pid = None
        else:
            zx, zy, cx, cy, field, hang = L.zx, L.zy, L.cx, L.cy, L.field, L.hang
            anchor = L.anchor
            pid = L.pid
            if anchor == "eyes":
                left = np.asarray(x) < cfg.eyes["mid_x"]
                x = np.where(left, cfg.eyes["centers"][0][0], cfg.eyes["centers"][1][0])
                y = np.where(left, cfg.eyes["centers"][0][1], cfg.eyes["centers"][1][1]).astype(float)
            elif isinstance(anchor, (list, tuple)):
                x = np.full_like(np.asarray(x, float), anchor[0])
                y = np.full_like(x, anchor[1])
        gr = self.groups[g]
        if cx or cy:
            u = (x - field[0]) / field[2]
            v = (y - field[1]) / field[3]
            b = np.maximum(1 - u * u - v * v, 0)
            b = b * b
            dx = gr.sx * (zx + cx * b)
            dy = -gr.sy * (zy + cy * b)
        else:
            dx = gr.sx * zx + 0 * x
            dy = -gr.sy * zy + 0 * y
        if g != "body":                                # 脖子钉住：下巴附近位移收掉，头不离开身子
            py, pd, px, pyk = h["pin"]
            k = np.clip((py - y) / pd, 0, 1)
            s = k * k * (3 - 2 * k)
            dx = (dx + gr.ex) * (px + (1 - px) * s)
            dy = (dy + gr.ey) * (pyk + (1 - pyk) * s)
        if hang:
            root, amp = hang["root"], hang["amp"]
            sway = getattr(self, hang.get("spring", "rib")).x
            d = np.maximum(y - root, 0)
            k = np.minimum(d / L.hlen, 1)
            dx = dx + amp * sway * k ** 1.6 + sw["hang_gravity"] * gr.tan * d * k
        elif L is not None and L.tassel:
            root, amp = L.tassel["root"], L.tassel["amp"]
            k = np.minimum(np.maximum(y - root, 0) / sw["tassel_span"], 1) ** 1.3
            dx = dx + amp * (self.loose_v.x + 26 * gr.tan) * k
        if L is not None and L.bend:                   # 垂下来的发梢、刘海下半：慢半拍地摆
            root, amp = L.bend["root"], L.bend["amp"]
            k = np.minimum(np.maximum(y - root, 0) / sw["bend_span"], 1) ** 1.5
            dx = dx + amp * getattr(self, L.bend.get("spring", "hair")).x * k
        return dx, dy

    def local(self):
        """每个部件自己的小动作 → {pid: (正向, 反向)}"""
        cfg = self.cfg
        out = {}
        faces = cfg.faces
        ec = cfg.eyes["centers"]
        sy = self.eye_sy.x
        sx = 1 + 0.3 * (1 - sy)
        # 转头：远侧那只眼整只均匀收窄、近侧略放宽（往右转时画面右边那只在远侧）
        t = self.groups["head"].sx
        far, near = cfg.eyes["foreshorten"]
        fs = (1 - far * max(-t, 0) + near * max(t, 0), 1 - far * max(t, 0) + near * max(-t, 0))
        eyes = [about(c, m_s(sx * k, sy)) for c, k in zip(ec, fs)]
        white, brow_pid, line = self._face("white"), self._face("brow"), self._face("line")
        brow = m_t(0, 5 * (1 - sy) - 4 * self.pop.x)
        if white:
            out[white] = piecewise(cfg.eyes["mid_x"], *eyes)
        if brow_pid:
            out[brow_pid] = piecewise(None, brow)
        # 「眼睛+眉毛」这层里还有眉毛的线稿：brow_y 以上跟眉毛走，以下才眨
        if white and brow_pid and line:
            ef, ei = out[white]
            bf, bi = out[brow_pid]
            by = cfg.eyes["brow_y"]

            def split_y(a, b, inverse):
                def fn(x, y):
                    ax, ay = a(x, y)
                    bx, by_ = b(x, y)
                    m = y < by
                    rx, ry = np.where(m, bx, ax), np.where(m, by_, ay)
                    if inverse:                # 反解出来落到另一半的点不要（不然眨眼时眉毛被拉下来一截）
                        ry = np.where(m == (ry < by), ry, -1e4)
                    return rx, ry
                return fn

            out[line] = (split_y(ef, bf, False), split_y(ei, bi, True))
        j = self.jelly.x
        px = clamp(self.eye_x.x + 0.15 * self.sx, -1, 1) * cfg.eyes["pupil"][0]
        py = clamp(self.eye_y.x + 0.2 * self.sy, -1, 1) * cfg.eyes["pupil"][1]
        if self._face("iris"):
            out[faces["iris"]] = piecewise(cfg.eyes["mid_x"], *[e @ about(c, m_t(px, py) @ m_s(1 - 0.45 * j, 1 + 0.6 * j))
                                                               for e, c in zip(eyes, ec)])
        hp = self.pop.x
        for role in ("closed", "happy"):
            pid = self._face(role)
            if pid:
                out[pid] = piecewise(cfg.eyes["mid_x"], *[about(c, m_s((1 + 0.04 * hp) * k, 1 + 0.12 * hp))
                                                         for c, k in zip(ec, fs)])
        vo = min(self.voice, 1.0)
        for pid in list(faces["mouths"]) + [faces["mouth"]]:
            if pid not in self.layers:
                continue
            m = about(cfg.mouth["center"], m_s((1 + 0.1 * hp) * (1 - 0.08 * abs(t)), 1 + 0.18 * hp))
            if pid != faces["mouth"] and vo > cfg.voice["open"]:   # 说话：张开的嘴从上沿往下拉开
                m = about(cfg.mouth["top"], m_s(0.85 + 0.2 * vo, 0.35 + 0.75 * vo)) @ m
            out[pid] = piecewise(None, m)
        if self.ear_on:
            self._ear_local(out)
        if self.has["flower"]:
            a = self.flw.x
            fl = about(cfg.layers["flower"].get("pivot", [0, 0]),
                       m_r(14 * a + 2.0 * math.sin(2 * math.pi * 0.45 * self.t)) @
                       m_s(1 + 0.025 * math.sin(2 * math.pi * 0.9 * self.t),
                           1 - 0.025 * math.sin(2 * math.pi * 0.9 * self.t)))
            out["flower"] = piecewise(None, fl)
            if "flower_shadow" in self.layers:
                out["flower_shadow"] = out["flower"]
        if self.has["ahoge"]:
            spec = cfg.layers["ahoge"].get("ahoge") or {}
            root, ln = spec.get("root", 0), max(1, spec.get("len", 1))
            sh = -1.2 * self.ahoge.x * ln

            def bend(sign):
                def fn(x, y):
                    k = np.clip((root - y) / ln, 0, 1)
                    return x + sign * sh * k ** 1.4, y
                return fn

            out["ahoge"] = (bend(1), bend(-1))
        return out

    def _ear_local(self, out):
        """耳朵的两段小动作：绕耳根转 + 被头带着压扁拉长，交界线附近权重为 0（不脱开）。"""
        cfg = self.cfg
        e = self.ear_cfg
        L, R = QPointF(*e["l"]), QPointF(*e["r"])
        sq = clamp(self.ear_sq.x, -0.18, 0.18)
        mats = (about((L.x(), L.y()), m_r(-self.ear_l - clamp(self.ear_swing.x, -20, 20)) @ m_s(1 - 0.5 * sq, 1 + sq)),
                about((R.x(), R.y()), m_r(self.ear_r + clamp(self.ear_swing.x, -20, 20)) @ m_s(1 - 0.5 * sq, 1 + sq)))
        center = e.get("center", [0, 0])

        def ear_w(x, y):
            ws = []
            for (a, b) in e["root"]:
                tx, ty = b[0] - a[0], b[1] - a[1]
                n = math.hypot(tx, ty)
                nx, ny = ty / n, -tx / n
                if nx * (center[0] - a[0]) + ny * (center[1] - a[1]) > 0:   # 法线朝外（背离头中心）
                    nx, ny = -nx, -ny
                k = np.clip(((x - a[0]) * nx + (y - a[1]) * ny) / e["ramp"], 0, 1)
                ws.append(k * k * (3 - 2 * k))
            return ws

        def ear_disp(x, y):
            wl, wr = ear_w(x, y)
            m = x < e["split"]
            dx = np.zeros_like(np.asarray(x, float))
            dy = np.zeros_like(dx)
            for mat, w, sel in ((mats[0], wl, m), (mats[1], wr, ~m)):
                ax, ay = apply(mat, x, y)
                dx = np.where(sel, w * (ax - x), dx)
                dy = np.where(sel, w * (ay - y), dy)
            return dx, dy

        def ear_fwd(x, y):
            dx, dy = ear_disp(x, y)
            return x + dx, y + dy

        def ear_inv(x, y):
            px, py = x, y
            for _ in range(8):
                dx, dy = ear_disp(px, py)
                px, py = x - dx, y - dy
            return px, py

        out["ears"] = (ear_fwd, ear_inv)

    def char_matrix(self):
        """整个人（不含桌子）：朝光标那边倾 + 上下弹 + 弹的时候压扁拉长 + 呼吸时轻轻伸缩。"""
        dx_, dy_ = self.cfg.desk_point
        b = self.bob.x
        sy = 1 + 0.008 * self.breath * (1 + 0.4 * self.sleep_k) - 0.0016 * b
        sx = 1 - 0.5 * (sy - 1)
        return m_t(dx_ + 8 * self.lean, dy_ + b + 4 * self.sleep_k + 3 * self.head_y.x) \
            @ m_r(1.5 * self.lean) @ m_s(sx, sy) @ m_t(-dx_, -dy_)

    def visible(self):
        cfg = self.cfg
        f = cfg.faces
        shut = self.sleep_k > 0.5 or self.blinking
        happy = self.happy > 0 and self.sleep_k < 0.5
        if self.sleep_k > 0.5:
            eyes = (f["sleep"],)
        elif shut:
            eyes = (f["blink"],)
        elif happy:
            eyes = (f["happy_eye"],)
        else:
            eyes = tuple(cfg.open_eyes)
        if not any(e in self.layers for e in eyes):    # 没画闭眼/笑眼：就一直睁着
            eyes = tuple(cfg.open_eyes)
        if self.voice > cfg.voice["open"] and self.sleep_k < 0.5:
            mouth = self.voice_mouth
        else:
            mouth = self.happy_mouth if happy else f["mouth"]
        return [pid for pid in cfg.order if pid not in cfg.expr or pid in eyes or pid == mouth]

    def warp(self, L, post, pre):
        cfg = self.cfg
        W, H = self.size
        grid, it, pad = 6, 7, 2
        fwd, inv = pre if pre else (None, None)
        g = L.group
        # 1. 这层落在窗口哪块：原图范围上撒 9×9 个点正向算一遍
        X, Y = np.meshgrid(np.linspace(L.x, L.x + L.w, 9), np.linspace(L.y, L.y + L.h, 9))
        if fwd:
            X, Y = fwd(X, Y)
        dx, dy = self.disp_at(g, X, Y, L)
        ox, oy = apply(post, X + dx, Y + dy)
        m = 2 * grid + 3
        x0, y0 = max(0, int(ox.min()) - m), max(0, int(oy.min()) - m)
        x1, y1 = min(W, int(ox.max()) + m + 1), min(H, int(oy.max()) + m + 1)
        if x1 <= x0 or y1 <= y0:
            return None
        w, h = x1 - x0, y1 - y0
        # 2. 粗网格上反解：窗口像素 → 头的局部坐标 → 去掉弧面位移 → 去掉部件小动作 → 原图像素
        nx, ny = max(2, -(-w // grid) + 1), max(2, -(-h // grid) + 1)
        gx = x0 + (np.arange(nx) + 0.5) * w / nx      # 和 cv2.resize 的采样位置对齐（+0.5 = 像素中心）
        gy = y0 + (np.arange(ny) + 0.5) * h / ny
        GX, GY = np.meshgrid(gx, gy)
        qx, qy = apply(np.linalg.inv(post), GX, GY)
        sx, sy = qx, qy
        for _ in range(it):
            dx, dy = self.disp_at(g, sx, sy, L)
            sx, sy = qx - dx, qy - dy
        if inv:
            sx, sy = inv(sx, sy)
        mx = ((sx - L.x) * L.fx + pad - 0.5).astype(np.float32)
        my = ((sy - L.y) * L.fy + pad - 0.5).astype(np.float32)
        mx = cv2.resize(mx, (w, h), interpolation=cv2.INTER_LINEAR)
        my = cv2.resize(my, (w, h), interpolation=cv2.INTER_LINEAR)
        img = cv2.remap(L.src, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        return x0, y0, img

    @staticmethod
    def clip(res, refs):
        """只留在 refs（已经变形好的层）的不透明范围里：刘海阴影只落在脸上、眼珠只在眼白里。"""
        x0, y0, arr = res
        h, w = arr.shape[:2]
        a = np.zeros((h, w), np.uint8)
        for rx, ry, ra in refs:
            ix0, iy0 = max(x0, rx), max(y0, ry)
            ix1, iy1 = min(x0 + w, rx + ra.shape[1]), min(y0 + h, ry + ra.shape[0])
            if ix1 > ix0 and iy1 > iy0:
                sub = a[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0]
                np.maximum(sub, ra[iy0 - ry:iy1 - ry, ix0 - rx:ix1 - rx, 3], out=sub)
        return x0, y0, cv2.multiply(arr, cv2.merge([a, a, a, a]), scale=1 / 255)

    def render(self):
        cfg = self.cfg
        f = self.f
        self.ct = self.char_matrix()
        c = cfg.canvas
        out_m = np.array([[f, 0, -c.x() * f], [0, f, -c.y() * f], [0, 0, 1]])
        post = {g: out_m @ self.ct @ gr.rigid for g, gr in self.groups.items()}
        post["body"] = out_m @ self.ct
        pre = self.local()
        done, frame = {}, []
        for pid in self.visible():
            L = self.layers[pid]
            res = self.warp(L, post[L.group], pre.get(pid))
            if res is None:
                continue
            if L.clip:
                res = self.clip(res, [done[r] for r in L.clip if r in done])
            done[pid] = res
            x0, y0, arr = res
            img = QImage(arr.data, arr.shape[1], arr.shape[0], arr.strides[0], QImage.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(self.dpr)
            frame.append((img, x0, y0, L.blend == "multiply"))
        self.frame = frame

    # ---------- 画 ----------
    def draw(self, p, pid, dx=0.0, dy=0.0):
        part = self.cfg.meta[pid]
        p.drawPixmap(QPointF(part["x"] + dx, part["y"] + dy), self.pix[pid])

    def body_point(self, pt):
        dx, dy = self.disp_at("body", pt.x(), pt.y())
        return QPointF(pt.x() + float(dx), pt.y() + float(dy))

    def paint(self, p):
        cfg = self.cfg
        dpr = self.dpr
        for img, x0, y0, mul in self.frame:
            p.setCompositionMode(QPainter.CompositionMode_Multiply if mul else QPainter.CompositionMode_SourceOver)
            p.drawImage(QPointF(x0 / dpr, y0 / dpr), img)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        S = self.scale
        c = cfg.canvas
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.scale(S, S)
        p.translate(-c.x(), -c.y())
        if cfg.sitting:
            if "mousepad" in self.pix:
                self.draw(p, "mousepad")
            self.doll_animal(p)
            self.paint_props(p)
        elif cfg.shadow.get("on"):
            self.paint_shadow(p)
        if self.sleep_k > 0.3:
            self.paint_zzz(p, (self.sleep_k - 0.3) / 0.7)
        p.restore()

    def paint_shadow(self, p):
        """站立模式：脚下一团椭圆影子，让人物看着站在桌面上而不是飘着。"""
        s = self.cfg.shadow
        c = self.cfg.canvas
        at = s.get("at") or (c.center().x(), c.bottom())
        w, h = s["size"]
        col = QColor(*s["color"])
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawEllipse(QPointF(at[0] + 8 * self.lean, at[1] + self.bob.x * 0.25), w / 2, h / 2)
        p.restore()

    def doll_animal(self, p):
        """桌上的小玩偶：原地轻轻晃，隔一会儿蹦一下（起跳压扁、空中拉长、落地砸一下）。"""
        cfg = self.cfg
        if "doll" not in self.pix:
            return
        m = cfg.meta["doll"]
        c = cfg.desk.get("doll_center", [0.42, 0.92])
        o = QPointF(m["x"] + m["w"] * c[0], m["y"] + m["h"] * c[1])
        e = self.t - self.doll_hop
        hop, sq, tilt = 0.0, 0.0, 0.0
        t0 = 0.0
        for i, (dur, hgt) in enumerate(((0.42, 40), (0.30, 20), (0.22, 9))):
            k = (e - t0) / dur
            if 0 <= k < 1:
                s = math.sin(math.pi * k)
                hop = s * hgt
                sq = -0.16 * (hgt / 40) * s + 0.2 * max(0.0, 1 - s / 0.35)
                tilt = (1 if i % 2 == 0 else -1) * 7 * (hgt / 40) * s
                break
            t0 += dur
        else:
            k = (e - t0) / 0.6
            if 0 <= k <= 1:
                sq = 0.2 * math.exp(-k * 4) * math.cos(k * 4 * math.pi)
        sq += 0.05 * math.sin(self.t * 1.7)
        p.save()
        p.translate(o.x(), o.y() - hop)
        p.rotate(4.5 * self.doll["a"].x + 2.0 * math.sin(self.t * 1.3) + tilt)
        p.scale(1 - 0.55 * sq, 1 + sq)
        p.translate(-o.x(), -o.y())
        self.draw(p, "doll")
        p.restore()

    def paint_props(self, p):
        """鼠标放桌上跟着光标挪；左手从肩膀（随身体）伸到鼠标；右手搁在身上，按键时落到键盘上。"""
        cfg = self.cfg
        d = cfg.desk
        if not d:
            return
        ct = qt(self.ct)
        mx, my = self.mxs.x, self.mys.x + 3 * self.press
        if "mouse" in self.pix:
            self.draw(p, "mouse", mx, my)
        if "hand_l" in self.pix:
            sh, grip = QPointF(*d["shoulder_l"]), QPointF(*d["grip_l"])
            p.save()
            motion.arm(p, sh, ct.map(self.body_point(sh)), grip, grip + QPointF(mx, my))
            self.draw(p, "hand_l")
            p.restore()
        if "hand_r_up" in self.pix or "hand_r_down" in self.pix:
            sh, tip = QPointF(*d["shoulder_r"]), QPointF(*d["tip_r"])
            sr = self.body_point(sh)
            p.save()
            if self.hand_down and "hand_r_down" in self.pix:
                motion.arm(p, sh, ct.map(sr), tip, tip + QPointF(0, 6 * self.tap))
                self.draw(p, "hand_r_down")
            elif "hand_r_up" in self.pix:
                p.setTransform(qt(m_t(sr.x() - sh.x(), sr.y() - sh.y())) * ct, True)
                self.draw(p, "hand_r_up")
            p.restore()

    def paint_zzz(self, p, alpha):
        z = self.cfg.zzz
        at, drift = z["at"], z["drift"]
        col = z.get("color", [110, 130, 190])
        font = QFont("Microsoft YaHei")
        font.setBold(True)
        for i in range(3):
            ph = (self.t / 2.4 + i / 3) % 1
            font.setPixelSize(int(40 + ph * 45))
            p.setFont(font)
            c = QColor(*col)
            c.setAlphaF(clamp(alpha * min(1.0, ph * 4) * (1 - ph), 0, 1))
            p.setPen(c)
            p.drawText(QPointF(at[0] + ph * drift[0], at[1] + ph * drift[1]), "Z" if ph > 0.5 else "z")

    # ---------- 图标 / 截图 ----------
    def snapshot(self, bg=None):
        """当前这一帧（不含桌子之外的窗口元素），给图标和离线预览用。"""
        w, h = self.size
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(bg if bg is not None else Qt.transparent)
        img.setDevicePixelRatio(self.dpr)
        p = QPainter(img)
        self.paint(p)
        p.end()
        return img

    def icon(self):
        cfg = self.cfg
        img = self.snapshot()
        c = cfg.canvas
        f = self.f
        if cfg.icon_box:
            x, y, side = cfg.icon_box
        else:
            x, y, side = c.x(), c.y(), min(c.width(), c.height())
        box = QRect(round((x - c.x()) * f), round((y - c.y()) * f), round(side * f), round(side * f))
        img = img.copy(box)
        img.setDevicePixelRatio(1.0)
        return img
