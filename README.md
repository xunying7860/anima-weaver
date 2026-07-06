# Anima Weaver — 提示词编织器

一个 ComfyUI 自定义节点，基于 Anima 提示词规则框架 结构化组装 AI 图像生成提示词，支持标签/自然语言混合输出。

**声明：** 本节点由 DeepSeek V4 Flash编写。

---

## 功能

- **三种工作模式：**
  - **manual（手动）** — 手填 8 个插槽标签，按 Anima 规则排序输出
  - **random（随机）** — 从 40 万条 Danbooru taglist 中随机抽取，自动分类到插槽
  - **hybrid（混合）** — Raffle 随机填充 + 手填标签追加，互斥时保留手填的
- **tag_ratio 滑块** — 控制输出中标签与自然语言的比例（纯标签 ←→ 纯自然语言）
- **LM Studio NL 增强** — 调用本地 LM Studio API 将标签转为英文描述
- **冲突检查** — 内置 Anima §3.1 互斥表（23 对），自动检测并处理冲突
- **8 个 Anima 插槽** — count_identity → appearance → clothing → pose_action → expression → camera → scene → detail_mood

---

## 安装

### 前提

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- 可选：[LM Studio](https://lmstudio.ai/)（用于 NL 增强模式）

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

3. 重启 ComfyUI。

---

## 使用

### 节点界面

```
┌─ Anima Prompt Weaver ─────────────────────┐
│ mode: [hybrid ▼]  tag_ratio: [0.60  ●]    │
│ scene_type: [solo_display ▼]               │
│ ☑ 冲突检查                                 │
├────────────────────────────────────────────┤
│ 人数/身份  [1girl, solo               ]    │
│ 外貌      [long blonde hair, blue eyes]    │
│ 服装      [school uniform            ]    │
│ 姿势/动作  [                          ]    │
│ 表情      [                          ]    │
│ 镜头      [                          ]    │
│ 场景/环境  [                          ]    │
│ 细节/氛围  [                          ]    │
├────────────────────────────────────────────┤
│ 自然语言来源: [manual ▼]                   │
│ 模型: [uncensored-ministral3-3b ▼]        │
│ 生成后卸载: ☐  上下文长度: [4096]          │
│ API地址: http://localhost:1234/v1           │
│ 自然语言描述: [a blonde girl...       ]    │
├──── Raffle ────────────────────────────────┤
│ 随机种子: [0]  生成后控制: [randomize]      │
│ ☐通用 ☐争议 ☑敏感 ☑露骨                    │
│ 标签列表必含: [1girl                       ]│
│ 过滤标签: [monochrome, greyscale...   ]    │
│ 排除含标签列表: [comic, furry...     ]    │
│ 排除标签分类: [artist, copyright...  ]    │
└────────────────────────────────────────────┘
```

### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `模式` | 下拉 | manual / random / hybrid |
| `标签比例` | 滑块 0.0~1.0 | 输出中标签的占比，默认 0.6 |
| `场景类型` | 下拉 | solo_display / couple_foreplay / couple_sex / group / yuri / special_theme |
| `人数/身份` | 文本 | Anima §6 插槽标签 |
| `外貌` | 文本 | Anima §7 插槽标签 |
| `服装` | 文本 | Anima §8 插槽标签 |
| `姿势/动作` | 文本 | Anima §9 插槽标签 |
| `表情` | 文本 | Anima §10 插槽标签 |
| `镜头` | 文本 | Anima §11 插槽标签 |
| `场景/环境` | 文本 | Anima §12 插槽标签 |
| `细节/氛围` | 文本 | Anima §13 插槽标签 |
| `自然语言来源` | 下拉 | manual（手动输入）/ lm_studio（API 生成） |
| `模型` | 下拉 | LM Studio 中的可用模型列表（自动获取） |
| `生成后卸载` | 开关 | 生成完成后是否卸载 LM Studio 模型 |
| `API密钥` | 密码 | 云端 API 密钥，留空=本地 LM Studio |
| `上下文长度` | 整数 | 模型加载时的上下文长度 |
| `API地址` | 文本 | LM Studio API 地址，默认 `http://localhost:1234/v1` |
| `自然语言描述` | 文本 | 手动输入的自然语言描述（manual 模式使用） |
| `随机种子` | 整数 | Raffle 随机种子（randomize 模式下自动随机） |
| `生成后控制` | 下拉 | fixed / randomize / increment |
| `通用/争议/敏感/露骨标签` | 开关 | 控制启用哪些分级的 taglist |
| `标签列表必含` | 文本 | 限定的 taglist 必须包含的标签 |
| `过滤标签` | 文本 | 从输出中排除的标签 |
| `排除含标签列表` | 文本 | 排除含有指定标签的整条 taglist |
| `排除标签分类` | 文本 | 排除整个分类的标签 |
| `冲突检查` | 开关 | 启用 Anima §3.1 互斥表检测 |

### 输出

| 输出 | 类型 | 说明 |
|------|------|------|
| `生成的提示词` | STRING | 最终组合的提示词（标签 + 自然语言） |
| `调试信息` | STRING | 模式、种子、冲突检查结果、插槽统计等 |

---

## 模式详解

### Manual 模式
用户手工填写 8 个插槽，节点按 Anima 槽位顺序（§4）排序输出。精确控制输出内容。

### Random 模式
从 4 个分级 taglist 文件中按用户选择随机抽取一条完整 taglist，用 `categorized_tags.txt` 归类，按 `category_to_slot.json` 映射到 8 个插槽，最终按 Anima 顺序输出。适合快速出图、探索多样性。

### Hybrid 模式
先用 Raffle 随机填充所有插槽，用户手填的标签追加在后面（权重更高）。
- 如果 Raffle 标签与手填标签互斥 → 只保留手填的
- 非互斥的 Raffle 标签保留 → 增加多样性

---

## 标签库来源

- **Anima 标签库** — 从 `anima提示词规则.md` 提取的 2,176 个标签，按 9 个分类保存
- **Danbooru 分类标签** — `categorized_tags.txt`（59,575 条），来自 [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle)
- **Raffle taglist** — 4 个分级 taglist 文件（各 10 万行），同上来源

`category_to_slot.json` 定义了 Danbooru 45 个分类到 8 个 Anima 插槽的映射关系。

---

## 推荐模型

以下模型适用于 NL 增强模式（英文自然语言生成），按体积排序：

| 模型 | 量化 | 体积 | 备注 |
|------|------|------|------|
| L3.2-Rogue-Creative-Uncensored-Abliterated-7B | Q6_K | 5.8GB | [下载](https://hf-mirror.com/DavidAU/L3.2-Rogue-Creative-Instruct-Uncensored-Abliterated-7B-GGUF) |
| Yi-1.5-9B-Chat-abliterated | Q6_K | 6.8GB | [下载](https://hf-mirror.com/byroneverson/Yi-1.5-9B-Chat-16K-abliterated) |
| Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated | Q6_K | 7.1GB | [下载](https://hf-mirror.com/huihui-ai/Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-GGUF) |
| WizardLM-1.0-Uncensored-Llama2-13B | Q4_K_M | 7.4GB | [下载](https://hf-mirror.com/TheBloke/WizardLM-1.0-Uncensored-Llama2-13B-GGUF) |
| Qwen2.5-14B-Instruct-abliterated | Q4_K_M | 8.4GB | [下载](https://hf-mirror.com/bartowski/Qwen2.5-Coder-14B-Instruct-abliterated-GGUF) |

---

## 依赖

| 依赖 | 用途 | 必需 |
|------|------|------|
| [LM Studio](https://lmstudio.ai/) | 本地 LLM 推理服务 | 仅 NL 增强模式 |
---

## 开发

```bash
# 克隆
git clone <repo-url>
cd anima-weaver

# 复制 taglist 数据（从已有 Raffle 安装）
cp ../raffle/lists/taglists-*.txt tags/
cp ../raffle/lists/categorized_tags.txt tags/

# 验证
python -c "from anima_weaver import AnimaWeaver; print('OK')"
```

---

## Credits

- **节点编写：** DeepSeek V4 Flash
- **Danbooru 标签数据：** 来自 [ComfyUI-Raffle](https://github.com/rainlizard/ComfyUI-Raffle)（rainlizard）
- **ComfyUI 集成：** 标准 ComfyUI 自定义节点接口

---

## License

MIT
