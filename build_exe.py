"""打包成 exe：

    python build_exe.py --model models/my_pet

→ dist\\<模型名>\\<模型名>.exe。整个文件夹一起拷走就能用，模型放在 exe 旁边的 model\\ 里，
以后换图只要替换 model\\ 文件夹，不用重新打包。图标用模型自己截一张头像。
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PSD2PET_DIR"] = str(ROOT / "build" / "tmp")       # 截图标时别动你在用的设置
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser(description="把 PSD2Pet 和一个模型打包成 exe")
    ap.add_argument("--model", required=True, help="模型文件夹")
    ap.add_argument("--name", help="exe 名字，默认用模型的 name")
    args = ap.parse_args()

    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from psd2pet.config import Config
    from psd2pet.rig import Rig

    model = Path(args.model).resolve()
    cfg = Config(model)
    name = args.name or cfg.name
    app = QApplication([])  # noqa: F841  画图标要有 QApplication
    rig = Rig(cfg)
    rig.build(min(cfg.scale_default * 1.5, cfg.scale_max), 1.0)
    png = ROOT / "build" / "icon.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    rig.icon().save(str(png))
    ico = ROOT / "build" / "icon.ico"
    Image.open(png).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", str(ROOT / "run_pet.py"),
        "--name", name, "--windowed", "--noconfirm", "--clean",
        "--icon", str(ico),
        "--paths", str(ROOT),
        "--hidden-import", "pynput.keyboard._win32", "--hidden-import", "pynput.mouse._win32",
        "--exclude-module", "PIL", "--exclude-module", "tkinter", "--exclude-module", "psd_tools",
        *[a for m in ("QtQuick", "QtQml", "QtPdf", "QtNetwork", "QtOpenGL", "QtSvg", "QtQuickWidgets",
                      "QtVirtualKeyboard")
          for a in ("--exclude-module", f"PySide6.{m}")],
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "work"),
        "--specpath", str(ROOT / "build"),
    ], cwd=str(ROOT))

    out = ROOT / "dist" / name
    # 用不上的大件：软件 OpenGL、视频解码、Qt 的 QML/PDF 等（只画 2D、不读视频）
    for pat in ("PySide6/opengl32sw.dll", "cv2/opencv_videoio_ffmpeg*.dll", "PySide6/Qt6Quick*.dll",
                "PySide6/Qt6Qml*.dll", "PySide6/Qt6Pdf*.dll", "PySide6/Qt6VirtualKeyboard*.dll",
                "PySide6/translations/*"):
        for f in (out / "_internal").glob(pat):
            f.unlink()
    shutil.rmtree(out / "model", ignore_errors=True)
    shutil.copytree(model, out / "model", ignore=shutil.ignore_patterns("preview*.png", "*_turn.png"))
    for f in ("LICENSE", "THIRD_PARTY_LICENSES.txt"):
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, out / f)
    print("[好了]", out / f"{name}.exe")


if __name__ == "__main__":
    main()
