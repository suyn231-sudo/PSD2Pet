# Config reference (for artists, riggers and tinkerers)

## How it works

Not Live2D, no mesh editor. Each part is a flat image. From "how deep it sits on the head" plus "the head is a
sphere" we compute a displacement field and warp each layer with cv2.remap. When the head turns, bangs (deep)
move most, back hair (negative depth) moves the other way, the middle of the face bulges while the edges stay,
and the chin is pinned to the neck. Every number lives in `config.json`; all coordinates are PSD canvas pixels.

A model folder:
```
models/<name>/
  config.json   how it moves
  parts.json    where each image sits {canvas, parts:[{id,x,y,w,h}]}
  parts/*.png   cropped part images, filename = id
```
Missing keys use the defaults in `psd2pet/config.py`. Layers listed in config but absent from parts.json are
skipped, so an incomplete model never crashes.

## How the importer reads layers

`python -m psd2pet.import_psd <psd or folder> --out models/<name> [--name label] [--force] [--no-preview]`

- PSD: walked bottom to top. Folders containing folders are opened further; an innermost folder (or a lone
  layer) is one part, its lineart/colour/multiply layers merged. Hidden parts are switched on in memory only;
  the PSD file is never written.
- PNG folder: filename order = bottom to top; every image must be full canvas size.
- Groups: outermost folder name first, then from the part name outward. The keyword tables are `GROUPS`,
  `ROLES`, `DESK_PARTS` at the top of `import_psd.py`; add your own words there.
- Hidden ordinary parts are treated as drafts and dropped; hidden expressions and desk parts are kept.
- Mouths: the one named normal / default / 平常 is the resting mouth; otherwise the visible one; the rest
  alternate while talking.
- A second closed-eye layer becomes the happy eye.
- Computed for you: canvas crop, default size (window ≈ 430 px tall), face ellipse
  (from a "face" layer if there is one), eye centres, mouth, neck pin, hand grip points. Motion amounts scale
  with face width.

## Keys

### Window and size
| Key | Meaning |
|---|---|
| `name` / `slug` | display name / settings folder (`%APPDATA%\PSD2Pet\<slug>`) |
| `mode` | `sitting` (desk mat, mouse, hands) / `standing` |
| `canvas` | [x, y, w, h] part of the canvas shown in the window |
| `scale` | size {default scale on first launch, min, max, step per wheel notch}. Users scroll to resize; the menu can reset to default |
| `icon_box` | tray icon crop [left, top, side] |
| `sleep_after` | seconds without input before sleeping |

### Head
| Key | Meaning |
|---|---|
| `look.neck` | origin for gaze (the neck) |
| `look.yaw` / `pitch` | max turn left-right / up-down |
| `look.tanh_x` / `tanh_y` | how far the cursor must be (px) to turn fully |
| `fields.head` | face ellipse [cx, cy, rx, ry], the bulging area |
| `head.shift` / `up` / `down` | how far the whole head slides while turning |
| `head.bang_up` / `bang_down` | extra slide for the bangs |
| `head.pin` | [pin y, blend height, keep x, keep y]. Put y at the chin; lower the keeps if the neck tears |
| `head.lag_max` / `roll_lag` | how much hair lags behind |

### Per part `layers[]` (order = drawn bottom to top)
| Key | Meaning |
|---|---|
| `id` | matches parts/<id>.png |
| `group` | head / bang / back / loose / body |
| `z` | [x, y] depth. Positive moves with the turn, negative against it |
| `bulge` | [x, y] sphere bulge. Large for the face, small for bangs, 0 for back hair |
| `field` | ellipse used by this layer, usually fields.head or fields.body |
| `hang` | hanging hair / ribbons: {root y, amp, spring "rib"/"hair"} |
| `bend` | lagging hair tips: {root, amp, spring} |
| `tassel` | charms / tassels: {root, amp} |
| `anchor` | `"eyes"` follow the eyes / [x, y] move rigidly with that point |
| `clip` | only visible inside these layers (irises clipped by eye whites) |
| `blend` | `multiply` |

`spring`: `rib` is softer and slower, `hair` a bit quicker.

### Face `faces`
`white`, `iris`, `line` (eye lines), `brow`, `closed`, `happy_eye`, `blink` / `sleep` (which image for blinking /
sleeping), `mouth` (resting), `mouths` (alternate while talking). Values are part ids, or null.

| Key | Meaning |
|---|---|
| `eyes.centers` | the two eye centres; blinks squash toward them |
| `eyes.mid_x` | left/right eye split |
| `eyes.brow_y` | brow height |
| `eyes.pupil` | max iris travel [x, y] |
| `eyes.foreshorten` | how much the far eye narrows / near eye widens when turning |
| `mouth.center` / `top` | centre and top edge of the opening mouth |
| `blink` | the two blink phase durations (s) |

### Sitting `desk`
| Key | Meaning |
|---|---|
| `parts` | rigid parts: mousepad, doll, mouse, hand_l, hand_r_up, hand_r_down |
| `shoulder_l` / `shoulder_r` | arm pivots |
| `grip_l` | where the left hand holds the mouse |
| `tip_r` | where the right fingertip presses |
| `mouse` | how far the desk mouse follows the real one [sideways, up, down] (px), 0 = still |
| `doll_center` | squash pivot of the plush (relative 0–1) |

### Other
| Key | Meaning |
|---|---|
| `keys` | key display {show default, pos, max_w} |
| `zzz` | sleeping Zzz {at, drift, color} |
| `voice` | lip sync {open threshold, gates sensitivity presets} |
| `window.key_color` | live-window background for OBS chroma key |
| `shadow` | standing shadow {on, size, color, at} |

## Tuning loop

1. Change one key.
2. `python -m psd2pet --model models/<name> --preview out.png`
3. Compare before/after. `out_turn.png` is the head sweep, for tearing.

## Advanced

- Ear flicks and ahoge bounce are special-cased: the part id must be `ears` / `ahoge`, with `ear` / `ahoge`
  parameters on the layer. See `local()` and `_ear_local()` in `psd2pet/rig.py`.
- New motion groups or expression triggers go in `rig.py`. The engine is config-driven; give every new key a
  default in `DEFAULTS` in `config.py`.
