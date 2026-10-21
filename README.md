# PSD2Pet

把拆好层的角色 PSD 变成会动的 Windows 桌宠。
Turn a layered character PSD into a living Windows desktop pet.

[中文](#中文) · [English](#english)

---

## 中文

### 能做什么

- 转头、看鼠标、眨眼、呼吸、头发和挂件跟着晃（2.5D 逐层变形，不是 Live2D，不用建模）
- 坐在桌前：桌垫、鼠标跟着你的鼠标挪、手跟着你打字按键
- 站立：全身角色待在屏幕角落，脚下有影子
- 说话张嘴（麦克风声捕）、按键显示、点她会笑、不碰电脑会睡觉
- 托盘菜单、滚轮缩放、置顶、鼠标穿透、记住位置大小、直播窗口（OBS 窗口捕获 + 色度键）
- 打包成 exe，双击就能开
- 只用 CPU，只支持 Windows

### 需要什么

一张拆好层的 PSD（或每个部件一张完整画布大小的 PNG）。还没拆？把 [拆层需求单](docs/zh/拆层需求单.md) 发给画师。

### 快速开始

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m psd2pet.import_psd "D:\我的角色.psd" --out models\xiaohu --name 小狐
.venv\Scripts\python run_pet.py --model models\xiaohu
.venv\Scripts\python build_exe.py --model models\xiaohu
```

导入后先看 `models\xiaohu\preview.png`。详细步骤看 [新手教程](docs/zh/新手教程.md)，每个参数的意思看 [配置说明](docs/zh/配置说明.md)。

用 Claude Code 之类的 AI 助手？把 `skill/psd2pet` 装成 skill，直接跟它说「帮我把这张 PSD 做成桌宠」。

### 版权

代码 MIT（见 [LICENSE](LICENSE)），第三方库见 [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt)。
你导入的角色图归画师和你所有，不属于本项目，也不要提交到仓库（`models/` 已在 .gitignore 里）。

---

## English

### What it does

- Head turns, follows the cursor, blinks, breathes; hair and charms sway (2.5D per-layer warping, not Live2D, no rigging)
- Sitting at a desk: desk mat, a mouse that follows yours, hands that type along
- Standing: a full-body character in a screen corner with a shadow
- Lip sync from the microphone, key display, smiles when poked, falls asleep when you're away
- Tray menu, wheel zoom, always-on-top, click-through, remembers position and size, live window for OBS
- Builds into a double-click exe
- CPU only, Windows only

### What you need

A layered PSD (or one full-canvas PNG per part). Not split yet? Send your artist the [layer brief](docs/en/layer-brief.md).

### Quick start

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m psd2pet.import_psd "D:\my_character.psd" --out models\fox --name Fox
.venv\Scripts\python run_pet.py --model models\fox
.venv\Scripts\python build_exe.py --model models\fox
```

Check `models\fox\preview.png` after importing. Step by step: [getting started](docs/en/getting-started.md);
every key explained: [config reference](docs/en/config.md).

Using an AI assistant like Claude Code? Install `skill/psd2pet` as a skill and just ask it to turn your PSD into a pet.

The in-app menu follows your Windows language (Chinese or English); switch it under Language in the menu.

### License

Code: MIT ([LICENSE](LICENSE)); third-party: [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt).
Character art you import belongs to its owners, not this project. Don't commit it (`models/` is git-ignored).
