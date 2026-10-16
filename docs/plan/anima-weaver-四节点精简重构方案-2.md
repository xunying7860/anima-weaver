# Anima Weaver 四节点精简与重构落地方案

> 目标：8 节点 → 4 节点（批量种子 / Anima批量总线 / Anima随机提示词 / 随机分辨率选择器），
> 清理失效输入输出与死代码，主节点分组改成两级，分辨率节点内置随机种子。
> 方案基于当前 `main`（commit `92f8760`）源码逐行核对，所有行号均为改动前的位置。

---

## 0. 变更总览（一屏看完）

| # | 动作 | 对象 | 破坏性 |
|---|------|------|--------|
| 1 | 删除 4 个节点 | Anima反推(caption.py)、画师Seed(artist_seed.py)、Anima加载图像(load_images.py)、Anima列表转多行(list_to_multiline.py) | 高（旧工作流报错） |
| 2 | 删主节点「反推串」输入 + 输出 | anima_weaver.py | 中（端口失效） |
| 3 | 修 RETURN 5→4→3 元组不一致 | anima_weaver.py:328/435/645 | 无（本来就是 bug） |
| 4 | 「系统提示词」forceInput → 可手填多行控件 + 独立二级组 | anima_weaver.py:273 | 中（端口→控件） |
| 5 | 「详细 NL 系统提示词」从死参数转正为控件 | anima_weaver.py:865/887 | 无 |
| 6 | 删除死控件「场景类型」、死参数 `aspect_ratio` | anima_weaver.py:196/860 | 高（widget 索引整体前移） |
| 7 | 删除旧兼容入口「槽位数据」「底部数据」 | anima_weaver.py:276-279 | 中 |
| 8 | 主节点删「画师串」输入+输出，画师只拼进提示词（替代画师Seed） | anima_weaver.py:263/291/497 | 中（端口失效） |
| 8b | 总线删「画师」通道（7→6），输入/输出 slot 同时位移 | batch_bus.py:34-44/81 | 中（不迁则静默接错） |
| 9 | 分组改两级：LLM设置/批量/laya判定/系统提示词 挂到「高级」下 | anima_weaver.py:203-287 + js/anima_groups.js | 中（widget 顺序变） |
| 10 | 分辨率节点内置随机种子（含输出语义修正） | resolution.py:460-536 | 中（端口失效） |
| 11 | 冗余清理：死函数、死模块、未注册脚本 | assembly.py / lm_studio.py / laya_finetune.py / docs/plan | 低 |
| 12 | 主节点删「随机种子」输入端口 → 内置 widget（含批量父种子语义） | anima_weaver.py:205/398/346 | 中（端口失效） |
| 13 | 体积治理：222 MB taglist 移出 git | tags/taglists-*.txt | 低（需改安装流程） |
| 14 | 性能优化（P8）：倒排索引惰性构建、分辨率归一化快路径、批量循环常量外提 | 见 §9 | 无（纯提速） |
| 15 | 连线 `target_slot` 按名字迁移（修「种子串」已在 main 上错位的遗留 bug） | workflows/*.json | 中（不迁则批量链路静默失效） |
| 16 | **工作流 6 → 2**，并按新名重命名 | workflows/ | 中（删除的 4 个不再提供） |
| 17 | 工作流内删 `ArtistSeedNode` + 删画师串连线 | 保留的 2 个工作流 | 无（脚本自动） |

---

## 1. 现状盘点

### 1.1 节点现状（`__init__.py`）

保留 4 个，删除 4 个：

| 保留 | 类 | 分类 | 说明 |
|------|----|------|------|
| Anima随机提示词 | `AnimaWeaver` | Anima Weaver | 主节点 |
| 随机分辨率选择器 | `RandomResolution` | Anima Weaver | 画幅/分辨率 |
| 批量种子 | `BatchSeedNode` | Anima Weaver / Batch | N 个种子串（跨节点共用） |
| Anima批量总线 | `AnimaBatchBus` | Anima Weaver / Batch | 合并/拆分二合一 |

| 删除 | 文件 | 连带影响 |
|------|------|----------|
| Anima反推 | caption.py (41 KB) | 是「反推串」的唯一上游；`lm_studio.image_b64` 只服务它 |
| 画师Seed | artist_seed.py | 其能力由主节点「画师种子」控件承担（画师直接拼进提示词，不再出画师串）。上游节点删除后，「画师串」输入/输出一并删（见 §3.2.1 / §3.2.2） |
| Anima加载图像 | load_images.py | 唯一 torch/PIL/numpy 使用者 |
| Anima列表转多行 | list_to_multiline.py | WD14 打标工作流的胶水节点 |

### 1.2 文件去留总表

| 文件 | 处置 | 理由 |
|------|------|------|
| `__init__.py` | 改 | 注册表砍到 4 项 |
| `anima_weaver.py` | 大改 | 见 §3.2 / §3.3 |
| `resolution.py` | 改 | 见 §3.4 |
| `batch_bus.py` | 小改 | 删「反推」通道？**建议保留**（见决策点 D2） |
| `batch_seed.py` | 保留 | 无需改动 |
| `js/anima_groups.js` | 改 | 支持嵌套分组（见 §3.3.2） |
| `caption.py` | **删** | 节点删除 |
| `artist_seed.py` | **删** | 节点删除；单例逻辑已在 `artist_index.py` |
| `load_images.py` | **删** | 节点删除 |
| `list_to_multiline.py` | **删** | 节点删除 |
| `laya_finetune.py` | **删/移 tools** | 从未注册，训练脚本，随 `data/laya_n2` 一起可去 |
| `laya_gate.py` | 保留 | 「laya判定」仍要；未用 API（`judge_prefer`/`judge_candidates`/`reroll`/`is_enabled`/`status`）标 deprecated 或删 |
| `lm_studio.py` | 小改 | 删 `image_b64` 参数（只服务 caption） |
| `assembly.py` | 小改 | 删死函数 `assemble_prompt`/`_check_slot_limits`/`_count_tags`/`SLOT_LIMITS`；保留 `SLOT_ORDER`/`mix_by_ratio` |
| `rules.py` / `tag_index.py` / `tag_extract.py` / `artist_index.py` | 保留 | 主节点依赖 |
| `download_tags.py` | 保留并升级 | 222 MB taglist 改为运行时下载（见 §3.5.3） |
| `tools/acceptance_check.py` | 改 | FILES 去掉 `caption.py`，suspects 去掉 caption 项 |
| `docs/plan/*` | 归档/删 | 是 11→8 那一轮的施工文档（184 KB），与 4 节点现状不符，留着误导 |
| `data/laya_n2/*` | 删 | 8.8 MB，仅服务未注册的 `laya_finetune.py` |
| `workflows/*.json` | **6 → 2** + 重命名 | 见 §5（只留 `anima双采-随机提示词.json` / `随机提示词-批量.json`） |
| `README.md` / `README_CN.md` / `更新日志.md` | 大改 | 见 **P7** |

### 1.3 现存技术债（证据级）

| 问题 | 位置 | 说明 |
|------|------|------|
| 单次模式返回 5 元组，RETURN_TYPES 只有 4 个 | `anima_weaver.py:435` vs `:291` | 多余的第 5 个值恒为空，ComfyUI 侧输出槽位数与返回值数不一致 |
| 「随机种子」输出实际返回宽度 | `resolution.py:508/511` | 手动模式 `return (w, ...)`，第一个槽名叫「随机种子」却是 `w` |
| 主节点种子只能外接，不接则每次随机 | `anima_weaver.py:205` | `forceInput` 端口，无 `control_after_generate`，无法 randomize；单次工作流必须外挂一个 seed 节点 |
| 「批量数量」模式不可复现 | `anima_weaver.py:347` | 走 `random.randint`，同参数每次跑出不同的一批 |
| 「画师串」输出是提示词的重复副本 | `anima_weaver.py:497-517` | 画师名已被拼进提示词正文，再单独出一列纯属冗余；下游（总线）也只做展示，无人二次拼接 |
| 「系统提示词」只能连线，不能手填 | `:273` `forceInput: True` | 与「标签槽位」那种可编辑槽位体验不一致 |
| `详细 NL 系统提示词` 被读 2 次但从未定义 | `:865` `:887` | 恒为空，`强制详细自然语言` 的独立提示词从未生效 |
| `aspect_ratio` 被读但从未定义 | `:860` | 恒为空 |
| 「场景类型」控件定义了但 `compose()` 从不读 | `:196` | 纯装饰，占一个 widget 位 |
| 「反推串」在主节点内是纯透传 | `:265` `:529/631` | 对生成的提示词零影响 |
| 「槽位数据」「底部数据」 | `:276-279` | 上游节点（提示词槽位/底部控制）两代前已删，纯空壳 |
| `assemble_prompt` 等 | `assembly.py:92-160` | 无调用点 |
| 仓库 236 MB | `tags/taglists-*.txt` 222 MB | git clone 体验灾难 |

---

## 2. 目标形态

### 2.1 节点清单（4 个）

```
Anima Weaver
├── Anima随机提示词          AnimaWeaver
└── 随机分辨率选择器         RandomResolution
Anima Weaver / 批量
├── 批量种子                 BatchSeedNode
└── Anima批量总线            AnimaBatchBus
```

### 2.2 Anima随机提示词 分组树（两级）

```
[一级常驻]
  模式 · 标签比例 · 随机种子（内置 widget，可 randomize / increment）
▸ 标签槽位            ← 一级组
    人数/身份 外貌 服装 姿势/动作 表情 镜头 场景/环境 细节/氛围 自然语言描述
▸ 过滤控制            ← 一级组
    标签列表必含 过滤标签 排除含标签列表 排除标签分类 通用/争议/敏感/露骨
▸ 高级                ← 一级组（父）
    画师种子 · 冲突检查
    ▸ LLM设置         ← 二级组（父关则整组消失）
        自然语言来源 强制详细自然语言 模型 API地址 API密钥 云端模型名
        上下文长度 自动上下文长度 最大截断长度 生成后卸载
    ▸ 批量            ← 二级组
        批量数量 请求数 最大并发数 + [种子串] 端口
    ▸ laya判定        ← 二级组
        启用laya门控 过滤质量标签
    ▸ 系统提示词      ← 二级组（新增，可开关）
        系统提示词（可手填） 详细NL系统提示词（可手填）
```

规则：`▸ 高级` 关闭 → 四个二级组连同它们的控件**全部隐藏**（不显示子开关）；
`▸ 高级` 打开 → 显示四个子开关（默认全关）→ 子开关打开才显示其成员。

### 2.3 Anima随机提示词 种子语义（内置种子 vs 种子串）

> ✅ **「种子串」输入端口保留不动**（在「高级 ▸ 批量」组下，`forceInput`）。
> 本轮删的是**「随机种子」输入端口**（改内置 widget）—— 两者是不同端口，别混：
>
> | 端口 | 处置 | 说明 |
> |------|------|------|
> | `随机种子` in | **删**（改内置 widget） | 单次随机源 |
> | `种子串` in | **保留**（forceInput） | 批量逐行种子，跨节点对齐用；「批量种子」节点照旧接这里 |
> | `画师串` in | **删** | 画师已拼进提示词，不再单独成串 |
> | `反推串` in | 删 | 纯透传，对提示词零影响 |
>

| 项 | 内置随机种子（widget） | 种子串（输入端口，「高级 ▸ 批量」下） |
|----|------------------------|--------------------------------------|
| 来源 | 节点自身 INT 控件，`control_after_generate=True` | 外部「批量种子」/总线拆分接入，多行 |
| 取值 | `0` = 每次执行内部随机；`>0` = 确定性复现 | 每行一个种子 |
| 单次模式 | 唯一随机源：驱动抽签 / 槽位抽样 / 画师子流 | 不接 |
| 批量：接了种子串 | **不参与**（种子串逐行接管，行为同旧版） | 每行一个独立种子 |
| 批量：只设「批量数量」 | 升级为**父种子**：派生 N 个可复现的子种子 | 不接 |
| 优先级 | 种子串非空 → 内置种子让位 | 非空即接管 |

> 「批量数量」派生父种子是本轮新增能力：旧版 `批量数量` 走
> `random.randint(1, 0x7FFF...)`，每次执行都变，**批量结果无法复现**。
> 改为内置种子派生后，`批量数量=8 + 种子=12345` 可完整复现整批 8 条。
> 派生用命名子流 `SeedRNG(eff_seed).get("batch_seeds")`，与抽签/画师子流互不干扰。

### 2.4 随机分辨率选择器 种子语义（与种子串严格区分）

| 项 | 内置随机种子（widget） | 种子串（输入端口） |
|----|------------------------|--------------------|
| 来源 | 节点自身 INT 控件，可 `control_after_generate=randomize` | 外部「批量种子」/总线拆分接入，多行 |
| 取值 | `0` = 每次执行内部随机；`>0` = 确定性复现 | 每行一个种子 |
| 用途 | 单次出图选比例/分辨率 | 批量逐行选比例/分辨率 |
| 优先级 | 接入种子串时**不使用**内置种子（仅作无串兜底） | 非空即接管 |
| 输出 | 「随机种子」INT = 本次实际使用的**单个**种子 | 「种子串」STRING = 原样透传，未接时**输出空串** |

两个节点的种子语义刻意保持一致：`0`=随机、`>0`=复现、接了种子串就让位。

---

## 3. 分阶段实施

### P0 准备

```bash
git checkout main && git pull
git tag pre-4node-$(date +%Y%m%d)     # 回滚锚点
git checkout -b refactor/four-nodes
python -m compileall -q .             # 记录基线：当前应无错
```

### P1 删除 4 个节点

**`__init__.py`** 改成：

```python
from .anima_weaver import AnimaWeaver
from .resolution import RandomResolution
from .batch_seed import BatchSeedNode
from .batch_bus import AnimaBatchBus

NODE_CLASS_MAPPINGS = {
    "AnimaWeaver": AnimaWeaver,
    "RandomResolution": RandomResolution,
    "BatchSeedNode": BatchSeedNode,
    "AnimaBatchBus": AnimaBatchBus,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaWeaver": "Anima随机提示词",
    "RandomResolution": "随机分辨率选择器",
    "BatchSeedNode": "批量种子",
    "AnimaBatchBus": "Anima批量总线",
}
WEB_DIRECTORY = "./js"
```

```bash
git rm caption.py artist_seed.py load_images.py list_to_multiline.py
```

> ⚠️ 不要顺手删 `artist_index.py`——它现在是画师数据的唯一入口（O(1) 单例），主节点仍依赖。

### P2 主节点输入输出瘦身（`anima_weaver.py`）

#### 2.1 输出瘦身：4 → 2（删「反推串」+「画师串」）

> 用户已拍板：**画师固定拼进提示词里就行，不再单独出画师串**。
> 所以「画师串」的**输入和输出一起删**，只保留「画师种子」控件（决定拼哪个画师）。

- 删 `:265-266`（`"反推串"` 输入）
- 删 `:263-264`（`"画师串"` 输入）
- `:291-292` →

```python
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("生成的提示词", "调试信息")
```

- `:328` 签名 → `def compose(self, **kwargs) -> tuple[str, str]:`
- `:435` → `return (final, "\n".join(debug_lines))`
- `:645-650` → `return (out_prompts, debug)`
- `:528-529`、`:609`、`:631` 删掉 `cap_lines` 相关代码
- `:520/528/607-631` 删掉 `artist_lines` / `artists_out` 相关代码

理由：

- `反推串`：在主节点里只被 `caps_out[orig_i] = 反推串第 i 行` 原样搬回输出，
  不参与提示词生成；反推节点删除后既无上游也无消费者，透传交给总线的「反推」通道。
- `画师串`：画师名已经在 `_finish_prompt` 里被 `final.rstrip(", ") + ", " + chosen`
  拼进了提示词正文，**再单独出一列画师串纯属重复**。删掉后下游不再需要
  把画师串再拼一次（旧工作流里画师串也确实只是进总线展示，没人真的二次拼接）。

**输出端的连线影响（好消息）**：旧输出顺序是
`[0 生成的提示词, 1 调试信息, 2 画师串, 3 反推串]`，删掉的正好是末尾两项，
**slot 0 / 1 原地不动 → 保留的两条输出连线一行都不用改**（实测见 §5.2）。

#### 2.2 画师只进提示词，不再输出画师串（替代画师Seed）

`_finish_prompt` 末尾（`:497-519`）：**画师名照旧拼进提示词，但不再返回画师行**：

```python
        # 画师：只拼进提示词正文，不再单独输出画师串
        artist_seed_val = kwargs.get("画师种子", None)
        if artist_seed_val is not None and str(artist_seed_val) != "":
            s = int(artist_seed_val)
            if s != 0:                      # 0 = 无画师（P8-7：此时连画师表都不用加载）
                artists = _load_artists()
                if artists:
                    if s == -1:             # 随机画师：种子派生，可复现
                        srng = SeedRNG(int(kwargs.get("随机种子", 0)))
                        s = srng.get("artist").randint(1, len(artists))
                    if s > 0:
                        idx = max(0, min(s - 1, len(artists) - 1))
                        chosen = artists[idx]
                        final = (final.rstrip(", ") + ", " + chosen) if final else chosen
        return (final, nl_prompt)           # 从 3 元组回到 2 元组
```

**批量模式**（`:589-598`、`:630`）：直接删掉 `artist_lines` / `artists_out` 的全部逻辑。
每个种子仍按 `画师种子` 独立派生画师（`-1` 时用 `SeedRNG(seed).get("artist")`），
但结果只拼进该行提示词，不再单独成列。

> 这样 `随机提示词-批量.json` 里的 `ArtistSeedNode` 可以直接删掉：
> 实测它的「画师串」输出本来只是灌进 `AnimaWeaver.画师串` **输入**，
> 而真正连到总线的 `AnimaWeaver.画师串（输出）→ AnimaBatchBus.画师串` 是主节点自己的线 ——
> 这条线本轮随画师串输出一起删掉（见 §4.4、§5.2）。

**「画师种子」控件保留**（在「高级」组下，`-1`=随机 / `0`=无 / `1~`=固定序号）。
它是「拼哪个画师」的唯一开关，删不得。

#### 2.3 「系统提示词」改成可开关、可手填的槽位

删掉 `:273-274`，在系统提示词组里改成（**放在「高级」之后、序列末尾**，见 §3.3.1）：

```python
                "▸ 系统提示词": ("BOOLEAN", {"default": False,
                                        "tooltip": "组开关：展开系统提示词编辑框"}),
                "系统提示词": ("STRING", {"multiline": True, "default": "",
                                     "tooltip": "自定义系统提示词，留空=用内置默认提示词"}),
                "详细NL系统提示词": ("STRING", {"multiline": True, "default": "",
                                          "tooltip": "仅在「强制详细自然语言」开启时使用；留空回落默认详细提示词"}),
```

两处读取点改成新键名（去掉空格，避免与旧死键混用）：

```python
# :865 与 :887
custom_sp = (kwargs.get("详细NL系统提示词", "") if detailed_nl
             else kwargs.get("系统提示词", ""))
```

#### 2.4 删除死控件与死参数

- 删 `:196-199` `"场景类型"`（从未被 `compose()` 读取）
- 删 `:860` `aspect_ratio = kwargs.get("aspect_ratio", "")` 及两处 `aspect_ratio=aspect_ratio` 传参
  （`lm_studio.generate_nl_from_lm_studio` 的 `aspect_ratio` 参数也一并删）

#### 2.5 删除旧兼容入口

删 `:276-279` `"槽位数据"` / `"底部数据"`，以及 `:353-373` 两段 JSON 合并逻辑。
这两个入口的上游节点在上一轮整合中已删除，现在没有任何节点能产出这两个 JSON，
`compose()` 里只是 `try/except: pass` 的空转。

#### 2.6 删除「随机种子」输入端口，改内置 widget

**a. 删端口**（`:204-207`，optional 第 1 项）：

```python
                # ── 随机种子：用得频繁，放一级区底部，只是不渲染成 widget ──
                "随机种子": ("INT", {"forceInput": True, "default": 0,
                                 "min": 0, "max": 0xFFFF_FFFF_FFFF_FFFF,
                                 "tooltip": "从外部种子节点接入，不接则使用内部随机值"}),
```

**b. 加内置 widget**（放进 `required`，紧跟「标签比例」之后，即 widget 序列第 3 位）：

```python
            "required": {
                "模式": (["manual", "random", "hybrid"], {"default": "hybrid"}),
                "标签比例": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0,
                                    "step": 0.05}),
                # 顶替原「场景类型」的位置（见 §4.1：下标 3 之后全部对齐，迁移最省事）
                "随机种子": ("INT", {
                    "default": 0, "min": 0, "max": 0xFFFF_FFFF_FFFF_FFFF, "step": 1,
                    "control_after_generate": True,
                    "tooltip": "0=每次执行内部随机；>0=确定性复现。"
                               "批量模式：接了种子串则让位；只设批量数量时作父种子派生 N 个子种子。",
                }),
            },
```

> `control_after_generate: True` → 前端出现 ComfyUI 原生 seed 的
> `randomize / increment / decrement / fixed` 菜单；极旧前端不识别也只是少个菜单，
> 手动填数字照常工作。

**c. 改 `compose()` 的种子解析**（`:398-406`）：

```python
        # ── 种子解析：内置 widget（0=内部随机，>0=复现）────────────────
        try:
            _in_seed = int(kwargs.get("随机种子", 0) or 0)
        except (TypeError, ValueError):
            _in_seed = 0
        raw_seed = _in_seed if _in_seed > 0 else random.randint(0, 0xFFFF_FFFF_FFFF_FFFF)

        debug_lines: list[str] = [f"Mode: {mode}", f"Seed: {raw_seed}"]
        seed_kwargs = dict(kwargs)
        seed_kwargs["随机种子"] = raw_seed        # 关键：写回，画师/抽签子流才能同步
        srng = SeedRNG(raw_seed)
```

原来那段的 `seed_val is None or ""` 判断是为 forceInput 端口的空值兜底，内置 widget 后恒有值，直接删。

**d. 批量：内置种子升级为父种子**（`:337-351`）：

```python
        batch_seeds_str = kwargs.get("种子串", "")
        if not batch_seeds_str.strip():
            try:
                _n = int(kwargs.get("批量数量", 0) or 0)
            except (TypeError, ValueError):
                _n = 0
            if _n > 0:
                # 旧版 random.randint：每次执行都变，批量结果不可复现。
                # 改：内置种子作父种子，命名子流派生 N 个可复现子种子。
                rng = SeedRNG(raw_seed).get("batch_seeds")
                batch_seeds_str = "\n".join(
                    str(rng.randint(1, 0x7FFFFFFFFFFFFFFF)) for _ in range(_n))
        is_batch = bool(batch_seeds_str.strip())
        if is_batch:
            kwargs.pop("随机种子", None)   # 保留：批量逐行种子由 seed_kwargs 覆盖
```

注意 `raw_seed` 的计算必须提到这个 `if` **之前**（上面 c 的解析块要整体前移到 `compose()` 开头、批量分支之前），否则 `批量数量` 分支拿不到它。

**e. 顺带清理**：

- `:350-351` 保留 `kwargs.pop("随机种子", None)` —— 批量模式仍由每个 `seed_kwargs["随机种子"] = raw_seed` 覆盖，语义不变；
- `IS_CHANGED`（`:305-324`）无需改：内置种子现在是一个真实 widget，值变了哈希就变，ComfyUI 会正确重算；反而修掉了旧版「端口接空值时哈希恒定」的隐患；
- `_finish_prompt`（`:507`）里 `SeedRNG(int(kwargs.get("随机种子", 0)))` 不变，因为 c 已把 `raw_seed` 写回 `seed_kwargs`。

#### 2.7 顺序与注释同步

`:25` 的死 import 注释、`:9` docstring 里提到的 `assembly.assemble_prompt` 一并更新。

#### 2.8 Anima批量总线：删「画师」通道（7 → 6）

画师既然不再单独成串，总线里那条 `画师串 → 画师` 通道也一并删（`batch_bus.py`）：

```python
_CHANNELS: list[tuple[str, str]] = [
    ("种子串", "种子"),
    ("提示词串", "提示词"),
    # 删：("画师串", "画师")
    ("分辨率串", "分辨率"),
    ("反推串", "反推"),
    ("宽度串", "宽度"),
    ("高度串", "高度"),
]

    RETURN_TYPES = ("STRING", "INT", "STRING", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("合并输出", "种子", "提示词", "反推", "分辨率", "宽度", "高度")
```

`_split` 里删掉 `get_str("画师")` 那一行；`_merge` 不用改（它按 `_CHANNELS` 遍历）。

**⚠️ 这条改动会同时位移输入和输出两端的 slot**（因为删的是中间项，不是末尾）：

| | 旧 slot | 新 slot |
|---|---------|---------|
| 输入 `分辨率串` | 3 | **2** |
| 输入 `反推串` | 4 | **3** |
| 输入 `宽度串` | 5 | **4** |
| 输入 `高度串` | 6 | **5** |
| 输入 `JSON行` | 7 | **6** |
| 输出 `反推` | 4 | **3** |
| 输出 `分辨率` | 5 | **4** |
| 输出 `宽度` | 6 | **5** |
| 输出 `高度` | 7 | **6** |

输出端尤其危险：`随机提示词-批量.json` 和 `anima双采-随机提示词.json` 里
**`宽度 → EmptyLatentImage.width`** 是真实连线，不重排就会接到「分辨率」上（静默出错）。
迁移脚本必须同时处理 input 和 output 两端（见 §4.4，已实测）。

> JSON 互逆性不受影响：合并产出的行里不再有 `画师` 字段；旧 JSON 行喂回来时
> `get_str("画师")` 已删，读不到就是跳过，其余 6 个字段照旧还原。

### P3 分组重构（两级）

#### 3.3.1 Python 侧新 `INPUT_TYPES` 顺序（dict 顺序 = 前端顺序）

```python
return {
    "required": {
        "模式": (["manual", "random", "hybrid"], {"default": "hybrid"}),
        "标签比例": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05}),
        # 内置随机种子：顶替原「场景类型」的位置（见 §4.1，下标 3 之后全部对齐）
        "随机种子": ("INT", {
            "default": 0, "min": 0, "max": 0xFFFF_FFFF_FFFF_FFFF, "step": 1,
            "control_after_generate": True,
        }),
    },
    "optional": {
        # ━━ 一级组 ━━
        "▸ 标签槽位": ("BOOLEAN", {"default": False}),
        "人数/身份": ..., "外貌": ..., "服装": ..., "姿势/动作": ...,
        "表情": ..., "镜头": ..., "场景/环境": ..., "细节/氛围": ...,
        "自然语言描述": ...,

        "▸ 过滤控制": ("BOOLEAN", {"default": False}),
        "标签列表必含": ..., "过滤标签": ..., "排除含标签列表": ..., "排除标签分类": ...,
        "通用标签": ..., "争议标签": ..., "敏感标签": ..., "露骨标签": ...,

        # ━━ 一级组「高级」：先放它自己的直属 widget（保住旧索引），再挂四个二级组 ━━
        "▸ 高级": ("BOOLEAN", {"default": False}),
        "画师种子": ("INT", {"default": 0, "min": -1, "max": 0x7FFFFFFF}),
        "冲突检查": ("BOOLEAN", {"default": True}),

        "▸ LLM设置": ("BOOLEAN", {"default": False}),
        "自然语言来源": (["manual", "lm_studio"], {"default": "manual"}),
        "强制详细自然语言": ..., "模型": (model_list,), "API地址": ..., "API密钥": ...,
        "云端模型名": ..., "上下文长度": ..., "自动上下文长度": ...,
        "最大截断长度": ..., "生成后卸载": ...,

        "▸ 批量": ("BOOLEAN", {"default": False}),
        "批量数量": ..., "请求数": ..., "最大并发数": ...,
        "种子串": ("STRING", {"forceInput": True, "multiline": True}),

        "▸ laya判定": ("BOOLEAN", {"default": False}),
        "启用laya门控": ..., "过滤质量标签": ...,

        "▸ 系统提示词": ("BOOLEAN", {"default": False}),
        "系统提示词": ("STRING", {"multiline": True, "default": ""}),
        "详细NL系统提示词": ("STRING", {"multiline": True, "default": ""}),
    },
}
```

关键约束（踩过的坑，别改）：

1. 组开关 `▸ xxx` 必须排在它管的 widget **前面**；
2. 隐藏的 widget **绝不能从 `node.widgets` 数组移除**，只改显示属性（前端 save 是 index-based，移除会让 `widgets_values` 整体错位）；
3. 隐藏的 widget 值照常提交后端 —— 用户填完再折叠，值依然生效，`compose()` 不用改；
4. `IS_CHANGED` 里已剔除 `▸` 前缀键，展开/收起不触发重算（`:313-317`），嵌套后仍然成立，无需改。

#### 3.3.2 JS 侧支持嵌套（`js/anima_groups.js`）

把 `GROUPS` 换成带 `parent` 的结构，其余逻辑（hideWidget/showWidget/findWidget/attachToggles/注册）保持不变：

```js
const NESTED = {
  "▸ 标签槽位": { parent: null, members: [
    "人数/身份", "外貌", "服装", "姿势/动作", "表情",
    "镜头", "场景/环境", "细节/氛围", "自然语言描述",
  ]},
  "▸ 过滤控制": { parent: null, members: [
    "标签列表必含", "过滤标签", "排除含标签列表", "排除标签分类",
    "通用标签", "争议标签", "敏感标签", "露骨标签",
  ]},
  "▸ 高级": { parent: null, members: [
    "画师种子", "冲突检查",
    "▸ LLM设置", "▸ 批量", "▸ laya判定", "▸ 系统提示词",
  ]},
  "▸ LLM设置": { parent: "▸ 高级", members: [
    "自然语言来源", "强制详细自然语言", "模型", "API地址", "API密钥",
    "云端模型名", "上下文长度", "自动上下文长度", "最大截断长度", "生成后卸载",
  ]},
  "▸ 批量": { parent: "▸ 高级", members: [
    "批量数量", "请求数", "最大并发数",
  ]},
  "▸ laya判定": { parent: "▸ 高级", members: [
    "启用laya门控", "过滤质量标签",
  ]},
  "▸ 系统提示词": { parent: "▸ 高级", members: [
    "系统提示词", "详细NL系统提示词",
  ]},
};

// 自己 + 所有祖先开关都必须勾选
function chainOpen(node, name) {
  let cur = name, guard = 0;
  while (cur && guard++ < 10) {
    const t = findWidget(node, cur);
    if (!t || !t.value) return false;
    cur = NESTED[cur] ? NESTED[cur].parent : null;
  }
  return true;
}

function wantShow(node, widgetName) {
  let shown = true;
  for (const [toggle, def] of Object.entries(NESTED)) {
    if (def.members.includes(widgetName) && !chainOpen(node, toggle)) shown = false;
  }
  return shown;
}

function applyVisibility(node) {
  let changed = false;
  const setVis = (w, show) => {
    if (!w) return;
    const before = !!w.__animaHidden;
    if (show) showWidget(w); else hideWidget(w);
    if (before !== !!w.__animaHidden) changed = true;
  };
  for (const [toggle, def] of Object.entries(NESTED)) {
    const tw = findWidget(node, toggle);
    if (tw) setVis(tw, def.parent ? chainOpen(node, def.parent) : true); // 子开关随父显隐
    for (const m of def.members) setVis(findWidget(node, m), wantShow(node, m));
  }
  if (changed || node.__animaFirstApply) { /* 原重算高度逻辑不变 */ }
}
```

`attachToggles` 里把 `Object.keys(GROUPS)` 换成 `Object.keys(NESTED)`。

> 内置「随机种子」是 required 里的普通 widget，**不要**写进 `NESTED`——
> 它永远常驻，不参与折叠。

### P4 随机分辨率选择器内置随机种子（`resolution.py`）

```python
class RandomResolution:
    @classmethod
    def INPUT_TYPES(s) -> dict[str, Any]:
        return {
            "required": {
                "模式": ("BOOLEAN", {"default": False,
                                   "tooltip": "True=自动(分析提示词), False=手动"}),
                "随机画幅": ("BOOLEAN", {"default": True}),
                "百万像素": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 32.0, "step": 0.01}),
                "固定比例": (ASPECT_NAMES, {"default": "3:4"}),
                "对齐到": ("INT", {"default": 8, "min": 1, "max": 256, "step": 1}),
                # 新增：内置随机种子（追加在末尾，旧工作流的 widgets_values 索引不受影响）
                "随机种子": ("INT", {
                    "default": 0, "min": 0, "max": 0xFFFF_FFFF_FFFF_FFFF, "step": 1,
                    "control_after_generate": True,
                    "tooltip": "0=每次执行内部随机；>0=按此种子确定性选画幅。"
                               "仅在不接「种子串」时生效；本值输出到「随机种子」槽。",
                }),
            },
            "optional": {
                # 删除原 "随机种子" forceInput 端口
                "种子串": ("STRING", {"forceInput": True, "multiline": True}),
                "提示词": ("STRING", {"forceInput": True, "multiline": True}),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("随机种子", "种子串", "宽度", "高度")
    FUNCTION = "pick"

    def pick(self, 模式, 随机画幅, 百万像素, 固定比例, 对齐到=8,
             随机种子=0, 种子串="", 提示词=""):
        seeds = []
        for s in (种子串 or "").split("\n"):
            s = s.strip()
            if s:
                try: seeds.append(int(s))
                except ValueError: pass

        prompt_lines = [l.strip() for l in (提示词 or "").split("\n") if l.strip()]

        # ── 内置种子解析：0 = 每次内部随机；>0 = 可复现 ──
        try: in_seed = int(随机种子 or 0)
        except (TypeError, ValueError): in_seed = 0
        eff_seed = in_seed if in_seed > 0 else random.randint(1, 0xFFFF_FFFF_FFFF_FFFF)

        # ── 批量：种子串接管，内置种子仅作缺省（不参与） ──
        if seeds:
            ws, hs = [], []
            for i, sv in enumerate(seeds):
                if 模式 and i < len(prompt_lines):
                    ratio = analyze_prompt(prompt_lines[i])
                elif 模式 and 随机画幅:
                    ratio = random.Random(sv).choice(ASPECT_NAMES)
                elif 模式:
                    ratio = 固定比例
                else:
                    ratio = (random.Random(sv).choice(ASPECT_NAMES)
                             if 随机画幅 else 固定比例)
                w, h = _resolve(百万像素, ratio, 对齐到)
                ws.append(str(w)); hs.append(str(h))
            first_ratio = (analyze_prompt(prompt_lines[0]) if 模式 and prompt_lines
                           else (random.Random(seeds[0]).choice(ASPECT_NAMES)
                                 if 随机画幅 else 固定比例))
            fw, fh = _resolve(百万像素, first_ratio, 对齐到)
            # 修 bug：第 1 个槽是「随机种子」，旧代码误返回宽度 fw
            return (seeds[0], "\n".join(map(str, seeds)), "\n".join(ws), "\n".join(hs))

        # ── 单次：用内置种子 ──
        if 模式:
            ratio = analyze_prompt(prompt_lines[0]) if prompt_lines else "3:4"
        else:
            ratio = (random.Random(eff_seed).choice(ASPECT_NAMES)
                     if 随机画幅 else 固定比例)
        w, h = _resolve(百万像素, ratio, 对齐到)
        # 种子串槽保持空：与批量模式严格区分，避免下游把它当批量串
        return (eff_seed, "", str(w), str(h))
```

要点：

- `control_after_generate: True` → 前端出现 randomize/increment 小控件，和 ComfyUI 原生 seed 一致；
- 未接种子串时「种子串」输出恒空串，**不会**把内置种子伪装成批量串（下游总线靠这个区分）；
- 「随机种子」输出修正为真正的种子（旧代码返回宽度）——这是本轮顺手修掉的 bug。

### P5 冗余与体积清理

1. `anima_weaver.py`：删 `_reorder_background_to_end`（`:1052-1071`，定义后从未调用）；
   `_load_artists` 的 `print` 改成一次性（`if not _ARTIST_PRINTED`）或去掉。
2. `assembly.py`：删 `SLOT_LIMITS`、`_count_tags`、`_check_slot_limits`、`assemble_prompt`、
   `check_detail_overload` 的 import；只留 `SLOT_ORDER` + `mix_by_ratio`。
3. `lm_studio.py`：`generate_nl_from_lm_studio` 删 `image_b64` 参数（只有 caption 用）；
   顺带核对 `get_models_cached` / `invalidate_model_cache` / `check_available` / `get_loaded_models`
   在 caption 删除后是否还有调用点，没有就删。
4. `laya_gate.py`：保留 `judge_keep`，未用的 `judge_prefer` / `judge_candidates` / `reroll` /
   `is_enabled` / `status` 标 deprecated 或直接删（推荐删，减少维护面）。
5. `git rm laya_finetune.py data/laya_n2`（共 ~9.9 MB）。README 里说明：微调脚本与数据可在
   `pre-4node-*` tag 找回，或用旧 commit 恢复。
6. `docs/plan/` → 移到 `docs/archive/2026-10-11-11to8/` 或直接删（建议归档 + 顶部加一行
   「本文档描述的是 11→8 那一轮，已实施完毕，当前为 4 节点」）。
7. **`tags/taglists-*.txt` 222 MB 治理**（可选但强烈建议）：
   - 方案 A（推荐）：4 个文件加 `.gitignore`，`download_tags.py` 升级为首次运行自动下载 +
     进度条 + 校验和；README 安装步骤加一句「首次启动会自动下载约 220 MB 标签库」。
   - 方案 B：`git lfs track "tags/taglists-*.txt"`。
   - 未下载时 `tag_index.get_tag_index()` 抛 `OSError` → `_run_raffle` 已 `return {}`，
     行为是「抽签为空」，需在 README 明示并建议在节点里加一句控制台提示。

### P6 加两个体检脚本（防技术债复发）

`tools/check_inputs.py`：静态解析 `anima_weaver.py`，报告两类问题——

- A 类：`kwargs.get("X")` 但 `INPUT_TYPES` 里没有 `X` → 死参数（本轮就是 `详细 NL 系统提示词`、`aspect_ratio`）；
- B 类：`INPUT_TYPES` 里有 widget `Y`，但全文件没人读 → 死控件（本轮就是 `场景类型`）。

```python
import ast, re, sys, pathlib
src = pathlib.Path("anima_weaver.py").read_text(encoding="utf-8")
tree = ast.parse(src)

def literal_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

defined, used = set(), set()
for n in ast.walk(tree):
    if isinstance(n, ast.Dict):
        for k in n.keys:
            s = literal_str(k)
            if s: defined.add(s)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
        if n.args:
            s = literal_str(n.args[0])
            if s: used.add(s)

declared = {d for d in defined if not d.startswith("▸")}
print("A 类 死参数（读了但没定义）:", sorted(used - declared) or "无")
print("B 类 死控件（定义了但没读）:", sorted(d for d in declared
      if d not in used and d not in {"模式", "标签比例"}) or "无")
```

（B 类需人工确认，因为 `compose` 用 `kwargs.get` 之外的路径也可能取值。）
`tools/acceptance_check.py` 同步：FILES 去掉 `caption.py`，`:64` 的 suspects 去掉 caption 项，
并把 `check_inputs.py` 加进 CI。

---

### P7 文档更新（README / 更新日志）

**`README_CN.md`**：

| 位置 | 改动 |
|------|------|
| 「节点列表」表（`:11-24`） | 8 行 → 4 行。删掉 Anima反推 / 画师Seed / Anima加载图像 / Anima列表转多行 四行；「批量种子」的用途说明补一句「也是主节点内置种子的替代方案（跨节点对齐时用）」 |
| `### Anima反推`（`:115-158`） | **整节删除** |
| `### 画师Seed`（`:216-228`） | **整节删除**，其能力并入主节点详解：新增小节「画师（画师种子）」—— `-1`=随机 / `0`=无 / `1~`=固定序号，**画师名直接拼进提示词末尾**，没有单独的画师串输出 |
| `### 同步串行` / `### 串行拆分` | 保留，但开头加一句「两者已合并为 **Anima批量总线**，此两节仅作旧版对照」 |
| `### 随机分辨率选择器`（`:159-207`） | 补一段「内置随机种子」：`0`=每次随机 / `>0`=复现；接了种子串则让位；种子串输出未接时为空串 |
| `### Anima随机提示词`（`:61-114`） | 补三段：① 内置随机种子（含批量父种子语义，附 §2.3 那张表）；② 两级分组树（§2.2 那棵树，文字版）；③ 「系统提示词」组：可开关、可手填、与「详细NL系统提示词」的关系 |
| 「批量管线架构」节 | 更新配图说明：种子串现在可由主节点内置种子派生，不必外挂「批量种子」节点 |
| 「安装」节 | 若采纳 D4，补一句「首次启动自动下载约 220 MB 标签库（或手动运行 `python download_tags.py`）」 |
| **「工作流」节（`:285-291`）** | **整表重写**。现只列一条 `anima批量自动打标.json`，而该文件本轮已删。改成两条：`anima双采-随机提示词.json`（完整出图：批量种子 → 提示词/分辨率 → 总线 → 双采样器 → 保存）、`随机提示词-批量.json`（只出提示词串 + 各通道展示，不含采样）。另加一句「旧版 `随机提示词润色.json` / `图片反推（自然语言）.json` / `随机提示词编织器-单次.json` 已移除，如需可在 `pre-4node-*` tag 找回」 |
| 「节点列表」表 | 「Anima批量总线」那行的用途补一句「保留的两个示例工作流都用它做合并/拆分」，并把「7 路」改成「6 路（种子/提示词/分辨率/反推/宽度/高度，画师通道已移除）」 |
| 「批量管线架构」节 | 配图与说明里的「画师串」通道删掉；补一句「画师已并入提示词，不再单独成列」 |

**`README.md`（英文）**：

- `:293` 的工作流表格同样只列 `anima批量自动打标.json` —— **整表重写**为上述两条；
- `:120` 提到 `Anima加载图像 → wd14 tagger → Anima列表转多行 → ... → Anima反推(none)` 这条链路，
  四个节点里三个已删 —— **整句删除**；
- 同步节点列表与内置种子说明，其余可简写。

**`更新日志.md`** 追加（沿用现有「致命 bug 修复 / 性能 / ⚠ 破坏性变更」三段式）：

```markdown
## 2026-10-16 四节点精简版（8 → 4）

### 节点精简
- **已删除**：Anima反推、画师Seed、Anima加载图像、Anima列表转多行
- **保留 4 个**：Anima随机提示词、随机分辨率选择器、批量种子、Anima批量总线

### 内置随机种子（两个主节点统一语义）
- Anima随机提示词 / 随机分辨率选择器 均内置 seed widget（`control_after_generate`），
  `0`=每次随机、`>0`=确定性复现；接入种子串时内置种子让位
- **「批量数量」现在可复现**：内置种子作父种子派生 N 个子种子
  （旧版走 `random.randint`，同参数每次跑出不同的一批）
- 修复：分辨率节点「随机种子」输出槽误返回宽度

### 主节点瘦身
- 删「反推串」输入/输出（纯透传，对提示词零影响）
- 删「场景类型」（死控件）、「槽位数据」「底部数据」（上游两代前已删的空壳入口）
- 删死参数 `aspect_ratio`；「详细NL系统提示词」从死参数转正为控件
- 「系统提示词」由 forceInput 端口改为可手填、可开关的槽位
- 主节点**删除「画师串」输入与输出**，画师名改为直接拼进提示词末尾
  （画师Seed 节点删除后，「画师种子」控件仍是唯一的画师开关）
- Anima批量总线通道 7 → 6：**移除「画师」通道**（输入/输出两端 slot 均前移，见迁移脚本）
- 分组改两级：LLM设置 / 批量 / laya判定 / 系统提示词 全部收进「高级」下

### ⚠ 破坏性变更（升级前必读）
1. **旧工作流必须迁移**：删「场景类型」会移动 widget 下标，
   请运行 `python tools/migrate_widgets.py`（只改 index 2 + 末尾补三项，其余参数原样保留）
2. 以下连线会失效，需手动删除重连：
   AnimaWeaver 的 `随机种子` / `反推串` / `槽位数据` / `底部数据` / `系统提示词`，
   RandomResolution 的 `随机种子`
3. 四个被删节点（`AnimaImageCaption` / `ArtistSeedNode` / `AnimaLoadImages` /
   `AnimaTextListToMultiline`）在旧工作流中会报红
4. **示例工作流 6 → 2**：只保留 `anima双采-随机提示词.json`（原 `-v2` 改名）
   和 `随机提示词-批量.json`（原 `随机提示词编织器-批量.json` 改名）；
   其余 4 份已移除，可在 `pre-4node-*` tag 找回。工作流内的 `ArtistSeedNode` 已删除，
   画师改由「画师种子」控件控制并直接拼进提示词（两个示例原本就是「无画师」，行为不变）
5. **画师串不再单独输出**：需要画师信息的下游（如把画师名另存、做二次拼接）
   请改从提示词里解析，或回退 `pre-4node-*` tag
6. 固定种子仍不保证复现旧图（随机内核自上一版已重构）

回滚：`git checkout pre-4node-YYYYMMDD`
```

---

### P8 性能优化（`tag_index` / `tag_extract` / `resolution` / `anima_weaver`）

详见 **§9（实测数据 + 代码）**。此处只列落地点：

| 编号 | 文件 | 动作 |
|------|------|------|
| P8-1 | `tag_extract.py` | 倒排索引改**惰性构建**（仅在真正需要第 2 级时触发），默认场景启动零成本 |
| P8-2 | `anima_weaver.py` | 修「索引未就绪 → 每种子全量扫描」雪崩（实测 256 种子 = **196 秒**） |
| P8-3 | `tag_extract.py` | 构建改为**顺序批量读**（1.64 s → ~0.9 s） |
| P8-4 | `tag_index.py` | `read_line` 复用句柄（8 µs → 3 µs） |
| P8-5 | `resolution.py` | `normalize()` 加规范形快速通道 + 预编译（**3.1x**，输出逐 token 一致） |
| P8-6 | `anima_weaver.py` | 批量循环内常量外提（每种子省 6 次重复解析） |
| P8-7 | `anima_weaver.py` | 画师表按需加载（`画师种子=0` 时不加载，省 3.5 MB） |
| P8-8 | `anima_weaver.py` | laya 门控移出串行的 Phase 1 |

---

## 4. 兼容性：`widgets_values` / 端口影响矩阵

ComfyUI 前端按 **widget 数组下标** 存 `widgets_values`。`forceInput` 的项不是 widget（是连线端口），不占下标。

### 4.1 Anima随机提示词

| 变更 | 对下标的影响 |
|------|--------------|
| 删「场景类型」（required 第 3 位）→ 内置「随机种子」顶替该位 | **长度不变，后面 40 项下标全部对齐** —— 只需改 index 2 一个值 |
| 删「随机种子」forceInput 端口 | 不占 `widgets_values` 下标，**但会让后续 forceInput 端口的 link `target_slot` 前移 1 位** —— 见 §4.4（第二高危） |
| 删「画师串」forceInput 端口 | 不占 `widgets_values` 下标（**widget 序列仍是 46 项**），只影响端口 slot —— 见 §4.4 |
| 新增 `▸ 系统提示词` / `系统提示词` / `详细NL系统提示词`（末尾） | 无（追加） |
| 删「槽位数据」「底部数据」（forceInput） | 无（不占下标） |
| 删「反推串」（forceInput） | 无下标影响，但已连的线失效 |
| 「系统提示词」forceInput → widget | 新增一个 widget 槽（放末尾 → 前面不变） |
| 「画师种子」「冲突检查」保持紧跟 `▸ 高级` | 保住旧下标 |

> 把内置「随机种子」放在原「场景类型」的位置（index 2）是刻意的：
> 让「删一项」和「加一项」互相抵消，旧 43 项与新前 43 项**逐位对齐**，
> 迁移脚本从「整表重排」降级为「改一个值 + 追加三项」。

**旧序列（43 项，已排除 forceInput 端口）**：

```
0 模式, 1 标签比例, 2 场景类型, 3 ▸ 标签槽位, 4 人数/身份, 5 外貌, 6 服装, 7 姿势/动作,
8 表情, 9 镜头, 10 场景/环境, 11 细节/氛围, 12 自然语言描述, 13 ▸ 过滤控制,
14 标签列表必含, 15 过滤标签, 16 排除含标签列表, 17 排除标签分类, 18 通用标签,
19 争议标签, 20 敏感标签, 21 露骨标签, 22 ▸ LLM设置, 23 自然语言来源,
24 强制详细自然语言, 25 模型, 26 API地址, 27 API密钥, 28 云端模型名, 29 上下文长度,
30 自动上下文长度, 31 最大截断长度, 32 生成后卸载, 33 ▸ 批量, 34 批量数量, 35 请求数,
36 最大并发数, 37 ▸ 高级, 38 画师种子, 39 冲突检查, 40 ▸ laya判定, 41 启用laya门控,
42 过滤质量标签
```

**新序列（46 项，前 43 位与旧逐位对齐）**：

```
0 模式, 1 标签比例, 2 随机种子, 3 ▸ 标签槽位, 4 人数/身份, ... （4~42 完全不变）
43 ▸ 系统提示词, 44 系统提示词, 45 详细NL系统提示词
```

`tools/migrate_widgets.py`（逐位对齐后只需两步）：

```python
OLD_LEN = 43          # 旧 widget 数
SEED_INDEX = 2        # 「场景类型」(combo) → 「随机种子」(INT)，必须重置
APPEND = [False, "", ""]   # ▸ 系统提示词 / 系统提示词 / 详细NL系统提示词

for f in glob("workflows/*.json"):
    j = json.load(open(f, encoding="utf-8"))
    for node in j.get("nodes", []):
        if node.get("type") != "AnimaWeaver": continue
        vals = node.get("widgets_values") or []
        if len(vals) < OLD_LEN: continue          # 空/残缺节点跳过
        out = list(vals[:OLD_LEN]) + APPEND
        out[SEED_INDEX] = 0                       # combo 字符串 → INT 默认值
        node["widgets_values"] = out
    json.dump(j, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
```

> 迁移只做两件事：`index 2` 置 `0`、末尾补三项默认值。**其余 40 项原样保留**，
> 用户的槽位标签、过滤条件、LLM 配置全部不受影响。

### 4.4 连线端口 `target_slot` 迁移（别漏，否则种子串静默接错）

ComfyUI 的 **widget 不占 input slot**，只有 `forceInput` 端口占；
`workflows/*.json` 里 `link.target_slot` 存的是**端口下标**，不是名字。
（依据：本仓库 `batch_bus.py` 头部注释——作者上一轮合并节点时就因为
顺序位移手工改过 `target_slot`；下面用仓库自带 6 个工作流实测复核。）

实测当前 `main` 与旧工作流的对照（AnimaWeaver）：

| 端口名 | 旧工作流保存的 slot | 当前 main 定义 | 改后 | 状态 |
|--------|--------------------|----------------|------|------|
| `随机种子` | 0 | 0 | **删除** | 改内置 widget，连线删掉 |
| `槽位数据` | 1 | 5 | **删除** | 空壳入口 |
| `底部数据` | 2 | 6 | **删除** | 空壳入口 |
| **`种子串`** | 3 | **1** | **0** | ⚠️ **当前 main 上已经错位** |
| `画师串` | 4 | 2 | **删除** | 画师已进提示词 |
| `反推串` | 5 | 3 | **删除** | 纯透传 |
| `系统提示词` | （旧工作流无此端口） | 4 | **改为 widget** | 连线删掉，改节点内手填 |

> **发现的历史遗留 bug**：`种子串` 在旧工作流里是 slot 3，但当前 `main` 的
> `INPUT_TYPES` 里它是 slot 1（上一轮新增「系统提示词」时挤掉了位置却没迁工作流）。
> 也就是说 `随机提示词编织器-批量.json` 的「批量种子 → 种子串」这条线，
> **在当前 main 上已经接到「反推串」端口了** —— 静默失效，无任何报错。
> 本次迁移脚本按 **input 名字**重算 slot，顺手把这个历史 bug 一起修掉。

RandomResolution 同理：

| 端口名 | 旧 slot | 改后 |
|--------|---------|------|
| `随机种子` | 0 | **删除**（改内置 widget） |
| `种子串` | 1 | **0** |
| `提示词` | 2 | **1** |

**迁移脚本（按名字重算，比按数字硬编码稳）**：

```python
# tools/migrate_workflows.py
# 裁剪+重命名 + 删节点 + input/output slot 重排 + widgets_values
import json, glob, os

# ── 1) 只保留 2 个工作流并重命名 ──
KEEP = {
    "anima双采-随机提示词-v2.json": "anima双采-随机提示词.json",
    "随机提示词编织器-批量.json":   "随机提示词-批量.json",
}
# ── 2) 改后各节点的 forceInput 端口顺序 ──
PORT_ORDER = {
    "AnimaWeaver":      ["种子串"],                 # 画师串已删
    "RandomResolution": ["种子串", "提示词"],
    "AnimaBatchBus":    ["种子串", "提示词串", "分辨率串", "反推串",
                         "宽度串", "高度串", "JSON行"],   # 画师通道已删
}
# ── 3) 改后各节点的输出顺序（删的是中间项，必须重排！）──
OUT_ORDER = {
    "AnimaWeaver":   ["生成的提示词", "调试信息"],   # 删 画师串 / 反推串（末尾，0/1 不动）
    "AnimaBatchBus": ["合并输出", "种子", "提示词", "反推",
                      "分辨率", "宽度", "高度"],     # 删 画师（中间！后面全部前移）
}
DELETE_NODES = {"ArtistSeedNode", "AnimaImageCaption",
                "AnimaLoadImages", "AnimaTextListToMultiline"}
OLD_WIDGETS, SEED_INDEX = 43, 2
APPEND = [False, "", ""]


def prune_and_rename(d):
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if f in KEEP:
            if KEEP[f] != f:
                os.rename(p, os.path.join(d, KEEP[f]))
                print("rename", f, "->", KEEP[f])
        else:
            os.remove(p)
            print("delete", f)


def migrate(path):
    j = json.load(open(path, encoding="utf-8"))
    links = j.get("links", [])
    drop = set()          # 只收集「要删的」，其余一律保留

    # A) 被删节点 -> 与之相连的所有线
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
                    drop.add(lid)                  # 端口已删 -> 删线
            n["inputs"] = [{"name": nm, "type": "*", "link": None} for nm in order]
            for l in links:
                if l[3] != n["id"] or l[0] in drop:
                    continue
                ns = remap.get(l[4])
                if ns is None:
                    drop.add(l[0]); continue       # 指到已删端口
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
                        drop.add(lid)              # 输出槽已删 -> 删线
            n["outputs"] = [{"name": nm, "type": "*", "links": []} for nm in oorder]
            for l in links:
                if l[1] != n["id"] or l[0] in drop:
                    continue
                ns = remap_o.get(l[2])
                if ns is None:
                    drop.add(l[0]); continue
                l[2] = ns
                n["outputs"][ns].setdefault("links", []).append(l[0])
            for o in n["outputs"]:
                if not o.get("links"):
                    o["links"] = None

        # D) widgets_values
        if t == "AnimaWeaver":
            v = n.get("widgets_values") or []
            if len(v) >= OLD_WIDGETS:
                out = list(v[:OLD_WIDGETS]) + APPEND
                out[SEED_INDEX] = 0                # 场景类型(combo) -> 随机种子(INT)
                n["widgets_values"] = out

    j["links"] = [l for l in links if l[0] not in drop]
    j["nodes"] = [n for n in j["nodes"] if n["id"] not in gone]
    json.dump(j, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return len(j["nodes"]), len(j["links"]), len(drop)


d = "workflows"
prune_and_rename(d)
for f in sorted(glob.glob(d + "/*.json")):
    nn, nl, nd = migrate(f)
    print("migrated %s -> nodes=%d links=%d (删除 %d 条)" % (f, nn, nl, nd))
```

**在仓库自带工作流上实测跑通**（沙盒，脚本已验证）：

```
rename anima双采-随机提示词-v2.json -> anima双采-随机提示词.json
rename 随机提示词编织器-批量.json   -> 随机提示词-批量.json
delete anima批量自动打标.json
delete 图片反推（自然语言）.json
delete 随机提示词润色.json
delete 随机提示词编织器-单次.json
migrated workflows/anima双采-随机提示词.json -> nodes=39 links=46 (删除 4 条)
migrated workflows/随机提示词-批量.json      -> nodes=15 links=16 (删除 4 条)
```

（比上一版多删 2 条：一条是 `ArtistSeedNode → AnimaWeaver.画师串`，
另一条是 `AnimaWeaver.画师串 → AnimaBatchBus.画师串`。）

迁移后校验（**实测输出，逐条对照**）：

```
### anima双采-随机提示词.json   nodes=39 links=46
  残留被删节点: 无 ✓        残留画师端口: 无 ✓        残留画师输出: 无 ✓
  [BatchSeedNode#309]
      out 种子串 -> AnimaBatchBus#304.种子串 / RandomResolution#310.种子串
                    AnimaWeaver#313.种子串 / easy showAnything#314
  [AnimaWeaver#313]
      in  种子串     <- BatchSeedNode#309.种子串
      out 生成的提示词 -> AnimaBatchBus#304.提示词串        ← 只剩这一条输出线
  [AnimaBatchBus#304]  (合并)
      in  种子串 / 提示词串 / 宽度串 / 高度串
      out 合并输出 -> easy promptLine#305.prompt
  [AnimaBatchBus#307]  (拆分)
      in  JSON行 <- easy promptLine#305.STRING
      out[1] 种子   -> easy showAnything#308 / KSamplerAdvanced#248.noise_seed
      out[2] 提示词  -> easy showAnything#298 / JoinStringMulti#280
      out[4] 分辨率  -> easy showAnything#300          ← 原 slot5，已前移 ✓
      out[5] 宽度    -> easy showAnything#301 / EmptyLatentImage#36.width  ← 原 slot6 ✓
      out[6] 高度    -> easy showAnything#302 / EmptyLatentImage#36.height ← 原 slot7 ✓
  ✓ AnimaWeaver   widgets=46  [2]=0  画师种子[38]=0  outputs=0:生成的提示词, 1:调试信息
  ✓ AnimaBatchBus inputs=0种子串,1提示词串,2分辨率串,3反推串,4宽度串,5高度串,6JSON行
                  outputs=0合并输出,1种子,2提示词,3反推,4分辨率,5宽度,6高度

### 随机提示词-批量.json   nodes=15 links=16
  （同上：种子串 / 提示词 / 宽度 / 高度 链路全部保留，画师链路已彻底移除）
  ✓ AnimaWeaver   widgets=46  [2]=0  画师种子[38]=0  outputs=0:生成的提示词, 1:调试信息
```

**⚠️ `EmptyLatentImage.width / height` 这两条是本轮最容易踩的雷**：
它们在拆分节点上原本是 output slot 6 / 7，删掉「画师」（slot 3）后必须前移到 5 / 6。
只做 input 重排、漏掉 output 重排的话，这两条会静默接到「分辨率」和「宽度」上 ——
出图尺寸全错，且不报任何错。

⚠️ **脚本踩过的坑（别重犯）**：第一版我用「`keep` 集合收集要保留的线」，
结果只有被脚本处理过的节点的连线进了 `keep`，其余全被当成「没确认过」删掉
—— 工作流从 50 条线掉到 2 条。正确做法是**只收集 `drop`、其余一律保留**：

```python
drop = set()                                       # ✅ 只收集要删的
j["links"] = [l for l in links if l[0] not in drop]
# 而不是：
# j["links"] = [l for l in links if l[0] in keep]  # ❌ 会误删绝大多数线
```

> 另一条：`drop` 必须**先收集、最后一次性过滤**。边遍历边删 `links` 会让后续节点的
> `remap` 读到错位下标，并残留指向已消失端口的悬空线（加载时报错）。
> `RandomResolution` 的 `widgets_values` 不用改（长度 5 保持，内置种子由前端自动补）。

### 4.2 随机分辨率选择器

旧 widget 序列 `模式, 随机画幅, 百万像素, 固定比例, 对齐到` 完全不动，内置种子追加在末尾 →
**旧工作流的参数值安全**，只有从外部种子节点连过来的那条线需要手动删掉。

### 4.2b 两个节点「内置种子」对照

| | Anima随机提示词 | 随机分辨率选择器 |
|---|---|---|
| 内置种子位置 | required 第 3 位（顶替「场景类型」） | required 末尾（第 6 位） |
| 是否影响旧 widgets_values | 仅 index 2 一个值 | 无（纯追加） |
| 单次模式 | 唯一随机源 | 唯一随机源 |
| 批量模式（接种子串） | 让位 | 让位 |
| 批量模式（仅批量数量） | **作父种子派生 N 个子种子** | 不适用（无批量数量控件） |
| `control_after_generate` | True | True |
| 种子语义 | `0`=随机 / `>0`=复现 | `0`=随机 / `>0`=复现 |

### 4.3 端口失效清单（旧工作流必须手动处理）

| 端口 | 所在节点 | 处置 | 由迁移脚本处理 |
|------|----------|------|----------------|
| **`种子串` in** | AnimaWeaver / RandomResolution | **保留**，只需改 `target_slot`（见 §4.4） | ✅ 自动重排 |
| `画师串` in | AnimaWeaver | **删**（画师已进提示词） | ✅ 自动删线 |
| `画师串` in / `画师` out | AnimaBatchBus | **删**（通道 7→6） | ✅ 自动删线 + 其余两端 slot 重排 |
| `随机种子` in | AnimaWeaver | **删**，改内置 widget（外挂 `easy seed` 一并删） | ✅ 自动删线 |
| `随机种子` in | RandomResolution | **删**，改内置 widget | ✅ 自动删线 |
| `反推串` in | AnimaWeaver | **删**，改接总线透传 | ✅ 自动删线 |
| `槽位数据` / `底部数据` in | AnimaWeaver | **删**（空壳入口） | ✅ 自动删线 |
| `系统提示词` in | AnimaWeaver | **删线**，改为节点内手填 | ✅ 自动删线 |
| 整节点消失 | AnimaImageCaption / ArtistSeedNode / AnimaLoadImages / AnimaTextListToMultiline | 见 §5 | ❌ 需手工/另写脚本 |

---

## 5. 工作流：6 → 2（并重命名）

### 5.1 去留与命名对照

| 原文件名 | 处置 | 新文件名 |
|----------|------|----------|
| `anima双采-随机提示词-v2.json` | **保留** | **`anima双采-随机提示词.json`**（去掉 `-v2`） |
| `随机提示词编织器-批量.json` | **保留** | **`随机提示词-批量.json`** |
| `随机提示词润色.json` | 删 | — |
| `随机提示词编织器-单次.json` | 删 | — |
| `图片反推（自然语言）.json` | 删 | — |
| `anima批量自动打标.json` | 删 | — |

删除理由（逐个）：

| 文件 | 为什么删 |
|------|----------|
| `随机提示词编织器-单次.json` | 单次用法已被「主节点内置种子 + 批量数量=1」覆盖；且它依赖 `ArtistSeedNode` |
| `随机提示词润色.json` | 用的是外部 `ImageCaption`，与四节点包无关，放在包里反而误导 |
| `图片反推（自然语言）.json` | 同上，纯外部节点，`RandomResolution` 只是配角 |
| `anima批量自动打标.json` | 唯一依赖三个被删节点（Anima反推 + Anima加载图像 + 列表转多行）的工作流，删掉节点后它必然报红 |

> `anima双采` 之所以保留 `-v2` 改名而来而不是沿用旧名：旧名带版本号会让人以为还有 v1/v3，
> 现在包里只有这一份，去掉后缀更干净。

### 5.2 保留的两个工作流需要改什么

两个都是**批量模式**，且都含 `ArtistSeedNode`。实测它们的完整拓扑：

改前（实测拓扑）：

```
BatchSeedNode.种子串 ─┬─> AnimaBatchBus.种子串
                     ├─> RandomResolution.种子串
                     ├─> AnimaWeaver.种子串
                     └─> ArtistSeedNode.种子串 ─> AnimaWeaver.画师串(输入)
AnimaWeaver.画师串(输出) ──────────────────────────> AnimaBatchBus.画师串
AnimaWeaver.生成的提示词 ──────────────────────────> AnimaBatchBus.提示词串
RandomResolution.宽度/高度 ───────────────────────> AnimaBatchBus.宽度串/高度串
AnimaBatchBus.合并输出 ─> easy promptLine ─> 拆分总线.JSON行 ─> KSampler / EmptyLatent
```

改后：

```
BatchSeedNode.种子串 ─┬─> AnimaBatchBus.种子串
                     ├─> RandomResolution.种子串
                     ├─> AnimaWeaver.种子串
                     └─> easy showAnything（展示用）
AnimaWeaver.生成的提示词 ──────────────────────────> AnimaBatchBus.提示词串
RandomResolution.宽度/高度 ───────────────────────> AnimaBatchBus.宽度串/高度串
AnimaBatchBus.合并输出 ─> easy promptLine ─> 拆分总线.JSON行 ─> KSampler / EmptyLatent
                                                    └─> 各通道 easy showAnything（画师那一路删掉）
```

**要删的 3 样东西**（脚本全自动，实测各工作流删 4 条线）：

1. `ArtistSeedNode` 节点本身（+ 它的一进一出 2 条线）；
2. `AnimaWeaver.画师串（输出）→ AnimaBatchBus.画师串` 这条线；
3. 拆分总线 `out 画师 → easy showAnything` 这条线。

**剩下的链路一行都不用改** —— 提示词、宽度、高度三路照旧。

**语义上也不损失任何东西**：两个工作流的 `ArtistSeedNode` widget 值都是 `[0]`
（`artist_seed=0` = 无画师），主节点「画师种子」默认也是 `0`，实测
`AnimaWeaver.widgets_values[38]` 确实是 `0`。也就是说这两个示例**本来就没用画师**，
删掉画师串对它们的出图结果零影响。真要用画师，把「画师种子」设成 `-1`（随机）
或具体序号，画师名会自动拼进提示词末尾。

### 5.3 迁移后必须手工确认的 3 件事

脚本（§4.4）能自动处理的：删节点、删它的 2 条连线、端口 slot 重排、`widgets_values` 迁移。
但下面三件**必须人工过一遍**：

1. **`AnimaWeaver` 的「随机种子」清空**：这两个工作流本来就没给它接线（`link=None`），
   删端口对它们零影响 —— 但要在 UI 里确认内置 seed 显示为 `0`（=每批随机）。
2. **`RandomResolution` 的「随机种子」**：同样本来就没接线，删端口零影响。
   「种子串」是接着 `BatchSeedNode` 的，改到 slot 0 后要确认仍在 slot 0。
3. **跑一次 8 行批量回归**：确认提示词 / 宽高三路逐行对齐，
   且总线「合并 → 拆分」往返后 6 个字段（种子/提示词/反推/分辨率/宽度/高度）逐一还原；
   特别盯 `EmptyLatentImage` 的宽高是否接对（output slot 前移的那两条）。

## 6. 验收清单

静态：

```bash
python -m compileall -q .                 # 0 error
python tools/check_inputs.py               # A 类 / B 类 均为空
python tools/acceptance_check.py           # 更新后全绿
grep -rn "caption\|artist_seed\|load_images\|list_to_multiline" --include=*.py .   # 只剩注释
git status --short                         # 确认删除文件列表
```

运行时（ComfyUI 重启后逐个走一遍）：

1. **节点菜单**：4 个节点在，其余 4 个消失，无 import 报错；
2. **两级分组**：勾 `▸ 高级` → 出现 4 个子开关；勾 `▸ LLM设置` → 展开 10 项；取消 `▸ 高级` → 全部收起且节点高度回落；刷新页面后展开状态随工作流保存；
3. **系统提示词**：手填一段 → LM Studio 生成结果随之变化；空 → 用内置默认；开「强制详细自然语言」→ 走「详细NL系统提示词」；
4. **分辨率内置种子**：`随机种子=12345` 跑两次宽高一致；设 `0` 跑两次不一致；接种子串（8 行）→ 输出 8 行宽高且「随机种子」= 第 1 行种子；
5. **分辨率输出修正**：「随机种子」槽不再等于宽度；
6. **画师只进提示词**：单次模式「画师种子=-1」→ 提示词**末尾带上画师名**，且没有「画师串」输出槽；批量 8 行 → 每行提示词各自带上画师；
7. **主节点内置种子（单次）**：`随机种子=12345` 跑两次，提示词**完全一致**；`随机种子=0` 跑两次不一致；点 randomize 后结果变化；
8. **主节点内置种子（批量父种子）**：`批量数量=8, 随机种子=12345` 跑两次 → 8 条提示词**逐条一致**（旧版此项必失败）；把种子改成 999 再跑 → 8 条全变；
9. **批量**：接「批量种子」8 行 → 内置种子让位，逐行对齐；总线合并→拆分往返后字段逐一还原；
10. **laya 判定**：未装模型时开启不报错、原样放行（回归旧的降级行为）；
11. **性能**（见 §9.11）：启动无 4 个 1.6 s 预热线程；严格必含 + 批量 256 秒级完成；分辨率 256 行耗时下降约 2/3；
12. **种子串链路**：迁移后打开 `随机提示词-批量.json`，确认「批量种子」→ 主节点「种子串」的线**仍连着且 slot=0**；跑一次 8 行批量，逐行提示词与外部种子对应；
13. **工作流目录**：`workflows/` 下只剩 `anima双采-随机提示词.json` 和 `随机提示词-批量.json`；两个都能加载无报红，不含 `ArtistSeedNode`，不含任何名字带「画师」的端口或连线；
14. **两个工作流各跑一次 8 行批量**：提示词 / 宽高三路逐行对齐；`EmptyLatentImage` 拿到的宽高与分辨率节点输出一致（验证 output slot 前移正确）；总线合并→拆分往返后 6 个字段逐一还原；
15. **画师不在提示词里重复**：`画师种子=100` 跑一次，提示词末尾出现一次画师名，且没有第二处重复（验证删画师串后没有残留拼接逻辑）。

---

## 7. 风险与回滚

| 风险 | 等级 | 对策 |
|------|------|------|
| `widgets_values` 错位（删「场景类型」） | 高 | 必跑 `tools/migrate_widgets.py`；CHANGELOG 顶部红字提示「v2 后旧工作流请用迁移脚本或重设参数」 |
| 「反推串」删除后旧工作流报错 | 中 | CHANGELOG 明示；给用户一行命令 `git checkout pre-4node-*` 回退 |
| `control_after_generate` 在极旧前端不生效 | 低 | 不显示随机化菜单也不影响功能（手动填数字即可） |
| 删端口后旧工作流「随机种子」连线报错 | 中 | 迁移脚本顺带把连到该端口的 `link` 删掉；CHANGELOG 明示 |
| **连线 `target_slot` 位移导致种子串静默接错** | **高** | 迁移脚本按 input 名字重算 slot（§4.4），已在 6 个自带工作流上实测；**不许用数字硬编码**，因为不同工作流是不同时期保存的、旧 slot 并不一致 |
| 内置种子 `0` 语义变更（旧版「不接=内部随机」→ 现在默认 0 也是随机） | 低 | 行为一致，无需用户介入；但「批量数量」模式从随机变可复现，CHANGELOG 里作为**新特性**写明 |
| 删除 4 个示例工作流，用户找不到「单次 / 反推 / 打标」示例 | 中 | 更新日志 + README 都写明可从 `pre-4node-*` tag 找回；单次用法在主节点详解里补一句「批量数量=1 即单次」 |
| **总线 output slot 漏重排 → `EmptyLatentImage` 宽高接错** | **高** | 迁移脚本必须同时重排 input 和 output 两端（§4.4）；验收第 14 条专门盯这个 |
| 有用户依赖画师串做二次处理 | 中 | 更新日志 + README 写明「画师已并入提示词」；可从 tag 回退 |
| 删除 laya 微调脚本 | 低 | tag 可找回 |
| taglist 移出 git 后新装用户抽签为空 | 中 | `download_tags.py` 必须好用到位，且 `get_tag_index` 失败时在控制台打明确提示 |
| P8-5 快速通道改错导致画幅判断变化 | 中 | 必须跑 §9.11 的逐 token 一致性断言；尤其验证下划线变体（`upper_body` 必须输出 `upper body`） |
| P8-1 惰性构建后首次严格过滤卡 1~2 s | 低 | 控制台提前打印提示；或只后台预热「当前启用文件」 |

回滚：`git checkout pre-4node-YYYYMMDD` 一键回到 8 节点版本。

---

## 8. 需要你拍板的 5 个决策点

| # | 决策 | 推荐 |
|---|------|------|
| D1 | 「场景类型」删还是留 | **删** —— 用内置「随机种子」顶替它的 index 2，迁移脚本只剩「改一个值 + 补三项」，代价极低 |
| D2 | 批量总线的「反推」通道是否保留 | **保留**（总线是通用管道，外部反推节点仍可接）。注：「画师」通道已按你的要求删除，总线 7 路 → 6 路 |
| D3 | `laya_finetune.py` + `data/laya_n2` 删还是移 `tools/` | **删**（9.9 MB，可 tag 找回） |
| D4 | 222 MB taglist：运行时下载 / LFS / 保持现状 | **运行时下载**（`download_tags.py` 升级 + README 写明） |
| D5 | P8-2 的 `_scan` 全量扫描：彻底删掉 vs 加同参数缓存保留 | **加缓存保留**（删掉后若构建失败会直接返回空，缓存版更稳） |

拍板后即可按 P0→P8 顺序执行；P7 已把「更新日志.md」要追加的整节文案写好，直接抄进去即可。
P8（性能优化）与功能改动正交，可以单独拆一个 PR 先合 —— 它不动任何输入输出，风险最低、收益最大。

---

## 9. 性能优化（实测驱动）

### 9.0 基准环境与方法

所有数字来自沙盒实测（合成 `taglists-test.txt`：100 000 行 / 45 MB / 4 000 007 条 posting，
结构与真实文件一致 `id, score, tag1, tag2, ...`）。真实文件 47~60 MB、约 10 万行，量级可直接套用。

复现脚本（放进 `tools/bench.py`）：

```python
import os, random, time, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tag_index import TagIndex
from tag_extract import InvertedIndex, _scan, fast_parse_line
import resource

def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

def gen(path, n=100_000):
    if os.path.exists(path): return path
    random.seed(7)
    V = [f"tag_{i:05d}" for i in range(3000)] + ["1girl","solo","blonde_hair","blue_eyes","smile"]
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(f"{i}, {random.randint(0,100)}, "
                    + ", ".join(random.sample(V, random.randint(20, 60))) + "\\n")
    return path

def main():
    p = gen("/tmp/taglists-test.txt")
    idx = TagIndex.build(p)
    print("lines:", idx.count)

    # 1) 倒排索引构建
    t0 = time.perf_counter(); inv = InvertedIndex.build(idx.read_line, idx.count)
    print("build: %.2fs  RSS %.0f MB" % (time.perf_counter()-t0, rss()))

    # 2) read_line 句柄开销
    t0 = time.perf_counter()
    for i in range(2000): idx.read_line(i * 37 % idx.count)
    print("read_line: %.0f us/次" % ((time.perf_counter()-t0)/2000*1e6))

    # 3) 全量扫描兜底（索引未就绪时）
    rng = random.Random(1); must = {"tag_00001", "tag_00002"}
    t0 = time.perf_counter()
    _scan(idx, rng, list(must), [], lambda t: must.issubset(set(t)))
    print("scan: %.2fs  -> 批量256种子 = %.0fs" % (time.perf_counter()-t0, (time.perf_counter()-t0)*256))

if __name__ == "__main__":
    main()
```

### 9.1 实测热点总表

| # | 热点 | 现状实测 | 优化后 | 触发条件 |
|---|------|----------|--------|----------|
| 1 | 启动预热建 4 份倒排索引 | **6.5 s CPU + ~92 MB RSS**（1.64 s/文件 ×4） | **0**（默认场景） | 每次 ComfyUI 启动 |
| 2 | 索引未就绪时的全量扫描兜底 | **0.77 s/种子 → 256 种子 = 196 s** | ~7 ms（构建一次） | 设了严格「必含」且预热未完成 |
| 3 | `InvertedIndex.build` 逐行 `open()` | 1.64 s（其中 ~1.0 s 是 10 万次 open/close） | ~0.9 s | 首次建索引 |
| 4 | `resolution.normalize()` 正则热循环 | 4.06 ms/次 → 256 行 **1040 ms** | 1.31 ms/次 → **334 ms（3.1x）** | 自动模式分析提示词 |
| 5 | 批量循环内重复解析常量 | 每种子 6 次（`_parse_comma_field`×4 + `_must_protected`×2） | 0 | 批量模式 |
| 6 | `TagIndex.read_line` 每次开关句柄 | 8 µs/次 | 3 µs/次 | 每次抽签 |
| 7 | 画师表（59 676 条）加载 | 3 ms + 3.5 MB | 0（`画师种子=0` 时） | 首次用到画师 |

**明确不做**（测过，收益 < 噪声，别浪费时间）：

| 项 | 实测 | 结论 |
|----|------|------|
| 批量 Phase 1 并行化 | 抽签 ~0.1 ms/种子 → 256 种子仅 26 ms | 并行化收益 < 线程开销，保持串行 |
| `IS_CHANGED` 的 `json.dumps` | 4096 行种子串（161 KB payload）0.6 ms/次 | 可忽略，不动 |
| `rules.check_conflicts` | 64 tag 时 0.03 ms/次 | 可忽略，不动 |

### 9.2 P8-1 倒排索引惰性构建（最大收益）

**问题**：`anima_weaver._start_warmup()` 在 import 时就为 **4 个 taglist 全量构建倒排索引**。
但倒排索引只在 `pick_line` **第 2 级**被用到，而第 2 级仅在「设了必含/排除 **且** 第 1 级
8 次拒绝采样全失败」时才触发。

默认场景（不设过滤）走的是第 1 级 `reject`，**根本不会碰倒排索引** ——
也就是说绝大多数用户每次启动都在为一份永远用不到的索引付 6.5 s CPU 和 92 MB 内存。

**改法**：删掉 `_start_warmup` 里的 `build_sync`，改成在 `pick_line` 第 1 级失败时按需构建：

```python
# tag_extract.py
_building: set = set()          # 正在构建的文件，防止并发重复触发
_build_lock = threading.Lock()

def _ensure_index(tag_index):
    """按需取索引；未就绪则同步构建一次（返回 None 表示本次放弃，走扫描）。"""
    hit = _inv_cache.get(tag_index.path)
    if hit is not None:
        return hit
    with _build_lock:
        hit = _inv_cache.get(tag_index.path)
        if hit is not None:
            return hit
        if tag_index.path in _building:      # 别的线程正在建，别跟着建
            return None
        _building.add(tag_index.path)
    try:
        print(f"[Anima] 首次严格过滤，构建倒排索引（约 1~2 s，之后缓存）: "
              f"{os.path.basename(tag_index.path)}")
        return build_sync(tag_index)
    finally:
        with _build_lock:
            _building.discard(tag_index.path)
```

`pick_line` 里把 `inv = get_index(tag_index)` 换成 `inv = _ensure_index(tag_index)`。

`_start_warmup` 只保留**分类字典**（`get_category_map`，1.9 MB，几十毫秒）+ 行偏移表
（`.idx` 落盘缓存，毫秒级），这两个才是每次抽签都用的。

> 折中选项：如果担心首次严格过滤卡 1~2 s，可在 `_ensure_index` 里保留后台预热，
> 但**只预热当前启用文件**（默认 sensitive+explicit 两个，而非四个），并加
> `ANIMA_NO_WARMUP=1` 开关（已有）。

### 9.3 P8-2 修「索引未就绪 → 每种子全量扫描」雪崩

**这是本轮发现的最严重问题。** `pick_line` 第 3 级 `_scan` 实测 **0.77 s/次**，
而批量模式对每个种子独立调用 `pick_line`：

```
批量 256 种子 + 设了严格「必含」+ 预热未完成  →  256 × 0.77 s ≈ 196 秒
```

旧预热是后台线程（约 6.5 s），用户完全可能在它完成前就点了运行 —— 一旦命中，
ComfyUI 界面假死三分半，且没有任何提示。

**改法**（与 P8-1 配套）：第 3 级不再是「默认兜底」，而是**最后手段**且**带一次性结果缓存**：

```python
    # ── 第 2 级：倒排索引精确求解（P8-1：按需构建）────────────────
    inv = _ensure_index(tag_index)
    if inv is not None:
        cand = inv.candidates(must, excl)
        if len(cand):
            i = cand[rng.randrange(len(cand))]
            return fast_parse_line(tag_index.read_line(i)), "index"
        return [], "index-empty"
    # 构建被跳过（并发中）→ 本次放宽过滤，绝不进全量扫描
    return fallback, "reject-relaxed"
```

要点：**删除 `_scan` 的自动触发路径**。索引一定能建起来（1~2 s，一次性），
建起来之后所有严格查询都是 2~7 ms。留着 `_scan` 只是给「构建失败」兜底，
真失败时应**明确降级 + 控制台告警**，而不是静默扫 0.77 s × N。

如果坚持保留 `_scan`，必须加**同参数结果缓存**（`(must, excl)` → 候选行号列表），
让 256 个种子只扫一次：

```python
_scan_cache: dict = {}   # (path, tuple(sorted(must)), tuple(sorted(excl))) -> list[list]

def _scan_cached(tag_index, must, excl):
    key = (tag_index.path, tuple(sorted(must)), tuple(sorted(excl)))
    hit = _scan_cache.get(key)
    if hit is None:
        hit = _scan(tag_index, random.Random(0), must, excl, _mk_ok(must, excl))
        _scan_cache[key] = hit
        print(f"[Anima] 倒排索引不可用，已全量扫描 {tag_index.count} 行（结果已缓存）")
    return hit
```

### 9.4 P8-3 倒排构建改顺序批量读

`InvertedIndex.build(read_line, n)` 对 10 万行逐行调 `read_line(i)`，
每次都是 `open → seek → readline → close`。实测：

```
A 现状（逐行 open）          1.64 s
B 仅顺序读 + 解析（不建索引） 0.62 s
   → 约 1.0 s（61%）纯粹花在 10 万次 open/close 上
```

**改法**：`build` 增加一条 bulk 路径，一次 open 顺序迭代：

```python
    @classmethod
    def build(cls, read_line, n_lines: int, bulk_lines=None) -> "InvertedIndex":
        if bulk_lines is None:
            src = (read_line(i) for i in range(n_lines))
        else:
            src = bulk_lines                    # 调用方传一次打开的文件对象
        buckets: dict = {}
        for line in src:
            for t in fast_parse_line(line):
                b = buckets.get(t)
                if b is None: buckets[t] = array("i", [len(buckets) and 0 or 0])  # 见下
                ...
```

更干净的写法是提供 `TagIndex.iter_lines()`：

```python
    def iter_lines(self):
        """顺序全量读（一次 open）；构建倒排索引专用，比 read_line×N 快 ~2.7x。"""
        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line
```

然后 `InvertedIndex.build(tag_index.iter_lines(), tag_index.count)`。
注意：`build` 的签名从「传函数 + 行数」改成「传可迭代」，调用点 `build_sync` 同步改。

### 9.5 P8-4 `read_line` 复用句柄

实测 8 µs/次 → 3 µs/次（2.3x）。`read_line` 现在每次 `open`，是为线程安全刻意做的，
但批量 Phase 1 是串行的。折中方案：**按线程缓存句柄**（`threading.local`），
既保线程安全又不重复 open：

```python
class TagIndex:
    __slots__ = ("path", "offsets", "count", "mtime", "size", "_tls")

    def __init__(...):
        ...
        self._tls = threading.local()

    def _handle(self):
        f = getattr(self._tls, "f", None)
        if f is None:
            f = open(self.path, "r", encoding="utf-8", errors="replace")
            self._tls.f = f
        return f

    def read_line(self, i: int) -> str:
        f = self._handle()
        f.seek(self.offsets[i])
        return f.readline()
```

批量 256 种子 × 最多 8 次探测 = 2048 次读：16 ms → 6 ms。绝对量不大，
但配合 P8-3（10 万次/文件）收益就显著了。

### 9.6 P8-5 `resolution.normalize()` 快速通道（3.1x）

**问题**：`normalize()` 对每个 token 遍历 **8 层 × 约 25 条正则 ≈ 200 次 `re.sub`**，
只有命中才 `break`。而实测真实提示词里 **97% 的 token 不会被任何层改写** ——
也就是 97% 的开销都是白跑。

自动模式下批量 256 行提示词：`4.06 ms × 256 = 1040 ms`。

**改法**：预编译 + 「已是规范形」集合做 O(1) 短路：

```python
# 模块级，import 时算一次（约 30 ms）
def _build_canon():
    exact, us = set(), {}
    for layer in NORM_LAYERS:
        for pat, rep in layer.items():
            if isinstance(rep, str):
                exact.add(rep)
                if " " in rep:
                    us[rep.replace(" ", "_")] = rep      # 下划线变体 -> 空格规范形
    for fs in (PERSON, COUPLE, GROUP_SMALL, GROUP_LARGE, MULTIPLE, POV, OTS, PANORAMA,
               WIDE_ANGLE, AERIAL, FIGHTING, ACTION, ACROBAT, FACE, BUST, AMERICAN,
               UPPER, LOWER, FOCUS, FULL, SITTING, LYING, CURLED, STILL, STILL_WIDE,
               ARGUE, TALL, SELFIE, CHIBI, LOW_ANGLE, HIGH_ANGLE):
        exact |= fs
    return exact, us

CANON_EXACT, CANON_US = _build_canon()
_LAYERS_C = [[(re.compile(p), r) for p, r in L.items()] for L in NORM_LAYERS]

def normalize(tokens: list[str]) -> list[str]:
    result = []
    for t in tokens:
        t = t.strip().lower()
        if not t:
            continue
        canon = CANON_US.get(t)          # 下划线变体（upper_body -> upper body）
        if canon is not None:
            result.append(canon); continue
        if t in CANON_EXACT:             # 已是规范形，跳过 ~200 次正则
            result.append(t); continue
        for layer in _LAYERS_C:          # 预编译版本
            matched = False
            for pattern, replacement in layer:
                new_t = pattern.sub(replacement, t)
                if new_t != t:
                    t = new_t; matched = True; break
            if matched:
                break
        result.append(t)
    return result
```

**实测（沙盒，60 tag 提示词 × 500 次）**：

```
A 现状 4.064 ms/次 | B 优化 1.305 ms/次 | 提速 3.1x
批量 256 行：1040 ms -> 334 ms
逐 token 比对：完全一致（含 upper_body / full_body / low_angle / wide_shot 等
               下划线变体，以及 face_close_up / over_the_shoulder 等复合词）
```

⚠️ 实现时注意：`CANON_US` 必须**先于** `CANON_EXACT` 判断，否则 `upper_body`
会命中 `CANON_EXACT`（因为它是 `upper body` 的下划线变体）而被原样返回，
与现状的 `upper body` 不一致 —— 这个坑我实测踩过一次。

### 9.7 P8-6 批量循环内常量外提

`_compose_batch` 的每个种子都会重复计算**与种子无关**的量：

| 重复项 | 位置 | 每种子次数 |
|--------|------|-----------|
| `_parse_comma_field(排除含标签列表)` | `_run_raffle` | 1 |
| `_parse_comma_field(标签列表必含)` | `_run_raffle` | 1 |
| `_parse_comma_field(排除标签分类)` | `_run_raffle` | 1 |
| `_parse_comma_field(过滤标签)` | `_run_raffle` | 1 |
| `_must_protected(kwargs)` | `compose` / `_compose_batch` 调 2 次 | 2 |

改法：在 `compose()` 里算一次，塞进 `kwargs` 传给 `_run_raffle` 复用：

```python
        kwargs["_filter"] = {
            "must": _parse_comma_field(kwargs.get("标签列表必含", "")),
            "excl": _parse_comma_field(kwargs.get("排除含标签列表", "")),
            "excl_cat": _parse_comma_field(kwargs.get("排除标签分类", "")),
            "drop_tag": _parse_comma_field(kwargs.get("过滤标签", "")),
        }
        kwargs["_protected"] = self._must_protected(kwargs)
```

`_run_raffle` 里改成 `f = kwargs.get("_filter") or <现算>`（保留兜底，兼容直接调用）。
256 种子省下 1536 次解析。

同类的还有 `sample_slot` 里每个槽位每种子重建 `idx = {t: i for i, t in enumerate(tags)}`
（8 槽 × 256 种子 = 2048 次）—— 可在 `_merge_slots` 外层按 slot 缓存不变量，
收益约几毫秒，优先级低，顺手改即可。

### 9.8 P8-7 画师表按需加载

`_finish_prompt` 现在的顺序是：

```python
        if artist_seed_val is not None and str(artist_seed_val) != "":
            s = int(artist_seed_val)
            artists = _load_artists()      # ← 无条件加载 59676 条
            if artists:
                if s == -1: ...
                if s > 0: ...              # ← 只有这里才真需要
```

`画师种子=0`（无画师，默认值）时也加载。实测 3 ms + 3.5 MB。改成：

```python
        s = int(artist_seed_val or 0) if str(artist_seed_val or "") != "" else 0
        if s != 0:
            artists = _load_artists()
            if artists:
                ...
```

配合 §3.2.2（画师只拼进提示词），批量模式下 `_load_artists()` 只在
`画师种子 != 0` 时调一次，之后命中缓存。

### 9.9 P8-8 laya 门控移出串行 Phase 1

`_gate_tag_prompt` 在 Phase 1 里**逐种子串行**调用。若开启且模型就绪，
每个种子一次 `judge_keep` 推理（几十到几百 ms），256 种子就是几十秒，
且完全串行 —— 而 Phase 2 已经有 `ThreadPoolExecutor` 闲置。

改法：把门控判定挪进 `_finish_prompt`（Phase 2 并行执行），
或者对不打分的场景做批量推理。注意门控失败会「派生种子重抽一次」，
重抽依赖 `_run_raffle`（CPU，无 GIL 竞争问题），放进线程是安全的。

> 优先级：**中**。默认关闭（`启用laya门控=False`），只有主动开启才受影响。
> 但如果保留 laya 功能，这条应该在开启前修掉，否则体验是「开一次卡一分钟」。

### 9.10 优化前后总账

| 场景 | 现状 | 优化后 | 收益 |
|------|------|--------|------|
| ComfyUI 启动（默认，无过滤） | 后台 6.5 s CPU + ~92 MB RSS | ~0.05 s + ~5 MB | **启动零负担** |
| 单次出图（严格必含，索引未就绪） | 0.77 s（全量扫描） | ~1.5 s 首次构建，之后 2~7 ms | 首次略慢，之后 100x |
| 批量 256 种子 + 严格必含 + 未预热 | **196 s** | ~1.5 s | **130x，修掉假死** |
| 批量 256 种子（无过滤） | ~26 ms + LLM 时间 | ~20 ms + LLM 时间 | 小幅 |
| 分辨率自动模式 256 行 | 1040 ms | 334 ms | **3.1x** |
| 常驻内存（4 份索引 + 画师表） | ~95 MB | ~5 MB（默认）/ ~23 MB（严格过滤后） | **-80%** |

### 9.11 性能验收

```bash
python tools/bench.py
# 期望：
#   lines: 100000
#   build: <1.0s        （P8-3 后；优化前 1.64s）
#   read_line: <4 us/次 （P8-4 后；优化前 8us）
#   scan: 不应再被自动触发（P8-2）

python - <<'EOF'
# P8-5 一致性回归：优化前后逐 token 必须完全相同
import sys; sys.path.insert(0, '.')
import resolution as R
VOCAB = ["1girl","solo","upper_body","full_body","low_angle","high_angle","wide_shot",
         "face_close_up","over_the_shoulder","2girls","group","selfie","chibi","lying"]
assert R.normalize(VOCAB) == R.normalize_fast(VOCAB), "归一化输出不一致！"
print("normalize 一致性 OK")
EOF
```

运行时手测：

1. 启动 ComfyUI，`htop` 观察：**不再有 4 个 anima-warmup 线程各跑 1.6 s**；
2. 单次默认参数出图 → 首次抽签 < 100 ms；
3. 设「标签列表必含 = 1girl, blonde_hair, blue_eyes, twintails」（严格，命中率 0.38%）+
   `批量数量=256` → **必须在几秒内完成**，控制台打印一次「首次严格过滤，构建倒排索引」；
4. 第二次跑同样参数 → 无构建日志，明显更快；
5. 分辨率节点接 256 行提示词（自动模式）→ 完成时间比改动前缩短约 2/3。
