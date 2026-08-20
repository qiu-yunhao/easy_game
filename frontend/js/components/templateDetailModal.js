import { api } from "../api.js";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export async function openTemplateDetail(templateId) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal modal-large">
      <div class="modal-head"><strong>模板详情 #${escapeHtml(String(templateId))}</strong>
        <button class="modal-close" type="button">✕</button></div>
      <div class="modal-body" id="detailBody"><div class="placeholder">加载中…</div></div>
    </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  try {
    const d = await api.templateDetail(templateId);
    const sb = d.style_bible || {};
    overlay.querySelector("#detailBody").innerHTML = `
      <h4>文风</h4>
      <p>基调：${escapeHtml((sb.tone_tags || []).join("、") || "-")}</p>
      <p>世界观：${escapeHtml(sb.world_premise || "-")}</p>
      <h4>情节节点（${(d.beats || []).length}）</h4>
      <ul>${(d.beats || []).map((b) => `<li><b>${escapeHtml(b.label)}</b>：${escapeHtml(b.summary)}</li>`).join("") || "<li>-</li>"}</ul>
      <h4>角色骨架（${(d.characters || []).length}）</h4>
      <ul>${(d.characters || []).map((c) => `<li><b>${escapeHtml(c.name)}</b>：${escapeHtml(c.role_summary)}</li>`).join("") || "<li>-</li>"}</ul>`;
  } catch (error) {
    overlay.querySelector("#detailBody").innerHTML = `<p>加载失败：${escapeHtml(error.message)}</p>`;
  }
}
