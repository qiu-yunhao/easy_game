import { api } from "../api.js";
import { appState } from "../state.js";
import { navigate } from "../router.js";

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function renderLogin(el) {
  el.innerHTML = `
    <section class="login-shell">
      <h2>连接账号</h2>
      <div class="login-row">
        <input id="usernameInput" type="text" value="demo-user" placeholder="输入账号名">
        <button id="connectBtn" class="button button-primary" type="button">连接账号</button>
      </div>
      <div id="saveHub" class="save-hub" hidden>
        <div class="save-slot-list" id="saveSlotList"></div>
      </div>
      <p id="loginMsg" class="login-msg"></p>
    </section>`;

  const msg = el.querySelector("#loginMsg");
  el.querySelector("#connectBtn").addEventListener("click", async () => {
    try {
      const { user } = await api.ensureUser(el.querySelector("#usernameInput").value.trim());
      appState.userId = user.id;
      appState.username = user.username;
      await renderSaves(el);
      el.querySelector("#saveHub").hidden = false;
      msg.textContent = "已连接，可选择存档或直接进入。";
    } catch (e) { msg.textContent = e.message; }
  });
}

async function renderSaves(el) {
  const { players } = await api.listPlayers(appState.userId);
  const list = el.querySelector("#saveSlotList");
  if (!players.length) {
    list.innerHTML = `<div class="save-empty"><strong>还没有存档</strong>
      <button id="enterNew" class="button button-primary" type="button">进入并新开一局</button></div>`;
  } else {
    list.innerHTML = players.map(p =>
      `<button class="save-slot" data-pid="${esc(p.id)}">${esc(p.slot_name || "存档")} · #${esc(p.id)}</button>`
    ).join("") + `<button id="enterNew" class="button button-ghost" type="button">再开一局</button>`;
    list.querySelectorAll(".save-slot").forEach(b =>
      b.addEventListener("click", () => {
        appState.activePlayerId = Number(b.dataset.pid);
        navigate("select");
      }));
  }
  const en = list.querySelector("#enterNew");
  if (en) en.addEventListener("click", () => navigate("select"));
}
