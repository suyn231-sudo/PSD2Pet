"""启动入口：

    python -m psd2pet --model models/my_pet                 # 开桌宠
    python -m psd2pet --model models/my_pet --preview a.png # 离屏画预览
    python run_pet.py                                       # 不写 --model：自己找 model/ 或 models/ 里的第一个
"""
import argparse
import ctypes
import sys
import traceback
from pathlib import Path

from .config import Config
from .i18n import system_lang, tr


def base_dir():
    """打包成 exe 时是 exe 所在的文件夹，平时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def find_model():
    """没指定模型：先找旁边的 model/，再找 models/ 下面第一个带 config.json 的文件夹。"""
    base = base_dir()
    if (base / "model" / "config.json").exists():
        return base / "model"
    for d in sorted((base / "models").glob("*")):
        if (d / "config.json").exists():
            return d
    return None


def say(text):
    """双击 exe 时没有控制台，出错用弹窗告诉人；命令行里跑的只打印，不弹窗。"""
    if sys.stdout is not None and not getattr(sys, "frozen", False):
        print(text)
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, "PSD2Pet", 0x10)
    except Exception:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="psd2pet", description="把拆好的 PSD 图层变成桌宠")
    ap.add_argument("--model", help="模型文件夹（里面是 config.json、parts.json、parts/）；不写就自己找")
    ap.add_argument("--preview", metavar="PNG", help="不开窗口，把几种状态画成一张图")
    ap.add_argument("--scale", type=float, help="预览用的缩放，默认用配置里的 scale.default")
    ap.add_argument("--seconds", type=float, default=3.0, help="每个状态先跑几秒（默认 3）")
    ap.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    model = Path(args.model) if args.model else find_model()
    if model is None or not (model / "config.json").exists():
        say(tr(system_lang(), "no_model", p=model or base_dir() / "model"))
        return 2
    model = model.resolve()

    if args.preview:
        from .preview import preview
        preview(model, args.preview, args.scale, args.seconds)
        return

    from . import app as appmod
    try:
        cfg = Config(model)
    except Exception:
        say(tr(system_lang(), "bad_model") + traceback.format_exc(limit=3))
        return 2
    try:
        # 以管理员身份重开自己时，带上同一个模型
        appmod.start(cfg, relaunch=["--model", str(model)], workdir=str(base_dir()))
    except Exception:
        appmod.log_error(cfg, traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
