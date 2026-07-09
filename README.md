# Anima Weaver — 提示词编织器

一个 ComfyUI 自定义节点包，基于结构化方式组装 AI 图像生成提示词，支持标签/自然语言混合输出、批量管线、图像反推/润色、随机画师与随机分辨率。

**声明：** 本节点由 DeepSeek V4 Flash 编写。

---

## 节点列表

| 节点 | 分类 | 用途 |
|------|------|------|
| **提示词编织器** | Anima Weaver | 主节点：组装标签 → NL → 完整提示词 |
| **图片反推描述** | Anima Weaver | 图像反推 / 无图时润色扩写 |
| **随机分辨率选择器** | Anima Weaver | 随机生成宽高比/分辨率文本 |
| **提示词槽位** | Anima Weaver | 手动输入标签槽位 |
| **底部控制** | Anima Weaver | 底部标签过滤控制 |
| **画师Seed** | Anima Weaver / Seed | 画师选择（随机/固定） |
| **批量种子** | Anima Weaver / Seed | 生成 N 个批量种子 |
| **同步串行** | Anima Weaver / Batch | 7 路输入合并为 JSON 多行输出 |
| **串行拆分** | Anima Weaver / Batch | JSON 行拆回 7 路（INT + STRING） |
| **STRING转INT** | Anima Weaver / Utils | 多行 STRING 取第一行转 INT |

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

### 提示词编织器

三种工作模式：

| 模式 | 说明 |
|------|------|
| `manual`（手动） | 手填 8 个插槽标签，按 Anima 规则排序输出 |
| `random`（随机） | 从 40 万条 Danbooru taglist 中随机抽取，自动分类到插槽 |
| `hybrid`（混合） | Raffle 随机填充 + 手填标签追加，互斥时保留手填的 |

**标签比例**滑块控制输出中标签与自然语言的比例（0.0=纯自然语言 ↔ 1.0=纯标签）。

支持 LM Studio NL 增强，调用本地 LLM 将标签转为英文描述。

**批量模式：** 接入 `种子串`（批量种子节点的输出）后，每种子独立 Raffle + NL 生成，LLM 加载一次跑完 N 组后按需卸载。

**冲突检查：** 内置 23 对互斥表，自动检测冲突标签并移除 Raffle 来源的冲突项，保留手动标签。

**输出：**

| 输出 | 类型 | 说明 |
|------|------|------|
| `生成的提示词` | STRING | 最终组合的提示词 |
| `调试信息` | STRING | 模式、种子、冲突检查结果等 |
| `提示词串` | STRING | 批量模式下的多行提示词 |
| `画师串` | STRING | 批量模式下的多行画师 |
| `分辨率串` | STRING | 批量模式下的多行分辨率 |
| `反推串` | STRING | 批量模式下的多行反推 |

---

### 图片反推描述

接入图像时调用 VL 模型进行图像反推描述；不接图像时使用润色扩写提示词。

**提示词优先级：** 自定义系统提示词 > 有图→图像反推 > 无图→润色扩写

**批量模式：** 接 `种子串` 后每种子独立生成描述（不接图像），LLM 加载一次跑 N 组后按需卸载。

**输出：**

| 输出 | 类型 | 说明 |
|------|------|------|
| `描述文本` | STRING | 生成的描述/润色文本 |
| `提示词串` | STRING | 批量透传 |
| `画师串` | STRING | 批量透传 |
| `分辨率串` | STRING | 批量透传 |
| `反推串` | STRING | 批量模式下的多行反推描述 |

---

### 随机分辨率选择器

生成随机分辨率的独立节点。

| 参数 | 类型 | 说明 |
|------|------|------|
| `随机画幅` | 开关 | 从 8 种比例中随机选择 |
| `百万像素` | 滑块 | 目标像素数，自动计算接近的宽高 |
| `固定比例` | 下拉 | 随机画幅关闭时使用的固定比例 |
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

画师选择节点，基于 `Anima2B_Artist_59k_numbered.txt`（约 5.9 万画师索引）。

| 参数 | 类型 | 说明 |
|------|------|------|
| `artist_seed` | 整数 | 0=随机画师，非0=对应序号画师 |
| `种子串` | STRING | 接入批量种子，每种子独立抽画师 |

**输出：** `artist_seed`(INT) + `状态`(STRING `[序号] @画师名`)

---

### 批量种子

生成 N 个随机种子供批量管线使用。

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

### STRING转INT

多行 STRING 取第一行转为 INT。

---

## 批量管线架构

```
批量种子(N=3)
  │ 种子串 STRING (3行)
  ├──→ 画师Seed → 画师串
  ├──→ 随机分辨率 → 分辨率串
  ├──→ 主节点 → 提示词串/画师串/分辨率串/反推串
  │
  ▼
同步串行 ──合并JSON──→ 提示词行(easy-use) ──预览N格──→ 串行拆分
                                                          │ 种子(INT) → KSampler
                                                          │ 宽度(INT) → 空Latent
                                                          │ 高度(INT) → 空Latent
                                                          │ 提示词(STR) → CLIP
```

每种子独立 Raffle + NL，LLM 加载一次跑 N 组，跑完后按需卸载。

---

## 推荐模型

### NL 增强（提示词编织器）

| 模型 | 量化 | 体积 | 备注 |
|------|------|------|------|
| L3.2-Rogue-Creative-Uncensored-Abliterated-7B | Q6_K | 5.8GB | [下载](https://hf-mirror.com/DavidAU/L3.2-Rogue-Creative-Instruct-Uncensored-Abliterated-7B-GGUF) |
| Yi-1.5-9B-Chat-abliterated | Q6_K | 6.8GB | [下载](https://hf-mirror.com/byroneverson/Yi-1.5-9B-Chat-16K-abliterated) |
| WizardLM-1.0-Uncensored-Llama2-13B | Q4_K_M | 7.4GB | [下载](https://hf-mirror.com/TheBloke/WizardLM-1.0-Uncensored-Llama2-13B-GGUF) |
| Qwen2.5-14B-Instruct-abliterated | Q4_K_M | 8.4GB | [下载](https://hf-mirror.com/bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF) |

### 图像反推（图片反推描述）

| 模型 | 量化 | 体积 | 下载 |
|------|------|------|------|
| Huihui-Qwen3-VL-4B-Instruct-abliterated | Q6_K | 3.2GB | [下载](https://hf-mirror.com/huihui-ai/Huihui-Qwen3-VL-4B-Instruct-abliterated-GGUF) |
| Huihui-Qwen3-VL-8B-Instruct-abliterated | Q6_K | 5.8GB | [下载](https://hf-mirror.com/huihui-ai/Huihui-Qwen3-VL-8B-Instruct-abliterated-GGUF) |

---

## 标签库来源

- **Anima 标签库** — 从 `anima提示词规则.md` 提取的 2,176 个标签，按 9 个分类保存
- **Danbooru 分类标签** — `categorized_tags.txt`（59,575 条），来自 [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle)
- **Raffle taglist** — 4 个分级 taglist 文件（各 10 万行），同上来源
- **画师索引** — `Anima2B_Artist_59k_numbered.txt`（约 5.9 万画师）

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
