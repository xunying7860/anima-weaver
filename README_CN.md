# Anima Weaver

<p align="right">
  <b>中文</b> | <a href="README.md">English</a>
</p>

Anima Weaver 是一套 ComfyUI 随机提示词生成套件：从 Danbooru 标签库抽签，与手填固定槽位和过滤规则合并，可选调用本地大模型（LM Studio）把标签混排成自然语言描述，并支持批量管线一次产出多组「种子 + 提示词 + 分辨率」。

---

## 节点列表

| 节点 | 类名 | 说明 |
|------|------|------|
| **Anima随机提示词** | `AnimaWeaver` | 主节点：固定标签槽 + Danbooru 抽签 + 过滤 + 可选 LLM 混排，输出完整提示词。 |
| **随机分辨率选择器** | `RandomResolution` | 按种子随机挑选画幅比例，并算出对齐后的宽高。 |
| **批量种子** | `BatchSeedNode` | 生成一批种子（上限 4096），供提示词/分辨率/采样器跨节点对齐共用。 |
| **Anima批量合并** | `AnimaBatchMerge` | 把种子/提示词/宽度/高度四路多行按行对齐，合并为逐行 JSON。 |
| **Anima批量拆分** | `AnimaBatchSplit` | 把单行 JSON 拆回种子/提示词/宽度/高度标量。 |

---

## 安装

1. 克隆到 ComfyUI 的 `custom_nodes` 目录：
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/xunying7860/anima-weaver.git
   ```
2. 拉取标签库（约 215 MB，`git clone` 安装必需）：
   ```bash
   cd anima-weaver
   python download_tags.py
   ```
   也可直接从 GitHub Releases 下载打包好的 zip 解压进 `custom_nodes`，无需手动拉标签库；Releases 页另有旧版快照 `v2026.10-legacy` 可下载。
3. 安装依赖：
   ```bash
   pip install requests
   ```
4. 需 Python ≥ 3.10；完成后重启 ComfyUI。

**批量管线**额外依赖 [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use)（管线中间用它的「提示词行」节点逐行取数据），同样装进 `custom_nodes`。
**NL 增强**（把标签转成自然语言）需本地 [LM Studio](https://lmstudio.ai/) 提供 OpenAI 兼容接口；不启用则纯标签输出。

---

## 快速上手

批量管线（文字箭头示意）：

```
批量种子 ─┬─→ 随机分辨率选择器 ─┐
          └─→ Anima随机提示词 ──┴─→ Anima批量合并
                                        │ 逐行 JSON
                                        ▼
                        easy-use「提示词行」(选第 start_index 行)
                                        │ 单行 JSON
                                        ▼
                                  Anima批量拆分
                                        ├─ 种子 → KSampler
                                        ├─ 提示词 → CLIP
                                        └─ 宽度/高度 → 空Latent
```

要点：

- **主节点内置随机种子**：`0` = 每次执行随机；`>0` = 确定性复现；接入「种子串」后由种子串逐行接管。
- **标签比例**：`1.0` = 纯标签、不触发 LLM；越低越偏自然语言。
- **自然语言来源**：只有选 `LM Studio` 才会调用本地大模型；选手动则不调。
- **画师种子**：`-1` = 随机画师，`0` = 无画师，`n>0` = 固定第 n 位；画师名直接拼进提示词末尾。
- **固定标签槽 + 抽签**：两者始终合并输出，冲突时保留手填标签。

---

## License

MIT
