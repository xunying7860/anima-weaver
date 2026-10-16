/**
 * Anima Weaver — 参数分组折叠
 * ===========================
 *
 * ComfyUI 的 INPUT_TYPES 只有 required / optional / hidden 三层，
 * 没有「分组」或「二级菜单」的原生语法。这个扩展在前端补上这一层：
 *
 *   每个分组前面放一个 BOOLEAN 开关（▸ 固定标签 / ▸ 过滤标签 / ...）
 *   勾选 → 展开该组的控件；取消 → 收起。
 *
 * 两级分组（2026-10 四节点版）：LLM设置 / 批量 / laya判定 / 系统提示词
 * 挂在一级组「▸ 高级」之下 —— ▸ 高级 关闭时，四个子开关连同成员
 * 全部隐藏（chainOpen 逐层检查所有祖先开关）；widget 数组顺序不变，
 * 嵌套关系只存在于本文件的 NESTED 表里，Python 侧无需感知。
 *
 * 设计要点（都是踩过的坑，别改）：
 *
 * 1. 组开关用**原生 BOOLEAN widget**，不是 DOM widget。
 *    DOM widget 必须 serialize=false 且只能 append 到 node.widgets 末尾
 *    （前端 save 是 index-based、restore 是 compacting counter，两者不对称，
 *      插在中间会让 widgets_values 错位，污染所有打开的工作流）。
 *    原生 BOOLEAN 没有这个问题，而且展开状态能随工作流一起保存。
 *
 * 2. 隐藏 widget **不从 node.widgets 数组里移除**，只改显示属性。
 *    理由同上：移除会改变索引，widgets_values 直接错位。
 *
 * 3. 隐藏三件套必须都设，只设 widget.type 是不够的：
 *       widget.hidden = true
 *       widget.options.hidden = true
 *       widget.computeSize = () => [0, -4]
 *       element.style.display = "none"      // STRING 会创建 DOM input，按 canvas 坐标定位，
 *                                           // 不改 display 的话即便 type 变了照样画出来
 *
 * 4. 被隐藏的 widget 值**照常提交给后端**。
 *    这是我们要的行为：用户填了再折叠，值依然生效；后端 compose() 完全不用改。
 */

// 分组定义（两级）：开关名 -> { parent: 父组开关名或null, members: 成员 widget 名 }
// 改名时记得和 Python 侧 INPUT_TYPES 保持一致。
// 注意：内置「随机种子」是 required 里的常驻 widget，不写进任何组。
const NESTED = {
  "▸ 固定标签": { parent: null, members: [
    "人数/身份", "外貌", "服装", "姿势/动作",
    "表情", "镜头", "场景/环境", "细节/氛围",
    "自然语言描述",
  ]},
  "▸ 过滤标签": { parent: null, members: [
    "标签列表必含", "过滤标签", "排除含标签列表", "排除标签分类",
    "通用标签", "争议标签", "敏感标签", "露骨标签",
  ]},
  "▸ 高级": { parent: null, members: [
    "画师种子", "冲突检查",
    "▸ LLM设置", "▸ 批量", "▸ laya判定", "▸ 系统提示词",
  ]},
  "▸ LLM设置": { parent: "▸ 高级", members: [
    "自然语言来源", "强制详细自然语言", "模型", "API地址", "API密钥",
    "云端模型名", "上下文长度", "自动上下文长度", "最大截断长度",
    "生成后卸载",
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

// 自己 + 所有祖先开关都必须勾选才算展开
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
  for (const [toggle, def] of Object.entries(NESTED)) {
    if (def.members.includes(widgetName) && !chainOpen(node, toggle)) {
      return false;
    }
  }
  return true;
}

// ── 隐藏 / 显示 ────────────────────────────────────────────────────
// 非破坏式：原始属性存在 widget 上，随时可还原

function hideWidget(w) {
  if (!w || w.__animaHidden) return;
  w.__animaHidden = true;
  w.__origType = w.type;
  w.__origComputeSize = w.computeSize;

  w.hidden = true;
  w.options = w.options || {};
  w.options.hidden = true;
  w.computeSize = () => [0, -4];

  for (const key of ["element", "inputEl"]) {
    const el = w[key];
    if (el && el.style) el.style.display = "none";
  }
}

function showWidget(w) {
  if (!w || !w.__animaHidden) return;
  w.__animaHidden = false;

  if (w.__origType !== undefined) w.type = w.__origType;
  if (w.__origComputeSize !== undefined) w.computeSize = w.__origComputeSize;

  w.hidden = false;
  if (w.options) delete w.options.hidden;

  for (const key of ["element", "inputEl"]) {
    const el = w[key];
    if (el && el.style) el.style.display = "";
  }
}

function findWidget(node, name) {
  return node.widgets ? node.widgets.find((w) => w && w.name === name) : undefined;
}

// ── 应用可见性 ─────────────────────────────────────────────────────
function applyVisibility(node) {
  let changed = false;

  const setVis = (w, show) => {
    if (!w) return;                           // 容错：widget 不存在就跳过
    const before = !!w.__animaHidden;
    if (show) showWidget(w); else hideWidget(w);
    if (before !== !!w.__animaHidden) changed = true;
  };

  for (const [toggleName, def] of Object.entries(NESTED)) {
    const toggle = findWidget(node, toggleName);
    if (!toggle) continue;                    // 节点还没建完 / 改名了，跳过
    // 子组开关本身随父链显隐（▸ 高级 关掉 → 四个子开关一起藏）
    setVis(toggle, def.parent ? chainOpen(node, def.parent) : true);
    for (const memberName of def.members) {
      setVis(findWidget(node, memberName), wantShow(node, memberName));
    }
  }

  if (changed || node.__animaFirstApply) {
    node.__animaFirstApply = false;
    // 重算节点高度，让折叠真正省出画幅
    const size = node.computeSize();
    if (size && size[1]) {
      node.setSize([node.size[0], size[1]]);
    }
    if (node.graph) node.graph.setDirtyCanvas(true, true);
    else if (typeof app !== "undefined" && app.graph) app.graph.setDirtyCanvas(true, true);
  }
}

// ── 给组开关挂上回调 ───────────────────────────────────────────────
function attachToggles(node) {
  for (const toggleName of Object.keys(NESTED)) {
    const toggle = findWidget(node, toggleName);
    if (!toggle || toggle.__animaHooked) continue;
    toggle.__animaHooked = true;

    const origCallback = toggle.callback;
    toggle.callback = function (value) {
      if (origCallback) {
        try { origCallback.apply(this, arguments); } catch (e) { /* 别让上游回调炸掉折叠 */ }
      }
      applyVisibility(node);
    };
  }
}

function setup(node) {
  attachToggles(node);
  node.__animaFirstApply = true;
  applyVisibility(node);
}

// ── 注册 ───────────────────────────────────────────────────────────
// WEB_DIRECTORY 复制后的路径在不同 ComfyUI 版本里层级不一样，
// 两种相对深度都试一遍，取第一个能 import 的。
async function resolveApp() {
  const candidates = [
    "../../../scripts/app.js",
    "../../scripts/app.js",
    "/scripts/app.js",
  ];
  for (const path of candidates) {
    try {
      const mod = await import(/* @vite-ignore */ path);
      if (mod && mod.app) return mod.app;
    } catch (e) { /* 换下一个 */ }
  }
  return null;
}

(async () => {
  const app = await resolveApp();
  if (!app) {
    console.warn("[Anima] 找不到 ComfyUI app.js，参数分组折叠未启用（不影响节点功能）");
    return;
  }

  app.registerExtension({
    name: "anima.weaver.groups",

    // 节点实例创建后：widget 还没初始化完，延迟一拍
    async nodeCreated(node) {
      if (node.comfyClass !== "AnimaWeaver") return;
      setTimeout(() => {
        try { setup(node); } catch (e) { console.warn("[Anima] group setup failed:", e); }
      }, 100);
    },

    // 打开已有工作流时：组开关的值从 widgets_values 恢复后要重新应用一次
    async loadedGraphNode(node) {
      if (node.comfyClass !== "AnimaWeaver") return;
      setTimeout(() => {
        try {
          attachToggles(node);
          node.__animaFirstApply = true;
          applyVisibility(node);
        } catch (e) { console.warn("[Anima] group restore failed:", e); }
      }, 100);
    },
  });

  console.log("[Anima] 参数分组折叠已启用");
})();
