# -*- coding: utf-8 -*-
"""tools/migrate_workflows.py — 四节点精简版（8→4）工作流迁移

用法：python tools/migrate_workflows.py [workflows目录]
（对已迁移过的工作流幂等：名字对了就只剩无害的空操作）

做六件事（全部按**名字**重排 slot，绝不按数字硬编码 —— 不同工作流是
不同时期保存的，旧 slot 数字并不一致）：
  1. 工作流 6→2：只留 anima双采-随机提示词-v2 / 随机提示词编织器-批量 并改名
  2. 删除 4 个已消失节点（Anima反推/画师Seed/Anima加载图像/Anima列表转多行）
     及其全部连线
  3. forceInput 输入端口 / 输出端口按新名字重排：
     - AnimaWeaver：只留「种子串」；RandomResolution：只留「种子串」
     - AnimaBatchBus（2026-10-16 用户裁剪后）：输入只留 种子串/提示词串/
       宽度串/高度串，输出只留 合并输出/种子/提示词/宽度/高度；
       「分辨率串/反推串/JSON行/分辨率/反推」全部删除
  4. 拆分总线的 JSON行 反查重接线：JSON行 的来源若是 easy promptLine 或
     合并总线，就把来源节点的 4 路通道连线复制给拆分总线（新总线已内置
     easy promptLine 选行逻辑），并删掉中间那个 easy promptLine 节点
  5. widgets_values：
     - AnimaWeaver 旧 43 项 → 新 46 项（index 2 场景类型→随机种子置 0；
       index 0/23 旧英文选项值 → 官方中文；末尾补 系统提示词 三项）
     - AnimaBatchBus 去掉首位「模式」widget（合并/拆分 下拉已删）
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

# ── 2) 改后各节点的 forceInput 输入端口顺序 ──
PORT_ORDER = {
    "AnimaWeaver":      ["种子串"],
    "RandomResolution": ["种子串"],
    "AnimaBatchBus":    ["种子串", "提示词串", "宽度串", "高度串"],
}

# ── 3) 改后各节点的输出顺序（删中间项的必须重排）──
OUT_ORDER = {
    "AnimaWeaver":   ["生成的提示词", "调试信息"],
    "AnimaBatchBus": ["合并输出", "种子", "提示词", "宽度", "高度"],
}

DELETE_NODES = {"ArtistSeedNode", "AnimaImageCaption",
                "AnimaLoadImages", "AnimaTextListToMultiline"}

# 无任何下游的展示/胶水节点：输入连线全断即删
ORPHAN_TYPES = {"easy showAnything", "ShowText|pysssss",
                "easy promptLine", "easy string"}

BUS_CHANNELS = ["种子串", "提示词串", "宽度串", "高度串"]

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


def migrate(path):
    with open(path, encoding="utf-8") as f:
        j = json.load(f)
    links = j.get("links", [])
    nodes = j.get("nodes", [])
    by_id = {n["id"]: n for n in nodes}
    l2n = {l[0]: l for l in links}
    next_lid = (max(l2n) + 1) if l2n else 1
    drop = set()          # 只收集「要删的」，其余一律保留
    gone = set()          # 要删的节点

    def link_of(node, name):
        for inp in (node.get("inputs") or []):
            if inp.get("name") == name and inp.get("link") is not None:
                return l2n.get(inp["link"])
        return None

    # A) 被删节点 → 与之相连的所有线
    for n in nodes:
        if n.get("type") in DELETE_NODES:
            gone.add(n["id"])
    for l in links:
        if l[1] in gone or l[3] in gone:
            drop.add(l[0])

    # B) 拆分总线：JSON行 反查来源，把来源的 4 路通道复制过来
    rewires = {}   # split_node_id -> [(通道名, src_id, src_slot), ...]
    for n in nodes:
        if n.get("type") != "AnimaBatchBus" or n["id"] in gone:
            continue
        jl = link_of(n, "JSON行")
        if jl is None:
            continue
        src = by_id.get(jl[1])
        if src is not None and src.get("type") == "easy promptLine":
            # 中间跳：promptLine 的输入来源（通常是合并总线的 合并输出）
            drop.add(jl[0])
            pl = None
            for inp in (src.get("inputs") or []):
                if inp.get("link") is not None:
                    pl = l2n.get(inp["link"])
                    break
            if pl is not None:
                drop.add(pl[0])
            gone.add(src["id"])              # 删的是中间 promptLine，不是来源
            src = by_id.get(pl[1]) if pl else None
        if src is not None and src.get("type") == "AnimaBatchBus":
            plan = []
            for ch in BUS_CHANNELS:
                cl = link_of(src, ch)
                if cl is not None:
                    plan.append((ch, cl[1], cl[2]))
            if plan:
                rewires[n["id"]] = plan
            drop.add(jl[0])   # JSON行 连线作废（set 幂等）

    # C) 输入端口：按名字重算 target_slot
    for n in nodes:
        t = n.get("type")
        order = PORT_ORDER.get(t)
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

    # D) 拆分总线重接线：新建 4 路通道连线（新 link id）
    for nid, plan in rewires.items():
        for ch, src_id, src_slot in plan:
            lid = next_lid
            next_lid += 1
            new_link = [lid, src_id, src_slot, nid,
                        BUS_CHANNELS.index(ch), "STRING"]
            links.append(new_link)
            l2n[lid] = new_link

    # E) 输出端口：按名字重算 origin_slot
    for n in nodes:
        t = n.get("type")
        oorder = OUT_ORDER.get(t)
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

    # F) widgets_values
    for n in nodes:
        t = n.get("type")
        if t == "AnimaWeaver":
            v = n.get("widgets_values") or []
            if len(v) >= OLD_WIDGETS:
                out = (list(v[:OLD_WIDGETS]) + APPEND
                       if len(v) < OLD_WIDGETS + 3 else list(v[:OLD_WIDGETS + 3]))
                out[SEED_INDEX] = 0 if not isinstance(out[SEED_INDEX], int) else out[SEED_INDEX]
                for idx, mp in MODE_MAP.items():
                    if isinstance(out[idx], str) and out[idx] in mp:
                        out[idx] = mp[out[idx]]
                n["widgets_values"] = out
        elif t == "AnimaBatchBus":
            v = n.get("widgets_values") or []
            if v and isinstance(v[0], str) and v[0] in ("合并", "拆分"):
                n["widgets_values"] = v[1:4]   # 去掉「模式」，保留三窗口参数

    # G) 应用删除：节点 + 连线
    j["links"] = [l for l in links if l[0] not in drop and
                  l[1] not in gone and l[3] not in gone]
    alive_nodes = [n for n in nodes if n["id"] not in gone]

    # H) 孤儿清理：ORPHAN_TYPES 且无任何「存活」输入连线
    #    （必须对着 j["links"] 的存活 id 判断 —— 两端指针要到 I 段才重建，
    #    此刻 inputs[].link 可能还指着已删连线，直接判 not None 会漏孤儿）
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

    # I) 收尾：以 links 表为唯一真源重建两端指针（三方一致性）
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
