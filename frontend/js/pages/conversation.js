import { api } from "../api.js";
import { appState } from "../state.js";
import { renderChat } from "./chat.js";

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function inlineMarkdown(value) {
  return String(value)
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function markdownToHtml(text) {
  const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let inCode = false;
  let codeBuf = [];
  let listBuf = [];
  let listType = null;

  const flushList = () => {
    if (!listBuf.length) return;
    const tag = listType === "ol" ? "ol" : "ul";
    out.push(`<${tag}>${listBuf.map((li) => `<li>${li}</li>`).join("")}</${tag}>`);
    listBuf = [];
    listType = null;
  };

  for (const raw of lines) {
    const line = raw.trim();

    if (inCode) {
      if (/^```/.test(line)) {
        out.push(`<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`);
        codeBuf = [];
        inCode = false;
      } else {
        codeBuf.push(raw);
      }
      continue;
    }

    if (/^```/.test(line)) {
      flushList();
      inCode = true;
      continue;
    }

    if (/^#{1,6}\s+/.test(line)) {
      flushList();
      const level = (line.match(/^#+/) || [""])[0].length;
      out.push(`<h${level}>${inlineMarkdown(esc(line.replace(/^#+\s+/, "")))}</h${level}>`);
      continue;
    }

    if (/^([-*]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\d+[.)]\s+/.test(line);
      const newType = ordered ? "ol" : "ul";
      if (listType !== null && listType !== newType) flushList();
      listType = newType;
      listBuf.push(inlineMarkdown(esc(line.replace(/^([-*]|\d+[.)])\s+/, ""))));
      continue;
    }

    if (!line) {
      flushList();
      continue;
    }

    flushList();
    out.push(`<p>${inlineMarkdown(esc(raw))}</p>`);
  }

  flushList();
  if (inCode) out.push(`<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`);
  return out.join("");
}

const DEFAULT_PROFILE = {
  gender: "未定",
  race: "人族",
  spiritual_root: "杂灵根",
  realm: "练气一层",
  main_technique: "基础吐纳术",
};

const GENRE_LABELS = {
  xianxia: "修仙",
  wuxia: "武侠",
  infinite_flow: "无限流",
};

const REQUEST_TIMEOUT_MS = 120000;

async function streamWorldChat(body, { onDelta, onDone } = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch("/api/world-builder/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body,
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      let message = "请求失败。";
      try { message = (await response.json()).error || message; } catch {}
      throw new Error(message);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let final = null;
    let finished = false;
    const dispatch = (rawEvent) => {
      const lines = rawEvent.split("\n");
      let eventName = "message";
      const dataLines = [];
      for (const line of lines) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) return;
      let data;
      try { data = JSON.parse(dataLines.join("\n")); } catch { return; }
      if (eventName === "delta") { if (typeof onDelta === "function") onDelta(data.text || ""); }
      else if (eventName === "done") { final = data; finished = true; if (typeof onDone === "function") onDone(data); }
      else if (eventName === "error") { throw new Error(data.error || "处理失败。"); }
    };

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        dispatch(rawEvent);
        if (finished) break;
      }
      if (finished) break;
    }
    if (!finished && buffer.trim()) dispatch(buffer);
    await reader.cancel().catch(() => {});
    return final;
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("世界观分析超过 120 秒，请重试。");
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function renderConversation(el, { experienceMode = "game" } = {}) {
  // Preserve connection/game across sidebar switches: an active game jumps
  // straight to chat, a connected-but-idle user stays on the save hub (which
  // auto-loads), only a fresh visitor sees the bare connect screen.
  const mode = experienceMode === "assistant" ? "assistant" : "game";
  let step = appState.activePlayerId ? "chat" : "connect";

  const go = (next) => { step = next; render(); };

  const render = () => {
    el.innerHTML = "";
    if (step === "connect") renderConnect(el, go);
    else if (step === "newgame") renderNewGame(el, go, mode);
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

function renderNewGame(el, go, experienceMode) {
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
      <label class="newgame-field">
        <span>世界设定起点</span>
        <select id="ngGenre"><option value="">加载中…</option></select>
      </label>
      <div class="newgame-actions">
        <button id="ngBack" class="button button-ghost" type="button">返回</button>
        <button id="ngStart" class="button button-primary" type="button">开始游戏</button>
      </div>
      <p id="ngMsg" class="login-msg"></p>
    </section>`;

  const msg = el.querySelector("#ngMsg");
  const styleSel = el.querySelector("#ngStyle");
  const genreSel = el.querySelector("#ngGenre");
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

  const genreOptions = (worldSettings) =>
    `<option value="">自定义（从零开始）</option>` +
    worldSettings.map((w) =>
      `<option value="${esc(w.genre_tag)}">${esc(GENRE_LABELS[w.genre_tag] || w.title || w.genre_tag)}</option>`).join("");

  (async () => {
    try {
      const [{ world_settings }, draft] = await Promise.all([
        api.listWorldSettings(),
        api.getWorldBuilderDraft().catch(() => ({ exists: false })),
      ]);
      const resumeOption = draft?.exists
        ? `<option value="__resume__">继续完善上次的世界观（未完成）</option>`
        : "";
      genreSel.innerHTML = resumeOption + genreOptions(Array.isArray(world_settings) ? world_settings : []);
    } catch (e) {
      genreSel.innerHTML = genreOptions(
        Object.entries(GENRE_LABELS).map(([tag, title]) => ({ genre_tag: tag, title })),
      );
      msg.textContent = `世界观选项加载失败：${e.message}`;
    }
  })();

  el.querySelector("#ngBack").addEventListener("click", () => go("connect"));

  startBtn.addEventListener("click", async () => {
    const name = el.querySelector("#ngName").value.trim() || "无名修士";
    const background = el.querySelector("#ngBackground").value.trim();
    const stylePreset = styleSel.value || null;
    const genreTag = el.querySelector("#ngGenre").value;
    startBtn.disabled = true;
    msg.textContent = "正在开局，可能较久…";
    try {
      const gameRequest = {
        user_id: appState.userId,
        slot_name: `${name} 的仙途`,
        save_label: `${name} / 开局快照`,
        player_profile: { ...DEFAULT_PROFILE, name, background, backpack: [] },
        narration_style_preset: stylePreset,
        experience_mode: experienceMode,
        selected_template_id: appState.selectedTemplateId ?? null,
      };
      const view = genreTag === "__resume__"
        ? await api.resumeWorldBuilder()
        : await api.startWorldBuilder(genreTag);
      renderWorldChat(el, go, gameRequest, view);
    } catch (e) {
      startBtn.disabled = false;
      msg.textContent = `世界观完善启动失败：${e.message}`;
    }
  });
}

function renderWorldChat(el, go, gameRequest, view) {
  let latestView = view;
  let busy = false;
  let lastUserMessage = "";

  el.innerHTML = `
    <section class="world-chat-shell">
      <h2>完善世界观</h2>
      <div class="world-chat-thread" id="worldChatThread"></div>
      <div class="world-chat-refs" id="worldChatRefs"></div>
      <div class="world-chat-composer">
        <textarea id="worldChatInput" rows="3" placeholder="描述你的世界观，Agent 会分析并逐项确认……"></textarea>
        <div class="composer-actions">
          <span id="worldChatStatus" class="chat-status"></span>
          <button id="worldChatSend" class="button button-primary" type="button">发送</button>
          <button id="worldChatFinish" class="button button-primary" type="button" hidden>完成并开始游戏</button>
        </div>
      </div>
      <p id="worldChatMsg" class="login-msg"></p>
    </section>`;

  const thread = el.querySelector("#worldChatThread");
  const input = el.querySelector("#worldChatInput");
  const statusEl = el.querySelector("#worldChatStatus");
  const sendBtn = el.querySelector("#worldChatSend");
  const finishBtn = el.querySelector("#worldChatFinish");
  const msgEl = el.querySelector("#worldChatMsg");
  const refsEl = el.querySelector("#worldChatRefs");

  const appendMsg = (role, text) => {
    const node = document.createElement("div");
    node.className = `world-chat-msg ${role}`;
    if (role === "user") node.textContent = text;
    else node.innerHTML = markdownToHtml(text);
    thread.appendChild(node);
    thread.scrollTop = thread.scrollHeight;
    return node;
  };

  const sync = () => {
    const complete = latestView?.status === "complete";
    sendBtn.disabled = busy || complete;
    input.disabled = busy || complete;
    finishBtn.hidden = !complete;
    statusEl.textContent = complete ? "设定已完成，可以开始游戏。" : "";
  };

  const renderRefs = () => {
    refsEl.innerHTML = "";
    const candidates = Array.isArray(latestView?.reference_candidates)
      ? latestView.reference_candidates
      : [];
    candidates.forEach((candidate) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button button-ghost world-chat-ref";
      button.textContent = `📚 参考《${candidate.source_title || candidate.template_id}》`;
      button.addEventListener("click", () => addReference(candidate.template_id, candidate.source_title));
      refsEl.appendChild(button);
    });
  };

  const addReference = async (templateId, title) => {
    if (busy) return;
    busy = true;
    sync();
    statusEl.textContent = "正在读取参考…";
    try {
      const res = await api.addWorldBuilderReference(
        templateId,
        latestView?.reference_query || lastUserMessage,
      );
      latestView = res?.view || latestView;
      if (latestView) latestView.reference_candidates = [];
      appendMsg("system", `已参考《${title || templateId}》，可继续回答当前问题。`);
      renderRefs();
      statusEl.textContent = "";
    } catch (e) {
      statusEl.textContent = "";
      msgEl.textContent = e.message;
    } finally {
      busy = false;
      sync();
    }
  };

  if (latestView?.question) appendMsg("assistant", latestView.question);
  sync();

  const send = async () => {
    const text = input.value.trim();
    if (!text || busy || latestView?.status === "complete") return;
    busy = true;
    lastUserMessage = text;
    sync();
    appendMsg("user", text);
    input.value = "";
    statusEl.textContent = "Agent 正在分析…";
    const bubble = appendMsg("assistant", "");
    let rawBubble = "";
    try {
      await streamWorldChat(JSON.stringify({ message: text }), {
        onDelta: (chunk) => {
          rawBubble += chunk;
          bubble.innerHTML = markdownToHtml(rawBubble);
          thread.scrollTop = thread.scrollHeight;
        },
        onDone: (data) => {
          latestView = data?.view || latestView;
          sync();
          if (latestView?.guidance) appendMsg("system", latestView.guidance);
          else if (latestView?.question) appendMsg("system", latestView.question);
          renderRefs();
        },
      });
      statusEl.textContent = "";
      msgEl.textContent = "";
    } catch (e) {
      if (!rawBubble) bubble.textContent = e.message;
      statusEl.textContent = "";
      msgEl.textContent = e.message;
    } finally {
      busy = false;
      sync();
    }
  };

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (ev) => {
    if (ev.isComposing) return;
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(); }
  });

  finishBtn.addEventListener("click", async () => {
    if (busy || latestView?.status !== "complete") return;
    busy = true;
    sync();
    statusEl.textContent = "正在创建存档…";
    try {
      const result = await api.newGame({ ...gameRequest, world_setting: latestView.draft });
      appState.activePlayerId = result.player?.id ?? null;
      go("chat");
    } catch (e) {
      busy = false;
      sync();
      statusEl.textContent = "";
      msgEl.textContent = `创建存档失败：${e.message}`;
    }
  });
}
