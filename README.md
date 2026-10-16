# Anima Weaver

<p align="right">
  <a href="README_CN.md">中文</a> | <b>English</b>
</p>

Anima Weaver is a ComfyUI random-prompt generation toolkit: it raffles tags from a Danbooru tag library and merges them with hand-filled fixed slots and filter rules, optionally calls a local LLM (LM Studio) to blend the tags into natural-language descriptions, and supports batch pipelines that produce many "seed + prompt + resolution" groups in one run.

---

## Nodes

| Node | Class | Description |
|------|-------|-------------|
| **Anima随机提示词** | `AnimaWeaver` | Core node: fixed tag slots + Danbooru raffle + filters + optional LLM blending → complete prompt. |
| **随机分辨率选择器** | `RandomResolution` | Picks a random aspect ratio from the seed and computes the aligned width/height. |
| **批量种子** | `BatchSeedNode` | Generates a batch of seeds (up to 4096) shared across the prompt/resolution/sampler nodes. |
| **Anima批量合并** | `AnimaBatchMerge` | Aligns the seed/prompt/width/height multiline channels per line into one JSON object per line. |
| **Anima批量拆分** | `AnimaBatchSplit` | Splits a single JSON line back into seed/prompt/width/height scalars. |

---

## Installation

1. Clone into ComfyUI's `custom_nodes` directory:
   ```bash
   cd ComfyUI/custom_nodes
   git clone https://github.com/xunying7860/anima-weaver.git
   ```
2. Fetch the tag library (~215 MB, required for a `git clone` install):
   ```bash
   cd anima-weaver
   python download_tags.py
   ```
   Alternatively download the packaged zip from GitHub Releases and extract it into `custom_nodes` (no manual tag fetch needed); the Releases page also offers an older snapshot, `v2026.10-legacy`.
3. Install dependencies:
   ```bash
   pip install requests
   ```
4. Requires Python ≥ 3.10; restart ComfyUI afterwards.

**Batch pipelines** additionally require [ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) (the pipeline uses its "Prompt Line" node to read one row at a time) — install it into `custom_nodes` as well.
**NL enhancement** (turning tags into natural language) needs a local [LM Studio](https://lmstudio.ai/) exposing an OpenAI-compatible endpoint; without it the output is pure tags.

---

## Quick Start

Batch pipeline (text-arrow sketch):

```
批量种子 ─┬─→ 随机分辨率选择器 ─┐
          └─→ Anima随机提示词 ──┴─→ Anima批量合并
                                        │ JSON lines
                                        ▼
                       easy-use "Prompt Line" (pick row start_index)
                                        │ single JSON line
                                        ▼
                                  Anima批量拆分
                                        ├─ Seed → KSampler
                                        ├─ Prompt → CLIP
                                        └─ Width/Height → Empty Latent
```

Key points:

- **Core node's built-in random seed**: `0` = random each run; `>0` = deterministic reproduction; a connected seed string takes over line by line.
- **Tag Ratio**: `1.0` = pure tags, the LLM is not called; lower values lean toward natural language.
- **NL source**: only `LM Studio` calls the local LLM; `Manual` never does.
- **Artist seed**: `-1` = random artist, `0` = no artist, `n>0` = fixed index n; the artist name is appended to the end of the prompt.
- **Fixed tag slots + raffle**: always merged into one output; manual tags win on conflict.

---

## License

MIT
