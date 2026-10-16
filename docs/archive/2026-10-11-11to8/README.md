# 归档：11→8 节点整合轮（2026-10-11）

本目录是 **11→8 那一轮**的施工文档与参考补丁，该轮已实施完毕，
当前仓库为 **4 节点版本**（2026-10-16 起，见
`docs/plan/anima-weaver-四节点精简重构方案-2.md`）。

内容：

- `00-总方案-从这里开始读.md` —— 11→8 轮总方案（已实施）
- `patches/` —— 该轮 9 个参考补丁（tag_index / artist_index / lm_studio 修复 /
  分组 INPUT_TYPES / 随机逻辑 / laya 门控 / laya 微调 / tag_extract / 冲突规则）
- `anima_groups.js` —— 该轮的前端分组扩展参考（当前生效版本在 `js/anima_groups.js`，
  已升级为两级分组）

注意：`patches/` 里的文件是当时改动前的参考实现，**不是当前代码**，
不要直接套用到 4 节点版本上。
