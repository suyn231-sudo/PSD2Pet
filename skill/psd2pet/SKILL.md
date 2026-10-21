---
name: psd2pet
description: Turn a layered character PSD (or a folder of full-canvas PNGs) into a Windows desktop pet with PSD2Pet — import, preview, tune config.json by looking at renders, run, and package an exe. Use when the user wants a desktop pet / 桌宠 from their VTuber or chibi artwork.
---

# PSD2Pet skill

You are helping someone (often a first-timer, sometimes an artist or rigger) turn their character art into a
desktop pet. Reply in the user's language. Keep it short and concrete; they want a pet, not a lecture.

The repo root contains `psd2pet/` (engine), `run_pet.py`, `build_exe.py`, `docs/zh`, `docs/en`.
Engine behaviour is driven entirely by `models/<name>/config.json`; you should almost never edit Python.

## Ground rules

- The artwork belongs to the user's artist. Never upload it anywhere, never commit it, never copy it outside
  `models/`. `models/` is git-ignored except its README.
- Never modify the user's PSD. The importer only reads it; write output to `models/<name>`.
- Always look at the preview images before saying something is fixed. Numbers or renders, not guesses.
- Don't start the pet window on your own (it is always-on-top). Use `--preview` renders; ask before launching.
- Windows only.

## 1. Setup (once)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
Python 3.10+.

## 2. Check what the user has

Ask (or inspect) only what you need:
- A PSD, or a folder of PNGs exported at full canvas size? (Cropped PNGs lose their positions.)
- Sitting at a desk (keyboard, mouse, hands) or standing (full body, no desk)? The importer decides by
  whether desk parts exist; the user can switch `mode` later.

If their artist hasn't split the layers yet, give them `docs/zh/拆层需求单.md` or `docs/en/layer-brief.md` to send.

## 3. Import

```
.venv\Scripts\python -m psd2pet.import_psd "<psd or folder>" --out models/<name> --name "<display name>"
```
`--force` overwrites an existing output folder. Read the printout:
- `[没放进去]` / skipped names: parts whose name has no known keyword. Either rename the folder in a *copy* of
  the PSD, or add the part to `layers` in config.json by hand (see 5).
- `五官` (faces): which layers became iris / eye-line / closed / mouth… Missing roles are fine (no blink if no
  closed eye, no lip sync if only one mouth), but tell the user what that means.
- `桌子` (desk): which desk parts were found.

Keyword tables live at the top of `psd2pet/import_psd.py` (`GROUPS`, `ROLES`, `DESK_PARTS`). Grouping logic:
outermost folder name first, then from the leaf upward. A folder whose children are all plain layers is one part.

## 4. Preview and look

The import writes `preview.png` (14 states: idle, look 6 ways, blink, poke, sleep, typing, talking) and
`preview_turn.png` (head sweep). Re-render after editing config:
```
.venv\Scripts\python -m psd2pet --model models/<name> --preview models/<name>/preview.png
```
Open both images and check, in this order:
1. Nothing cut off at the window edge → `canvas`.
2. Head turns without tearing at the neck or between bangs and face → `head.pin`, group z values.
3. Eyes follow and stay in the whites; blink closes in the right place → `eyes`.
4. Mouth opens at the mouth → `mouth`.
5. Hands sit on the mouse / keys (sitting) → `desk`.

## 5. Tuning cheat sheet (config.json)

All coordinates are PSD canvas pixels. Change one thing, re-render, compare.

| Symptom | Key |
|---|---|
| Window cuts the character / too much empty space | `canvas` [x, y, w, h] |
| Default size wrong | `scale.default`, `scale.min/max` |
| Head turns too much / too little | `look.yaw`, `look.pitch`, `head.shift/up/down` |
| Bangs slide off the face / not enough parallax | bang layers' `z`, `head.bang_up/bang_down` |
| Neck tears or head floats off the body | `head.pin` = [pin y, blend height, keep x, keep y]; pin y ≈ chin |
| Face bulges too much / too flat | layer `bulge` [x, y], `fields.head` [cx, cy, rx, ry] (ellipse of the face) |
| Eyes move too far / not enough | `eyes.pupil` [x, y] |
| Blink squashes in the wrong spot | `eyes.centers` (two eye centres), `eyes.mid_x`, `eyes.brow_y` |
| Mouth opens in the wrong place | `mouth.center`, `mouth.top` |
| Wrong layer used as eye / mouth | `faces` (white, iris, line, brow, closed, happy_eye, mouth, mouths[]) |
| Part should swing like hair / ribbon | add to that layer: `"hang": {"root": y, "amp": 400, "spring": "rib"}` |
| Tips of hair should lag | `"bend": {"root": y, "amp": 60, "spring": "hair"}` |
| Charm / tassel should dangle | `"tassel": {"root": y, "amp": 3}` |
| A small part should ride with an eye | `"anchor": "eyes"` or `"anchor": [x, y]` |
| A layer should move with something else | its `group`: head / bang / back / loose / body |
| Hands in wrong place (sitting) | `desk.grip_l`, `desk.tip_r`, `desk.shoulder_l/r` |
| Key display position | `keys.pos`, `keys.max_w`; on by default only when sitting |
| Sleep "Zzz" position | `zzz.at` |
| Shadow under a standing pet | `shadow.on/size/at` |
| Talking too / not sensitive | `voice.gates` |
| Falls asleep too soon | `sleep_after` (seconds) |

Missing keys fall back to defaults in `psd2pet/config.py`; layers listed in config but missing from
`parts.json` are skipped, so it never crashes on an incomplete model.

## 6. Run

Ask first, then:
```
.venv\Scripts\python run_pet.py --model models/<name>
```
Right-click or tray icon for the menu (reset size, always-on-top, click-through, key display, voice, live-capture
window for OBS, language 中文/English, follows the system by default). Scroll wheel resizes. Settings are saved in `%APPDATA%\PSD2Pet\<slug>`.

## 7. Package

```
.venv\Scripts\python build_exe.py --model models/<name>
```
→ `dist\<name>\<name>.exe`, with the model copied to `dist\<name>\model\`. Zip the whole folder.
Remind the user: sharing the exe shares the artwork; check with their artist first.

## Limits to be honest about

- It is 2.5D warping of flat layers, not Live2D. Big turns will show missing paint behind parts.
- No arm/leg animation for standing pets beyond the body sway; that needs extra layers and hand-written config.
- Generic names like 图层 12 or 眼睛1 aren't recognised; renaming is faster than guessing.
