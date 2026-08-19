import { api } from "../api.js";
import { appState } from "../state.js";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export async function openTemplatePicker(onDone) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal modal-small">
      <div class="modal-head">
        <strong>选择情节模板</strong>
        <span class="modal-status" id="pickStatus"></span>
        <button class="modal-close" type="button">✕</button>
      </div>
      <div class="tpl-grid" id="pickGrid"><div class="placeholder">加载中…</div></div>
      <div class="modal-foot">
        <button id="clearTpl" class="button button-ghost" type="button">清除模板</button>
        <button id="confirmTpl" class="button button-primary" type="button">确认</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  const status = overlay.querySelector("#pickStatus");
  const grid = overlay.querySelector("#pickGrid");
  let chosen = appState.selectedTemplateId;
  const refreshStatus = () => {
    status.textContent = chosen ? `已选 #${chosen}` : "默认：未使用模板";
  };
  refreshStatus();

  try {
    const { templates } = await api.listTemplates();
    grid.innerHTML =
      `<button class="tpl-card ${!chosen ? "is-active" : ""}" data-id="">不用模板<br><small>自由发挥</small></button>` +
      (templates || [])
        .map((t) =>
          `<button class="tpl-card ${chosen === t.template_id ? "is-active" : ""}" data-id="${t.template_id}"><b>${escapeHtml(t.source_title)}</b><br><small>${escapeHtml(String(t.beat_count))} 情节节点</small></button>`)
        .join("");
  } catch (error) {
    grid.innerHTML = `<div class="placeholder">加载失败：${escapeHtml(error.message)}</div>`;
    return;
  }

  grid.querySelectorAll(".tpl-card").forEach((c) =>
    c.addEventListener("click", () => {
      chosen = c.dataset.id ? Number(c.dataset.id) : null;
      grid.querySelectorAll(".tpl-card").forEach((x) => x.classList.remove("is-active"));
      c.classList.add("is-active");
      refreshStatus();
    }));

  overlay.querySelector("#clearTpl").addEventListener("click", () => {
    chosen = null;
    grid.querySelectorAll(".tpl-card").forEach((x) =>
      x.classList.toggle("is-active", x.dataset.id === ""));
    refreshStatus();
  });

  overlay.querySelector("#confirmTpl").addEventListener("click", async () => {
    try {
      await api.selectTemplate(chosen);
      appState.selectedTemplateId = chosen;
      close();
      if (onDone) onDone();
    } catch (error) {
      status.textContent = `保存失败：${error.message}`;
    }
  });
}
