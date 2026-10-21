"""把画师给的分好组的 PSD 转成桌宠模型：切图、写 parts.json、生成一份能直接跑的 config.json。

    python -m psd2pet.import_psd 我的角色.psd --out models/xiaohu   # 从 PSD
    python -m psd2pet.import_psd 导出的文件夹 --out models/xiaohu   # 从一堆 PNG

PSD 里最外面那层文件夹 = 动作组，往里才是要切开的图层。组名按关键字认：
头/脸/眼/嘴 → head，刘海/前发 → bang，后发/尾巴/呆毛 → back，挂件/飘带 → loose，
身体/衣服 → body，桌子/键盘/鼠标/手 → desk。认不出的会列出来，不会乱猜。

头组里名字带眼白、眼珠、眉毛、眼线、闭眼、眯眼、嘴的，会被认成对应表情。其余是普通部件，
按 PSD 里的上下顺序叠。生成后先看预览图，不合适就改 config.json 里的数字，不用碰代码。
PSD 只读，不会被改动。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------------------------------------------------------- 名字 → 动作组

GROUPS = {
    "bang": ("刘海", "前发", "前髪", "bangs", "bang", "fringe"),
    "back": ("后发", "后髮", "后脑", "双马尾", "马尾", "呆毛", "丸子", "发髻", "尾巴", "後ろ髪", "後髪",
             "hairback", "backhair", "ahoge", "tail", "bun"),
    "loose": ("挂件", "坠", "飘带", "蝴蝶结", "穗", "饰品", "loose", "charm", "ribbon"),
    "desk": ("桌子", "桌垫", "桌面", "键盘", "鼠标", "玩偶", "desk", "table", "mousepad",
             "keyboard", "mouse", "doll"),
    "head": ("头", "脸", "面部", "五官", "表情", "眼", "眉", "嘴", "耳", "鬓", "侧发", "中发",
             "head", "face", "eye", "brow", "mouth", "ear", "顔", "頭", "目", "口"),
    "body": ("身体", "身", "衣服", "body", "clothes", "torso", "手", "hand", "arm"),
}

# 表情 / 五官。顺序很重要：先认最具体的（「眯眼」「闭眼」里也有「眼」）。
ROLES = (
    ("happy_eye", ("眯眼", "笑眼", "星星眼", "happy", "smile")),
    ("closed", ("闭眼", "眨眼", "closed", "blink", "shut")),
    ("line", ("眼线", "眼睛+眉毛", "眼睛和眉毛", "眼睛轮廓", "眼眶", "eyeline", "outline")),
    ("brow", ("眉", "brow")),
    ("white", ("眼白", "white", "sclera")),
    ("iris", ("眼珠", "瞳孔", "虹膜", "iris", "pupil")),
    ("mouth", ("嘴", "口", "mouth")),
)

DESK_PARTS = {
    "mousepad": ("桌垫", "鼠标垫", "mousepad", "mat"),
    "doll": ("玩偶", "doll", "plush"),
    "mouse": ("鼠标", "mouse"),
    "hand_l": ("左手", "handl", "lefthand"),
    "hand_r_up": ("右手抬", "抬手", "缩", "收", "handrup", "rightup"),
    "hand_r_down": ("右手", "按键", "handrdown", "rightdown"),
}

ROLE_IDS = {"white": "eyewhite", "iris": "iris", "line": "eye-line", "brow": "brow",
            "closed": "eye-closed", "happy_eye": "eye-happy"}
Z = {"head": [26, 18], "bang": [40, 22], "back": [-14, -10], "loose": [-34, -16], "body": [0, 0]}
BULGE = {"head": [88, 62], "bang": [40, 30], "back": [0, 0], "loose": [0, 0], "body": [0, 0]}


def norm(s):
    return re.sub(r"[_\-\s·.。、()（）\[\]【】]+", "", s).lower()


def hit(name, words):
    n = norm(name)
    return any(norm(w) in n for w in words)


def group_of(name):
    """名字 → 动作组。先看最外层文件夹名，认不出再一段段往里看。"""
    segs = [s for s in name.split("/") if s]
    for s in segs[:1] + segs[:0:-1]:
        for g, words in GROUPS.items():
            if hit(s, words):
                return g
    # 组名里没写清楚，但名字本身是桌子部件（右手抬）或五官（瞳孔、iris）的，也能认
    if desk_part_of(name):
        return "desk"
    if role_of(name):
        return "head"
    return None


def desk_part_of(name):
    leaf = name.split("/")[-1]
    for pid, words in DESK_PARTS.items():
        if hit(leaf, words):
            return pid
    return None


def role_of(name):
    leaf = name.split("/")[-1]
    for role, words in ROLES:
        if hit(leaf, words):
            return role
    return None


def slug(name):
    return re.sub(r"[\\/:*?\"<>|\s]+", "_", name).strip("_") or "pet"


def safe_id(name):
    return re.sub(r"[^\w-]+", "-", name.replace("/", "-")).strip("-") or "part"


# ---------------------------------------------------------------- 读 PSD / 文件夹

class Pic:
    """切出来的一张图：名字（文件夹/图层）、RGBA、画布上的框、是否隐藏、混合模式。"""

    def __init__(self, name, image, box, hidden=False, blend="normal"):
        self.name, self.image, self.box, self.hidden, self.blend = name, image, box, hidden, blend


def _crop(img, box, doc):
    """图 → 裁到不透明的边（并裁掉画布外的部分），返回 (RGBA 图, 画布上的框)。"""
    a = np.array(img.convert("RGBA"))
    ys, xs = np.where(a[..., 3] > 0)
    if len(xs) == 0:
        return None, None
    x0, y0 = max(box[0] + int(xs.min()), 0), max(box[1] + int(ys.min()), 0)
    x1, y1 = min(box[0] + int(xs.max()) + 1, doc[0]), min(box[1] + int(ys.max()) + 1, doc[1])
    if x1 <= x0 or y1 <= y0:
        return None, None
    cut = a[y0 - box[1]:y1 - box[1], x0 - box[0]:x1 - box[0]]
    return Image.fromarray(np.ascontiguousarray(cut), "RGBA"), (x0, y0, x1 - x0, y1 - y0)


def from_psd(path):
    """从下往上走一遍，返回 (画布大小, [Pic])。只读。

    一个「部件」= 最里面那层文件夹（里面的线稿、上色、阴影会先合成一张），
    或者直接放在外面的单个图层。文件夹里还有文件夹的，就继续往里拆。
    """
    from psd_tools import PSDImage

    psd = PSDImage.open(str(path))
    doc = (int(psd.width), int(psd.height))

    def flat(layer, chain):
        """合成一个部件。备用表情、另一只手常常是藏着的：只在内存里临时打开它和上层文件夹的眼睛，
        合成完马上还原（不保存，PSD 文件不会变）。部件里面藏着的草稿层照样不要。"""
        hidden = [l for l in chain + [layer] if not l.visible]
        for l in hidden:
            l.visible = True
        try:
            if layer.kind == "pixel":
                return layer.topil(), layer.bbox[:2]
            return layer.composite(force=True), layer.bbox[:2]
        finally:
            for l in hidden:
                l.visible = False

    def walk(node, chain, hidden):
        for layer in node:
            hid = hidden or not layer.visible
            path_ = tuple(l.name for l in chain) + (layer.name,)
            if layer.is_group() and any(c.is_group() for c in layer):
                yield from walk(layer, chain + [layer], hid)
                continue
            try:
                img, at = flat(layer, chain)
            except Exception as e:
                print(f"[读不出来，跳过] {'/'.join(path_)}：{e}")
                continue
            if img is None:
                continue
            cut, box = _crop(img, at, doc)
            if cut is None:
                continue
            blend = "multiply" if "multiply" in str(layer.blend_mode).lower() else "normal"
            yield Pic("/".join(path_), cut, box, hid, blend)

    return doc, list(walk(psd, [], False))


def from_folder(path):
    """已经导出成一堆 PNG 的：子文件夹名 = 动作组，文件名 = 图层名，文件名排序 = 从下往上。

    导出时每张都保留完整画布大小，位置才对得上；裁过边的只能对齐左上，要手动改 parts.json 的 x/y。
    """
    path = Path(path)
    pngs = sorted(p for p in path.rglob("*") if p.suffix.lower() == ".png")
    if not pngs:
        raise SystemExit(f"这个文件夹里没有 PNG：{path}")
    ims = [(p, Image.open(p).convert("RGBA")) for p in pngs]
    doc = (max(im.width for _, im in ims), max(im.height for _, im in ims))
    pics, small = [], []
    for p, im in ims:
        if im.size != doc:
            small.append(p.name)
        cut, box = _crop(im, (0, 0), doc)
        if cut is None:
            continue
        pics.append(Pic("/".join(p.relative_to(path).with_suffix("").parts), cut, box))
    if small:
        print(f"[注意] 这些图比画布小，像是裁过边的，位置会对不上：{', '.join(small[:6])}"
              f"{' …' if len(small) > 6 else ''}。导出时选「保留画布大小」可以省掉手调。")
    return doc, pics


# ---------------------------------------------------------------- 分组、认表情

def plan(pics):
    """→ (按叠放顺序的 [(组, 角色或 None, 图)], 桌子部件 {pid: 图}, 跳过的名字)"""
    order, desk, skipped = [], {}, []
    for pic in pics:
        g = group_of(pic.name)
        if g == "desk" or (g == "body" and desk_part_of(pic.name)):
            pid = desk_part_of(pic.name)          # 另一只手常常是藏着的，桌子部件不管隐不隐藏都要
            if pid and pid not in desk:
                desk[pid] = pic
            elif not pid and not pic.hidden:
                skipped.append(pic.name)
            continue
        role = role_of(pic.name) if g == "head" else None
        if pic.hidden and not role:
            continue                                  # 隐藏的普通层是画师的草稿/备用，不要
        if g is None:
            skipped.append(pic.name)
            continue
        order.append((g, role, pic))

    # 同一种角色出现两次：第二张闭眼当笑眼；嘴里看得见的那张是平常，其余是说话时换着用的
    # 名字里写了「平常」的优先（PNG 文件夹没有隐藏这回事，只能靠名字）
    seen, mouths = set(), 0
    ms = [p for g, r, p in order if r == "mouth"]
    first_mouth = next((p for p in ms if hit(p.name.split("/")[-1], ("平常", "默认", "常态", "normal", "default"))),
                       next((p for p in ms if not p.hidden), ms[0] if ms else None))
    out = []
    for g, role, pic in order:
        if role == "mouth" and pic is not first_mouth:
            role = "mouth_alt"
        if role == "closed" and "closed" in seen and "happy_eye" not in seen:
            role = "happy_eye"
        if role == "mouth_alt":
            mouths += 1
            role = f"mouth{mouths}"
        elif role in seen:
            role = None                               # 第二张眼白之类：当普通部件
        if pic.hidden and role is None:
            continue
        if role:
            seen.add(role)
        out.append((g, role, pic))
    return out, desk, skipped


def union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def field_of(box, grow=1.0):
    x, y, w, h = box
    return [round(x + w / 2, 1), round(y + h / 2, 1),
            round(max(w * 0.55 * grow, 1), 1), round(max(h * 0.55 * grow, 1), 1)]


def build_config(name, doc, order, desk):
    boxes = {g: [p.box for gg, r, p in order if gg == g] for g in Z}
    head_box = union(boxes["head"] + boxes["bang"]) or union([p.box for _, _, p in order])
    body_box = union(boxes["body"]) or head_box
    hx, top, hw, hh = head_box
    cx = hx + hw / 2
    bottom = body_box[1] + body_box[3] if boxes["body"] else top + hh
    neck_y = round(body_box[1] + body_box[3] * 0.06) if boxes["body"] else round(top + hh * 0.9)
    desk_y = round(bottom)
    # 弧面（脸鼓起来的那块）：有「脸」就按脸算，没有就按整个头估
    face = next((p.box for g, r, p in order if g == "head" and hit(p.name.split("/")[-1], ("脸", "face", "顔"))),
                None)
    if face:
        fx, fy, fw, fh = face
        head_field = [round(fx + fw / 2, 1), round(fy + fh / 2, 1), round(fw * 0.7, 1), round(fh * 0.65, 1)]
    else:
        head_field = field_of(head_box, 0.8)
    body_field = field_of(body_box, 0.8)
    cx = head_field[0]
    sitting = bool(desk)
    # 默认的挪动量是按「脸宽 470 像素」调的，脸画得大/小就按比例放大/缩小
    k = head_field[2] / 330

    def kk(v):
        return [round(x * k, 1) for x in v]

    everything = union([p.box for _, _, p in order] + [p.box for p in desk.values()])
    m = round(max(everything[2], everything[3]) * 0.04)
    canvas = [max(0, everything[0] - m), max(0, everything[1] - m),
              min(doc[0], everything[0] + everything[2] + m), min(doc[1], everything[1] + everything[3] + m)]
    canvas = [canvas[0], canvas[1], canvas[2] - canvas[0], canvas[3] - canvas[1]]

    specs, faces, mouths, used = [], {}, [], {}
    for g, role, pic in order:
        base = ROLE_IDS.get(role) or ("mouth" if role and role.startswith("mouth") else safe_id(pic.name))
        n = used.get(base, 0)
        used[base] = n + 1
        pid = f"{base}-{n + 1}" if n else base
        spec = {"id": pid, "group": g, "z": kk(Z[g]), "bulge": kk(BULGE[g]),
                "field": head_field if g in ("head", "bang") else body_field}
        if pic.blend == "multiply":
            spec["blend"] = "multiply"
        if role == "iris" and "white" in faces:       # 眼白在眼珠下面才能裁：眼珠只露在眼白里
            spec["clip"] = [faces["white"]]
        if role and role.startswith("mouth"):
            spec["z"] = kk([28, 18])
            mouths.insert(0 if role == "mouth" else len(mouths), (pid, pic))
        elif role:
            faces[role] = pid
        specs.append((spec, pic, role))

    def box_of(role):
        return next((p.box for s, p, r in specs if r == role), None)

    # 五官定位：有图就从图的位置量，没有就按头的比例估
    eye_box = union([box_of(r) for r in ("white", "iris", "line", "closed")])
    if eye_box:
        ex, ey, ew, eh = eye_box
        mid_x = ex + ew / 2
        eye_c = [[round(ex + ew * 0.25), round(ey + eh / 2)], [round(ex + ew * 0.75), round(ey + eh / 2)]]
    else:
        mid_x = cx
        eye_c = [[round(cx - hw * 0.12), round(top + hh * 0.55)], [round(cx + hw * 0.12), round(top + hh * 0.55)]]
    brow = box_of("brow")
    brow_y = round(brow[1] + brow[3] * 0.75) if brow else round(eye_c[0][1] - hh * 0.1)
    mb = mouths[0][1].box if mouths else None
    mouth_c = [round(mb[0] + mb[2] / 2), round(mb[1] + mb[3] / 2)] if mb else [round(cx), round(top + hh * 0.8)]
    mouth_top = [mouth_c[0], mb[1]] if mb else [mouth_c[0], mouth_c[1] - 8]

    closed = faces.get("closed") or faces.get("happy_eye")
    happy = faces.get("happy_eye") or closed
    faces = {"white": faces.get("white"), "iris": faces.get("iris"), "line": faces.get("line"),
             "brow": faces.get("brow"), "closed": closed, "happy": happy if happy != closed else None,
             "blink": closed, "sleep": closed, "happy_eye": happy,
             "mouth": mouths[0][0] if mouths else None, "mouths": [m for m, _ in mouths[1:]]}

    # 第一次打开窗口高约 430 像素，之后用滚轮调
    mid = round(430 / canvas[3], 3)
    hand =lambda pid: desk[pid].box if pid in desk else None   # noqa: E731
    hl, hr = hand("hand_l"), hand("hand_r_down")
    return {
        "name": name, "slug": slug(name), "mode": "sitting" if sitting else "standing",
        "parts": "parts.json", "parts_dir": "parts",
        "canvas": canvas,
        "scale": {"default": mid, "min": round(mid * 0.3, 3), "max": round(mid * 2.2, 3), "step": 1.08},
        "sleep_after": 90,
        "icon_box": [int(hx), int(top), int(max(hw, hh))],
        "look": {"neck": [round(cx), neck_y], "aim_y": desk_y - round(hh * 0.4),
                 "yaw": 26, "pitch": 18, "tanh_x": 450, "tanh_y": 350},
        "fields": {"head": head_field, "body": body_field},
        "head": {"shift": round(26 * k), "up": round(20 * k), "down": round(30 * k),
                 "bang_up": round(18 * k), "bang_down": round(34 * k), "lag_max": 4.0, "roll_lag": 1.5,
                 "pin": [neck_y, round(160 * k), 0.35, 0.45]},
        "body": {"desk": [round(cx), desk_y]},
        "eyes": {"mid_x": round(mid_x), "brow_y": brow_y, "centers": eye_c,
                 "pupil": kk([9, 6]), "foreshorten": [0.2, 0.05]},
        "mouth": {"center": mouth_c, "top": mouth_top},
        "swing": {"hang_gravity": 0.7},
        "layers": [s for s, _, _ in specs],
        "faces": faces,
        "desk": {"parts": [p for p in DESK_PARTS if p in desk],
                 "shoulder_l": [round(cx - hw * 0.17), neck_y + round(hh * 0.12)],
                 "shoulder_r": [round(cx + hw * 0.17), neck_y + round(hh * 0.12)],
                 # 手腕：手那张图靠肩膀的一头
                 # 手按在鼠标/键盘上的那个点：手图的下沿附近
                 "grip_l": [round(hl[0] + hl[2] * 0.35), round(hl[1] + hl[3] * 0.88)] if hl
                 else [round(cx - hw * 0.3), desk_y],
                 "tip_r": [round(hr[0] + hr[2] * 0.56), round(hr[1] + hr[3] * 0.95)] if hr
                 else [round(cx + hw * 0.25), desk_y],
                 "mouse": kk([42, 18, 30]), "doll_center": [0.42, 0.92]},
        "keys": {"show": sitting, "pos": [canvas[0] + round(canvas[2] * 0.02), canvas[1] + round(canvas[3] * 0.06)],
                 "max_w": round(canvas[2] * 0.8)},
        "zzz": {"at": [round(cx + hw * 0.45), round(top + hh * 0.15)],
                "drift": kk([100, -200]), "color": [110, 130, 190]},
        "blink": [0.055, 0.075],
        "voice": {"open": 0.12, "gates": {"高": 6, "中": 10, "低": 15}},
        "window": {"key_color": [255, 0, 255]},
        "shadow": {"on": not sitting, "size": [round(hw * 1.2), round(hw * 0.2)],
                   "color": [0, 0, 0, 60], "at": [round(cx), desk_y]},
    }, [(s["id"], p) for s, p, _ in specs]


# ---------------------------------------------------------------- 落盘

def write(out, cfg, saved, desk, doc):
    out = Path(out)
    parts = out / "parts"
    if parts.exists():
        shutil.rmtree(parts)
    parts.mkdir(parents=True)
    meta = {"canvas": list(doc), "parts": []}
    for pid, pic in saved + list(desk.items()):
        pic.image.save(parts / f"{pid}.png")
        x, y, w, h = pic.box
        meta["parts"].append({"id": pid, "x": x, "y": y, "w": w, "h": h})
    (out / "parts.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(meta["parts"])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="psd2pet.import_psd", description="把分好组的 PSD（或导出的 PNG）变成桌宠模型")
    ap.add_argument("src", help="PSD 文件，或者一个放着 PNG 的文件夹")
    ap.add_argument("--out", required=True, help="模型输出文件夹，例如 models/xiaohu")
    ap.add_argument("--name", help="角色名（默认用输出文件夹名）")
    ap.add_argument("--force", action="store_true", help="输出文件夹已有模型也覆盖")
    ap.add_argument("--no-preview", action="store_true", help="不画预览图")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    src, out = Path(args.src), Path(args.out)
    if not src.exists():
        raise SystemExit(f"找不到：{src}")
    if (out / "config.json").exists() and not args.force:
        raise SystemExit(f"{out} 里已经有模型了，要覆盖加 --force")

    doc, pics = from_folder(src) if src.is_dir() else from_psd(src)
    order, desk, skipped = plan(pics)
    if not order:
        raise SystemExit("一个动作组都没认出来。最外层文件夹名要带「头/刘海/后发/身体」之类的词，见 docs 里的拆层需求单。")
    if skipped:
        print(f"[没放进去] {', '.join(skipped[:10])}{' …' if len(skipped) > 10 else ''}"
              "（名字里加上组名就能认出来）")

    cfg, saved = build_config(args.name or out.name, doc, order, desk)
    n = write(out, cfg, saved, desk, doc)
    print(f"[好了] {out}")
    print(f"  画布 {doc[0]}x{doc[1]}，共 {n} 张图，{len(cfg['layers'])} 张参与变形，模式 {cfg['mode']}")
    print(f"  五官：{ {k: v for k, v in cfg['faces'].items() if v} }")
    print(f"  桌子：{cfg['desk']['parts'] or '无'}")
    if not args.no_preview:
        try:
            from .preview import preview
            preview(out, out / "preview.png", None, 1.0)
            print(f"  预览：{out / 'preview.png'}")
        except Exception as e:
            print(f"  [预览没画出来，不影响模型] {type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
