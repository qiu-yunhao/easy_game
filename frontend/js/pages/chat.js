import { api } from "../api.js";
import { appState } from "../state.js";
import { openTemplatePicker } from "../components/templatePickerModal.js";

const REQUEST_TIMEOUT_MS = 300000;

const MODE_LABELS = {
  speak: "言语",
  action: "行动",
  interrupt: "打断",
  silent: "沉默",
  event: "旁白",
};
const TOOL_MESSAGE_LABELS = {
  query_inventory: "背包检索",
  query_player_status: "角色状态",
  query_relation: "关系查询",
  query_quests: "任务检索",
  save_checkpoint: "手动存档",
  load_checkpoint: "读取存档",
};
const NARRATION_PRESENTATION_MAP = {
  director_lead_in: { channel: "冲突引子", speaker: "引子旁白", role: "紧张铺垫" },
  director_wrap_up: { channel: "冲突余波", speaker: "余波旁白", role: "情绪缓冲" },
  narrator_agent: { channel: "场景旁白", speaker: "系统旁白", role: "叙事过渡" },
  heuristic: { channel: "过渡旁白", speaker: "系统旁白", role: "回退叙述" },
  cultivation_progress: { channel: "修行回响", speaker: "系统旁白", role: "成长反馈" },
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function looksCorruptedText(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  return /[ÃÂÆÐØÞßà-ÿ]/.test(text) && !/[一-鿿]/.test(text);
}

function normalizeDisplayText(value, fallback = "") {
  const text = String(value || "").trim();
  if (!text || looksCorruptedText(text)) return fallback;
  return text;
}

function formatModeLabel(mode) {
  return MODE_LABELS[mode] || mode || MODE_LABELS.speak;
}

function formatTurnLabel(turn) {
  const parsed = Number(turn);
  if (!Number.isFinite(parsed)) return "当前轮次";
  return `第 ${parsed + 1} 轮`;
}

function classifyMessage(entry) {
  if (entry?.kind === "player") {
    return {
      variant: "user",
      tone: "message-player",
      channel: "你的行动",
      speaker: normalizeDisplayText(entry?.speaker, "你"),
      role: normalizeDisplayText(entry?.role, "玩家"),
      primaryBadge: formatModeLabel(entry?.mode),
    };
  }

  const toolName = normalizeDisplayText(entry?.tool_name, "");
  const speakerText = `${entry?.speaker || ""}${entry?.role || ""}`;
  if ((entry?.kind === "system" || speakerText.includes("系统")) && toolName) {
    return {
      variant: "system",
      tone: "system-tool",
      channel: "功能回执",
      speaker: "功能回执",
      role: TOOL_MESSAGE_LABELS[toolName] || "工具调用",
      primaryBadge: TOOL_MESSAGE_LABELS[toolName] || "工具调用",
    };
  }

  if (entry?.mode === "event" || entry?.kind === "system" || speakerText.includes("系统")) {
    const narrationSource = normalizeDisplayText(entry?.narration_source, "");
    const p = NARRATION_PRESENTATION_MAP[narrationSource] || {
      channel: "系统旁白",
      speaker: "系统旁白",
      role: "叙事过渡",
    };
    return {
      variant: "system",
      tone: "system-narration",
      channel: p.channel,
      speaker: p.speaker,
      role: p.role,
      primaryBadge: p.channel,
    };
  }

  return {
    variant: "assistant",
    tone: "message-assistant",
    channel: "角色回应",
    speaker: normalizeDisplayText(entry?.speaker, "角色"),
    role: normalizeDisplayText(entry?.role, "角色"),
    primaryBadge: formatModeLabel(entry?.mode),
  };
}

function resolveMessageContent(entry) {
  return (
    normalizeDisplayText(entry?.content, "") ||
    normalizeDisplayText(entry?.spoken_text, "") ||
    normalizeDisplayText(entry?.nonverbal_action, "") ||
    "……"
  );
}

function buildHistoryCard(entry) {
  const p = classifyMessage(entry);
  const article = document.createElement("article");
  article.className = ["message-card", p.variant, p.tone].filter(Boolean).join(" ");
  article.innerHTML = `
    <div class="message-top">
      <div class="message-copy">
        <span class="message-channel">${escapeHtml(p.channel)}</span>
        <strong>${escapeHtml(p.speaker)}</strong>
        <span class="message-role">${escapeHtml(p.role)}</span>
      </div>
      <div class="message-meta-line">
        <span class="message-badge">${escapeHtml(p.primaryBadge)}</span>
        <span class="message-badge">${escapeHtml(formatTurnLabel(entry?.turn))}</span>
      </div>
    </div>
    <p class="message-content">${escapeHtml(resolveMessageContent(entry))}</p>
  `;
  return article;
}

// Stream a player action over SSE. Calls onEntry for each committed history
// entry, and returns the final full state from the terminating "done" event.
async function streamAction(body, { onEntry } = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body,
      signal: controller.signal,
    });

    if (!response.ok || !response.body) {
      let message = "请求失败。";
      try {
        const payload = await response.json();
        message = payload.error || message;
      } catch (error) {
        // Non-JSON error body — keep default message.
      }
      throw new Error(message);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalState = null;
    let streamError = null;

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
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch (error) {
        return;
      }
      if (eventName === "entry") {
        if (typeof onEntry === "function") onEntry(data);
      } else if (eventName === "done") {
        finalState = data;
      } else if (eventName === "error") {
        streamError = new Error(data.error || "流式处理失败。");
      }
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
      }
    }
    if (buffer.trim()) dispatch(buffer);

    if (streamError) throw streamError;
    return finalState;
  } catch (error) {
    if (error?.name === "AbortError") throw new Error("行动处理超过 300 秒，请稍后重试。");
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function renderChat(el) {
  el.innerHTML = `
    <div class="chat-workspace">
      <div class="chat-topbar">
        <button id="toggleSideCard" class="button button-ghost" type="button">角色/背包</button>
        <span id="currentTemplateTag" class="tpl-tag">未使用模板</span>
        <div class="chat-topbar-right">
          <button id="pickTemplateBtn" class="button button-ghost" type="button">📚 选模板</button>
          <label class="auto-toggle"><input type="checkbox" id="autoModeToggle"><span>自动</span></label>
        </div>
      </div>
      <aside id="sideCard" class="chat-sidecard" hidden>
        <div class="sidecard-head">
          <strong id="scName">修士</strong>
          <span id="scRealm" class="sidecard-realm">—</span>
        </div>
        <p id="scLine" class="sidecard-line">—</p>
        <div class="sidecard-stats">
          <span>张力 <b id="scTension">0</b></span>
        </div>
        <ul id="scBackpack" class="sidecard-backpack"><li class="inventory-empty">暂无物品</li></ul>
      </aside>
      <div class="chat-thread" id="storyFeed"><div class="chat-empty">等待剧情开始</div></div>
      <div class="chat-composer">
        <textarea id="playerInput" rows="4" placeholder="描述你想说什么、做什么……"></textarea>
        <div class="composer-actions">
          <span id="chatStatus" class="chat-status"></span>
          <button id="saveButton" class="button button-ghost" type="button">存档</button>
          <button id="submitButton" class="button button-primary" type="button">发送</button>
        </div>
      </div>
      <details class="json-fold"><summary>JSON 调试</summary><pre id="parserJson"></pre></details>
    </div>`;

  const feed = el.querySelector("#storyFeed");
  const input = el.querySelector("#playerInput");
  const jsonPre = el.querySelector("#parserJson");
  const submit = el.querySelector("#submitButton");
  const saveBtn = el.querySelector("#saveButton");
  const autoToggle = el.querySelector("#autoModeToggle");
  const statusEl = el.querySelector("#chatStatus");

  let latestState = null;
  let isBusy = false;
  let autoTimer = null;
  let autoBusy = false;
  let chapterPaused = false;
  let autoEpoch = 0;

  const setStatus = (text) => { statusEl.textContent = text || ""; };

  const refreshTemplateTag = () => {
    el.querySelector("#currentTemplateTag").textContent =
      appState.selectedTemplateId ? `模板 #${appState.selectedTemplateId}` : "未使用模板";
  };

  const renderHistoryFull = (history) => {
    const entries = Array.isArray(history) ? history : [];
    feed.innerHTML = "";
    if (!entries.length) {
      feed.innerHTML = `<div class="chat-empty">等待剧情开始</div>`;
      return;
    }
    entries.forEach((entry) => feed.appendChild(buildHistoryCard(entry)));
    window.requestAnimationFrame(() => { feed.scrollTop = feed.scrollHeight; });
  };

  const appendHistoryEntry = (entry) => {
    if (!entry) return;
    const placeholder = feed.querySelector(".chat-empty");
    if (placeholder) feed.innerHTML = "";
    feed.appendChild(buildHistoryCard(entry));
    window.requestAnimationFrame(() => { feed.scrollTop = feed.scrollHeight; });
  };

  const renderSideCard = (state) => {
    const profile = state?.player_profile || {};
    el.querySelector("#scName").textContent = normalizeDisplayText(profile.name, "修士");
    el.querySelector("#scRealm").textContent =
      normalizeDisplayText(profile.realm, "—");
    el.querySelector("#scLine").textContent =
      `${normalizeDisplayText(profile.spiritual_root, "杂灵根")} · ${normalizeDisplayText(profile.main_technique, "基础吐纳术")}`;
    el.querySelector("#scTension").textContent = String(state?.tension_percent ?? 0);
    const backpack = Array.isArray(profile.backpack) ? profile.backpack : [];
    const list = el.querySelector("#scBackpack");
    if (!backpack.length) {
      list.innerHTML = `<li class="inventory-empty">暂无物品</li>`;
    } else {
      list.innerHTML = backpack
        .map((item) => `<li class="inventory-item">${escapeHtml(item.name || item.id || "未知道具")} ×${escapeHtml(String(item.quantity || 0))}</li>`)
        .join("");
    }
  };

  const renderState = (state) => {
    if (!state) return;
    latestState = state;
    jsonPre.textContent = JSON.stringify(state, null, 2);
    renderHistoryFull(state.history || []);
    renderSideCard(state);
    syncControls();
  };

  const syncControls = () => {
    const storyInitialized = Boolean(latestState?.story_initialized);
    const sceneFinished = Boolean(latestState?.scene_finished);
    const autoActive = autoTimer !== null || chapterPaused;
    const hasDraft = Boolean(input.value.trim());
    submit.disabled = isBusy || autoActive || !storyInitialized || sceneFinished || !hasDraft;
    input.disabled = isBusy || autoActive || !storyInitialized || sceneFinished;
    saveBtn.disabled = isBusy || autoActive || !storyInitialized || !appState.activePlayerId;
  };

  const setBusy = (next) => { isBusy = next; syncControls(); };

  const handleSave = async () => {
    if (isBusy || !appState.activePlayerId || !latestState?.story_initialized) return;
    setBusy(true);
    setStatus("正在存档…");
    try {
      const result = await api.save({
        user_id: appState.userId,
        player_id: appState.activePlayerId,
        save_kind: "manual",
        save_label: `${appState.username || "修士"} / 手动存档`,
      });
      if (result?.state) renderState(result.state);
      setStatus(`已存档：${result?.player?.slot_name || `#${appState.activePlayerId}`}`);
    } catch (error) {
      setStatus(error.message || "存档失败。");
    } finally {
      setBusy(false);
      syncControls();
    }
  };

  const handleSubmit = async () => {
    if (isBusy) return;
    const draft = input.value.trim();
    if (!draft || !latestState?.story_initialized || latestState?.scene_finished) {
      input.focus();
      return;
    }
    setBusy(true);
    setStatus("正在解析意图…");
    try {
      let firstSeen = false;
      const state = await streamAction(JSON.stringify({ input: draft }), {
        onEntry: (entry) => {
          if (!firstSeen) {
            firstSeen = true;
            setStatus("正在生成剧情…");
            input.value = "";
          }
          appendHistoryEntry(entry);
        },
      });
      if (state) renderState(state);
      input.value = "";
      setStatus("");
    } catch (error) {
      setStatus(error.message || "行动处理失败。");
    } finally {
      setBusy(false);
      syncControls();
    }
  };

  // ---- Auto mode (epoch guard + chapter pause) ----
  const stopAutoPolling = () => {
    if (autoTimer !== null) { clearInterval(autoTimer); autoTimer = null; }
  };
  const startAutoPolling = () => {
    if (autoTimer === null) autoTimer = setInterval(pollAutoStep, 1500);
  };
  const stopAutoMode = async () => {
    autoEpoch++;
    stopAutoPolling();
    chapterPaused = false;
    if (autoToggle.checked) autoToggle.checked = false;
    syncControls();
    try {
      const state = await api.setAuto(false);
      renderState(state);
    } catch (error) {
      console.error(error);
    }
  };
  async function pollAutoStep() {
    if (autoBusy || chapterPaused) return;
    if (latestState?.scene_finished) { stopAutoMode(); return; }
    autoBusy = true;
    try {
      const state = await api.autoStep(4);
      renderState(state);
      if (state?.scene_finished) {
        stopAutoMode();
      } else if (state?.chapter_paused) {
        chapterPaused = true;
        stopAutoPolling();
        syncControls();
      }
    } catch (error) {
      console.error(error);
      stopAutoMode();
    } finally {
      autoBusy = false;
    }
  }
  const startAutoMode = async () => {
    const epoch = ++autoEpoch;
    try {
      const state = await api.setAuto(true);
      if (epoch !== autoEpoch || !autoToggle.checked) return;
      renderState(state);
      startAutoPolling();
    } catch (error) {
      autoToggle.checked = false;
      setStatus(error.message || "开启自动模式失败。");
    }
  };

  // ---- Wire events ----
  el.querySelector("#toggleSideCard").addEventListener("click", () => {
    const s = el.querySelector("#sideCard");
    s.hidden = !s.hidden;
  });
  el.querySelector("#pickTemplateBtn").addEventListener("click", () =>
    openTemplatePicker(() => refreshTemplateTag()));
  submit.addEventListener("click", handleSubmit);
  saveBtn.addEventListener("click", handleSave);
  input.addEventListener("input", syncControls);
  input.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  });
  autoToggle.addEventListener("change", () => {
    if (autoToggle.checked) startAutoMode();
    else stopAutoMode();
  });

  refreshTemplateTag();

  // ---- Bootstrap: load current state (开局由「自定义开局」子步负责) ----
  (async () => {
    setBusy(true);
    setStatus("正在加载状态…");
    try {
      const state = await api.getState();
      renderState(state);
      setStatus(state?.story_initialized ? "" : "请先在上一步新开一局。");
    } catch (error) {
      setStatus(error.message || "加载失败。");
    } finally {
      setBusy(false);
      syncControls();
    }
  })();
}
