# Anima Weaver

<p align="right">
  <a href="README_CN.md">中文</a> | <b>English</b>
</p>

A ComfyUI custom node package for structured AI image prompt assembly. Supports tag/NL hybrid output, batch pipelines, random artist selection, and random resolution generation.

---

## Node Reference

| Node | Category | Description |
|------|----------|-------------|
| **Anima随机提示词** | Anima Weaver | Core node: assembles tags → NL → complete prompt (two-level collapsible groups, built-in random seed) |
| **随机分辨率选择器** | Anima Weaver | Random aspect ratio & resolution generator (built-in random seed) |
| **批量种子** | Anima Weaver / Batch | N-seed generator (max 4096) shared across pipeline nodes; also an alternative to the core node's built-in seed (for cross-node alignment) |
| **Anima批量合并** | Anima Weaver / Batch | 4 multiline channels (seed/prompt/width/height) aligned per line → merged multiline JSON (one data group per line) |
| **Anima批量拆分** | Anima Weaver / Batch | one JSON line (picked by Easy-Use promptLine in between) → seed/prompt/width/height scalars |

> As of 2026-10-16 the package is trimmed 8 → 4 nodes: Anima反推 (image captioning), 画师Seed,
> Anima加载图像 and Anima列表转多行 are removed (artist selection is now the 画师种子 widget on the
> core node — the artist name is appended to the prompt directly; caption passthrough lives in the
> batch bus). The laya fine-tune script (`laya_finetune.py`) and its data (`data/laya_n2/`) were
> removed too — recover them from the `pre-4node-20261016` tag.

---

## Installation

### Prerequisites

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- Optional: [LM Studio](https://lmstudio.ai/) (for NL enhancement)

### Steps

1. Clone or copy this repository into ComfyUI's `custom_nodes` directory:
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/xunying7860/anima-weaver.git
   ```

2. Install dependencies:
   ```bash
   pip install requests
   ```

3. Install the required prerequisite: [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) (mandatory for batch pipelines)
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/yolain/ComfyUI-Easy-Use.git
   ```

4. Restart ComfyUI.

> **Tag library (~215 MB):** a `git clone` install needs `python download_tags.py` to fetch the
> ~215 MB tag library; downloading the Release zip and extracting it is ready to use as-is.
> Without the taglists, raffle (random/hybrid mode) returns empty (the node still runs;
> the prompt only contains the manually-filled parts).

---

## Node Details

<img width="2471" height="1624" alt="image" src="https://github.com/user-attachments/assets/bdb769ca-6b5d-4683-846d-de2bb0a529c2" />



### Anima随机提示词

Fixed behaviour (the 模式 dropdown was removed on 2026-10-16; the three former modes
collapsed into one): **manual slots + raffle (≈400K Danbooru tag entries) are always
merged**, conflicting manual tags take precedence. Whether the LLM runs is decided solely
by “LLM设置 ▸ 自然语言来源” (手动 / LM Studio); with **Tag Ratio = 1.0** the LLM is skipped
entirely (pure tags).

**Tag Ratio** slider controls the tag-to-NL proportion (0.0 = pure NL ↔ 1.0 = pure tags).

LM Studio NL enhancement: calls a local LLM to convert tags into fluent English descriptions.

**Built-in random seed:** the node now has a built-in `随机种子` widget (`control_after_generate`,
randomize/increment). `0` = random internally each run; `>0` = deterministic reproduction.
In batch mode a connected `种子串` takes over (the built-in seed steps aside); with only
`批量数量` set, the built-in seed becomes a **parent seed** deriving N reproducible child seeds
(the old `批量数量` used `random.randint` — the same parameters produced a different batch every run).

| | Built-in seed (widget) | 种子串 (input port, under 高级 ▸ 批量) |
|---|------------------------|--------------------------------------|
| Source | The node's own INT control, `control_after_generate=True` | External 批量种子 / bus split output, multiline |
| Value | `0` = random internally each run; `>0` = deterministic | One seed per line |
| Single-shot mode | The only random source: drives raffle / slot sampling / artist sub-stream | Not connected |
| Batch: 种子串 connected | **Does not participate** (seed string takes over per line, same as old behavior) | One independent seed per line |
| Batch: only 批量数量 set | Upgraded to a **parent seed**: derives N reproducible child seeds | Not connected |
| Priority | 种子串 non-empty → built-in seed steps aside | Takes over when non-empty |

**Two-level groups:** widgets are organized in two collapsible levels (top-level groups:
标签槽位 / 过滤控制 / 高级; four second-level groups hang under 高级):

```
[top-level, always visible]
  标签比例 · 随机种子 (built-in widget, randomize / increment)
▸ 标签槽位            ← top-level group
    人数/身份 外貌 服装 姿势/动作 表情 镜头 场景/环境 细节/氛围 自然语言描述
▸ 过滤控制            ← top-level group
    标签列表必含 过滤标签 排除含标签列表 排除标签分类 通用/争议/敏感/露骨
▸ 高级                ← top-level group (parent)
    画师种子 · 冲突检查
    ▸ LLM设置         ← second-level group (hidden entirely when the parent is off)
        自然语言来源 强制详细自然语言 模型 API地址 API密钥 云端模型名
        上下文长度 自动上下文长度 最大截断长度 生成后卸载
    ▸ 批量            ← second-level group
        批量数量 请求数 最大并发数 + [种子串] port
    ▸ laya判定        ← second-level group
        启用laya门控 过滤质量标签
    ▸ 系统提示词      ← second-level group (new, switchable)
        系统提示词 (hand-editable) 详细NL系统提示词 (hand-editable)
```

`▸ 高级` off → all four second-level groups and their widgets are hidden; `▸ 高级` on →
the four sub-switches appear (all off by default); a sub-group's members show only when its
switch is on.

**System prompt group:** the 系统提示词 forceInput port is now a switchable, hand-editable
multiline widget in the ▸ 系统提示词 group: empty = built-in default prompt; fill it in to
override the default NL system prompt. 详细NL系统提示词 is only used when 强制详细自然语言
is on; empty falls back to the default detailed prompt.

**Batch mode:** When a `种子串` (seed string) from the Batch Seed node is connected, each seed
undergoes independent Raffle + NL generation. The LLM is loaded once, processes all N seeds in
parallel, and unloads on completion.

**Concurrent Batch LLM:** supports `请求数` (request count, default 4) and `最大并发数`
(max concurrency, default 4). In batch mode, the model is loaded once, then N HTTP requests run
concurrently via `ThreadPoolExecutor`. This applies to both local LM Studio and cloud API
endpoints. `自动上下文长度` (auto context length) can be enabled to automatically compute
context window = max_concurrency × 2048 tokens (local models only).

**Conflict checking:** Built-in 23-pair mutual exclusion table. Automatically detects conflicting
tags and removes raffle-sourced conflicts while preserving manually-entered tags.

**Artist (画师种子):** `-1` = random artist, `0` = no artist, `≥1` = fixed artist index.
The artist name is appended to the end of the prompt — there is **no separate artist-string
output** anymore (the old 画师Seed node is removed).

| Parameter | Type | Description |
|-----------|------|-------------|
| 标签比例 | FLOAT | Tag-to-NL ratio (0.0–1.0; LLM skipped at 1.0) |
| 随机种子 | INT | Built-in seed: 0=random each run, >0=deterministic; batch mode steps aside for a connected 种子串, or acts as parent seed when only 批量数量 is set |
| 自然语言来源 | COMBO | 手动 / LM Studio (old English values auto-mapped) |
| 强制详细自然语言 | BOOLEAN | Force NL to be very detailed (512 tokens) |
| 模型 | COMBO | LM Studio model selection (choose `none` to disable LLM and pass through 变化文本) |
| 生成后卸载 | BOOLEAN | Unload model after generation |
| API地址 | STRING | LM Studio / OpenAI-compatible API endpoint |
| API密钥 | STRING | API key (blank for local) |
| 云端模型名 | STRING | Cloud model name (overrides local model when API key is set) |
| 上下文长度 | INT | Context window size (0–262144, default 8192) |
| 自动上下文长度 | BOOLEAN | Auto-compute context = max_concurrency × 2048 (local only) |
| 请求数 | INT | Number of requests to generate (1–128, default 4) |
| 最大并发数 | INT | Max concurrent predictions / parallel threads (1–128, default 4) |
| 最大截断长度 | INT | Max output tokens (0=auto 256/512, 8–1080) |
| 画师种子 | INT | -1=random artist, 0=no artist, ≥1=fixed artist index |
| 冲突检查 | BOOLEAN | Enable conflict detection |
| 系统提示词 | multiline STRING | Custom system prompt (in the ▸ 系统提示词 group, hand-editable; empty = built-in default) |
| 详细NL系统提示词 | multiline STRING | Only used when 强制详细自然语言 is on; empty falls back to the default detailed prompt |

**Outputs:**

| Output | Type | Description |
|--------|------|-------------|
| `生成的提示词` | STRING | Final assembled prompt (artist name already appended at the end) |
| `调试信息` | STRING | Debug info: mode, seed, conflict results |

---

### 随机分辨率选择器

Independent node for random resolution generation.

#### Manual Mode
- Full original functionality preserved, pick from 13 aspect ratios or random

#### Auto Mode (Scoring-based Decision Engine v7)
- With a prompt connected, the node automatically analyzes composition via **7-layer priority normalization + 3D scoring engine**
- No manual rule maintenance needed — handles shot type, person count, pose, and viewpoint automatically

**Built-in random seed:** built-in `随机种子` widget (`control_after_generate`):
`0` = random each run / `>0` = deterministic aspect pick; a connected `种子串` takes over
(the built-in seed is only a fallback when no string is connected). The `随机种子` INT output
is the single seed actually used this run (the old code wrongly returned the width); the
`种子串` STRING output passes through unchanged and is an empty string when nothing is connected.

**Supported Aspect Ratios:** 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9

**Scoring System (Width / Height / Square 3D scoring):**
- **Width factors:** fighting(+3), action(+2), OTS(+3), wide angle(+2~3), aerial(+2~4), small group(+1), large group(+5), multiple(+2), panorama(+5), full body+group(+2), argue(+1), lying(+2,overrides sitting), hug+group(+2), low angle(+1)
- **Height factors:** tall portrait(+4~1), selfie(+4), full body+solo(+2), bust/half body(+1), upper/lower body(+2), sitting(+3), curled(+1)
- **Square factors:** face close-up(+5), focus detail(+5), chibi(+4), american shot(+3), still life(+2), high angle(+1)
- **Combo bonuses:** fighting+action(+1), panorama+wide(+1), full body+action(+1)

**Covered Composition Scenes:**
- Solo / Couple / Small group (3-4) / Large group (5+)
- Standing / Sitting / Lying / Curled up
- Face close-up / Bust / Full body
- Hug / Family group / Fighting / Action / Acrobat
- POV / Over-the-shoulder / Selfie
- Panorama / Wide angle / Aerial
- Still life / Product photography
- Various angles (low/high/eye-level)

**7-Layer Priority Normalization:**
- Layer 0: Compound words first (prevents "face close up" being corrupted by "close up")
- Layer 1: Person count & group
- Layer 2: Shot type & framing
- Layer 3: POV perspective
- Layer 4: Action & pose
- Layer 5: Face & focus
- Layer 6: Scene & environment
- Layer 7: Angle

**Outputs:**
- 宽度/高度 are STRING type (manual=single value, auto=comma-separated multiline)
- Final outputs: 随机种子(INT) + 种子串(STRING) + 宽度(STRING) + 高度(STRING)

**Resolution Calculation:**
- Global min edge 512px, max edge 2048px
- Alignment step 16 (compatible with Illustrious / anima-base DiT)
- Area loss < 3%

---

### 批量种子

Generates N random seeds for batch pipeline consumption (max 4096).
Also an alternative to the core node's built-in seed (for cross-node alignment): connect its
`种子串` output to the `种子串` ports of the prompt/resolution/sampler nodes when the same seed
batch must drive several nodes; otherwise the core node can derive seeds from its built-in seed
+ `批量数量`.

### 同步串行

> Historic section (同步串行). Today this node is **Anima批量合并 (AnimaBatchMerge)** —
> for reference against the old version only.

Merges 7 multiline STRING inputs into a single multiline JSON output (one complete data group per line). Supports row selection. Designed for use with Easy-Use Prompt Line node.

| Parameter | Description |
|-----------|-------------|
| `start_index` | Starting row index |
| `max_rows` | Maximum number of rows to output |
| `remove_empty_lines` | Whether to filter out empty lines |

**Output format (one JSON object per line):**
```json
{"种子":"42","提示词":"1girl,solo...","画师":"@artist","分辨率":"1024x768","反推":"A girl...","宽度":"1024","高度":"768"}
```

### 串行拆分

> Historic section (同步串行). Today this node is **Anima批量合并 (AnimaBatchMerge)** —
> for reference against the old version only.

Receives a single JSON line from the Prompt Line node and splits it into 7 independent typed outputs:

| Output | Type |
|--------|------|
| 种子 | INT |
| 提示词 | STRING |
| 画师 | STRING |
| 分辨率 | STRING |
| 反推 | STRING |
| 宽度 | INT |
| 高度 | INT |

---

## Batch Pipeline Architecture

```
Batch Seed(N)   ← optional: the core node's built-in seed + 批量数量 can derive N reproducible child seeds
  │  Seed String STRING (N lines)
  ├──→ 随机分辨率选择器 → Width/Height Strings
  ├──→ Anima随机提示词 → Prompt String (artist already merged into the prompt, no separate column)
  │
  ▼
Anima批量合并 ──JSON lines──→ Prompt Line (Easy-Use) ──single line──→ Anima批量拆分
                                                          │ Seed (INT) → KSampler
                                                          │ Width (INT) → Empty Latent
                                                          │ Height (INT) → Empty Latent
                                                          │ Prompt (STR) → CLIP
```

Each seed undergoes independent Raffle + NL generation. The LLM is loaded once, processes N seeds
in parallel (configurable via `请求数` and `最大并发数`, default 4 each), and unloads on
completion — all seeds are then fed to the sampler in a single batch, minimizing VRAM overhead.
The seed string can now be derived from the core node's built-in seed, so an external 批量种子
node is no longer required; connect one when the same seed batch must align across nodes
(prompt/resolution/sampler).

---

## Workflows

Workflow files are located in the `workflows/` directory (6 → 2 in this release):

| File | Description |
|------|-------------|
| `anima双采-随机提示词.json` | Full image generation: batch seeds → prompt/resolution → batch bus → dual samplers → save |
| `随机提示词-批量.json` | Prompt strings + per-channel display only, no sampling |

The old `随机提示词润色.json` / `图片反推（自然语言）.json` / `随机提示词编织器-单次.json` /
`anima批量自动打标.json` are removed — recover them from the `pre-4node-20261016` tag if needed.

> Dependency note: the decorative helper nodes in `anima双采-随机提示词.json` come from
> common third-party packs (ComfyUI-Custom-Scripts: Text Multiline / Int / ShowText;
> ComfyRoll: CR Text). Missing packs only red-mark those nodes — the four Anima nodes
> themselves have zero third-party dependencies.

---

## Recommended Models

### NL Enhancement (Anima随机提示词)

| Model | Quant | Size | Download |
|-------|-------|------|----------|
| L3.2-Rogue-Creative-Uncensored-Abliterated-7B | Q6_K | 5.8GB | [Download](https://hf-mirror.com/DavidAU/L3.2-Rogue-Creative-Instruct-Uncensored-Abliterated-7B-GGUF) |
| Yi-1.5-9B-Chat-abliterated | Q6_K | 6.8GB | [Download](https://hf-mirror.com/byroneverson/Yi-1.5-9B-Chat-16K-abliterated) |
| WizardLM-1.0-Uncensored-Llama2-13B | Q4_K_M | 7.4GB | [Download](https://hf-mirror.com/TheBloke/WizardLM-1.0-Uncensored-Llama2-13B-GGUF) |
| Qwen2.5-14B-Instruct-abliterated | Q4_K_M | 8.4GB | [Download](https://hf-mirror.com/bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF) |

### Cloud API Compatible Models

These nodes support any OpenAI-compatible API provider (SiliconFlow, DeepSeek, OpenAI, etc.).
Set `API地址` to the provider's base URL, provide an `API密钥`, and specify the `云端模型名`.
The `enable_thinking` parameter is automatically omitted for cloud API calls.

---

## Tag Data Sources

- **Anima tag library** — 2,176 tags extracted from `anima提示词规则.md`, organized into 9 categories
- **Danbooru categorized tags** — `categorized_tags.txt` (59,575 entries), sourced from [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle)
- **Raffle tag lists** — 4 tiered taglist files (~100K lines each, ~215 MB total; run `python download_tags.py` after a `git clone`), same source
- **Artist index** — `Anima2B_Artist_Index_59k.txt` (~59K artists)

---

## Dependencies

| Dependency | Purpose | Required |
|------------|---------|----------|
| [LM Studio](https://lmstudio.ai/) | Local LLM inference server | NL enhancement only |
| [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | Prompt Line node (list preview) | **Mandatory** for batch pipelines (install as prerequisite) |

---

## Credits

- **Danbooru tag data:** Sourced from [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle) by rainlizard
- **ComfyUI integration:** Standard ComfyUI custom node interface
- **Artist index:** Built from Danbooru tag data

---

## License

MIT
