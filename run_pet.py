"""双击就能开的入口（也是打包 exe 的入口）。不带参数时自己去找 model/ 或 models/ 里的模型。

    python run_pet.py
    python run_pet.py --model models/my_pet
"""
import sys

from psd2pet.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
