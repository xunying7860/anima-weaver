# -*- coding: utf-8 -*-
"""tools/migrate_workflows.py — 四节点精简版（8→4）工作流迁移

用法：python tools/migrate_workflows.py [workflows目录]

做四件事（全部按**名字**重排 slot，绝不按数字硬编码 —— 不同工作流是
不同时期保存的，旧 slot 数字并不一致，例如「种子串」在旧文件里是 3、
在上一版 main 上是 1，历史上已经因此静默接错过一次）：
  1. 工作流 6→2：只留 anima双采-随机提示词-v2 / 随机提示词编织器-批量 并改名
  2. 删除 4 个已消失节点（Anima反推/画师Seed/Anima加载图像/Anima列表转多行）
     及其全部连线
  3. forceInput 输入端口 / 输出端口按新名字重排（AnimaWeaver 删 随机种子/
     画师串/反推串/系统提示词/槽位数据/底部数据；AnimaBatchBus 删「画师」
     通道 → 其余通道两端 slot 全部前移；RandomResolution 删 随机种子 端口）
  4. AnimaWeaver widgets_values：旧 43 项 → 新 46 项（index 2 场景类型→随机
     种子置 0；index 0/23 选项值改官方中文用语；末尾补 系统提示词 三项）

⚠ 只收集 drop、其余连线一律保留（用 keep 集合会误删绝大多数线）；
⚠ drop 先收集、最后一次性过滤（边遍历边删会让后续 remap 读到错位下标）。
"""
import json
import glob
import os
import sys

# ── 1) 只保留 2 个工作流并重命名 ──
KEEP = {
    "anima双采-随机提示词-v2.json": "anima双采-随机提示词.json",
    "随机提示词编织器-批量.json":   "随机提示词-批量.json",
}

# ── 2) 改后各节点的 forceInput 输入端口顺序 ──
PORT_ORDER = {
    "AnimaWeaver":      ["种子串"],
    "RandomResolution": ["种子串", "提示词"],
    "AnimaBatchBus":    ["种子串", "提示词串", "分辨率串", "反推串",
                         "宽度串", "高度串", "JSON行"],
}

# ── 3) 改后各节点的输出顺序（删中间项的必须重排）──
OUT_ORDER = {
    "AnimaWeaver":   ["生成的提示词", "调试信息"],
    "AnimaBatchBus": ["合并输出", "种子", "提示词", "反推",
                      "分辨率", "宽度", "高度"],
}

DELETE_NODES = {"ArtistSeedNode", "AnimaImageCaption",
                "AnimaLoadImages", "AnimaTextListToMultiline"}

OLD_WIDGETS = 43          # 旧 AnimaWeaver widget 数（43 → 46）
SEED_INDEX = 2            # 「场景类型」(combo) → 「随机种子」(INT)
APPEND = [False, "", ""]  # ▸ 系统提示词 / 系统提示词 / 详细NL系统提示词

# 选项官方用语：旧英文值 → 新中文值（widget 下标不变，只换值）
MODE_MAP = {0: {"manual": "手动", "random": "随机", "hybrid": "混合"},
            23: {"manual": "手动", "lm_studio": "LM Studio"}}


def prune_and_rename(d):
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        p = os.path.join(d, f)
        if f in KEEP:
            if KEEP[f] != f:
                os.rename(p, os.path.join(d, KEEP[f]))
                print("rename", f, "->", KEEP[f])
        else:
            os.remove(p)
            print("delete", f)


def migrate(path):
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    links = j.get("links", [])
    drop = set()          # 只收集「要删的」，其余一律保留

    # A) 被删节点 → 与之相连的所有线
    gone = {n["id"] for n in j["nodes"] if n.get("type") in DELETE_NODES}
    for l in links:
        if l[1] in gone or l[3] in gone:
            drop.add(l[0])

    for n in j["nodes"]:
        t = n.get("type")

        # B) 输入端口：按名字重算 target_slot
        order = PORT_ORDER.get(t)
        if order:
            new_slot = {nm: i for i, nm in enumerate(order)}
            remap = {}
            for slot, inp in enumerate(n.get("inputs") or []):
                nm, lid = inp.get("name"), inp.get("link")
                if nm in new_slot:
                    remap[slot] = new_slot[nm]
                elif lid is not None:
                    drop.add(lid)                  # 端口已删 → 删线
            n["inputs"] = [{"name": nm, "type": "*", "link": None}
                           for nm in order]
            for l in links:
                if l[3] != n["id"] or l[0] in drop:
                    continue
                ns = remap.get(l[4])
                if ns is None:
                    drop.add(l[0])
                    continue                       # 指到已删端口
                l[4] = ns
                n["inputs"][ns]["link"] = l[0]

        # C) 输出端口：按名字重算 origin_slot
        oorder = OUT_ORDER.get(t)
        if oorder:
            new_oslot = {nm: i for i, nm in enumerate(oorder)}
            remap_o = {}
            for slot, o in enumerate(n.get("outputs") or []):
                nm = o.get("name")
                if nm in new_oslot:
                    remap_o[slot] = new_oslot[nm]
                else:
                    for lid in (o.get("links") or []):
                        drop.add(lid)              # 输出槽已删 → 删线
            n["outputs"] = [{"name": nm, "type": "*", "links": []}
                            for nm in oorder]
            for l in links:
                if l[1] != n["id"] or l[0] in drop:
                    continue
                ns = remap_o.get(l[2])
                if ns is None:
                    drop.add(l[0])
                    continue
                l[2] = ns
                n["outputs"][ns].setdefault("links", []).append(l[0])
            for o in n["outputs"]:
                if not o.get("links"):
                    o["links"] = None

        # D) widgets_values（AnimaWeaver：43→46 + 选项官方用语）
        if t == "AnimaWeaver":
            v = n.get("widgets_values") or []
            if len(v) >= OLD_WIDGETS:
                out = list(v[:OLD_WIDGETS]) + APPEND
                out[SEED_INDEX] = 0                # 场景类型(combo) → 随机种子(INT)
                for idx, mp in MODE_MAP.items():
                    if isinstance(out[idx], str) and out[idx] in mp:
                        out[idx] = mp[out[idx]]    # 旧英文选项值 → 官方中文
                n["widgets_values"] = out

    j["links"] = [l for l in links if l[0] not in drop]
    j["nodes"] = [n for n in j["nodes"] if n["id"] not in gone]

    # E) 悬空指针清扫（三方一致性的最后一环）：被删 link 的引用必须在
    #    src 侧 outputs[].links 与 tgt 侧 inputs.link 两边同步抹掉 ——
    #    本脚本只重建了 PORT_ORDER/OUT_ORDER 里的节点，其余节点（如
    #    BatchSeedNode 的 outputs、showAnything 的 inputs）指向已删
    #    link 的悬空指针会让前端加载时报错。
    alive = {l[0] for l in j["links"]}
    for n in j["nodes"]:
        for o in (n.get("outputs") or []):
            if o.get("links"):
                kept = [lid for lid in o["links"] if lid in alive]
                o["links"] = kept or None
        for inp in (n.get("inputs") or []):
            if inp.get("link") is not None and inp["link"] not in alive:
                inp["link"] = None

    with open(path, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=2)
    return len(j["nodes"]), len(j["links"]), len(drop)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "workflows")
    prune_and_rename(d)
    for f in sorted(glob.glob(d + "/*.json")):
        nn, nl, nd = migrate(f)
        print("migrated %s -> nodes=%d links=%d (删除 %d 条)" % (f, nn, nl, nd))


if __name__ == "__main__":
    main()
