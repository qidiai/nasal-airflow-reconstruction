/* ============================================================
   patient-viewer.js — 3D 查看器右侧 <aside> 面板的「患者可读」改写层
   ------------------------------------------------------------------
   背景：iframe 内的 webapp/cases/pA/viewer_single.html 是冻结资产（禁止改动）。
        该查看器右侧面板有 9 个区块、内容高达 2352px，对患者不可读。
   做法：全部在父页面内对 iframe 文档做注入（同源，可用 iframe.contentDocument）：
         · 按 <aside> 直接子区块的「标题文本」定位（冻结资产里没有稳定 class/id 可用）；
         · 每块包成 <details class="pv-collapse">，标题进 <summary>，原 h2 仅隐藏不删；
         · 患者模式再把 6 块工程内容收进 <details class="pv-expert">（默认收起）；
         · 数字与单位一律不动：只替换"标题文字"、只"新增副标题/免责行"，原有 .metric-row 等原样保留。
   可逆：clearPanel() 按注入前的快照（原父节点 + 原 nextSibling）把 DOM 原样搬回，不重载 iframe
        （重载会丢掉相机视角/图层勾选，还要重新吃 15MB 资产，故选择 DOM 还原）。
   兜底：全流程 try/catch —— 注入失败就保持查看器原样，绝不影响查看器自身渲染。
   ============================================================ */
(function (global) {
  "use strict";

  var CSS_HREF   = "/static/patient-viewer.css";
  var STYLE_ID   = "pv-style";
  var HEAD_ID    = "pv-head";
  var FOOT_ID    = "pv-foot";
  var MAX_BLOCKS = 12;   /* 只服务 9 块式单例查看器（pA/demo）；功能更多的 viewer_plus 不碰 */
  var MIN_MATCH  = 3;    /* 标题匹配数下限：结构对不上就不处理 */

  /* ---------- 患者模式：保留的 3 块（标题 → 患者可读名 + 一句人话） ---------- */
  var KEEP = [
    { name: "呼吸阻力（压差）",
      sub : "数字越大，呼吸越费劲。下面三档＝模拟不同大小的支撑物。",
      test: function (t) { return t.indexOf("压差") === 0; } },
    { name: "空气怎么走",
      sub : "左右两侧各分到多少气流。",
      test: function (t) { return t.indexOf("流场统计") === 0; } },
    { name: "按多少气流算的",
      sub : "按这个气流大小算出来的阻力；换成别的流量按比例推算。",
      test: function (t) { return t.indexOf("仿真流量") === 0; } }
  ];

  /* ---------- 患者模式：移入「高级参数」的区块（按标题文本判定） ---------- */
  var EXPERT = [
    function (t) { return t.indexOf("曲线") >= 0; },
    function (t) { return t.indexOf("体绘制") >= 0; },
    function (t) { return t.indexOf("方法学") >= 0; },
    function (t) { return t.indexOf("缩略图") >= 0; },
    function (t) { return t.indexOf("图层控制") >= 0; },
    function (t) { return t.indexOf("视角操作") >= 0; }
  ];

  /* ---------- 患者模式：技术词 → 人话（**精确匹配整段原文**才替换；数字与单位原样保留） ----------
     只认"文本节点 trim 后与键全等"，不做子串替换；医务/操作员模式一律不启用。 */
  var PATIENT_TEXT = {
    "ΔP 基线": "当前阻力",
    "三档仿真工况 ΔP": "三种支撑物大小下的阻力",
    "层流下界估计，不确定度±20-50%（占位档为仿真工况，非推荐）":
      "这是按层流估的下限，误差可能 ±20-50%；1/2/3mm 只是模拟的支撑物大小，不是推荐尺寸"
  };

  var frames = [];   /* 已接线的 iframe（父页面内） */
  var states = [];   /* 每个 iframe 文档的注入快照 */

  function warn(e) {
    try { if (global.console && console.warn) console.warn("[patient-viewer] 已跳过（保持原样）：", e); } catch (x) {}
  }
  function guard(fn) { try { return fn(); } catch (e) { warn(e); return null; } }

  /* ================= 角色 ================= */
  function currentRole() {
    try {
      var b = global.document && global.document.body;
      var r = b && b.getAttribute ? b.getAttribute("data-role") : null;
      if (r === "patient" || r === "clinical" || r === "operator") return r;
    } catch (e) {}
    return "operator";
  }

  /* ================= 定位 aside 与区块 ================= */
  function norm(t) {
    return String(t == null ? "" : t)
      .replace(/\u00a0/g, " ")
      .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]/g, "-")
      .replace(/\\s+/g, " ")
      .trim();
  }

  function findPanel(doc) {
    if (!doc) return null;
    var a = doc.getElementById("panel");
    if (a && a.tagName && String(a.tagName).toLowerCase() === "aside") return a;
    var list = doc.getElementsByTagName("aside") || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].getElementsByTagName("section").length) return list[i];
    }
    return null;
  }

  /* aside 的直接子区块：有 <h2> 标题的元素（#data-error 这类无标题块自动跳过） */
  function blocksOf(panel) {
    var out = [];
    if (!panel || !panel.children) return out;
    for (var i = 0; i < panel.children.length; i++) {
      var el = panel.children[i];
      if (!el || el.nodeType !== 1 || !el.getElementsByTagName) continue;
      if (el.classList && (el.classList.contains("pv-collapse") || el.classList.contains("pv-expert"))) continue;
      if (!el.getElementsByTagName("h2").length) continue;
      out.push(el);
    }
    return out;
  }

  function titleOf(el) {
    var h = el && el.getElementsByTagName ? el.getElementsByTagName("h2")[0] : null;
    return norm(h ? h.textContent : "");
  }

  function matchCount(blocks) {
    var n = 0, i, j;
    for (i = 0; i < blocks.length; i++) {
      var t = titleOf(blocks[i]), hit = false;
      for (j = 0; j < KEEP.length; j++) if (KEEP[j].test(t)) { hit = true; break; }
      if (!hit) for (j = 0; j < EXPERT.length; j++) if (EXPERT[j](t)) { hit = true; break; }
      if (hit) n += 1;
    }
    return n;
  }

  /* ================= 快照 ================= */
  function newState(doc, panel, role, blocks) {
    var order = [], i;
    for (i = 0; i < blocks.length; i++) {
      order.push({ el: blocks[i], parent: blocks[i].parentNode, ref: blocks[i].nextSibling });
    }
    return { doc: doc, panel: panel, role: role, order: order,
             wraps: [], moves: [], extras: [], h2s: [], observers: [], nodes: [], texts: [] };
  }
  function stateFor(doc) {
    for (var i = 0; i < states.length; i++) if (states[i].doc === doc) return states[i];
    return null;
  }

  /* ================= 注入样式表 ================= */
  function ensureStyle(st) {
    var doc = st.doc;
    if (!doc || !doc.head) return;
    if (doc.getElementById(STYLE_ID)) return;
    var l = doc.createElement("link");
    l.id = STYLE_ID;
    l.rel = "stylesheet";
    l.href = CSS_HREF;
    doc.head.appendChild(l);
    st.nodes.push(l);
  }

  /* ================= 折叠包装 ================= */
  function wrap(st, el, title, targetParent) {
    var doc = st.doc;
    var d = doc.createElement("details");
    d.className = "pv-collapse";
    d.open = true;                                   /* 默认展开（患者模式的高级组另有开关） */
    var s = doc.createElement("summary");
    s.textContent = title || "面板";
    d.appendChild(s);

    /* 先记账再动 DOM：中途抛异常时 clearPanel 也能摘掉半成品（否则会留下空 <details>） */
    var rec = { d: d, el: el };
    st.wraps.push(rec);
    if (targetParent) {
      targetParent.appendChild(d);
    } else {
      el.parentNode.insertBefore(d, el);
    }
    d.appendChild(el);

    var h = el.getElementsByTagName ? el.getElementsByTagName("h2")[0] : null;
    if (h && h.style) {                              /* 标题已进 summary：原 h2 仅隐藏、不删 */
      st.h2s.push({ el: h, disp: h.style.display });
      h.style.display = "none";
    }
    watchVisibility(st, rec);
    return d;
  }

  /* 查看器 JS 会切 section.style.display（CT 卡/曲线卡等）：wrapper 跟着显隐，避免空标题条 */
  function syncVisible(rec) {
    try {
      var hidden = (rec.el.style && rec.el.style.display === "none");
      rec.d.style.display = hidden ? "none" : "";
    } catch (e) {}
  }
  function watchVisibility(st, rec) {
    syncVisible(rec);
    try {
      var win = st.doc.defaultView;
      if (!win || typeof win.MutationObserver !== "function") return;
      var mo = new win.MutationObserver(function () { syncVisible(rec); });
      mo.observe(rec.el, { attributes: true, attributeFilter: ["style"] });
      st.observers.push(mo);
    } catch (e) {}
  }

  /* 搬走节点（记原父节点 + 原 nextSibling，可原位还原） */
  function moveInto(st, node, target) {
    if (!node || !node.parentNode || !target) return;
    st.moves.push({ node: node, parent: node.parentNode, ref: node.nextSibling });
    target.appendChild(node);
  }

  /* 患者模式文案替换：走文本节点（绝不重写 innerHTML，避免破坏查看器内部节点引用）。
     只认"整段文本 trim 后全等"，因此不会误伤其它文案；命中即记账，还原时逐条写回原文。 */
  function translateText(st) {
    var panel = st.panel;
    if (!panel || !panel.ownerDocument || !panel.ownerDocument.createTreeWalker) return;
    var keys = Object.keys(PATIENT_TEXT), walker, n;
    try {
      walker = panel.ownerDocument.createTreeWalker(panel, 4 /* NodeFilter.SHOW_TEXT */, null, false);
    } catch (e) { return; }
    n = walker.nextNode();
    while (n) {
      var tag = (n.parentNode && n.parentNode.tagName) ? String(n.parentNode.tagName).toUpperCase() : "";
      if (tag !== "SCRIPT" && tag !== "STYLE") {
        var raw = String(n.nodeValue == null ? "" : n.nodeValue);
        var key = raw.trim();
        for (var i = 0; i < keys.length; i++) {
          if (key === keys[i]) {
            st.texts.push({ node: n, orig: raw });
            n.nodeValue = PATIENT_TEXT[keys[i]];
            break;
          }
        }
      }
      n = walker.nextNode();
    }
  }
  function restoreText(st) {
    for (var i = st.texts.length - 1; i >= 0; i--) {
      try { st.texts[i].node.nodeValue = st.texts[i].orig; } catch (e) {}
    }
    st.texts = [];
  }

  /* ================= 患者模式 ================= */
  function applyPatientPanel(doc) {
    var panel = findPanel(doc);
    if (!panel) { warn("panel structure mismatch: 未找到结果面板（aside/#panel）"); return false; }
    var blocks = blocksOf(panel);
    if (blocks.length < 3 || blocks.length > MAX_BLOCKS) {
      warn("panel structure mismatch: 区块数 " + blocks.length + " 越界（允许 3.." + MAX_BLOCKS + "）");
      return false;
    }

    /* 1) 定位 3 个保留块；结构对不上就整体不做 */
    var remaining = blocks.slice(), keep = [], i, j;
    for (i = 0; i < KEEP.length; i++) {
      var hit = null;
      for (j = 0; j < remaining.length; j++) {
        if (KEEP[i].test(titleOf(remaining[j]))) { hit = remaining[j]; remaining.splice(j, 1); break; }
      }
      if (!hit) { warn("panel structure mismatch: 保留块缺失「" + KEEP[i].name + "」"); return false; }
      keep.push({ cfg: KEEP[i], el: hit });
    }
    var nMatch = matchCount(blocks);
    if (nMatch < MIN_MATCH) {
      warn("panel structure mismatch: 可识别区块 " + nMatch + " 个 < 下限 " + MIN_MATCH);
      return false;
    }

    var st = newState(doc, panel, "patient", blocks);
    states.push(st);

    /* 原子性（B3）：从这里起的任何异常都必须回到注入前原样——半折叠状态
       （DOM 已改一半、st 滞留 states）会破坏"患者模式绝不影响查看器"的承诺。
       回滚直接复用 clearPanel：同一套还原逻辑（迁回节点/恢复 h2/摘掉注入节点/state 出栈），
       因此 catch 里只做 try{clearPanel} 兜底，不另写第二份还原。 */
    try {
      ensureStyle(st);

      /* 2) 顶部一行：免责 + 高级参数开关 */
      var head = doc.createElement("div");
      head.id = HEAD_ID;
      head.className = "pv-head";
      var hint = doc.createElement("span");
      hint.className = "pv-hint";
      hint.textContent = "这只是模拟结果，不是诊断";
      var btn = doc.createElement("button");
      btn.type = "button";
      btn.className = "pv-toggle";
      btn.textContent = "高级参数 \u25B8";
      head.appendChild(hint);
      head.appendChild(btn);
      var first = panel.firstElementChild;
      if (first && first.id === "data-error") first = first.nextElementSibling;
      panel.insertBefore(head, first || null);
      st.extras.push(head);

      /* 3) 保留块：加人话副标题 + 改标题（进 summary）+ 包折叠（默认展开） */
      for (i = 0; i < keep.length; i++) {
        var it = keep[i];
        var sub = doc.createElement("p");
        sub.className = "pv-sub";
        sub.textContent = it.cfg.sub;
        var h = it.el.getElementsByTagName("h2")[0];
        if (h && h.parentNode === it.el) it.el.insertBefore(sub, h.nextSibling);
        else it.el.insertBefore(sub, it.el.firstChild);
        st.extras.push(sub);
        wrap(st, it.el, it.cfg.name, null);
      }

      /* 4) 高级（工程参数）折叠组：默认收起，其余区块原样搬进去 */
      var group = doc.createElement("details");
      group.className = "pv-expert";
      group.id = "pv-expert";
      var gs = doc.createElement("summary");
      gs.textContent = "高级参数（工程数据）";
      group.appendChild(gs);
      var inner = doc.createElement("div");
      inner.className = "pv-group";
      group.appendChild(inner);

      var lastWrap = st.wraps[st.wraps.length - 1].d;
      lastWrap.parentNode.insertBefore(group, lastWrap.nextSibling);
      st.extras.push(group);

      for (i = 0; i < remaining.length; i++) {
        wrap(st, remaining[i], titleOf(remaining[i]) || "工程参数", inner);
      }

      /* 5) 技术明细：WSS 行 / 分侧压降（Run-A 口径）行 / 流量线性外推原文 → 搬进高级 */
      var moved = doc.createElement("section");
      moved.className = "card pv-moved";
      var mh = doc.createElement("h3");
      mh.textContent = "技术明细（原面板原文）";
      moved.appendChild(mh);
      inner.appendChild(moved);
      st.extras.push(moved);

      ["m-wss", "m-splitdp"].forEach(function (id) {
        var v = doc.getElementById(id);
        var row = v && v.parentNode;
        if (row && row.nodeType === 1 && row !== moved && row.getElementsByTagName && !row.getElementsByTagName("h2").length) {
          moveInto(st, row, moved);
        }
      });
      var flowCard = doc.getElementById("flow-card");
      var caliber = flowCard ? flowCard.querySelector(".caliber") : null;
      if (caliber) moveInto(st, caliber, moved);

      /* 6) 底部免责句（患者面板常驻可见；方法学原文仍完整保留在高级里） */
      var foot = doc.createElement("p");
      foot.id = FOOT_ID;
      foot.className = "pv-foot";
      foot.textContent = "以上全部为仿真结果，非临床结论，不能作为诊断依据。";
      panel.appendChild(foot);
      st.extras.push(foot);

      /* 8) 3 条技术词换人话（数字/单位原样；只在患者角色、只在文本节点上换） */
      translateText(st);

      /* 7) 高级参数开关 */
      function syncToggle() {
        btn.textContent = group.open ? "高级参数 \u25BE" : "高级参数 \u25B8";
        try { btn.setAttribute("aria-expanded", group.open ? "true" : "false"); } catch (e) {}
      }
      btn.addEventListener("click", function () { group.open = !group.open; syncToggle(); });
      group.addEventListener("toggle", syncToggle);
      syncToggle();

      return true;
    } catch (e) {
      warn(e);
      try { clearPanel(doc); } catch (x) {}   /* 回滚失败也不能把异常抛给查看器 */
      return false;
    }
  }

  /* ================= 医务/操作员模式：分块可折叠（默认全开，保持现状） ================= */
  function applyCollapseAll(doc) {
    var panel = findPanel(doc);
    if (!panel) return false;
    var blocks = blocksOf(panel);
    if (blocks.length < 3 || blocks.length > MAX_BLOCKS) return false;
    if (matchCount(blocks) < MIN_MATCH) return false;

    var st = newState(doc, panel, "expert", blocks);
    states.push(st);
    ensureStyle(st);
    for (var i = 0; i < blocks.length; i++) wrap(st, blocks[i], titleOf(blocks[i]), null);
    return true;
  }

  /* ================= 还原 ================= */
  function clearPanel(doc) {
    var st = stateFor(doc);
    if (!st) return false;
    try {
      st.observers.forEach(function (o) { try { o.disconnect(); } catch (e) {} });
      restoreText(st);

      /* 前提（N4）：本节的顺序还原依赖「块之间无杂项节点」——aside 的直接子元素除 section
         外只有本模块注入的 pv-* 节点（extras/nodes/wraps 三类，下面统一摘除），所以按
         order 原样 insertBefore(ref) 就能回到原始排列。若将来 aside 混入非本模块的杂项
         节点，这里必须改成按原始索引重建，不能只靠 ref。 */
      /* 1) 搬走的节点放回原父节点/原位置 */
      for (var i = st.moves.length - 1; i >= 0; i--) {
        var m = st.moves[i];
        try {
          if (!m.parent || m.parent.nodeType !== 1) continue;
          if (m.ref && m.ref.parentNode === m.parent) m.parent.insertBefore(m.node, m.ref);
          else m.parent.appendChild(m.node);
        } catch (e) {}
      }
      /* 2) 各区块搬回 aside 原位置（原父节点 + 原 nextSibling；顺序与原 DOM 一致） */
      for (var k = 0; k < st.order.length; k++) {
        var o = st.order[k];
        try {
          if (!o.parent) continue;
          if (o.ref && o.ref.parentNode === o.parent) o.parent.insertBefore(o.el, o.ref);
          else o.parent.appendChild(o.el);
        } catch (e) {}
      }
      /* 3) 标题 h2 显示恢复 */
      st.h2s.forEach(function (r) { try { r.el.style.display = r.disp || ""; } catch (e) {} });
      /* 4) 移除注入的包裹/行/样式表 */
      st.extras.forEach(function (el) { try { if (el.parentNode) el.parentNode.removeChild(el); } catch (e) {} });
      st.nodes.forEach(function (el) { try { if (el.parentNode) el.parentNode.removeChild(el); } catch (e) {} });
      st.wraps.forEach(function (r) { try { if (r.d.parentNode) r.d.parentNode.removeChild(r.d); } catch (e) {} });
    } catch (e) {
      warn(e);
    } finally {
      states = states.filter(function (s) { return s !== st; });
    }
    return true;
  }

  /* ================= 按角色应用（幂等：先还原再注入） ================= */
  function apply(doc, role) {
    if (!doc) return false;
    var r = role || currentRole();
    clearPanel(doc);
    if (r === "patient") return applyPatientPanel(doc);
    return applyCollapseAll(doc);
  }

  function applyToFrame(frame, role) {
    var doc = null;
    try {
      doc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
    } catch (e) { return false; }            /* 跨源/不可访问：静默退出 */
    if (!doc || !doc.documentElement) return false;
    return apply(doc, role);
  }

  /* ================= 父页面接线：iframe load 之后按角色应用 ================= */
  function hookFrame(frame) {
    if (!frame) return;
    var known = false, i;
    for (i = 0; i < frames.length; i++) if (frames[i] === frame) { known = true; break; }
    if (!known) {
      frames.push(frame);
      guard(function () {
        frame.addEventListener("load", function () {
          guard(function () { applyToFrame(frame); });
        });
      });
    }
    guard(function () { applyToFrame(frame); });   /* 同 src 不触发 load 时（角色互切）直接应用 */
  }

  /* 角色变化（body[data-role]）→ 对所有已接线 iframe 重新应用 */
  function watchRole() {
    try {
      var body = global.document && global.document.body;
      if (!body || typeof global.MutationObserver !== "function") return;
      var last = currentRole();
      var mo = new global.MutationObserver(function () {
        var r = currentRole();
        if (r === last) return;
        last = r;
        frames = frames.filter(function (f) { return f && f.isConnected !== false; });
        frames.forEach(function (f) { guard(function () { applyToFrame(f, r); }); });
      });
      mo.observe(body, { attributes: true, attributeFilter: ["data-role"] });
    } catch (e) { warn(e); }
  }

  watchRole();

  global.NasalPatientViewer = {
    hookFrame: hookFrame,
    applyToFrame: applyToFrame,
    apply: apply,
    applyPatientPanel: function (doc) { return applyPatientPanel(doc); },   /* 患者模式 */
    applyCollapseAll: function (doc) { return applyCollapseAll(doc); },      /* 医务/操作员 */
    clearPanel: clearPanel,
    clearPatientPanel: clearPanel,
    currentRole: currentRole
  };
}(typeof window !== "undefined" ? window : this));
