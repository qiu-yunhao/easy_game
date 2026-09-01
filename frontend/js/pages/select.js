import { appState } from "../state.js";
import { renderConversation } from "./conversation.js";
import { renderTemplates } from "./templates.js";

export function renderSelect(el) {
  el.innerHTML = `
    <div class="select-shell">
      <nav class="sidebar">
        <div class="sidebar-brand">Stagebound</div>
        <button class="side-item is-active" data-view="game" data-mode="game" type="button">🎮 游戏模式</button>
        <button class="side-item" data-view="assistant" data-mode="assistant" type="button">✍️ 写作模式</button>
        <button class="side-item" data-view="templates" type="button">📚 模板库</button>
        <div class="sidebar-user">👤 ${appState.username || "未连接"}</div>
      </nav>
      <main class="workspace" id="workspace"></main>
    </div>`;

  const ws = el.querySelector("#workspace");
  const items = el.querySelectorAll(".side-item");
  const show = (item) => {
    items.forEach((i) => i.classList.toggle("is-active", i === item));
    ws.innerHTML = "";
    if (item.dataset.view === "templates") renderTemplates(ws);
    else renderConversation(ws, { experienceMode: item.dataset.mode || "game" });
  };
  items.forEach((i) => i.addEventListener("click", () => show(i)));
  show(items[0]);
}
