"""数值小工具：裁切、弹簧、3×3 仿射、手臂对齐。"""
import math

import numpy as np
from PySide6.QtGui import QTransform


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Spring:
    """k 越大跟得越快，damp 越大越不容易来回弹。"""

    def __init__(self, k, damp):
        self.k, self.damp, self.x, self.v = k, damp, 0.0, 0.0

    def step(self, target, dt):
        self.v += (self.k * (target - self.x) - self.damp * self.v) * dt
        self.x += self.v * dt


def m_t(x, y):
    return np.array([[1, 0, x], [0, 1, y], [0, 0, 1]], float)


def m_r(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)


def m_s(sx, sy):
    return np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], float)


def about(c, m):
    return m_t(*c) @ m @ m_t(-c[0], -c[1])


def apply(m, x, y):
    return m[0, 0] * x + m[0, 1] * y + m[0, 2], m[1, 0] * x + m[1, 1] * y + m[1, 2]


def qt(m):
    """3×3 numpy → QTransform（Qt 的构造顺序是 m11 m12 m21 m22 dx dy）。"""
    return QTransform(m[0, 0], m[1, 0], m[0, 1], m[1, 1], m[0, 2], m[1, 2])


def piecewise(split, left, right=None):
    """部件自己的小动作（眨眼压扁、眼珠转、耳朵抖）：左右两半各一个仿射。返回 (正向, 反向)。"""
    if right is None:
        li = np.linalg.inv(left)
        return (lambda x, y: apply(left, x, y)), (lambda x, y: apply(li, x, y))
    li, ri = np.linalg.inv(left), np.linalg.inv(right)

    def run(a, b, x, y):
        lx, ly = apply(a, x, y)
        rx, ry = apply(b, x, y)
        m = x < split
        return np.where(m, lx, rx), np.where(m, ly, ry)

    return (lambda x, y: run(left, right, x, y)), (lambda x, y: run(li, ri, x, y))


def arm(p, s0, s1, h0, h1):
    """把一条手臂从 肩 s0→手 h0 摆到 肩 s1→手 h1：绕肩旋转 + 沿手臂方向伸缩。"""
    a0 = math.atan2(h0.y() - s0.y(), h0.x() - s0.x())
    a1 = math.atan2(h1.y() - s1.y(), h1.x() - s1.x())
    l0 = math.hypot(h0.x() - s0.x(), h0.y() - s0.y())
    l1 = math.hypot(h1.x() - s1.x(), h1.y() - s1.y())
    p.translate(s1)
    p.rotate(math.degrees(a1))
    p.scale(l1 / l0, 1)
    p.rotate(-math.degrees(a0))
    p.translate(-s0)
