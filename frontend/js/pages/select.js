import { appState } from "../state.js";
import { renderConversation } from "./conversation.js";
import { renderTemplates } from "./templates.js";

export function renderSelect(el) {
  el.innerHTML = `
    <div class="select-shell">
      <nav class="sidebar">
        <div class="sidebar-brand">Stagebound</div>
        <button class="side-item is-active" data-view="chat" type="button">💬 对话</button>
        <button class="side-item" data-view="templates" type="button">📚 模板库</button>
        <div class="sidebar-user">👤 ${appState.username || "未连接"}</div>
      </nav>
      <main class="workspace" id="workspace"></main>
    </div>`;

  const ws = el.querySelector("#workspace");
  const items = el.querySelectorAll(".side-item");
  const show = (view) => {
    items.forEach((i) => i.classList.toggle("is-active", i.dataset.view === view));
    ws.innerHTML = "";
    (view === "templates" ? renderTemplates : renderConversation)(ws);
  };
  items.forEach((i) => i.addEventListener("click", () => show(i.dataset.view)));
  show("chat");
}
