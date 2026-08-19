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
      await renderSaves(el, msg);
      el.querySelector("#saveHub").hidden = false;
      msg.textContent = "已连接，可选择存档或直接进入。";
    } catch (e) { msg.textContent = e.message; }
  });
}

async function loadAndEnter(playerId, msg) {
  msg.textContent = "正在载入存档…";
  try {
    const loaded = await api.load({ user_id: appState.userId, player_id: playerId });
    appState.activePlayerId = loaded.player?.id ?? playerId;
    navigate("select");
  } catch (e) {
    msg.textContent = `载入存档失败：${e.message}`;
  }
}

async function createAndEnter(msg) {
  msg.textContent = "正在新开一局…";
  try {
    const result = await api.newGame({
      user_id: appState.userId,
      slot_name: `${appState.username || "修士"} 的仙途`,
      selected_template_id: appState.selectedTemplateId ?? null,
    });
    appState.activePlayerId = result.player?.id ?? null;
    navigate("select");
  } catch (e) {
    msg.textContent = `新开一局失败：${e.message}`;
  }
}

async function renderSaves(el, msg) {
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
      b.addEventListener("click", () => loadAndEnter(Number(b.dataset.pid), msg)));
  }
  const en = list.querySelector("#enterNew");
  if (en) en.addEventListener("click", () => createAndEnter(msg));
}
