import { api } from "../api.js";
import { appState } from "../state.js";
import { openTemplatePicker } from "../components/templatePickerModal.js";

const REQUEST_TIMEOUT_MS = 300000;
// 逐条上屏的最小间隔:后端并行回应组会把多条 entry 背靠背 flush 到同一帧,
// 用它把这些条目摊开成逐条出现,而非一次性全部弹出。
const STREAM_ENTRY_INTERVAL_MS = 280;

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

// Signature of everything buildHistoryCard renders, so reconciliation can
// tell an unchanged card from one the backend rewrote in place (e.g. narration
// back-filled onto an already-committed turn).
function historyEntrySignature(entry) {
  const p = classifyMessage(entry);
  return [
    p.channel, p.speaker, p.role, p.primaryBadge,
    formatTurnLabel(entry?.turn),
    resolveMessageContent(entry),
  ].join("");
}

function buildHistoryCard(entry) {
  const p = classifyMessage(entry);
  const article = document.createElement("article");
  article.className = ["message-card", p.variant, p.tone].filter(Boolean).join(" ");
  const turn = Number(entry?.turn);
  if (Number.isFinite(turn)) article.dataset.turn = String(turn);
  article.dataset.sig = historyEntrySignature(entry);
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

// Stream over SSE against `url`. Calls onEntry for each committed history
// entry (both first-emit and in-place rewrites, keyed by turn), and returns the
// final full state from the terminating "done" event.
async function streamAction(url, body, { onEntry } = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
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
      <section id="writerReview" class="writer-review" hidden>
        <div class="writer-review-head"><strong>编剧工作台</strong><span>可直接编辑完整规划 JSON</span></div>
        <textarea id="writerReviewDraft" rows="16" spellcheck="false"></textarea>
        <textarea id="writerReviewGuidance" rows="3" placeholder="给 PlayerWriter 的修改要求；重新加工时会保留当前稿的意图。"></textarea>
        <div class="composer-actions">
          <button id="writerRewrite" class="button button-ghost" type="button">重新加工</button>
          <button id="writerApprove" class="button button-primary" type="button">通过，交给导演</button>
        </div>
      </section>
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
  const writerReview = el.querySelector("#writerReview");
  const writerDraft = el.querySelector("#writerReviewDraft");
  const writerGuidance = el.querySelector("#writerReviewGuidance");
  const writerRewrite = el.querySelector("#writerRewrite");
  const writerApprove = el.querySelector("#writerApprove");

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

  // 增量对账:按 turn 逐条比对已渲染卡片与目标 history——缺失则插入、签名变化
  // 则原地替换、多余则移除。用于流结束后的 renderState,避免整表 innerHTML 清空
  // 重建把刚流式进来的 DOM 全部销毁重造(即"二次闪烁")。
  const reconcileHistory = (history) => {
    const entries = Array.isArray(history) ? history : [];
    const placeholder = feed.querySelector(".chat-empty");
    if (placeholder) feed.innerHTML = "";
    if (!entries.length) {
      feed.innerHTML = `<div class="chat-empty">等待剧情开始</div>`;
      return;
    }
    const targetTurns = new Set(
      entries.map((entry) => String(Number(entry?.turn))).filter((t) => t !== "NaN"),
    );
    feed.querySelectorAll(".message-card").forEach((card) => {
      if (!targetTurns.has(card.dataset.turn)) card.remove();
    });
    let anchor = null;
    entries.forEach((entry) => {
      const turn = Number(entry?.turn);
      const existing = Number.isFinite(turn)
        ? feed.querySelector(`.message-card[data-turn="${turn}"]`)
        : null;
      if (!existing) {
        const card = buildHistoryCard(entry);
        if (anchor && anchor.nextSibling) feed.insertBefore(card, anchor.nextSibling);
        else feed.appendChild(card);
        anchor = card;
        return;
      }
      if (existing.dataset.sig !== historyEntrySignature(entry)) {
        const card = buildHistoryCard(entry);
        feed.replaceChild(card, existing);
        anchor = card;
      } else {
        anchor = existing;
      }
    });
  };

  const appendHistoryEntry = (entry) => {
    if (!entry) return;
    const placeholder = feed.querySelector(".chat-empty");
    if (placeholder) feed.innerHTML = "";
    // 旁白会就地改写已提交条目(如攒够一批后补写过渡),后端会按 turn 重发;
    // 同 turn 已在流里出现过则原地替换(签名不变则跳过),否则追加,避免重复卡片。
    const turn = Number(entry?.turn);
    const existing = Number.isFinite(turn)
      ? feed.querySelector(`.message-card[data-turn="${turn}"]`)
      : null;
    if (existing) {
      if (existing.dataset.sig === historyEntrySignature(entry)) return;
      feed.replaceChild(buildHistoryCard(entry), existing);
    } else {
      feed.appendChild(buildHistoryCard(entry));
      window.requestAnimationFrame(() => { feed.scrollTop = feed.scrollHeight; });
    }
  };

  // 节流队列:onEntry 把条目推进来,首条立即上屏(单角色 beat 不引入延迟),
  // 其余按 STREAM_ENTRY_INTERVAL_MS 逐条排开。drain() 在流结束、renderState 对账前
  // 把积压同步清空并停表,保证最终态立即到位,不与逐条动画打架。
  const makeEntryQueue = () => {
    const pending = [];
    let timer = null;
    const step = () => {
      if (!pending.length) { timer = null; return; }
      appendHistoryEntry(pending.shift());
      timer = window.setTimeout(step, STREAM_ENTRY_INTERVAL_MS);
    };
    const stop = () => {
      if (timer !== null) { window.clearTimeout(timer); timer = null; }
    };
    return {
      push(entry) {
        pending.push(entry);
        if (timer === null) step();
      },
      drain() {
        stop();
        while (pending.length) appendHistoryEntry(pending.shift());
      },
      reset() {
        stop();
        pending.length = 0;
      },
    };
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
    reconcileHistory(state.history || []);
    renderSideCard(state);
    autoToggle.nextElementSibling.textContent = state?.experience_mode === "assistant" ? "自动审阅" : "自动";
    autoToggle.checked = Boolean(
      state?.experience_mode === "assistant" ? state?.writer_auto_approve : state?.player?.auto_mode,
    );
    syncControls();
    if (state?.writer_review_pending && writerReview.hidden) loadWriterReview();
    if (!state?.writer_review_pending) writerReview.hidden = true;
  };

  const syncControls = () => {
    const storyInitialized = Boolean(latestState?.story_initialized);
    const sceneFinished = Boolean(latestState?.scene_finished);
    const autoActive = autoTimer !== null || chapterPaused;
    const hasDraft = Boolean(input.value.trim());
    const reviewing = Boolean(latestState?.writer_review_pending);
    submit.disabled = isBusy || reviewing || autoActive || !storyInitialized || sceneFinished || !hasDraft;
    input.disabled = isBusy || reviewing || autoActive || !storyInitialized || sceneFinished;
    saveBtn.disabled = isBusy || autoActive || !storyInitialized || !appState.activePlayerId;
  };

  const setBusy = (next) => { isBusy = next; syncControls(); };

  const loadWriterReview = async () => {
    try {
      const review = await api.writerReview();
      writerDraft.value = JSON.stringify(review.draft, null, 2);
      writerGuidance.value = "";
      writerReview.hidden = false;
    } catch (error) {
      setStatus(error.message || "编剧方案加载失败。");
    }
  };

  const readWriterDraft = () => {
    try { return JSON.parse(writerDraft.value); }
    catch { throw new Error("编剧方案必须是有效 JSON。") }
  };

  const handleWriterReview = async (kind) => {
    let draft;
    try { draft = readWriterDraft(); }
    catch (error) { setStatus(error.message); return; }
    setBusy(true);
    try {
      const state = kind === "rewrite"
        ? await api.rewriteWriterReview(draft, writerGuidance.value.trim())
        : await api.approveWriterReview(draft);
      if (kind === "rewrite") {
        writerDraft.value = JSON.stringify(state.draft, null, 2);
        if (state.state) renderState(state.state);
      } else {
        writerReview.hidden = true;
        renderState(state);
        if (state?.experience_mode === "assistant") {
          chapterPaused = false;
          startAutoPolling();
        }
      }
      setStatus("");
    } catch (error) {
      setStatus(error.message || "编剧工作台操作失败。");
    } finally { setBusy(false); }
  };

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
    const queue = makeEntryQueue();
    try {
      let firstSeen = false;
      const state = await streamAction("/api/action", JSON.stringify({ input: draft }), {
        onEntry: (entry) => {
          if (!firstSeen) {
            firstSeen = true;
            setStatus("正在生成剧情…");
            input.value = "";
          }
          queue.push(entry);
        },
      });
      queue.drain();
      if (state) renderState(state);
      input.value = "";
      setStatus("");
    } catch (error) {
      queue.reset();
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
    const epoch = autoEpoch;
    const queue = makeEntryQueue();
    try {
      const state = await streamAction("/api/auto/step", JSON.stringify({ max_beats: 4 }), {
        onEntry: (entry) => {
          // 关自动/换局后到达的迟到条目丢弃,避免串档。
          if (epoch !== autoEpoch) return;
          setStatus("正在生成剧情…");
          queue.push(entry);
        },
      });
      if (epoch !== autoEpoch) { queue.reset(); return; }
      queue.drain();
      if (state) renderState(state);
      setStatus("");
      if (state?.scene_finished) {
        stopAutoMode();
      } else if (state?.chapter_paused) {
        chapterPaused = true;
        stopAutoPolling();
        syncControls();
      }
    } catch (error) {
      queue.reset();
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
  writerRewrite.addEventListener("click", () => handleWriterReview("rewrite"));
  writerApprove.addEventListener("click", () => handleWriterReview("approve"));
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
