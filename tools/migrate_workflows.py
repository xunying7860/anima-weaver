# -*- coding: utf-8 -*-
"""tools/migrate_workflows.py — 四节点精简版工作流迁移（v3：总线拆回两节点）

用法：python tools/migrate_workflows.py [workflows目录]
（幂等：已迁移的工作流再跑是无害空操作）

做六件事（全部按**名字**重排 slot，绝不按数字硬编码）：
  1. 工作流 6→2：只留 anima双采-随机提示词(-v2) / 随机提示词编织器-批量 并改名
  2. 删除 4 个已消失节点（Anima反推/画师Seed/Anima加载图像/Anima列表转多行）
     及其全部连线
  3. AnimaBatchBus（带「模式」下拉的合并体）按模式 widget 拆回两个节点：
       模式=合并 → Anima批量合并 AnimaBatchMerge
           输入  种子串/提示词串/宽度串/高度串（分辨率串/反推串/JSON行 删）
           输出  合并输出（其余输出槽删，已有连线作废）
           widget [start_index, max_rows, remove_empty_lines]（去掉模式）
       模式=拆分 → Anima批量拆分 AnimaBatchSplit
           输入  JSON行（唯一入口；上游挂 easy-use 提示词行）
           输出  种子/提示词/宽度/高度（合并输出/反推/分辨率 槽删）
       无模式 widget 的（2026-10-16 上午单节点版）：按端口推断
           （JSON行 已连线→拆分，否则→合并）
     中间的 easy-use「easy promptLine（提示词行）」节点保持原位（用户管线
     本就要求合并与拆分之间挂它）
  4. AnimaWeaver 只留「种子串」输入、RandomResolution 只留「种子串」
     （删 随机种子/画师串/反推串/系统提示词/槽位数据/底部数据/提示词 端口）
  5. widgets_values：
     - AnimaWeaver 旧 43 项 → 新 46 项（index 2 场景类型→随机种子置 0；
       index 0/23 旧英文选项值 → 官方中文；末尾补 系统提示词 三项）
     - 合并/拆分 widget 只留三窗口参数
  6. 孤儿清理：输入连线全部失效的 easy showAnything / ShowText|pysssss /
     easy promptLine / easy string 节点一并删除（它们没有下游）

⚠ 只收集 drop、其余连线一律保留；drop 先收集、最后一次性过滤；
⚠ 收尾用 links 表为唯一真源重建所有节点的 inputs[].link / outputs[].links
  （三方一致性），否则前端加载报悬空错。
"""
import json
import glob
import os
import sys

# ── 1) 只保留 2 个工作流并重命名（幂等） ──
KEEP = {
    "anima双采-随机提示词-v2.json": "anima双采-随机提示词.json",
    "anima双采-随机提示词.json": "anima双采-随机提示词.json",
    "随机提示词编织器-批量.json":   "随机提示词-批量.json",
    "随机提示词-批量.json":         "随机提示词-批量.json",
}

# ── 4) 改后各节点的 forceInput 输入端口顺序（按新类型） ──
PORT_ORDER = {
    "AnimaWeaver":       ["种子串"],
    "RandomResolution":  ["种子串"],
    "AnimaBatchMerge":   ["种子串", "提示词串", "宽度串", "高度串"],
    "AnimaBatchSplit":   ["JSON行"],
}

# ── 改后各节点的输出顺序（删中间项的必须重排）──
OUT_ORDER = {
    "AnimaWeaver":       ["生成的提示词", "调试信息"],
    "AnimaBatchMerge":   ["合并输出"],
    "AnimaBatchSplit":   ["种子", "提示词", "宽度", "高度"],
    # 分辨率节点删「随机种子」输出槽（2026-10-16 用户要求），其余前移
    "RandomResolution":  ["种子串", "宽度", "高度"],
}

DELETE_NODES = {"ArtistSeedNode", "AnimaImageCaption",
                "AnimaLoadImages", "AnimaTextListToMultiline"}

# 无任何下游的展示/胶水节点：输入连线全断即删
ORPHAN_TYPES = {"easy showAnything", "ShowText|pysssss",
                "easy promptLine", "easy string"}

OLD_WIDGETS = 43          # 旧 AnimaWeaver widget 数（43 → 46）
SEED_INDEX = 2            # 「场景类型」(combo) → 「随机种子」(INT)
APPEND = [False, "", ""]  # ▸ 系统提示词 / 系统提示词 / 详细NL系统提示词

# 选项官方用语：旧英文值 → 新中文值（widget 下标不变，只换值；幂等）
MODE_MAP = {0: {"manual": "手动", "random": "随机", "hybrid": "混合"},
            23: {"manual": "手动", "lm_studio": "LM Studio"}}


def prune_and_rename(d):
    present = {f for f in os.listdir(d) if f.endswith(".json")}
    keep_now = set()
    for f in present:
        target = KEEP.get(f)
        if target is None:
            os.remove(os.path.join(d, f))
            print("delete", f)
            continue
        if target != f:
            os.rename(os.path.join(d, f), os.path.join(d, target))
            print("rename", f, "->", target)
        keep_now.add(target)
    for want in set(KEEP.values()):
        if want not in keep_now:
            print("warn: 期望保留的工作流不存在:", want)


def convert_bus(n, l2n):
    """AnimaBatchBus → AnimaBatchMerge / AnimaBatchSplit（按模式 widget）。"""
    if n.get("type") != "AnimaBatchBus":
        return
    v = n.get("widgets_values") or []
    if v and isinstance(v[0], str) and v[0] in ("合并", "拆分"):
        mode = v[0]
        w3 = list(v[1:4])
    else:
        # 2026-10-16 上午的单节点版（无模式）：JSON行 有连线 → 拆分，否则合并
        has_json = any(i.get("name") == "JSON行" and i.get("link") in l2n
                       for i in (n.get("inputs") or []))
        mode = "拆分" if has_json else "合并"
        w3 = list(v)
    while len(w3) < 3:
        w3.append([0, 1000, True][len(w3)])
    n["widgets_values"] = w3[:3]
    n["type"] = "AnimaBatchMerge" if mode == "合并" else "AnimaBatchSplit"


def migrate(path):
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    links = j.get("links", [])
    nodes = j.get("nodes", [])
    by_id = {n["id"]: n for n in nodes}
    l2n = {l[0]: l for l in links}
    drop = set()          # 只收集「要删的」，其余一律保留
    gone = set()          # 要删的节点

    # A) 被删节点 → 与之相连的所有线
    for n in nodes:
        if n.get("type") in DELETE_NODES:
            gone.add(n["id"])
    for l in links:
        if l[1] in gone or l[3] in gone:
            drop.add(l[0])

    # B) 总线实例按模式拆回两个节点（先换类型，后面的重排按新类型走）
    for n in nodes:
        convert_bus(n, l2n)

    # C) 输入端口：按名字重算 target_slot
    for n in nodes:
        order = PORT_ORDER.get(n.get("type"))
        if not order or n["id"] in gone:
            continue
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

    # D) 输出端口：按名字重算 origin_slot
    for n in nodes:
        oorder = OUT_ORDER.get(n.get("type"))
        if not oorder or n["id"] in gone:
            continue
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

    # E) widgets_values
    for n in nodes:
        if n.get("type") == "AnimaWeaver":
            v = n.get("widgets_values") or []
            if len(v) >= OLD_WIDGETS:
                out = (list(v[:OLD_WIDGETS]) + APPEND
                       if len(v) < OLD_WIDGETS + 3 else list(v[:OLD_WIDGETS + 3]))
                if not isinstance(out[SEED_INDEX], int):
                    out[SEED_INDEX] = 0
                for idx, mp in MODE_MAP.items():
                    if isinstance(out[idx], str) and out[idx] in mp:
                        out[idx] = mp[out[idx]]
                # 2026-10-16 二级子组挪到「▸ 高级」之后显示：46 项就地置换。
                # 幂等标记：旧序 v[25]=「模型」(str)；新序 v[25]=「▸ LLM设置」(bool)
                if len(out) == 46 and isinstance(out[25], str):
                    out = (out[0:22] + [out[37], out[38], out[39]] + [out[22]]
                           + out[23:33] + [out[33]] + out[34:37] + out[40:46])
                n["widgets_values"] = out
        # 合并/拆分的 widget 已在 convert_bus 里归一成三窗口参数

    # F) 应用删除：节点 + 连线
    j["links"] = [l for l in links if l[0] not in drop and
                  l[1] not in gone and l[3] not in gone]
    alive_nodes = [n for n in nodes if n["id"] not in gone]

    # G) 孤儿清理：ORPHAN_TYPES 且无任何「存活」输入连线
    alive_ids = {l[0] for l in j["links"]}
    def has_input_link(n):
        return any(inp.get("link") in alive_ids for inp in (n.get("inputs") or []))
    removed_orphans = set()
    for n in alive_nodes:
        if n.get("type") in ORPHAN_TYPES and not has_input_link(n):
            removed_orphans.add(n["id"])
    if removed_orphans:
        j["links"] = [l for l in j["links"]
                      if l[1] not in removed_orphans and l[3] not in removed_orphans]
        alive_nodes = [n for n in alive_nodes if n["id"] not in removed_orphans]

    # H) 收尾：以 links 表为唯一真源重建两端指针（三方一致性）
    j["nodes"] = alive_nodes
    final = {}
    for l in j["links"]:
        final.setdefault((l[3], l[4]), l[0])
    out_map = {}
    for l in j["links"]:
        out_map.setdefault((l[1], l[2]), []).append(l[0])
    for n in j["nodes"]:
        for i, inp in enumerate(n.get("inputs") or []):
            inp["link"] = final.get((n["id"], i))
        for o_i, o in enumerate(n.get("outputs") or []):
            o["links"] = out_map.get((n["id"], o_i)) or None

    with open(path, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=2)
    return (len(j["nodes"]), len(j["links"]), len(drop),
            len(gone) + len(removed_orphans))


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "workflows")
    prune_and_rename(d)
    for f in sorted(glob.glob(d + "/*.json")):
        nn, nl, nd, nrm = migrate(f)
        print("migrated %s -> nodes=%d links=%d (删连线 %d, 删节点 %d)"
              % (f, nn, nl, nd, nrm))


if __name__ == "__main__":
    main()
