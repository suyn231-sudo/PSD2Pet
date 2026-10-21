"""声捕：麦克风音量 → 0..1。只算每 20ms 的音量，不录音、不存盘。"""
import math

import numpy as np

from .motion import clamp


class Voice:
    def __init__(self, cfg):
        self.level = 0.0
        self.floor = -60.0                            # 环境噪音（dB），自己慢慢学
        gates = cfg.voice.get("gates") or {"中": 10}
        self.gates = dict(gates)
        self.gate = self.gates.get("中", next(iter(self.gates.values())))
        self.stream = None
        self.error = ""
        self.name = ""

    @staticmethod
    def devices():
        """同一套驱动下的麦克风名字（不然一个麦会列出好几遍）。"""
        try:
            import sounddevice as sd
            api = sd.query_devices(kind="input")["hostapi"]
            return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0 and d["hostapi"] == api]
        except Exception:
            return []

    def start(self, name=None):
        self.stop()
        try:
            import sounddevice as sd
            dev = None
            if name:
                api = sd.query_devices(kind="input")["hostapi"]
                for i, d in enumerate(sd.query_devices()):
                    if d["name"] == name and d["max_input_channels"] > 0 and d["hostapi"] == api:
                        dev = i
            sr = int(sd.query_devices(dev, "input")["default_samplerate"])
            self.stream = sd.InputStream(device=dev, channels=1, samplerate=sr, blocksize=sr // 50,
                                         dtype="float32", callback=self._cb)
            self.stream.start()
            self.error, self.name = "", name or ""
            return True
        except Exception as e:
            self.stream, self.error = None, str(e)
            return False

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        self.stream = None
        self.level = 0.0

    def _cb(self, data, _frames, _t, _status):
        db = 10 * math.log10(float(np.mean(data[:, 0] ** 2)) + 1e-10)
        # 噪音底：往下跟得快，往上很慢（一直说话也不会把它抬上去）
        self.floor += (db - self.floor) * (0.2 if db < self.floor else 0.0005)
        self.floor = clamp(self.floor, -85.0, -25.0)
        self.level = clamp((db - self.floor - self.gate) / 18, 0.0, 1.0)

    def gate_name(self):
        return next((k for k, v in self.gates.items() if v == self.gate), "中")
