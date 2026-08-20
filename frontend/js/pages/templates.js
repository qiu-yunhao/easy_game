import { api } from "../api.js";
import { appState } from "../state.js";
import { openTemplateDetail } from "../components/templateDetailModal.js";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderTemplates(el) {
  el.innerHTML = `
    <div class="tpl-workspace">
      <section class="tpl-upload">
        <h3>上传小说 · 解析情节</h3>
        <input id="tplTitle" type="text" placeholder="来源标题（如：鹿鼎记）">
        <input id="tplFile" type="file" accept=".txt,text/plain">
        <button id="tplImport" class="button button-primary" type="button">开始解析情节</button>
        <p id="tplProgress" class="tpl-progress"></p>
      </section>
      <section class="tpl-list">
        <h3>已有模板</h3>
        <div class="tpl-grid" id="tplGrid"><div class="placeholder">加载中…</div></div>
      </section>
    </div>`;

  const grid = el.querySelector("#tplGrid");
  const progress = el.querySelector("#tplProgress");

  const loadList = async () => {
    try {
      const { templates } = await api.listTemplates();
      grid.innerHTML = (templates || []).length
        ? templates
            .map((t) => `<button class="tpl-card" data-id="${t.template_id}"><b>${escapeHtml(t.source_title)}</b><br><small>${escapeHtml(String(t.beat_count))} 情节节点</small></button>`)
            .join("")
        : `<div class="placeholder">还没有模板，先上传一部小说解析。</div>`;
      grid.querySelectorAll(".tpl-card").forEach((c) =>
        c.addEventListener("click", () => openTemplateDetail(Number(c.dataset.id))));
    } catch (error) {
      grid.innerHTML = `<div class="placeholder">加载失败：${escapeHtml(error.message)}</div>`;
    }
  };
  loadList();

  el.querySelector("#tplImport").addEventListener("click", async () => {
    const title = el.querySelector("#tplTitle").value.trim();
    const file = el.querySelector("#tplFile").files[0];
    if (!title || !file) { progress.textContent = "请填写标题并选择文件。"; return; }
    progress.textContent = "读取文件…";
    const text = await file.text();
    progress.textContent = "解析中：分块 → 聚类 → 提取骨架（可能较久）…";
    try {
      const { template_id } = await api.importTemplate({
        source_title: title, text, user_id: appState.userId || 0,
      });
      progress.textContent = `解析完成，模板 #${template_id}`;
      await loadList();
    } catch (error) {
      progress.textContent = `解析失败：${error.message}`;
    }
  });
}
