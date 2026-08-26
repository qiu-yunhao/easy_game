import { api } from "../api.js";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fieldsList(pairs) {
  const items = pairs
    .filter(([, v]) => v)
    .map(([k, v]) => `<li><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(v)}</span></li>`)
    .join("");
  return `<ul class="tpl-fields">${items || "<li><span class=\"v\">（无内容）</span></li>"}</ul>`;
}

export async function openTemplateDetail(templateId, sourceTitle = "") {
  const bookTitle = sourceTitle || `模板 #${templateId}`;
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal modal-large">
      <div class="modal-head"><strong>${escapeHtml(bookTitle)}</strong>
        <button class="modal-close" type="button">✕</button></div>
      <div class="modal-body" id="detailBody"><div class="placeholder">加载中…</div></div>
    </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  const body = overlay.querySelector("#detailBody");

  let data;
  try {
    data = await api.templateDetail(templateId);
  } catch (error) {
    body.innerHTML = `<p>加载失败：${escapeHtml(error.message)}</p>`;
    return;
  }
  const skeleton = data.skeleton || [];
  const beats = data.beats || [];

  // view: {level:"categories"} | {level:"list", kind:"chapters"|"beats"} | {level:"item", kind, index}
  let view = { level: "categories" };

  const crumb = (trail) => {
    const parts = trail.map((t, i) =>
      i === trail.length - 1
        ? `<span>${escapeHtml(t.label)}</span>`
        : `<button class="tpl-back" type="button" data-go="${i}">${escapeHtml(t.label)}</button>`);
    return `<div class="tpl-crumb">${parts.join(" › ")}</div>`;
  };

  const render = () => {
    if (view.level === "categories") {
      body.innerHTML = crumb([{ label: bookTitle }]) + `
        <div class="tpl-grid">
          <button class="tpl-card" data-kind="chapters"><b>章节</b><br><small>${skeleton.length} 个骨架节点</small></button>
          <button class="tpl-card" data-kind="beats"><b>情节</b><br><small>${beats.length} 个情节节点</small></button>
        </div>`;
      body.querySelectorAll(".tpl-card").forEach((c) =>
        c.addEventListener("click", () => { view = { level: "list", kind: c.dataset.kind }; render(); }));
      return;
    }

    if (view.level === "list") {
      const isChapters = view.kind === "chapters";
      const label = isChapters ? "章节" : "情节";
      const cards = isChapters
        ? skeleton.map((n, i) =>
            `<button class="tpl-card" data-index="${i}"><b>第${escapeHtml(String(n.order_index))}节 · ${escapeHtml(n.title)}</b></button>`)
        : beats.map((b, i) =>
            `<button class="tpl-card" data-index="${i}"><b>${escapeHtml(b.label)}</b>${(b.tags || []).length ? `<br><small>${escapeHtml((b.tags || []).slice(0, 3).join("、"))}</small>` : ""}</button>`);
      body.innerHTML = crumb([{ label: bookTitle }, { label }]) +
        (cards.length ? `<div class="tpl-grid">${cards.join("")}</div>` : `<div class="placeholder">暂无${label}节点。</div>`);
      body.querySelector(".tpl-crumb [data-go]")?.addEventListener("click", () => { view = { level: "categories" }; render(); });
      body.querySelectorAll(".tpl-card").forEach((c) =>
        c.addEventListener("click", () => { view = { level: "item", kind: view.kind, index: Number(c.dataset.index) }; render(); }));
      return;
    }

    // item level
    const isChapters = view.kind === "chapters";
    const label = isChapters ? "章节" : "情节";
    let title;
    let fields;
    if (isChapters) {
      const n = skeleton[view.index];
      title = `第${n.order_index}节 · ${n.title}`;
      fields = fieldsList([
        ["事件概要", n.event_summary],
        ["前置条件", (n.preconditions || []).join("、")],
        ["对应章节提示", n.maps_to_chapter_hint],
      ]);
    } else {
      const b = beats[view.index];
      title = b.label;
      fields = fieldsList([
        ["概要", b.summary],
        ["标签", (b.tags || []).join("、")],
        ["戏剧功能", b.dramatic_function],
        ["可复用冲突", b.reusable_conflict],
      ]);
    }
    body.innerHTML = crumb([{ label: bookTitle }, { label }, { label: title }]) + `<h4>${escapeHtml(title)}</h4>` + fields;
    body.querySelectorAll(".tpl-crumb [data-go]").forEach((btn) =>
      btn.addEventListener("click", () => {
        view = Number(btn.dataset.go) === 0 ? { level: "categories" } : { level: "list", kind: view.kind };
        render();
      }));
  };

  render();
}
