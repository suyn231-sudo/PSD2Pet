# Getting started: your first desktop pet

No coding needed. The flow: get split layers → import → look at the preview → tweak a few numbers → build an exe.

## What you need

1. A Windows PC.
2. The artwork: a layered PSD, or one PNG per part, each exported at full canvas size.
   If it isn't split yet, send your artist the [layer brief](layer-brief.md).
3. Python 3.10+ (https://www.python.org, tick "Add Python to PATH" when installing).

The art belongs to your artist and you. The exe contains your art; ask your artist before sharing it.

## Two ways

### A. Let an AI assistant do it (recommended for beginners)

If you use an assistant that can run commands (Claude Code, Cursor, …):

1. Download this project and open the folder in the assistant.
2. Install `skill/psd2pet` as a skill (Claude Code: copy it to `.claude/skills/psd2pet`).
3. Say: "Turn D:\my_character.psd into a desktop pet."

It imports, shows you the preview, and edits the config as you describe what's wrong
("the head turns too much", "the irises leave the eyes").

### B. By hand

Type `cmd` in the project folder's address bar and press Enter, then:

1. Set up (once)
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
2. Import (use your own path and name)
   ```
   .venv\Scripts\python -m psd2pet.import_psd "D:\my_character.psd" --out models\fox --name Fox
   ```
   For a PNG folder, pass the folder instead of the PSD.
3. Open `models\fox\preview.png`: idle, looking around, blinking, being poked, sleeping, typing, talking.
   `preview_turn.png` sweeps the head left to right to spot tearing.
4. Try it live
   ```
   .venv\Scripts\python run_pet.py --model models\fox
   ```
   Right-click or use the tray icon for the menu; scroll to resize.
5. Build the exe
   ```
   .venv\Scripts\python build_exe.py --model models\fox
   ```
   You get `dist\Fox\Fox.exe`; copy the whole folder.

## What the importer prints

- `[没放进去] xxx` (not used): the part's name has no known keyword. Rename it and import again,
  or add it by hand (see the [config reference](config.md)).
- `五官：{...}` (face parts): which eyes and mouths were found. No closed eye = no blinking;
  one mouth only = no talking. Everything else still works.
- `桌子：[...]` (desk): which desk parts were found. None = standing mode.

## FAQ

Head turns too much / bangs slide off / the neck tears / irises escape?
Open `models\fox\config.json`, change the matching number from the [config reference](config.md), re-render:
```
.venv\Scripts\python -m psd2pet --model models\fox --preview models\fox\preview.png
```
Change one thing at a time and compare.

Key display while standing? Turn on Show keys in the menu.

It ignores key presses in a game? Some games run as administrator; turn on Admin mode in the menu.

The menu follows your Windows language; switch between 中文 and English under Language.
