# Anima Weaver

<p align="right">
  <a href="README_CN.md">中文</a> | <b>English</b>
</p>

A ComfyUI custom node package for structured AI image prompt assembly. Supports tag/NL hybrid output, batch pipelines, image captioning / prompt refinement, random artist selection, and random resolution generation.

---

## Node Reference

| Node | Category | Description |
|------|----------|-------------|
| **Anima随机提示词** | Anima Weaver | Core node: assembles tags → NL → complete prompt |
| **Anima反推** | Anima Weaver | VL model-based image captioning / prompt refinement |
| **随机分辨率选择器** | Anima Weaver | Random aspect ratio & resolution generator |
| **提示词槽位** | Anima Weaver | Manual tag input slots |
| **底部控制** | Anima Weaver | Raffle tag filtering controls |
| **画师Seed** | Anima Weaver / Seed | Artist selector (random / none / fixed) |
| **批量种子** | Anima Weaver / Seed | N-seed generator for batch pipelines |
| **同步串行** | Anima Weaver / Batch | Merges 7 channels into JSON-per-line output |
| **串行拆分** | Anima Weaver / Batch | Splits one JSON line back to 7 typed outputs (INT + STRING) |
| **Anima加载图像** | Anima Weaver | Load images from folder → IMAGE list + MASK + file paths |
| **Anima列表转多行** | Anima Weaver | Merge batch text items into multiline STRING (INPUT_IS_LIST) |

---

## Installation

### Prerequisites

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- Optional: [LM Studio](https://lmstudio.ai/) (for NL enhancement / Image Caption node)

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

---

## Node Details

<img width="2471" height="1624" alt="image" src="https://github.com/user-attachments/assets/bdb769ca-6b5d-4683-846d-de2bb0a529c2" />



### Anima随机提示词

Three operation modes:

| Mode | Description |
|------|-------------|
| `manual` | User fills 8 tag slots manually, output ordered by Anima slot specification |
| `random` | Randomly samples ~400K Danbooru tag entries, auto-classifies into slots |
| `hybrid` | Raffle fills slots + manual tags appended; conflicting manual tags take precedence |

**Tag Ratio** slider controls the tag-to-NL proportion (0.0 = pure NL ↔ 1.0 = pure tags).

LM Studio NL enhancement: calls a local LLM to convert tags into fluent English descriptions.

**系统提示词** (optional forceInput port, top-left): When connected, overrides the default NL generation system prompt. Behaves identically to the Image Caption node's custom prompt.

**Batch mode:** When a `种子串` (seed string) from the Batch Seed node is connected, each seed undergoes independent Raffle + NL generation. The LLM is loaded once, processes all N seeds in parallel, and unloads on completion.

**Concurrent Batch LLM:** Both Anima随机提示词 and Anima反推 support `请求数` (request count, default 4) and `最大并发数` (max concurrency, default 4). In batch mode, the model is loaded once, then N HTTP requests run concurrently via `ThreadPoolExecutor`. This applies to both local LM Studio and cloud API endpoints. `自动上下文长度` (auto context length) can be enabled to automatically compute context window = max_concurrency × 2048 tokens (local models only).

**Conflict checking:** Built-in 23-pair mutual exclusion table. Automatically detects conflicting tags and removes raffle-sourced conflicts while preserving manually-entered tags.

| Parameter | Type | Description |
|-----------|------|-------------|
| 模式 | COMBO | manual / random / hybrid |
| 标签比例 | FLOAT | Tag-to-NL ratio (0.0–1.0) |
| 场景类型 | COMBO | Scene category for raffle sampling |
| 自然语言来源 | COMBO | manual / lm_studio |
| 强制详细自然语言 | BOOLEAN | Force NL to be very detailed (512 tokens) |
| 模型 | COMBO | LM Studio model selection |
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

**Outputs:**

| Output | Type | Description |
|--------|------|-------------|
| `生成的提示词` | STRING | Final assembled prompt |
| `调试信息` | STRING | Debug info: mode, seed, conflict results |
| `画师串` | STRING | Multiline artists (batch mode) |
| `分辨率串` | STRING | Multiline resolutions (batch mode) |
| `反推串` | STRING | Multiline captions (batch mode) |

---

### Anima反推

When an image input is connected, invokes a VL (vision-language) model for image captioning. Without an image, operates in prompt refinement mode.

**Prompt priority:** Custom system prompt > Image connected → caption mode > No image → refinement mode

**Batch mode:** Accepts `种子串` for per-seed independent generation (no image input in batch mode). LLM loads once, processes N seeds concurrently, unloads on completion.

**Fixed prefix:** The `固定前缀` parameter lets you prepend a string (e.g., `masterpiece, best quality`) to every generated description.

**Save as txt:** Enable `保存为txt` to save each description as a `.txt` file alongside the source image.

**Align to multiple:** The `对齐倍数` parameter (default 14 for Qwen-VL series) ensures image dimensions are aligned to the specified multiple, preventing vision encoder failures.

| Parameter | Type | Description |
|-----------|------|-------------|
| 模型 | COMBO | LM Studio model selection |
| API地址 | STRING | LM Studio / OpenAI-compatible API endpoint |
| API密钥 | STRING | API key (blank for local) |
| 云端模型名 | STRING | Cloud vision model name |
| 上下文长度 | INT | Context window size (0–262144, default 8192) |
| 自动上下文长度 | BOOLEAN | Auto-compute context = max_concurrency × 2048 (local only) |
| 最大截断长度 | INT | Max output tokens (128–1024, default 1024) |
| 生成后卸载 | BOOLEAN | Unload model after generation |
| 请求数 | INT | Number of requests to generate (1–128, default 4) |
| 最大并发数 | INT | Max concurrent predictions (1–128, default 4) |
| 固定前缀 | STRING | Custom prefix prepended to each description |
| 图片路径 | STRING | Folder path to batch-process images (lower priority than 种子串) |
| 对齐倍数 | INT | Align image dimensions to this multiple (default 14) |
| 保存为txt | BOOLEAN | Save each description as a `.txt` file next to the source image |

**Outputs:**

| Output | Type | Description |
|--------|------|-------------|
| `描述文本` | STRING | Generated caption / refined text |
| `提示词串` | STRING | Batch passthrough |
| `画师串` | STRING | Batch passthrough |
| `分辨率串` | STRING | Batch passthrough |

---

### 随机分辨率选择器

Independent node for random resolution generation.

| Parameter | Type | Description |
|-----------|------|-------------|
| `随机画幅` | BOOLEAN | Randomly selects from 8 aspect ratios |
| `百万像素` | FLOAT | Target megapixels; automatically computes nearest width/height |
| `固定比例` | COMBO | Fixed aspect ratio when random is disabled |
| `对齐到` | INT | Align dimensions to this multiple (1–256, default 8) |
| `随机种子` | INT (forceInput) | Optional external seed input |
| `种子串` | STRING | Accepts batch seeds for per-seed independent resolutions |

**Outputs:**

| Output | Type | Description |
|--------|------|-------------|
| `宽度` | INT | Computed width |
| `高度` | INT | Computed height |
| `分辨率` | STRING | Formatted as `1024x768` |
| `分辨率串` | STRING | Multiline resolutions (batch mode) |
| `宽度串` | STRING | Multiline width values (batch mode) |
| `高度串` | STRING | Multiline height values (batch mode) |

---

### 画师Seed

Artist selection node backed by `Anima2B_Artist_Index_59k.txt` (~59K indexed artists).

| Parameter | Type | Description |
|-----------|------|-------------|
| `artist_seed` | INT | `-1` = random artist, `0` = no artist (skip), `≥1` = fixed artist by index |
| `种子串` | STRING | Accepts batch seeds for per-seed independent artist selection |

**Outputs:** `artist_seed` (INT) + `状态` (STRING, formatted as `[index] @artist_name`)

---

### 批量种子

Generates N random seeds for batch pipeline consumption (max 4096).

### 同步串行

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
Batch Seed(N)
  │  Seed String STRING (N lines)
  ├──→ 画师Seed → Artist String
  ├──→ 随机分辨率选择器 → Resolution String
  ├──→ Anima随机提示词 → Prompt/Artist/Res/Caption Strings
  │
  ▼
同步串行 ──Merge JSON──→ Prompt Line (Easy-Use) ──→ 串行拆分
                                                          │ Seed (INT) → KSampler
                                                          │ Width (INT) → Empty Latent
                                                          │ Height (INT) → Empty Latent
                                                          │ Prompt (STR) → CLIP
```

Each seed undergoes independent Raffle + NL generation. The LLM is loaded once, processes N seeds in parallel (configurable via `请求数` and `最大并发数`, default 4 each), and unloads on completion — all seeds are then fed to the sampler in a single batch, minimizing VRAM overhead.

---

## Recommended Models

### NL Enhancement (Anima随机提示词)

| Model | Quant | Size | Download |
|-------|-------|------|----------|
| L3.2-Rogue-Creative-Uncensored-Abliterated-7B | Q6_K | 5.8GB | [Download](https://hf-mirror.com/DavidAU/L3.2-Rogue-Creative-Instruct-Uncensored-Abliterated-7B-GGUF) |
| Yi-1.5-9B-Chat-abliterated | Q6_K | 6.8GB | [Download](https://hf-mirror.com/byroneverson/Yi-1.5-9B-Chat-16K-abliterated) |
| WizardLM-1.0-Uncensored-Llama2-13B | Q4_K_M | 7.4GB | [Download](https://hf-mirror.com/TheBloke/WizardLM-1.0-Uncensored-Llama2-13B-GGUF) |
| Qwen2.5-14B-Instruct-abliterated | Q4_K_M | 8.4GB | [Download](https://hf-mirror.com/bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF) |

### Image Caption (Anima反推)

| Model | Quant | Size | Download |
|-------|-------|------|----------|
| Huihui-Qwen3-VL-4B-Instruct-abliterated | Q6_K | 3.2GB | [Download](https://hf-mirror.com/huihui-ai/Huihui-Qwen3-VL-4B-Instruct-abliterated-GGUF) |
| Huihui-Qwen3-VL-8B-Instruct-abliterated | Q6_K | 5.8GB | [Download](https://hf-mirror.com/huihui-ai/Huihui-Qwen3-VL-8B-Instruct-abliterated-GGUF) |

### Cloud API Compatible Models

These nodes support any OpenAI-compatible API provider (SiliconFlow, DeepSeek, OpenAI, etc.). Set `API地址` to the provider's base URL, provide an `API密钥`, and specify the `云端模型名`. The `enable_thinking` parameter is automatically omitted for cloud API calls.

---

## Tag Data Sources

- **Anima tag library** — 2,176 tags extracted from `anima提示词规则.md`, organized into 9 categories
- **Danbooru categorized tags** — `categorized_tags.txt` (59,575 entries), sourced from [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle)
- **Raffle tag lists** — 4 tiered taglist files (~100K lines each), same source
- **Artist index** — `Anima2B_Artist_Index_59k.txt` (~59K artists)

---

## Dependencies

| Dependency | Purpose | Required |
|------------|---------|----------|
| [LM Studio](https://lmstudio.ai/) | Local LLM inference server | NL enhancement / caption mode only |
| [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | Prompt Line node (list preview) | **Mandatory** for batch pipelines (install as prerequisite) |

---

## Credits

- **Node implementation:** DeepSeek V4 Flash
- **Danbooru tag data:** Sourced from [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle) by rainlizard
- **ComfyUI integration:** Standard ComfyUI custom node interface
- **Artist index:** Built from Danbooru tag data

---

## License

MIT
