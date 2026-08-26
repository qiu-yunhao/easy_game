import { api } from "../api.js";
import { appState } from "../state.js";
import { renderChat } from "./chat.js";

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

const DEFAULT_PROFILE = {
  gender: "未定",
  race: "人族",
  spiritual_root: "杂灵根",
  realm: "练气一层",
  main_technique: "基础吐纳术",
};

export function renderConversation(el) {
  // Preserve connection/game across sidebar switches: an active game jumps
  // straight to chat, a connected-but-idle user stays on the save hub (which
  // auto-loads), only a fresh visitor sees the bare connect screen.
  let step = appState.activePlayerId ? "chat" : "connect";

  const go = (next) => { step = next; render(); };

  const render = () => {
    el.innerHTML = "";
    if (step === "connect") renderConnect(el, go);
    else if (step === "newgame") renderNewGame(el, go);
    else renderChat(el);
  };

  render();
}

function renderConnect(el, go) {
  el.innerHTML = `
    <section class="login-shell">
      <h2>连接账号</h2>
      <div class="login-row">
        <input id="usernameInput" type="text" value="${esc(appState.username || "demo-user")}" placeholder="输入账号名">
        <button id="connectBtn" class="button button-primary" type="button">连接账号</button>
      </div>
      <div id="saveHub" class="save-hub" ${appState.userId ? "" : "hidden"}>
        <div class="save-slot-list" id="saveSlotList"></div>
      </div>
      <p id="loginMsg" class="login-msg"></p>
    </section>`;

  const msg = el.querySelector("#loginMsg");
  const connect = async () => {
    try {
      const { user } = await api.ensureUser(el.querySelector("#usernameInput").value.trim());
      appState.userId = user.id;
      appState.username = user.username;
      await renderSaves(el, msg, go);
      el.querySelector("#saveHub").hidden = false;
      msg.textContent = "已连接，可选择存档或新开一局。";
    } catch (e) { msg.textContent = e.message; }
  };
  el.querySelector("#connectBtn").addEventListener("click", connect);
  if (appState.userId) renderSaves(el, msg, go).catch((e) => { msg.textContent = e.message; });
}

async function renderSaves(el, msg, go) {
  const { players } = await api.listPlayers(appState.userId);
  const list = el.querySelector("#saveSlotList");
  if (!players.length) {
    list.innerHTML = `<div class="save-empty"><strong>还没有存档</strong>
      <button id="enterNew" class="button button-primary" type="button">进入并新开一局</button></div>`;
  } else {
    list.innerHTML = players.map((p) =>
      `<button class="save-slot" data-pid="${esc(p.id)}">${esc(p.slot_name || "存档")} · #${esc(p.id)}</button>`
    ).join("") + `<button id="enterNew" class="button button-ghost" type="button">新开一局</button>`;
    list.querySelectorAll(".save-slot").forEach((b) =>
      b.addEventListener("click", () => loadAndEnter(Number(b.dataset.pid), msg, go)));
  }
  const en = list.querySelector("#enterNew");
  if (en) en.addEventListener("click", () => go("newgame"));
}

async function loadAndEnter(playerId, msg, go) {
  msg.textContent = "正在载入存档…";
  try {
    const loaded = await api.load({ user_id: appState.userId, player_id: playerId });
    appState.activePlayerId = loaded.player?.id ?? playerId;
    go("chat");
  } catch (e) {
    msg.textContent = `载入存档失败：${e.message}`;
  }
}

function renderNewGame(el, go) {
  el.innerHTML = `
    <section class="newgame-form">
      <h2>自定义开局</h2>
      <label class="newgame-field">
        <span>角色名</span>
        <input id="ngName" type="text" value="无名修士" placeholder="给你的修士起个名字">
      </label>
      <label class="newgame-field">
        <span>背景故事</span>
        <textarea id="ngBackground" rows="4" placeholder="描述你的出身与际遇……">出身凡俗，尚未真正看清自己的仙途。</textarea>
      </label>
      <label class="newgame-field">
        <span>叙事风格</span>
        <select id="ngStyle"><option value="">加载中…</option></select>
      </label>
      <div class="newgame-actions">
        <button id="ngBack" class="button button-ghost" type="button">返回</button>
        <button id="ngStart" class="button button-primary" type="button">开始游戏</button>
      </div>
      <p id="ngMsg" class="login-msg"></p>
    </section>`;

  const msg = el.querySelector("#ngMsg");
  const styleSel = el.querySelector("#ngStyle");
  const startBtn = el.querySelector("#ngStart");

  (async () => {
    try {
      const state = await api.getState();
      const options = Array.isArray(state?.available_narration_styles) ? state.available_narration_styles : [];
      const current = state?.narration_style_preset || "";
      styleSel.innerHTML = options.length
        ? options.map((o) =>
            `<option value="${esc(o.value)}" ${o.value === current ? "selected" : ""}>${esc(o.label || o.value)}</option>`).join("")
        : `<option value="">默认</option>`;
    } catch (e) {
      styleSel.innerHTML = `<option value="">默认</option>`;
      msg.textContent = `叙事风格加载失败：${e.message}`;
    }
  })();

  el.querySelector("#ngBack").addEventListener("click", () => go("connect"));

  startBtn.addEventListener("click", async () => {
    const name = el.querySelector("#ngName").value.trim() || "无名修士";
    const background = el.querySelector("#ngBackground").value.trim();
    const stylePreset = styleSel.value || null;
    startBtn.disabled = true;
    msg.textContent = "正在开局，可能较久…";
    try {
      const result = await api.newGame({
        user_id: appState.userId,
        slot_name: `${name} 的仙途`,
        save_label: `${name} / 开局快照`,
        player_profile: { ...DEFAULT_PROFILE, name, background, backpack: [] },
        narration_style_preset: stylePreset,
        selected_template_id: appState.selectedTemplateId ?? null,
      });
      appState.activePlayerId = result.player?.id ?? null;
      go("chat");
    } catch (e) {
      startBtn.disabled = false;
      msg.textContent = `开局失败：${e.message}`;
    }
  });
}
