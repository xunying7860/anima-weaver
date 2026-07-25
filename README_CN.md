# Anima Weaver

<p align="right">
  <b>中文</b> | <a href="README.md">English</a>
</p>

一个 ComfyUI 自定义节点包，基于结构化方式组装 AI 图像生成提示词，支持标签/自然语言混合输出、批量管线、图像反推/提示词润色、随机画师与随机分辨率。

---

## 节点列表

| 节点 | 分类 | 用途 |
|------|------|------|
| **Anima随机提示词** | Anima Weaver | 主节点：组装标签 → NL → 完整提示词 |
| **Anima反推** | Anima Weaver | VL 模型图像反推 / 润色扩写 |
| **随机分辨率选择器** | Anima Weaver | 随机生成宽高比/分辨率文本 |
| **提示词槽位** | Anima Weaver | 手动输入标签槽位 |
| **底部控制** | Anima Weaver | Raffle标签过滤控制 |
| **画师Seed** | Anima Weaver / Seed | 画师选择（随机/无/固定） |
| **批量种子** | Anima Weaver / Seed | 生成 N 个种子（上限 4096） |
| **同步串行** | Anima Weaver / Batch | 7 路输入合并为 JSON 多行输出 |
| **串行拆分** | Anima Weaver / Batch | JSON 行拆回 7 路（INT + STRING） |

---

## 安装

### 前提

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- 可选：[LM Studio](https://lmstudio.ai/)（用于 NL 增强模式/反推节点）

### 步骤

1. 克隆或复制本仓库到 ComfyUI 的 `custom_nodes` 目录：
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/xunying7860/anima-weaver.git
   ```

2. 安装依赖：
   ```bash
   pip install requests
   ```

3. 安装前置依赖：[ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use)（批量管线必需）
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/yolain/ComfyUI-Easy-Use.git
   ```

4. 重启 ComfyUI。

---

## 节点详解

<img width="2471" height="1624" alt="image" src="https://github.com/user-attachments/assets/523fff97-7b53-4f9c-ad8a-041d82918363" />


### Anima随机提示词

三种工作模式：

| 模式 | 说明 |
|------|------|
| `manual`（手动） | 手填 8 个插槽标签输出 |
| `random`（随机） | 从 40 万条 Danbooru taglist 中随机抽取 |
| `hybrid`（混合） | 随机填充 + 手填标签追加，互斥时保留手填的 |

**标签比例**滑块控制输出中标签与自然语言的比例（0.0=纯自然语言 ↔ 1.0=纯标签）。

支持 LM Studio NL 增强，调用本地 LLM 将标签转为英文描述。

**系统提示词**（左上角可选 forceInput 端口）：接入后覆盖默认 NL 生成提示词，逻辑同反推节点。

**批量模式：** 接入 `种子串`（批量种子节点的输出）后，每种子独立 Raffle + NL 生成。LLM 加载一次，然后 N 组请求并发执行，全部完成后按需卸载。

**并发批量 LLM：** Anima随机提示词和 Anima反推均支持 `请求数`（默认 4）和 `最大并发数`（默认 4）参数。模型加载一次，然后 N 个线程同时发 HTTP 请求，本地 LM Studio 和云端 API 均适用。`自动上下文长度` 开启后自动计算上下文 = 最大并发数 × 2048（仅本地模型有效）。

**冲突检查：** 内置 23 对互斥表，自动检测冲突标签并移除 Raffle 来源的冲突项，保留手动标签。

| 参数 | 类型 | 说明 |
|------|------|------|
| 模式 | 下拉 | manual / random / hybrid |
| 标签比例 | 滑块 | 标签与自然语言比例（0.0–1.0） |
| 场景类型 | 下拉 | Raffle 采样场景分类 |
| 自然语言来源 | 下拉 | manual / lm_studio |
| 强制详细自然语言 | 开关 | 强制 NL 非常详细（512 tokens） |
| 模型 | 下拉 | LM Studio 模型选择 |
| 生成后卸载 | 开关 | 生成后卸载模型 |
| API地址 | 文本 | LM Studio / OpenAI 兼容 API 地址 |
| API密钥 | 文本 | API 密钥（本地留空） |
| 云端模型名 | 文本 | 云端模型名（填密钥后覆盖本地模型） |
| 上下文长度 | 整数 | 上下文窗口大小（0–262144，默认 8192） |
| 自动上下文长度 | 开关 | 自动计算上下文 = 最大并发数 × 2048（仅本地） |
| 请求数 | 整数 | 生成请求数量（1–128，默认 4） |
| 最大并发数 | 整数 | 最大并发预测/线程数（1–128，默认 4） |
| 最大截断长度 | 整数 | 最大输出 token（0=自动 256/512，8–1080） |
| 画师种子 | 整数 | -1=随机画师，0=无画师，≥1=固定画师序号 |
| 冲突检查 | 开关 | 开启冲突检测 |

**输出：**

| 输出 | 类型 | 说明 |
|------|------|------|
| `生成的提示词` | STRING | 最终组合的提示词 |
| `调试信息` | STRING | 模式、种子、冲突检查结果等 |
| `画师串` | STRING | 批量模式下的多行画师 |
| `分辨率串` | STRING | 批量模式下的多行分辨率 |
| `反推串` | STRING | 批量模式下的多行反推 |

---

### Anima反推

接入图像时调用 VL 模型进行图像反推描述；不接图像时使用润色扩写提示词。

**提示词优先级：** 自定义系统提示词 > 有图→图像反推 > 无图→润色扩写

**批量模式：** 接 `种子串` 后每种子独立生成描述（不接图像），LLM 加载一次，N 组并发执行，跑完后按需卸载。

**固定前缀：** `固定前缀` 参数可在每段描述前加上固定文本（如 `masterpiece, best quality`）。

**保存为 txt：** 启用 `保存为txt` 后将每张图的描述保存为同名的 `.txt` 文件到图片所在目录。

**对齐倍数：** `对齐倍数` 参数（默认 14，适用 Qwen-VL 系列）确保图片宽高对齐到指定倍数，防止视觉编码器崩溃。

| 参数 | 类型 | 说明 |
|------|------|------|
| 模型 | 下拉 | LM Studio 模型选择 |
| API地址 | 文本 | LM Studio / OpenAI 兼容 API 地址 |
| API密钥 | 文本 | API 密钥（本地留空） |
| 云端模型名 | 文本 | 云端视觉模型名 |
| 上下文长度 | 整数 | 上下文窗口大小（0–262144，默认 8192） |
| 自动上下文长度 | 开关 | 自动计算上下文 = 最大并发数 × 2048（仅本地） |
| 最大截断长度 | 整数 | 最大输出 token（128–1024，默认 1024） |
| 生成后卸载 | 开关 | 生成后卸载模型 |
| 请求数 | 整数 | 生成请求数量（1–128，默认 4） |
| 最大并发数 | 整数 | 最大并发预测数（1–128，默认 4） |
| 固定前缀 | 文本 | 每段描述前添加的固定前缀 |
| 图片路径 | 文本 | 批处理图片文件夹路径（优先级低于种子串） |
| 对齐倍数 | 整数 | 将图片宽高对齐到该值的倍数（默认 14） |
| 保存为txt | 开关 | 将每张图的描述保存为同目录下的 `.txt` 文件 |

**输出：**

| 输出 | 类型 | 说明 |
|------|------|------|
| `描述文本` | STRING | 生成的描述/润色文本 |
| `提示词串` | STRING | 批量透传 |
| `画师串` | STRING | 批量透传 |
| `分辨率串` | STRING | 批量透传 |

---

### 随机分辨率选择器

生成随机分辨率的独立节点。

| 参数 | 类型 | 说明 |
|------|------|------|
| `随机画幅` | 开关 | 从 8 种比例中随机选择 |
| `百万像素` | 滑块 | 目标像素数，自动计算接近的宽高 |
| `固定比例` | 下拉 | 随机画幅关闭时使用的固定比例 |
| `对齐到` | 整数 | 将宽高对齐到该值的倍数（1–256，默认 8） |
| `随机种子` | INT (forceInput) | 可选外部种子输入 |
| `种子串` | STRING | 接入批量种子，每种子独立分辨率 |

**输出：**

| 输出 | 类型 | 说明 |
|------|------|------|
| `宽度` | INT | 计算后的宽度 |
| `高度` | INT | 计算后的高度 |
| `分辨率` | STRING | 格式 `1024x768` |
| `分辨率串` | STRING | 批量模式多行 |
| `宽度串` | STRING | 批量模式多行宽度值 |
| `高度串` | STRING | 批量模式多行高度值 |

---

### 画师Seed

画师选择节点，基于 `Anima2B_Artist_Index_59k.txt`（约 5.9 万画师索引）。

| 参数 | 类型 | 说明 |
|------|------|------|
| `artist_seed` | 整数 | -1=随机画师，0=无画师，≥1=对应序号画师 |
| `种子串` | STRING | 接入批量种子，每种子独立抽画师 |

**输出：** `artist_seed`(INT) + `状态`(STRING `[序号] @画师名`)

---

### 批量种子

生成 N 个随机种子供批量管线使用（上限 4096）。

### 同步串行

将 7 路多行 STRING 合并为 JSON 多行（每行一个完整的数据组），支持行选择。配合提示词行节点使用。

| 参数 | 说明 |
|------|------|
| `start_index` | 起始行号 |
| `max_rows` | 最大输出行数 |
| `remove_empty_lines` | 是否移除空行 |

**输出格式（每行一个 JSON）：**
```json
{"种子":"42","提示词":"1girl,solo...","画师":"@artist","分辨率":"1024x768","反推":"A girl...","宽度":"1024","高度":"768"}
```

### 串行拆分

接收提示词行输出的单个 JSON 行，拆回 7 路独立信号：

| 输出 | 类型 |
|------|------|
| 种子 | INT |
| 提示词 | STRING |
| 画师 | STRING |
| 分辨率 | STRING |
| 反推 | STRING |
| 宽度 | INT |
| 高度 | INT |

---

## 批量管线架构

```
批量种子(N个)
  │ 种子串 STRING (N行)
  ├──→ 画师Seed → 画师串
  ├──→ 随机分辨率选择器 → 分辨率串
  ├──→ Anima随机提示词 → 提示词串/画师串/分辨率串/反推串
  │
  ▼
同步串行 ──合并JSON──→ 提示词行(easy-use) ──→ 串行拆分
                                                          │ 种子(INT) → KSampler
                                                          │ 宽度(INT) → 空Latent
                                                          │ 高度(INT) → 空Latent
                                                          │ 提示词(STR) → CLIP
```

每种子独立 Raffle + NL，LLM 加载一次，N 组并发执行（通过 `请求数` 和 `最大并发数` 控制，默认均为 4），跑完后按需卸载，统一进入采样器采样，不额外占用显存。

---

## 工作流

工作流文件位于 `workflows/` 目录：

| 文件 | 说明 |
|------|------|
| `anima批量自动打标.json` | 批量图片自动打标工作流（WD14 + Anima反推 + 保存txt） |

## 推荐模型

### NL 增强（Anima随机提示词）

| 模型 | 量化 | 体积 | 下载 |
|------|------|------|------|
| L3.2-Rogue-Creative-Uncensored-Abliterated-7B | Q6_K | 5.8GB | [下载](https://hf-mirror.com/DavidAU/L3.2-Rogue-Creative-Instruct-Uncensored-Abliterated-7B-GGUF) |
| Yi-1.5-9B-Chat-abliterated | Q6_K | 6.8GB | [下载](https://hf-mirror.com/byroneverson/Yi-1.5-9B-Chat-16K-abliterated) |
| WizardLM-1.0-Uncensored-Llama2-13B | Q4_K_M | 7.4GB | [下载](https://hf-mirror.com/TheBloke/WizardLM-1.0-Uncensored-Llama2-13B-GGUF) |
| Qwen2.5-14B-Instruct-abliterated | Q4_K_M | 8.4GB | [下载](https://hf-mirror.com/bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF) |

### 图像反推（Anima反推）

| 模型 | 量化 | 体积 | 下载 |
|------|------|------|------|
| Huihui-Qwen3-VL-4B-Instruct-abliterated | Q6_K | 3.2GB | [下载](https://hf-mirror.com/huihui-ai/Huihui-Qwen3-VL-4B-Instruct-abliterated-GGUF) |
| Huihui-Qwen3-VL-8B-Instruct-abliterated | Q6_K | 5.8GB | [下载](https://hf-mirror.com/huihui-ai/Huihui-Qwen3-VL-8B-Instruct-abliterated-GGUF) |

### 云端 API 兼容

所有节点均支持任意兼容 OpenAI 格式的 API 提供商（SiliconFlow、DeepSeek、OpenAI 等）。填写 `API地址`、`API密钥`、`云端模型名` 即可使用。调用云端 API 时自动跳过 `enable_thinking` 参数。

---

## 标签库来源

- **Anima 标签库** — 从 `anima提示词规则.md` 提取的 2,176 个标签，按 9 个分类保存
- **Danbooru 分类标签** — `categorized_tags.txt`（59,575 条），来自 [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle)
- **Raffle taglist** — 4 个分级 taglist 文件（各 10 万行），同上来源
- **画师索引** — `Anima2B_Artist_Index_59k.txt`（约 5.9 万画师）

---

## 依赖

| 依赖 | 用途 | 必需 |
|------|------|------|
| [LM Studio](https://lmstudio.ai/) | 本地 LLM 推理服务 | 仅 NL 增强/反推模式 |
| [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | 提示词行节点（列表预览） | **批量管线必需**，作为前置节点安装 |

---

## Credits

- **节点编写：** DeepSeek V4 Flash
- **Danbooru 标签数据：** 来自 [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle)（rainlizard）
- **ComfyUI 集成：** 标准 ComfyUI 自定义节点接口
- **画师索引：** 基于 Danbooru 标签数据构建

---

## License

MIT
