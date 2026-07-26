"""
Anima Weaver — Random Resolution Selector v7
Scoring-based decision engine with 7-layer normalization.
"""

from __future__ import annotations

import math
import random
import re
from typing import Any

# ── 比例映射表 ──
ASPECT_MAP = {
    "1:1":   (1, 1),
    "2:3":   (2, 3),
    "3:2":   (3, 2),
    "3:4":   (3, 4),
    "4:3":   (4, 3),
    "4:5":   (4, 5),
    "5:4":   (5, 4),
    "9:16":  (9, 16),
    "16:9":  (16, 9),
    "21:9":  (21, 9),
}
ASPECT_NAMES = list(ASPECT_MAP.keys())

RATIO_THRESHOLD = {
    "21:9": 5,
    "16:9": 3,
    "3:2":  1,
    "9:16": 4,
    "2:3":  2,
    "4:5":  3,
    "1:1":  3,
    "4:3":  2,
}

# ── 关键词集合 ──
PERSON      = frozenset({"solo", "1girl", "1boy", "alone", "person"})
COUPLE      = frozenset({"2girls", "2boys", "couple"})
GROUP_SMALL = frozenset({"3girls", "3boys", "4girls", "4boys"})
GROUP_LARGE = frozenset({"group", "crowd"})
MULTIPLE = frozenset({"multiple"})
POV         = frozenset({"pov"})
OTS         = frozenset({"over the shoulder"})
PANORAMA    = frozenset({"panorama", "grand vista", "breathtaking view", "scenic view"})
WIDE_ANGLE  = frozenset({"wide angle", "wide shot", "wide view", "landscape composition"})
AERIAL      = frozenset({"aerial view", "bird's eye view", "top down view"})
FIGHTING    = frozenset({"fighting"})
ACTION      = frozenset({"action pose", "dynamic pose", "mid-air", "airborne",
                         "leaping", "sprinting", "dashing", "jumping", "flying"})
ACROBAT     = frozenset({"flip", "somersault", "cartwheel", "spin", "dive", "roll", "vault"})
FACE        = frozenset({"face close up", "headshot", "muzzle", "only face", "face shot", "closeup"})
BUST        = frozenset({"bust", "half body", "mid shot", "medium shot",
                         "waist shot", "bust portrait"})
AMERICAN    = frozenset({"american shot", "knee shot"})
UPPER       = frozenset({"upper body", "waist up", "chest up", "upper half"})
LOWER       = frozenset({"lower body", "waist down", "lower half"})
FOCUS       = frozenset({"thighs focus", "crotch focus", "belly focus", "abdomen focus"})
FULL        = frozenset({"full body"})
SITTING     = frozenset({"sitting", "kneeling", "legs crossed"})
LYING       = frozenset({"lying", "sleeping"})
CURLED      = frozenset({"curled up"})
STILL       = frozenset({"still life", "item focus", "object close up",
                         "macro shot", "tabletop", "flower arrangement",
                         "object study", "artifact display"})
STILL_WIDE  = frozenset({"weapon detail", "food close up", "flower close up",
                         "crystal detail", "gem close up", "product shot",
                         "food photography", "product display"})
ARGUE       = frozenset({"arguing", "facing off", "standing apart", "separated", "distance"})
TALL        = frozenset({"tall portrait", "vertical composition", "phone format"})
SELFIE      = frozenset({"selfie"})
CHIBI       = frozenset({"chibi"})
LOW_ANGLE   = frozenset({"low angle", "from below"})
HIGH_ANGLE  = frozenset({"high angle", "from above"})

# ── 7层归一化 ──
NORM_LAYERS = [
    # Layer 0: 复合词优先
    {
        r'\bface[_\- ]?close[_\- ]?up\b': 'face close up',
        r'\bclose[_\- ]?up[_\- ]?face\b': 'face close up',
        r'\bmacro\b': 'macro shot',
        r'\bstill[_\- ]?life\b': 'still life',
        r'\bproduct[_\- ]?shot\b': 'product shot',
        r'\bobject[_\- ]?close[_\- ]?up\b': 'object close up',
        r'\bweapon[_\- ]?detail\b': 'weapon detail',
        r'\bfood[_\- ]?close[_\- ]?up\b': 'food close up',
        r'\bflower[_\- ]?close[_\- ]?up\b': 'flower close up',
        r'\bgem[_\- ]?close[_\- ]?up\b': 'gem close up',
        r'\bcrystal[_\- ]?detail\b': 'crystal detail',
        r'\bartifact[_\- ]?display\b': 'artifact display',
        r'\bproduct[_\- ]?display\b': 'product display',
        r'\bobject[_\- ]?study\b': 'object study',
        r'\bfood[_\- ]?photography\b': 'food photography',
        r'\bflower[_\- ]?arrangement\b': 'flower arrangement',
        r'\btabletop\b': 'tabletop',
        r'\blandscape[_\- ]?composition\b': 'landscape composition',
        r'\blandscape[_\- ]?orientation\b': 'landscape composition',
        r'\bvertical[_\- ]?composition\b': 'vertical composition',
        r'\btall[_\- ]?portrait\b': 'tall portrait',
        r'\bupright[_\- ]?format\b': 'tall portrait',
        r'\bphone[_\- ]?format\b': 'phone format',
        r'\bvertical[_\- ]?shot\b': 'tall portrait',
        r'\bgroup[_\- ]?photo\b': 'group',
        r'\bgroup[_\- ]?shot\b': 'group',
        r'\bback[_\- ]?view\b': 'back view',
        r'\bfrom[_\- ]?behind\b': 'back view',
        r'\bbird[_\- ]?s?[_\- ]?eye[_\- ]?view\b': "bird's eye view",
        r'\btop[_\- ]?down[_\- ]?view\b': 'top down view',
    },
    # Layer 1: 人数与群体
    {
        r'\b1(boy|girl)s\b': lambda m: f"1{m.group(1)}",
        r'\b([2-4])(boy|girl)(?![s])\b': lambda m: f"{m.group(1)}{m.group(2)}s",
        r'\b([5-9]\d*|1\d+)(boy|girl)s?\b': 'group',
        r'\btwo\s+(girls?|boys?)\b': lambda m: f"2{m.group(1).rstrip('s')}s",
        r'\bthree\s+(girls?|boys?)\b': lambda m: f"3{m.group(1).rstrip('s')}s",
        r'\bfour\s+(girls?|boys?)\b': lambda m: f"4{m.group(1).rstrip('s')}s",
        r'\bmultiple[s]?\b': 'multiple',
        r'\bmultiple[_\- ]?(girls|boys|people|girl|boy)\b': 'multiple',
        r'\bmany\b': 'multiple',
        r'\beveryone\b': 'group',
        r'\b(s?he|they)\b': 'person',
        r'\bperson\b': 'person',
        r'\balone\b': 'solo',
        r'\bduo\b': 'couple',
        r'\bpair\b': 'couple',
        r'\bcrowd\b': 'crowd',
        r'\bmultiple\s+(girls|boys|people)\b': 'multiple',
    },
    # Layer 2: 景别与镜头
    {
        r'\bfull[_\- ]?body\b': 'full body',
        r'\bfullbody\b': 'full body',
        r'\bwhole\s+body\b': 'full body',
        r'\bentire\s+body\b': 'full body',
        r'\bfull[_\- ]?length\b': 'full body',
        r'\bfull[_\- ]?shot\b': 'full body',
        r'\bfull[_\- ]?figure\b': 'full body',
        r'\bfull[_\- ]?portrait\b': 'full body',
        r'\bmid[_\- ]?shot\b': 'mid shot',
        r'\bmedium[_\- ]?shot\b': 'medium shot',
        r'\bwaist[_\- ]?shot\b': 'waist shot',
        r'\bamerican[_\- ]?shot\b': 'american shot',
        r'\bknee[_\- ]?shot\b': 'american shot',
        r'\bhalfbody\b': 'half body',
        r'\bhalf[_\- ]?length\b': 'half body',
        r'\bupper[_\- ]?half\b': 'upper half',
        r'\blower[_\- ]?half\b': 'lower half',
        r'\bwaist[_\- ]?down\b': 'waist down',
        r'\bwaist[_\- ]?up\b': 'waist up',
        r'\bchest[_\- ]?up\b': 'chest up',
        r'\bupper[_\- ]?body\b': 'upper body',
        r'\blower[_\- ]?body\b': 'lower body',
        r'\bbust[_\- ]?portrait\b': 'bust portrait',
        r'\bportrait\b': 'portrait',
        r'\bselfie\b': 'selfie',
        r'\bchibi\b': 'chibi',
        r'\bonly[_\- ]?face\b': 'only face',
        r'\bface[_\- ]?shot\b': 'face shot',
    },
    # Layer 3: POV
    {
        r'\bp\.?o\.?v\b': 'pov',
        r'\bpoint[_\- ]?of[_\- ]?view\b': 'pov',
        r'\bfirst[_\- ]?person\b': 'pov',
        r'\bpov[_\- ]?shot\b': 'pov',
        r'\bover[_\- ]?the[_\- ]?shoulder\b': 'over the shoulder',
    },
    # Layer 4: 动作/姿态
    {
        r'\baction[_\- ]?pose\b': 'action pose',
        r'\bdynamic[_\- ]?pose\b': 'dynamic pose',
        r'\bjumping\b': 'jumping',
        r'\bflying\b': 'flying',
        r'\bsprinting\b': 'sprinting',
        r'\bdashing\b': 'dashing',
        r'\bairborne\b': 'airborne',
        r'\bleaping\b': 'leaping',
        r'\bfighting\b': 'fighting',
        r'\bcombat\b': 'fighting',
        r'\bbattle\b': 'fighting',
        r'\bflip\b': 'flip',
        r'\bsomersault\b': 'somersault',
        r'\bcartwheel\b': 'cartwheel',
        r'\bspin\b': 'spin',
        r'\bdive\b': 'dive',
        r'\broll\b': 'roll',
        r'\bvault\b': 'vault',
        r'\blying\b': 'lying',
        r'\blaying\b': 'lying',
        r'\breclining\b': 'lying',
        r'\blounging\b': 'lying',
        r'\bprone\b': 'lying',
        r'\bsupine\b': 'lying',
        r'\bsprawled\b': 'lying',
        r'\bsleeping\b': 'sleeping',
        r'\bsitting\b': 'sitting',
        r'\bseated\b': 'sitting',
        r'\bkneeling\b': 'kneeling',
        r'\blegs[_\- ]?crossed\b': 'legs crossed',
        r'\bcurled[_\- ]?up\b': 'curled up',
        r'\bfetal[_\- ]?position\b': 'curled up',
        r'\barguing?\b': 'arguing',
        r'\bfacing[_\- ]?off\b': 'facing off',
        r'\bstanding[_\- ]?apart\b': 'standing apart',
        r'\bseparated\b': 'separated',
        r'\bdistance\b': 'distance',
    },
    # Layer 5: 面部/焦点
    {
        r'\bheadshot\b': 'headshot',
        r'\bmuzzle\b': 'muzzle',
        r'\bfocus[_\- ]?on\b': 'focus',
        r'\bthighs?\s+focus\b': 'thighs focus',
        r'\bthigh\s+close[_\- ]?up\b': 'thighs focus',
        r'\bcrotch[_\- ]?focus\b': 'crotch focus',
        r'\bbelly[_\- ]?focus\b': 'belly focus',
        r'\babdomen[_\- ]?focus\b': 'abdomen focus',
    },
    # Layer 6: 场景/环境
    {
        r'\bpanorama\b': 'panorama',
        r'\bpanoramic\b': 'panorama',
        r'\bwide[_\- ]?angle\b': 'wide angle',
        r'\bwide[_\- ]?shot\b': 'wide shot',
        r'\bwide[_\- ]?view\b': 'wide view',
        r'\bgrand[_\- ]?vista\b': 'grand vista',
        r'\bbreathtaking[_\- ]?view\b': 'breathtaking view',
        r'\bscenic[_\- ]?view\b': 'scenic view',
        r'\baerial[_\- ]?view\b': 'aerial view',
    },
    # Layer 7: 角度
    {
        r'\blow[_\- ]?angle\b': 'low angle',
        r'\bhigh[_\- ]?angle\b': 'high angle',
        r'\beye[_\- ]?level\b': 'eye level',
        r'\bfrom[_\- ]?below\b': 'from below',
        r'\bfrom[_\- ]?above\b': 'from above',
        r'\bfront[_\- ]?view\b': 'front view',
        r'\bside[_\- ]?view\b': 'side view',
        r'\bthree[_\- ]?quarter\b': 'three quarter view',
        r'\btilted\b': 'tilted',
        r'\bdutch[_\- ]?angle\b': 'low angle',
        r'\bcanted\b': 'low angle',
        r'\boverhead\b': 'from above',
        r'\btop[_\- ]?view\b': 'top down view',
        r'\bground[_\- ]?level\b': 'low angle',
        r'\bworm[_\- ]?s?[_\- ]?eye[_\- ]?view\b': 'low angle',
        r'\bstraight[_\- ]?on\b': 'front view',
    },
]


def normalize(tokens: list[str]) -> list[str]:
    result = []
    for t in tokens:
        t = t.strip().lower()
        if not t:
            continue
        for layer in NORM_LAYERS:
            matched = False
            for pattern, replacement in layer.items():
                if callable(replacement):
                    new_t = re.sub(pattern, replacement, t)
                else:
                    new_t = re.sub(pattern, replacement, t)
                if new_t != t:
                    t = new_t
                    matched = True
                    break
            if matched:
                break
        result.append(t)
    return result


def resolve_ratio(tokens: list[str]) -> str:
    tset = frozenset(tokens)

    ws = 0
    hs = 0
    ss = 0

    has_group = (COUPLE | GROUP_SMALL | GROUP_LARGE | MULTIPLE) & tset
    has_person = PERSON & tset
    is_lying = LYING & tset
    is_curled = CURLED & tset

    # 独立分支
    if POV & tset:
        return "9:16" if SELFIE & tset else "16:9"
    if ACROBAT & tset:
        return "3:2"
    if STILL_WIDE & tset and not has_person:
        return "4:3"

    # 宽屏因子
    if FIGHTING & tset:
        ws += 3
    if ACTION & tset:
        ws += 2
    if OTS & tset:
        ws += 3
    if WIDE_ANGLE & tset:
        ws += 3 if has_person else 2
    if AERIAL & tset:
        ws += 3 if has_person else 4
    if tset & GROUP_SMALL:
        ws += 1
    if tset & GROUP_LARGE:
        ws += 5
    if PANORAMA & tset:
        ws += 5
    if FULL & tset and has_group:
        ws += 2
    if ARGUE & tset and (GROUP_SMALL & tset or GROUP_LARGE & tset):
        ws += 1
    if is_lying and has_person and not has_group and not is_curled:
        ws += 2
        hs = 0
    if is_curled and has_person and not has_group:
        hs = 0  # curled up cancels FULL hs bonus
    if LOW_ANGLE & tset:
        ws += 1
    # 组合加分
    if FIGHTING & tset and ACTION & tset:
        ws += 1
    if PANORAMA & tset and WIDE_ANGLE & tset:
        ws += 1
    if FULL & tset and ACTION & tset:
        ws += 1
    # COUPLE bonus when combined with composition keywords
    if tset & COUPLE and (FULL & tset or FIGHTING & tset or ACTION & tset or
            OTS & tset or WIDE_ANGLE & tset or AERIAL & tset or
            tset & GROUP_SMALL or tset & GROUP_LARGE or
            PANORAMA & tset or ARGUE & tset or LOW_ANGLE & tset):
        ws += 2

    # 竖屏因子
    if TALL & tset:
        hs += 4 if not has_group else 1
    if SELFIE & tset:
        hs += 4
    if FULL & tset and has_person and not has_group and not is_lying and not is_curled:
        hs += 2
    if BUST & tset:
        hs += 1
    if UPPER & tset or LOWER & tset:
        hs += 2
    if SITTING & tset:
        hs += 3
    if is_curled and has_person and not has_group:
        hs += 1

    # 方屏因子
    if FACE & tset or FOCUS & tset:
        ss += 5
    if CHIBI & tset:
        ss += 4
    if AMERICAN & tset:
        ss += 3
    if STILL & tset and not STILL_WIDE & tset:
        ss += 2
    if HIGH_ANGLE & tset:
        ss += 1

    # 群体/双人无修饰 → 3:4
    if (tset & COUPLE or tset & MULTIPLE) and ws == 0 and hs == 0 and ss == 0:
        return "3:4"

    # 躺卧全身 → 4:3
    if is_lying and FULL & tset and has_person and not has_group:
        return "4:3"

    # OTS 硬覆盖
    if OTS & tset:
        return "16:9"

    # TALL + group → 3:4
    if TALL & tset and has_group:
        return "3:4"

    # AMERICAN → 4:5
    if AMERICAN & tset and ss >= 2:
        return "4:5"

    # 评分决策
    if ss >= RATIO_THRESHOLD["1:1"] and ss > max(ws, hs):
        return "1:1"

    if ws > hs:
        if ws >= RATIO_THRESHOLD["21:9"]:
            return "21:9"
        if ws >= RATIO_THRESHOLD["16:9"]:
            return "16:9"
        if ws >= RATIO_THRESHOLD["3:2"]:
            return "3:2"
        return "16:9"

    if hs > ws:
        if hs >= RATIO_THRESHOLD["9:16"]:
            return "9:16"
        if hs >= RATIO_THRESHOLD["4:5"]:
            return "4:5"
        if hs >= RATIO_THRESHOLD["2:3"]:
            return "2:3"
        return "3:4"

    if ws == hs and ws > 0:
        return "3:4" if has_person else "1:1"

    if has_person:
        return "2:3"
    return "1:1"


def _resolve(megapixels: float, ratio_key: str, align: int = 16) -> tuple[int, int]:
    w_r, h_r = ASPECT_MAP[ratio_key]
    area = megapixels * 1024 * 1024
    k = math.sqrt(area / (w_r * h_r))
    w = int(k * w_r)
    h = int(k * h_r)
    w = max(512, (w // align) * align)
    h = max(512, (h // align) * align)
    if max(w, h) > 2048:
        s = 2048.0 / max(w, h)
        w = int(w * s)
        h = int(h * s)
        w = (w // align) * align
        h = (h // align) * align
    return w, h


def _pick_manual(随机画幅: bool, 固定比例: str, 百万像素: float, 对齐到: int,
                 seed_val: int | None = None) -> tuple[int, int]:
    if seed_val is None:
        _seed = random.randint(0, 0x7FFFFFFF)
    else:
        _seed = seed_val
    rng = random.Random(_seed)
    ratio_name = rng.choice(ASPECT_NAMES) if 随机画幅 else 固定比例
    return _resolve(百万像素, ratio_name, 对齐到)


def analyze_prompt(prompt: str) -> str:
    if not prompt or not prompt.strip():
        return "1:1"
    tokens = normalize([t.strip() for t in prompt.replace(",", "\n").split("\n") if t.strip()])
    return resolve_ratio(tokens)


class RandomResolution:
    @classmethod
    def INPUT_TYPES(s) -> dict[str, Any]:
        return {
            "required": {
                "模式": ("BOOLEAN", {"default": False, "tooltip": "True=自动(分析提示词), False=手动"}),
                "随机画幅": ("BOOLEAN", {"default": True, "tooltip": "手动模式/自动补齐: 随机选比例"}),
                "百万像素": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 32.0, "step": 0.01}),
                "固定比例": (ASPECT_NAMES, {"default": "3:4"}),
                "对齐到": ("INT", {"default": 8, "min": 1, "max": 256, "step": 1}),
            },
            "optional": {
                "随机种子": ("INT", {"forceInput": True, "default": 0, "min": 0, "max": 0x7FFFFFFF}),
                "种子串": ("STRING", {"forceInput": True, "multiline": True}),
                "提示词": ("STRING", {"forceInput": True, "multiline": True}),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("INT", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("随机种子", "种子串", "宽度", "高度")
    FUNCTION = "pick"
    OUTPUT_NODE = False

    def pick(self, 模式: bool, 随机画幅: bool, 百万像素: float, 固定比例: str,
             对齐到: int = 8, 随机种子: int | None = None,
             种子串: str = "", 提示词: str = "") -> tuple[int, str, str, str]:
        seed_str = 种子串.strip()
        prompt_str = 提示词.strip() if 提示词 else ""

        seeds = []
        if seed_str:
            for s in seed_str.split("\n"):
                s = s.strip()
                if s:
                    try:
                        seeds.append(int(s))
                    except ValueError:
                        pass

        if not 模式:
            if seeds:
                ws, hs = [], []
                for sv in seeds:
                    w, h = _pick_manual(随机画幅, 固定比例, 百万像素, 对齐到, sv)
                    ws.append(str(w))
                    hs.append(str(h))
                fw, fh = _pick_manual(随机画幅, 固定比例, 百万像素, 对齐到, seeds[0])
                return (fw, "\n".join(map(str, seeds)), "\n".join(ws), "\n".join(hs))
            sv = int(随机种子) if 随机种子 is not None and str(随机种子) != "" else None
            w, h = _pick_manual(随机画幅, 固定比例, 百万像素, 对齐到, sv)
            return (w, str(sv) if sv else "", str(w), str(h))

        prompt_lines = [l.strip() for l in prompt_str.split("\n") if l.strip()] if prompt_str else []

        if not seeds:
            ratio = analyze_prompt(prompt_lines[0]) if prompt_lines else "3:4"
            w, h = _resolve(百万像素, ratio, 对齐到)
            return (random.randint(0, 0x7FFFFFFF), "", str(w), str(h))

        ws, hs = [], []
        for i, sv in enumerate(seeds):
            if i < len(prompt_lines):
                ratio = analyze_prompt(prompt_lines[i])
            else:
                if 随机画幅:
                    rng = random.Random(sv)
                    ratio = rng.choice(ASPECT_NAMES)
                else:
                    ratio = 固定比例
            w, h = _resolve(百万像素, ratio, 对齐到)
            ws.append(str(w))
            hs.append(str(h))

        first_ratio = analyze_prompt(prompt_lines[0]) if prompt_lines else "3:4"
        fw, fh = _resolve(百万像素, first_ratio, 对齐到)
        return (fw, "\n".join(map(str, seeds)), "\n".join(ws), "\n".join(hs))


NODE_CLASS_MAPPINGS = {"RandomResolution": RandomResolution}
NODE_DISPLAY_NAME_MAPPINGS = {"RandomResolution": "随机分辨率选择器"}
