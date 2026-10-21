"""窗口：桌面上那个透明小窗、托盘菜单、直播捕获窗、滚轮缩放、设置读写。"""
import ctypes
import json
import math
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QLockFile, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from .i18n import LANGS, gate_label, resolve, tr
from .inputs import Inputs
from .keys import paint_keys
from .motion import clamp
from .rig import Rig
from .voice import Voice


def app_dir(slug):
    """设置存哪：%APPDATA%\\PSD2Pet\\<slug>。设了 PSD2PET_DIR 就整个挪过去（方便测试、不碰正式设置）。"""
    base = os.environ.get("PSD2PET_DIR")
    if base:
        return Path(base) / slug
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "PSD2Pet" / slug


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_elevated(relaunch, workdir, frozen=False):
    """用管理员身份再开一个自己（弹 UAC）。游戏是管理员权限跑的时候，普通权限的键盘钩子收不到按键。"""
    tail = subprocess.list2cmdline(list(relaunch or []) + ["--elevated"])
    if frozen:
        exe = Path(sys.executable)
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe), tail, str(exe.parent), 0)
        return r > 32
    pythonw = Path(sys.executable)
    if pythonw.name.lower().startswith("python"):
        cand = pythonw.with_name("pythonw.exe")
        if cand.exists():
            pythonw = cand
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(pythonw), "-m psd2pet " + tail, str(workdir), 0)
    return r > 32


class LiveWindow(QWidget):
    """直播用：普通窗口（不置顶、不抢焦点），纯色底。OBS「窗口捕获」+「色度键」抠掉底色。"""

    def __init__(self, pet):
        super().__init__()
        self.pet = pet
        self.retitle()
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setFixedSize(pet.size())

    def retitle(self):
        self.setWindowTitle(f"{self.pet.cfg.name} · {tr(self.pet.lang, 'live_title')}")

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(*self.pet.cfg.window["key_color"]))
        self.pet.paint_all(p)
        p.end()

    def contextMenuEvent(self, e):
        self.pet.menu(e.globalPos())

    def closeEvent(self, e):
        self.pet.live = None
        self.pet.desktop_on = True
        self.pet.show()
        self.pet.save_settings()
        super().closeEvent(e)


class Pet(QWidget):
    def __init__(self, cfg, rig, inputs, lock, relaunch=None, workdir=None):
        super().__init__()
        self.cfg, self.rig, self.inputs, self.lock = cfg, rig, inputs, lock
        self.relaunch, self.workdir = relaunch, workdir
        self.dir = app_dir(cfg.slug)
        self.settings_file = self.dir / "settings.json"
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setWindowTitle(cfg.name)
        st = self.load_settings()
        try:
            s = float(st["scale"])
        except Exception:
            s = cfg.scale_default
        self.lang_choice = st.get("lang", "auto")     # auto 跟随系统 / zh / en
        self.lang = resolve(self.lang_choice)
        self.scale_v = self.want = clamp(s, cfg.scale_min, cfg.scale_max)
        self.show_keys = bool(st.get("keys", cfg.keys_show))
        self.admin = bool(st.get("admin", False))
        self.desktop_on = bool(st.get("desktop", True))
        self.on_top = bool(st.get("top", True))
        self.through = bool(st.get("through", False))
        self.voice_on = bool(st.get("voice", False))
        self.mic = st.get("mic") or None
        self.voice = Voice(cfg)
        self.voice.gate = self.voice.gates.get(st.get("voice_gate"), self.voice.gate)
        if self.voice_on:
            self.voice_on = self.voice.start(self.mic) or self.voice.start(None)
        inputs.show_names = self.show_keys
        self.live = None
        self.apply_flags()
        self.apply_size()
        self.place(st)
        self.zoom_timer = QTimer(self)                # 滚轮连着滚：攒一下再重建，不一格建一次
        self.zoom_timer.setSingleShot(True)
        self.zoom_timer.timeout.connect(lambda: self.set_scale(self.want))
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(QIcon(QPixmap.fromImage(rig.icon())), self)
            self.tray.setToolTip(cfg.name)
            self.tray_menu = QMenu()
            self.tray_menu.aboutToShow.connect(lambda: (self.tray_menu.clear(), self.fill_menu(self.tray_menu)))
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(self.tray_click)
            self.tray.show()
        if st.get("live"):
            self.open_live(st.get("live_pos"))
        if not self.desktop_on and self.live is None and self.tray is None:
            self.desktop_on = True                    # 没托盘又没直播窗口：藏起来就再也找不回来了
        self.drag = None
        self.forced_sleep, self.forced_at = False, 0.0
        self.was_sleeping = False
        self.last_cursor = QCursor.pos()
        self.last_move = -99.0
        self.keys_seen = 0
        self.last_render = 0.0
        self.clock = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(15)

    # ---------- 设置 ----------
    def load_settings(self):
        for path in (self.settings_file, self.cfg.dir / "settings.json"):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def save_settings(self):
        data = {"x": self.x(), "y": self.y(), "scale": round(self.scale_v, 4), "keys": self.show_keys,
                "admin": self.admin, "desktop": self.desktop_on, "live": self.live is not None,
                "top": self.on_top, "through": self.through, "voice": self.voice_on, "mic": self.mic,
                "voice_gate": self.voice.gate_name(), "lang": self.lang_choice}
        if self.live is not None:
            data["live_pos"] = [self.live.x(), self.live.y()]
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def apply_flags(self):
        """置顶、鼠标穿透：改窗口标志后要重新 show 一下才生效。"""
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.on_top:
            flags |= Qt.WindowStaysOnTopHint
        if self.through:
            flags |= Qt.WindowTransparentForInput
        shown = self.isVisible()
        self.setWindowFlags(flags)
        if shown:
            self.show()

    def apply_size(self):
        S = self.scale_v
        dpr = max(s.devicePixelRatio() for s in QGuiApplication.screens())
        self.rig.build(S, dpr)
        c = self.cfg.canvas
        self.setFixedSize(round(c.width() * S), round(c.height() * S))
        if self.live is not None:
            self.live.setFixedSize(self.size())

    def place(self, st):
        if "x" in st and "y" in st:
            c = QPoint(st["x"] + self.width() // 2, st["y"] + self.height() // 2)
            if QGuiApplication.screenAt(c) is not None:
                self.move(st["x"], st["y"])
                return
        g = QGuiApplication.primaryScreen().availableGeometry()
        self.move(g.right() - self.width() - 20, g.bottom() - self.height())

    def set_scale(self, s):
        s = clamp(s, self.cfg.scale_min, self.cfg.scale_max)
        self.want = s
        if abs(s - self.scale_v) < 1e-4:
            return
        anchor = QPoint(self.x() + self.width() // 2, self.y() + self.height())   # 以脚底中间为准缩放
        self.scale_v = s
        self.apply_size()
        self.move(anchor.x() - self.width() // 2, anchor.y() - self.height())
        self.save_settings()

    def wheelEvent(self, e):
        n = e.angleDelta().y() / 120
        if n:
            self.want = clamp(self.want * self.cfg.scale_step ** n, self.cfg.scale_min, self.cfg.scale_max)
            if not self.zoom_timer.isActive():
                self.zoom_timer.start(40)

    # ---------- 每帧 ----------
    def tick(self):
        now = time.perf_counter()
        dt, self.clock = now - self.clock, now
        r, inp, cfg = self.rig, self.inputs, self.cfg
        m = time.monotonic()

        cur = QCursor.pos()
        if cur != self.last_cursor:
            inp.last_input = self.last_move = m
            self.last_cursor = cur
        r.look_active = m - self.last_move < 2.5
        r.typing = m - inp.last_key < 2.0

        S = r.scale
        c = cfg.canvas
        hx = self.x() + (cfg.neck[0] - c.x()) * S
        hy = self.y() + (cfg.aim_y - c.y()) * S
        r.tx = math.tanh((cur.x() - hx) / cfg.tanh[0])     # 软饱和：远处的光标不会把头拧到底
        r.ty = math.tanh((cur.y() - hy) / cfg.tanh[1])

        vg = QGuiApplication.primaryScreen().virtualGeometry()
        scr = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        sg = scr.geometry()
        mx_span, up, down = cfg.desk.get("mouse", [0, 0, 0]) if cfg.desk else (0, 0, 0)
        if mx_span:
            nx = clamp((cur.x() - vg.x()) / max(1, vg.width()) * 2 - 1, -1, 1)
            ny = clamp((cur.y() - sg.y()) / max(1, sg.height()) * 2 - 1, -1, 1)
            r.mx_t = nx * mx_span
            r.my_t = ny * (down if ny > 0 else up)
        r.mouse_down = inp.mouse_down

        if inp.pressed and m - inp.last_key > 3:
            inp.pressed.clear()                       # 防止漏掉的松键事件卡住
        r.hand_down = bool(inp.pressed) or m - inp.last_key < 0.1
        if inp.key_count != self.keys_seen:
            self.keys_seen = inp.key_count
            r.on_key()

        if self.forced_sleep and inp.last_input > self.forced_at + 2:
            self.forced_sleep = False
        r.voice_in = self.voice.level if self.voice_on else 0.0
        if r.voice_in > 0.3:
            inp.last_input = m                        # 在说话就不睡
        r.sleeping = self.forced_sleep or (m - inp.last_input > cfg.sleep_after)
        if self.was_sleeping and not r.sleeping:
            r.blink()                                 # 醒来眨一下
        self.was_sleeping = r.sleeping

        r.update(dt)
        # 全 CPU 软件画：动的时候 30 帧，发呆 24，睡觉 12
        if r.sleeping:
            fps = 12
        elif r.look_active or r.typing or r.happy > 0 or r.voice > 0.05 or self.drag is not None:
            fps = 30
        else:
            fps = 24
        if now - self.last_render >= 1 / fps - 0.004:
            self.last_render = now
            r.render()
            if self.desktop_on:
                self.update()
            if self.live is not None:
                self.live.update()

    def paint_all(self, p):
        cfg = self.cfg
        self.rig.paint(p)
        if self.show_keys and cfg.keys and cfg.keys.get("pos"):
            inp, m = self.inputs, time.monotonic()
            alpha = 1.0 if inp.pressed else clamp(1 - (m - inp.key_t - 0.8) / 0.6, 0, 1)
            pop = clamp(1 - (m - inp.key_pop) / 0.12, 0, 1)
            S = self.rig.scale
            c = cfg.canvas
            p.save()
            p.scale(S, S)
            p.translate(-c.x(), -c.y())
            paint_keys(p, inp.key_text, alpha, pop, cfg, 4 * self.rig.breath)
            p.restore()

    def paintEvent(self, _):
        p = QPainter(self)
        self.paint_all(p)
        p.end()

    # ---------- 交互 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            gp = e.globalPosition().toPoint()
            self.drag, self.press_at, self.moved = gp - self.pos(), gp, False

    def mouseMoveEvent(self, e):
        if self.drag is not None and e.buttons() & Qt.LeftButton:
            gp = e.globalPosition().toPoint()
            if (gp - self.press_at).manhattanLength() > 4:
                self.moved = True
            if self.moved:
                self.move(gp - self.drag)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.drag is not None:
            if self.moved:
                self.save_settings()
            else:
                self.forced_sleep = False
                self.inputs.last_input = time.monotonic()
                self.rig.poke()
            self.drag = None

    def contextMenuEvent(self, e):
        self.menu(e.globalPos())

    def menu(self, pos):
        menu = QMenu(self)
        self.fill_menu(menu)
        menu.exec(pos)

    def fill_menu(self, menu):
        L = self.lang

        def item(text, on, fn, where=menu):
            where.addAction(("● " if on else "　 ") + text).triggered.connect(fn)

        pct = round(self.scale_v / self.cfg.scale_default * 100)
        menu.addAction("　 " + tr(L, "size", p=pct)).setEnabled(False)
        if pct != 100:
            item(tr(L, "size_reset"), False, lambda: self.set_scale(self.cfg.scale_default))
        menu.addSeparator()
        item(tr(L, "top"), self.on_top, self.toggle_top)
        item(tr(L, "through"), self.through, self.toggle_through)
        if self.tray is not None or self.live is not None:
            item(tr(L, "desktop"), self.desktop_on, self.toggle_desktop)
        menu.addSeparator()
        item(tr(L, "keys"), self.show_keys, self.toggle_keys)
        item(tr(L, "wake" if self.rig.sleeping else "sleep"), False, self.toggle_sleep)
        menu.addSeparator()
        item(tr(L, "live"), self.live is not None, self.toggle_live)
        item(tr(L, "voice"), self.voice_on, self.toggle_voice)
        if self.voice_on:
            sub = menu.addMenu("　 " + tr(L, "mic"))
            item(tr(L, "mic_default"), not self.mic, lambda: self.set_mic(None), sub)
            for name in Voice.devices():
                item(name, self.mic == name, lambda _=False, n=name: self.set_mic(n), sub)
            sub = menu.addMenu("　 " + tr(L, "gate"))
            for name, g in self.voice.gates.items():
                item(gate_label(L, name), g == self.voice.gate, lambda _=False, g=g: self.set_gate(g), sub)
        item(tr(L, "admin"), self.admin, self.toggle_admin)
        menu.addSeparator()
        sub = menu.addMenu("　 " + tr(L, "lang"))
        item(tr(L, "lang_auto"), self.lang_choice not in ("zh", "en"), lambda: self.set_lang("auto"), sub)
        for code, label in LANGS:
            item(label, self.lang_choice == code, lambda _=False, c=code: self.set_lang(c), sub)
        item(tr(L, "quit"), False, self.quit)

    def set_lang(self, choice):
        self.lang_choice = choice
        self.lang = resolve(choice)
        if self.live is not None:
            self.live.retitle()
        self.save_settings()

    def tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:        # 左键点托盘：藏起来 / 叫出来
            self.toggle_desktop()

    def toggle_voice(self):
        if self.voice_on:
            self.voice.stop()
            self.voice_on = False
        else:
            self.voice_on = self.voice.start(self.mic) or self.voice.start(None)
            if not self.voice_on and self.tray is not None:
                self.tray.showMessage(self.cfg.name, tr(self.lang, "mic_fail") + self.voice.error[:80])
        self.save_settings()

    def set_mic(self, name):
        self.mic = name
        if self.voice_on:
            self.voice_on = self.voice.start(name) or self.voice.start(None)
        self.save_settings()

    def set_gate(self, g):
        self.voice.gate = g
        self.save_settings()

    def toggle_top(self):
        self.on_top = not self.on_top
        self.apply_flags()
        self.save_settings()

    def toggle_through(self):
        if not self.through and self.tray is None:
            return                                    # 没托盘就关不回来了
        self.through = not self.through
        self.apply_flags()
        self.save_settings()

    def toggle_keys(self):
        self.show_keys = not self.show_keys
        self.inputs.show_names = self.show_keys
        self.inputs.key_text = ""
        self.save_settings()

    def toggle_sleep(self):
        if self.rig.sleeping:
            self.forced_sleep = False
            self.inputs.last_input = time.monotonic()
        else:
            self.forced_sleep, self.forced_at = True, time.monotonic()

    def open_live(self, pos=None):
        self.live = LiveWindow(self)
        if pos and QGuiApplication.screenAt(QPoint(pos[0] + 40, pos[1] + 40)) is not None:
            self.live.move(pos[0], pos[1])
        self.live.show()

    def toggle_live(self):
        if self.live is None:
            self.open_live()
        else:
            live, self.live = self.live, None
            live.close()
        self.save_settings()

    def toggle_desktop(self):
        if self.desktop_on and self.tray is None and self.live is None:
            return
        self.desktop_on = not self.desktop_on
        self.setVisible(self.desktop_on)
        self.save_settings()

    def toggle_admin(self):
        self.admin = not self.admin
        self.save_settings()
        if self.admin and not is_admin():
            self.lock.unlock()                        # 让新开的那个能拿到锁
            if run_elevated(self.relaunch, self.workdir, getattr(sys, "frozen", False)):
                self.quit()
                return
            self.lock.tryLock(100)                    # UAC 点了「否」：接着用现在这个
            self.admin = False
            self.save_settings()

    def quit(self):
        self.save_settings()
        if self.live is not None:
            live, self.live = self.live, None
            live.close()
        if self.tray is not None:
            self.tray.hide()
        self.voice.stop()
        self.inputs.stop()
        QApplication.quit()


def start(cfg, relaunch=None, workdir=None):
    """启动整套：单实例锁、键盘钩子、窗口、事件循环。"""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    d = app_dir(cfg.slug)
    d.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(d / "pet.lock"))
    if not lock.tryLock(100):
        return 0                                      # 已经开着一个了
    inputs = Inputs()
    inputs.start()
    rig = Rig(cfg)
    pet = Pet(cfg, rig, inputs, lock, relaunch=relaunch, workdir=workdir)
    if pet.desktop_on:
        pet.show()
    return app.exec()


def log_error(cfg, exc_text):
    try:
        d = app_dir(cfg.slug)
        d.mkdir(parents=True, exist_ok=True)
        (d / "error.log").write_text(exc_text, encoding="utf-8")
    except OSError:
        pass
