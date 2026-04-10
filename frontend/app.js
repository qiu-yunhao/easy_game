const API = {
  state: "/api/state",
  action: "/api/action",
  reset: "/api/reset",
  ensureUser: "/api/users/ensure",
  players: "/api/players",
  newGame: "/api/new-game",
  save: "/api/save",
  load: "/api/load",
};

const DEFAULT_SPIRITUAL_ROOT = "杂灵根";
const DEFAULT_REALM = "练气一层";
const DEFAULT_MAIN_TECHNIQUE = "基础吐纳术";
const DEFAULT_BACKPACK_EMPTY_TEXT = "暂无物品";
const DEFAULT_SCENE_GOAL = "看清局势，找出下一步修行方向";
const DEFAULT_SCENE_LOCATION = "云峰地界";

const storyFeed = document.getElementById("storyFeed");
const playerInput = document.getElementById("playerInput");
const clearButton = document.getElementById("clearButton");
const submitButton = document.getElementById("submitButton");
const startSceneButton = document.getElementById("startSceneButton");
const restartSceneButton = document.getElementById("restartSceneButton");
const editProfileButton = document.getElementById("editProfileButton");
const toggleBackpackButton = document.getElementById("toggleBackpackButton");
const backpackDrawer = document.getElementById("backpackDrawer");
const profileFlipbook = document.getElementById("profileFlipbook");
const parserJson = document.getElementById("parserJson");
const parserStatus = document.getElementById("parserStatus");
const runtimeModeText = document.getElementById("runtimeModeText");
const liveRound = document.getElementById("liveRound");
const liveMood = document.getElementById("liveMood");
const tensionValue = document.getElementById("tensionValue");
const inputCount = document.getElementById("inputCount");
const modePreview = document.getElementById("modePreview");
const summaryMode = document.getElementById("summaryMode");
const summaryTarget = document.getElementById("summaryTarget");
const summaryIntent = document.getElementById("summaryIntent");
const stepCapture = document.getElementById("stepCapture");
const stepParse = document.getElementById("stepParse");
const stepCommit = document.getElementById("stepCommit");
const hintButtons = document.querySelectorAll("[data-prompt-index]");
const sceneGoalValue = document.getElementById("sceneGoalValue");
const sceneGoalHint = document.getElementById("sceneGoalHint");
const playerCardName = document.getElementById("playerCardName");
const playerCardLine = document.getElementById("playerCardLine");
const playerRootValue = document.getElementById("playerRootValue");
const playerRootLine = document.getElementById("playerRootLine");
const sceneChip = document.getElementById("sceneChip");
const controlBadge = document.getElementById("controlBadge");
const identityNote = document.getElementById("identityNote");
const currentIdentityNote = document.getElementById("currentIdentityNote");
const playerBackpackList = document.getElementById("playerBackpackList");
const sidebarPlayerAvatar = document.getElementById("sidebarPlayerAvatar");
const sidebarPlayerName = document.getElementById("sidebarPlayerName");
const sidebarPlayerMeta = document.getElementById("sidebarPlayerMeta");
const sidebarRealmText = document.getElementById("sidebarRealmText");
const sidebarStatusText = document.getElementById("sidebarStatusText");
const playerLevelValue = document.getElementById("playerLevelValue");
const playerHpValue = document.getElementById("playerHpValue");
const playerExpValue = document.getElementById("playerExpValue");
const playerStateValue = document.getElementById("playerStateValue");
const jsonMeta = document.getElementById("jsonMeta");
const jsonCopyButton = document.getElementById("jsonCopyButton");
const jsonToggleButton = document.getElementById("jsonToggleButton");
const jsonPanel = document.querySelector(".json-panel");
const jsonPanelBody = document.getElementById("jsonPanelBody");
const jsonRoundValue = document.getElementById("jsonRoundValue");
const jsonPlayerValue = document.getElementById("jsonPlayerValue");
const jsonTensionValue = document.getElementById("jsonTensionValue");
const saveStatusChip = document.getElementById("saveStatusChip");
const saveUsernameInput = document.getElementById("saveUsernameInput");
const ensureUserButton = document.getElementById("ensureUserButton");
const refreshPlayersButton = document.getElementById("refreshPlayersButton");
const saveSlotList = document.getElementById("saveSlotList");
const slotNameInput = document.getElementById("slotNameInput");
const activePlayerLabel = document.getElementById("activePlayerLabel");
const activeSaveMeta = document.getElementById("activeSaveMeta");
const loadPlayerButton = document.getElementById("loadPlayerButton");
const newGameButton = document.getElementById("newGameButton");
const saveGameButton = document.getElementById("saveGameButton");

const playerNameInput = document.getElementById("playerName");
const playerGenderInput = document.getElementById("playerGender");
const playerRaceInput = document.getElementById("playerRace");
const playerSpiritualRootInput = document.getElementById("playerSpiritualRoot");
const playerRealmInput = document.getElementById("playerRealm");
const playerMainTechniqueInput = document.getElementById("playerMainTechnique");
const playerBackgroundInput = document.getElementById("playerBackground");
const narrationStylePresetInput = document.getElementById("narrationStylePreset");
const narrationStyleHint = document.getElementById("narrationStyleHint");

const profileInputs = [
  playerNameInput,
  playerGenderInput,
  playerRaceInput,
  playerSpiritualRootInput,
  playerRealmInput,
  playerMainTechniqueInput,
  playerBackgroundInput,
];

let isBusy = false;
let latestState = null;
let latestJsonText = "";
let isJsonCollapsed = false;
let isBackpackOpen = false;
let sidebarMode = "setup";
let persistenceAvailable = null;
let currentUser = null;
let players = [];
let selectedPlayerId = null;
let currentPlayerId = null;

const REQUEST_TIMEOUT_MS = 300000;
const ACTION_REQUEST_TIMEOUT_MS = REQUEST_TIMEOUT_MS;
const RESET_REQUEST_TIMEOUT_MS = REQUEST_TIMEOUT_MS;
const PERSISTENCE_STORAGE_KEYS = {
  username: "stagebound.persistence.username",
  userId: "stagebound.persistence.userId",
  playerId: "stagebound.persistence.playerId",
};

const messageTimestampCache = new Map();
const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});
const datetimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

const DEFAULT_NARRATION_STYLE_OPTIONS = [
  {
    value: "xianxia_default",
    label: "仙侠默认",
    description: "适合宗门、山野、秘境等修仙场景，语言更有道韵和留白。",
  },
  {
    value: "light_novel",
    label: "轻小说",
    description: "节奏更轻快，人物反应更贴近角色互动与即时情绪。",
  },
  {
    value: "epic",
    label: "史诗感",
    description: "气势更厚重，适合大战、宗门争锋和命运转折。",
  },
];

const DEFAULT_PROMPT_TEMPLATES = [
  {
    label: "谨慎探路",
    fill: "我先观察周围环境和在场人物，不急着表态，想弄清这里的规矩与机会。",
  },
  {
    label: "试探问讯",
    fill: "我向面前的人拱手询问此地来历、可去之处，以及适合我这种初入仙门之人的路数。",
  },
  {
    label: "开始修炼",
    fill: "我找一处相对安静的地方，尝试运转主修功法，先感受体内灵气是否能顺畅流转。",
  },
];

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
  director_lead_in: {
    channel: "冲突引子",
    speaker: "引子旁白",
    role: "紧张铺垫",
  },
  director_wrap_up: {
    channel: "冲突余波",
    speaker: "余波旁白",
    role: "情绪缓冲",
  },
  narrator_agent: {
    channel: "场景旁白",
    speaker: "系统旁白",
    role: "叙事过渡",
  },
  heuristic: {
    channel: "过渡旁白",
    speaker: "系统旁白",
    role: "回退叙述",
  },
  cultivation_progress: {
    channel: "修行回响",
    speaker: "系统旁白",
    role: "成长反馈",
  },
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function setText(element, value) {
  if (element) {
    element.textContent = value;
  }
}

function readStoredValue(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (error) {
    return null;
  }
}

function storeValue(key, value) {
  try {
    if (value === null || value === undefined || value === "") {
      window.localStorage.removeItem(key);
      return;
    }
    window.localStorage.setItem(key, String(value));
  } catch (error) {
    // Ignore localStorage failures so the page can still run in private contexts.
  }
}

function isPersistenceUnavailable() {
  return persistenceAvailable === false;
}

function hasConnectedUser() {
  return Number.isInteger(Number(currentUser?.id));
}

function isConnectedUserSynced() {
  return hasConnectedUser() && saveUsernameInput.value.trim() === String(currentUser?.username || "").trim();
}

function canUsePersistence() {
  return !isPersistenceUnavailable() && isConnectedUserSynced();
}

function setConnectedUser(user) {
  currentUser = user || null;
  if (currentUser?.username) {
    saveUsernameInput.value = currentUser.username;
    storeValue(PERSISTENCE_STORAGE_KEYS.username, currentUser.username);
  }
  storeValue(PERSISTENCE_STORAGE_KEYS.userId, currentUser?.id || "");
}

function setSelectedPlayer(playerId) {
  const normalized = Number(playerId);
  selectedPlayerId = Number.isFinite(normalized) && normalized > 0 ? normalized : null;
  storeValue(PERSISTENCE_STORAGE_KEYS.playerId, selectedPlayerId || "");
}

function setCurrentPlayer(playerId) {
  const normalized = Number(playerId);
  currentPlayerId = Number.isFinite(normalized) && normalized > 0 ? normalized : null;
  if (currentPlayerId) {
    setSelectedPlayer(currentPlayerId);
  }
}

function resolveSelectedPlayer() {
  return players.find((item) => Number(item?.id) === Number(selectedPlayerId)) || null;
}

function resolveCurrentPlayer() {
  return players.find((item) => Number(item?.id) === Number(currentPlayerId)) || null;
}

function deriveDefaultSlotName() {
  const fallbackProfile = normalizeProfile(latestState?.player_profile || {});
  const name = playerNameInput.value.trim() || fallbackProfile.name || "新存档";
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  const hour = String(now.getHours()).padStart(2, "0");
  const minute = String(now.getMinutes()).padStart(2, "0");
  return `${name} · ${month}/${day} ${hour}:${minute}`;
}

function ensureSlotNameDraft({ force = false } = {}) {
  if (force || !slotNameInput.value.trim()) {
    slotNameInput.value = deriveDefaultSlotName();
  }
}

function resolvePlayerSceneLabel(player) {
  const scene =
    normalizeDisplayText(player?.current_scene_location_id, "") ||
    normalizeDisplayText(player?.current_scene_id, "") ||
    "未进入场景";
  const beat = normalizeDisplayText(player?.current_scene_beat, "") || "等待开局";
  return `${scene} / ${beat}`;
}

function resolvePlayerSaveLabel(player) {
  const savedAt = player?.last_saved_at;
  if (!savedAt) {
    return "尚未手动存档";
  }
  return `最近保存 ${formatDateTime(savedAt)}`;
}

function setSaveStatus(text, tone = "warning") {
  setText(saveStatusChip, text);
  saveStatusChip.classList.remove("status-chip-success", "status-chip-warning", "status-chip-danger");
  if (tone === "success") {
    saveStatusChip.classList.add("status-chip-success");
    return;
  }
  if (tone === "danger") {
    saveStatusChip.classList.add("status-chip-danger");
    return;
  }
  if (tone === "warning") {
    saveStatusChip.classList.add("status-chip-warning");
  }
}

function renderSaveEmptyState(title, description) {
  saveSlotList.innerHTML = `
    <div class="save-empty">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(description)}</p>
    </div>
  `;
}

function renderSaveSummary() {
  const currentPlayer = resolveCurrentPlayer();
  const selectedPlayer = resolveSelectedPlayer();
  const focusPlayer = currentPlayer || selectedPlayer;

  if (hasConnectedUser() && !isConnectedUserSynced()) {
    activePlayerLabel.textContent = "账号待确认";
    activeSaveMeta.textContent = "你已经修改了账号输入框，点击“连接账号”后会读取新账号下的存档。";
    return;
  }

  if (!hasConnectedUser()) {
    activePlayerLabel.textContent = "未载入存档";
    activeSaveMeta.textContent = isPersistenceUnavailable()
      ? "当前服务还没有启用数据库，存档列表和手动存档会保持不可用。"
      : "连接账号后可以继续游戏、再开一局或执行手动存档。";
    return;
  }

  if (!focusPlayer) {
    activePlayerLabel.textContent = "尚未选择存档";
    activeSaveMeta.textContent = players.length
      ? "先从左侧列表选中一个存档，然后继续游戏或进行手动存档。"
      : "该账号下还没有存档，可以直接点击“再开一局”创建新的角色槽位。";
    return;
  }

  activePlayerLabel.textContent = focusPlayer.slot_name || `存档 #${focusPlayer.id}`;
  activeSaveMeta.textContent = `${resolvePlayerSceneLabel(focusPlayer)} · ${resolvePlayerSaveLabel(focusPlayer)}`;
}

function renderSaveSlotList() {
  if (isPersistenceUnavailable()) {
    renderSaveEmptyState("数据库未启用", "后端当前没有配置数据库连接，暂时无法读取或写入存档。");
    renderSaveSummary();
    return;
  }

  if (hasConnectedUser() && !isConnectedUserSynced()) {
    renderSaveEmptyState("账号已变更", "点击“连接账号”后，将切换到新的用户名并重新拉取存档列表。");
    renderSaveSummary();
    return;
  }

  if (!hasConnectedUser()) {
    renderSaveEmptyState("先连接账号", "输入一个玩家账号并连接后，这里会展示该用户名下的全部存档。");
    renderSaveSummary();
    return;
  }

  if (!players.length) {
    renderSaveEmptyState("该账号下暂无存档", "可以直接点击“再开一局”创建第一个角色槽位。");
    renderSaveSummary();
    return;
  }

  saveSlotList.innerHTML = players
    .map((player) => {
      const playerId = Number(player?.id || 0);
      const isSelected = playerId === Number(selectedPlayerId);
      const isCurrent = playerId === Number(currentPlayerId);
      const slotName = normalizeDisplayText(player?.slot_name, `存档 #${playerId}`);
      const statusText = player?.story_initialized ? "可继续" : "待开局";
      const savedAt = player?.last_saved_at ? formatDateTime(player.last_saved_at) : "暂无";
      return `
        <button
          class="save-slot-card${isSelected ? " is-selected" : ""}${isCurrent ? " is-current" : ""}"
          type="button"
          data-player-id="${playerId}"
        >
          <div class="save-slot-top">
            <strong>${escapeHtml(slotName)}</strong>
            <span class="save-slot-pill${isCurrent ? " is-current" : ""}">${escapeHtml(
              isCurrent ? "当前存档" : statusText,
            )}</span>
          </div>
          <p>${escapeHtml(resolvePlayerSceneLabel(player))}</p>
          <div class="save-slot-meta">
            <span class="save-slot-pill">${escapeHtml(`轮次 ${Number(player?.current_scene_index || 0) + 1}`)}</span>
            <span class="save-slot-pill">${escapeHtml(savedAt)}</span>
          </div>
        </button>
      `;
    })
    .join("");

  renderSaveSummary();
}

function looksCorruptedText(value) {
  const text = String(value || "").trim();
  if (!text) {
    return false;
  }
  return /[ÃÂÆÐØÞßà-ÿ]/.test(text) && !/[\u4e00-\u9fff]/.test(text);
}

function normalizeDisplayText(value, fallback = "") {
  const text = String(value || "").trim();
  if (!text || looksCorruptedText(text)) {
    return fallback;
  }
  return text;
}

function stripTrailingSentenceMarks(value, fallback = "") {
  let text = normalizeDisplayText(value, fallback);
  while (text && /[。！？!?；;…]$/.test(text)) {
    text = text.slice(0, -1).trimEnd();
  }
  return text || fallback;
}

function formatModeLabel(mode) {
  return MODE_LABELS[mode] || mode || MODE_LABELS.speak;
}

function formatTurnLabel(turn) {
  const parsed = Number(turn);
  if (!Number.isFinite(parsed)) {
    return "当前轮次";
  }
  return `第 ${parsed + 1} 轮`;
}

function formatClock(value) {
  return timeFormatter.format(new Date(value));
}

function formatDateTime(value) {
  return datetimeFormatter.format(new Date(value));
}

function inferDraftMode(text) {
  const value = text.trim().toLowerCase();
  if (!value) {
    return latestState?.next_act?.mode || "speak";
  }

  const interruptTokens = ["interrupt", "cut in", "stop", "hold on", "打断", "等等", "先别", "住手"];
  if (interruptTokens.some((token) => value.includes(token))) {
    return "interrupt";
  }

  const actionTokens = [
    "move",
    "step",
    "push",
    "grab",
    "walk",
    "attack",
    "open",
    "search",
    "look",
    "移动",
    "靠近",
    "拿起",
    "拔剑",
    "出手",
    "探查",
    "搜寻",
    "观察",
    "修炼",
    "运转功法",
  ];
  if (actionTokens.some((token) => value.includes(token))) {
    return "action";
  }

  return "speak";
}

function setPipelineState(active) {
  [stepCapture, stepParse, stepCommit].forEach((step) => {
    step.classList.remove("is-active");
    step.classList.remove("is-done");
  });

  if (active === "capture") {
    stepCapture.classList.add("is-active");
    return;
  }

  if (active === "parse") {
    stepCapture.classList.add("is-done");
    stepParse.classList.add("is-active");
    return;
  }

  if (active === "commit") {
    stepCapture.classList.add("is-done");
    stepParse.classList.add("is-done");
    stepCommit.classList.add("is-active");
    return;
  }

  stepCapture.classList.add("is-active");
}

function setBusy(nextBusy) {
  isBusy = nextBusy;
  syncControlsFromState();
}

function setSidebarMode(nextMode) {
  sidebarMode = nextMode === "live" ? "live" : "setup";
  profileFlipbook.classList.toggle("is-live", sidebarMode === "live");
}

function syncSidebarModeFromState(state = latestState) {
  if (state?.story_initialized) {
    setSidebarMode("live");
    return;
  }
  setSidebarMode("setup");
}

function setBackpackOpen(nextOpen) {
  const backpack = Array.isArray(latestState?.player_profile?.backpack)
    ? latestState.player_profile.backpack
    : [];
  const count = backpack.reduce((sum, item) => sum + Number(item?.quantity || 0), 0);

  isBackpackOpen = Boolean(nextOpen) && Boolean(latestState?.story_initialized);
  backpackDrawer.hidden = !isBackpackOpen;
  toggleBackpackButton.textContent = isBackpackOpen ? `收起背包 (${count})` : `背包 (${count})`;
}

function syncControlsFromState(state = latestState) {
  const storyInitialized = Boolean(state?.story_initialized);
  const sceneFinished = Boolean(state?.scene_finished);
  const hasDraft = Boolean(playerInput.value.trim());
  const saveUiUnavailable = isPersistenceUnavailable();
  const userConnected = hasConnectedUser();
  const userSynced = isConnectedUserSynced();
  const persistenceReady = canUsePersistence();

  startSceneButton.textContent = storyInitialized
    ? persistenceReady
      ? "再开一局"
      : "重新开局"
    : "开局";
  restartSceneButton.textContent = persistenceReady ? "再开一局" : "重新开局";
  submitButton.disabled = isBusy || !storyInitialized || sceneFinished || !hasDraft;
  clearButton.disabled = isBusy || !playerInput.value;
  startSceneButton.disabled = isBusy;
  restartSceneButton.disabled = isBusy;
  editProfileButton.disabled = isBusy;
  toggleBackpackButton.disabled = isBusy || !storyInitialized;
  playerInput.disabled = isBusy || !storyInitialized || sceneFinished;
  narrationStylePresetInput.disabled = isBusy;
  jsonCopyButton.disabled = !latestJsonText;
  saveUsernameInput.disabled = isBusy || saveUiUnavailable;
  ensureUserButton.disabled = isBusy || saveUiUnavailable || !saveUsernameInput.value.trim();
  refreshPlayersButton.disabled = isBusy || saveUiUnavailable || !userSynced;
  slotNameInput.disabled = isBusy || saveUiUnavailable || !userConnected;
  loadPlayerButton.disabled = isBusy || !persistenceReady || !selectedPlayerId;
  newGameButton.disabled = isBusy || !persistenceReady;
  saveGameButton.disabled = isBusy || !persistenceReady || !currentPlayerId;

  profileInputs.forEach((input) => {
    input.disabled = isBusy;
  });

  hintButtons.forEach((button) => {
    button.disabled = isBusy || !storyInitialized || sceneFinished;
  });

  renderSaveSummary();
}

function syncInputMeta() {
  const text = playerInput.value;
  inputCount.textContent = `${text.length} 字`;
  modePreview.textContent = `预计模式：${formatModeLabel(inferDraftMode(text))}`;
  syncControlsFromState();
}

function resolveNarrationStyleOptions(state = latestState) {
  const options = Array.isArray(state?.available_narration_styles)
    ? state.available_narration_styles
    : [];
  if (!options.length) {
    return DEFAULT_NARRATION_STYLE_OPTIONS;
  }

  return options.map((option) => {
    const fallback = DEFAULT_NARRATION_STYLE_OPTIONS.find(
      (candidate) => candidate.value === option?.value,
    );
    return {
      value: option?.value || fallback?.value || "xianxia_default",
      label: fallback?.label || option?.label || option?.value || "仙侠默认",
      description: fallback?.description || option?.description || "",
    };
  });
}

function updateNarrationStyleHint(state = latestState) {
  const options = resolveNarrationStyleOptions(state);
  const selectedValue =
    narrationStylePresetInput.value ||
    state?.narration_style_preset ||
    DEFAULT_NARRATION_STYLE_OPTIONS[0].value;
  const selectedOption =
    options.find((option) => option.value === selectedValue) || options[0] || null;

  if (selectedOption) {
    narrationStylePresetInput.value = selectedOption.value;
  }
  setText(narrationStyleHint, selectedOption?.description || "");
}

function renderNarrationStyleControls(state) {
  const options = resolveNarrationStyleOptions(state);
  const selectedValue =
    state?.narration_style_preset ||
    narrationStylePresetInput.value ||
    DEFAULT_NARRATION_STYLE_OPTIONS[0].value;

  narrationStylePresetInput.innerHTML = "";
  options.forEach((option) => {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label || option.value;
    narrationStylePresetInput.appendChild(element);
  });

  if (options.some((option) => option.value === selectedValue)) {
    narrationStylePresetInput.value = selectedValue;
  } else if (options[0]) {
    narrationStylePresetInput.value = options[0].value;
  }

  updateNarrationStyleHint(state);
}

function normalizeProfile(profile = {}) {
  return {
    name: profile.name || "无名修士",
    gender: profile.gender || "未定",
    race: profile.race || "人族",
    background: profile.background || "出身凡俗，尚未真正看清自己的仙途。",
    spiritual_root: profile.spiritual_root || DEFAULT_SPIRITUAL_ROOT,
    realm: profile.realm || DEFAULT_REALM,
    main_technique: profile.main_technique || DEFAULT_MAIN_TECHNIQUE,
    backpack: Array.isArray(profile.backpack) ? profile.backpack : [],
  };
}

function populateProfileForm(profile) {
  const resolved = normalizeProfile(profile);
  playerNameInput.value = resolved.name;
  playerGenderInput.value = resolved.gender;
  playerRaceInput.value = resolved.race;
  playerSpiritualRootInput.value = resolved.spiritual_root;
  playerRealmInput.value = resolved.realm;
  playerMainTechniqueInput.value = resolved.main_technique;
  playerBackgroundInput.value = resolved.background;
}

function buildPromptTemplatesFromState(state = latestState) {
  const templates = Array.isArray(state?.prompt_templates) ? state.prompt_templates : [];
  if (templates.length) {
    return templates
      .map((item) => ({
        label: normalizeDisplayText(item?.label, ""),
        fill: normalizeDisplayText(item?.fill, ""),
      }))
      .filter((item) => item.label && item.fill);
  }

  const sceneGoal = stripTrailingSentenceMarks(
    state?.scene_goal || state?.chapter_goal || DEFAULT_SCENE_GOAL,
    DEFAULT_SCENE_GOAL,
  );
  const sceneLocation = state?.scene_location || DEFAULT_SCENE_LOCATION;
  const beatGoal = stripTrailingSentenceMarks(state?.beat_goal || sceneGoal, sceneGoal);
  const chapterGoal = stripTrailingSentenceMarks(state?.chapter_goal || sceneGoal, sceneGoal);
  return [
    {
      label: "谨慎探路",
      fill: `我先不急着出手，先观察${sceneLocation}附近的环境、人物和气氛，重点确认哪些线索能帮助我推进“${sceneGoal}”。`,
    },
    {
      label: "试探问讯",
      fill: `我向在场人物试探打听消息，想知道这里最值得接触的人、能获取的资源，以及和“${chapterGoal || beatGoal}”有关的方向。`,
    },
    {
      label: "开始修炼",
      fill: `我先尝试运转主修功法，感受灵气流转是否顺畅，再判断这一步是否有助于推进“${sceneGoal}”。`,
    },
  ];
}

function renderHints(state) {
  const hints = buildPromptTemplatesFromState(state);
  hintButtons.forEach((button, index) => {
    const hint = hints[index] || DEFAULT_PROMPT_TEMPLATES[index];
    if (!hint) {
      return;
    }
    button.textContent = hint.label;
    button.dataset.fill = hint.fill;
  });
}

function getHistoryEntryKey(entry) {
  return [
    entry?.turn ?? "",
    entry?.actor ?? "",
    entry?.mode ?? "",
    entry?.speaker ?? "",
    entry?.content ?? "",
    entry?.spoken_text ?? "",
    entry?.nonverbal_action ?? "",
  ].join("::");
}

function resolveHistoryTimestamp(entry) {
  const key = getHistoryEntryKey(entry);
  if (!messageTimestampCache.has(key)) {
    messageTimestampCache.set(key, Date.now() + messageTimestampCache.size);
  }
  return messageTimestampCache.get(key);
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
    const narrationPresentation = NARRATION_PRESENTATION_MAP[narrationSource] || {
      channel: "系统旁白",
      speaker: "系统旁白",
      role: "叙事过渡",
    };
    return {
      variant: "system",
      tone: "system-narration",
      channel: narrationPresentation.channel,
      speaker: narrationPresentation.speaker,
      role: narrationPresentation.role,
      primaryBadge: narrationPresentation.channel,
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

function scrollHistoryToBottom() {
  window.requestAnimationFrame(() => {
    storyFeed.scrollTop = storyFeed.scrollHeight;
  });
}

function renderHistory(history) {
  const entries = Array.isArray(history) ? history : [];
  storyFeed.innerHTML = "";

  if (!entries.length) {
    storyFeed.innerHTML = `
      <div class="chat-empty">
        <strong>等待剧情开始</strong>
        <p>发送一条消息后，这里会分层展示你的行动、角色回应、系统旁白与功能回执。</p>
      </div>
    `;
    return;
  }

  entries.forEach((entry) => {
    const presentation = classifyMessage(entry);
    const timestamp = resolveHistoryTimestamp(entry);
    const article = document.createElement("article");
    article.className = ["message-card", presentation.variant, presentation.tone].filter(Boolean).join(" ");
    article.innerHTML = `
      <div class="message-top">
        <div class="message-copy">
          <span class="message-channel">${escapeHtml(presentation.channel)}</span>
          <strong>${escapeHtml(presentation.speaker)}</strong>
          <span class="message-role">${escapeHtml(presentation.role)}</span>
        </div>
        <div class="message-meta-line">
          <span class="message-badge">${escapeHtml(presentation.primaryBadge)}</span>
          <span class="message-badge">${escapeHtml(formatTurnLabel(entry?.turn))}</span>
          <span class="message-badge">${escapeHtml(formatClock(timestamp))}</span>
        </div>
      </div>
      <p class="message-content">${escapeHtml(resolveMessageContent(entry))}</p>
    `;
    storyFeed.appendChild(article);
  });

  scrollHistoryToBottom();
}

function renderParsedAct(parsedAct) {
  const payload = parsedAct || latestState?.player?.last_parsed_act || null;
  const nextAct = latestState?.next_act || {};
  summaryMode.textContent = formatModeLabel(payload?.mode || nextAct.mode || "speak");
  summaryTarget.textContent = payload?.target || nextAct.target || "当前场景";
  summaryIntent.textContent =
    payload?.next_intent ||
    latestState?.chapter_transition_requirement ||
    latestState?.chapter_goal ||
    latestState?.scene_goal ||
    DEFAULT_SCENE_GOAL;
}

function renderBackpack(items) {
  const backpack = Array.isArray(items) ? items : [];
  playerBackpackList.innerHTML = "";

  if (!backpack.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "inventory-empty";
    emptyItem.textContent = DEFAULT_BACKPACK_EMPTY_TEXT;
    playerBackpackList.appendChild(emptyItem);
    setBackpackOpen(false);
    return;
  }

  backpack.forEach((item) => {
    const label = item.name || item.id || "未知道具";
    const icon = String(label).trim().slice(0, 1) || "?";
    const row = document.createElement("li");
    row.className = "inventory-item";
    row.innerHTML = `
      <div class="inventory-main">
        <span class="inventory-icon">${escapeHtml(icon)}</span>
        <div class="inventory-copy">
          <span class="inventory-name">${escapeHtml(label)}</span>
          <small class="inventory-id">${escapeHtml(item.id || "背包物品")}</small>
        </div>
      </div>
      <span class="inventory-count">x${escapeHtml(String(item.quantity || 0))}</span>
    `;
    playerBackpackList.appendChild(row);
  });

  setBackpackOpen(isBackpackOpen);
}

function deriveProfileStats(state) {
  const chapterIndex = Number(state?.current_chapter_index || 0);
  const sceneIndex = Number(state?.current_scene_index || 0);
  const tension = Number(state?.tension_percent || 0);
  const level = Math.max(1, chapterIndex + 1);
  const hpValue = Math.max(36, 100 - tension);
  const expValue = Math.min(96, 12 + sceneIndex * 18 + Math.round(tension * 0.2));
  const statusText = !state?.story_initialized
    ? "待初始化"
    : state?.scene_finished
    ? "场景结束"
    : tension >= 70
    ? "高压中"
    : "探索中";

  return {
    level: `Lv.${String(level).padStart(2, "0")}`,
    hp: `${hpValue} / 100`,
    exp: `${expValue}%`,
    status: statusText,
  };
}

function renderProfile(state) {
  const profile = normalizeProfile(state.player_profile || {});
  const storyPremise = normalizeDisplayText(state.story_premise, "");
  const explorationDrive = normalizeDisplayText(state.exploration_drive, "");
  const outline = Array.isArray(state?.story_outline) ? state.story_outline : [];
  const outlinePreview = outline
    .slice(0, 3)
    .map((entry) => String(entry?.title || "").trim())
    .filter(Boolean)
    .join(" / ");
  const transitionRequirement = normalizeDisplayText(state.chapter_transition_requirement, "");
  const stats = deriveProfileStats(state);
  const avatarText = String(profile.name || "修").trim().slice(0, 1) || "修";

  playerCardName.textContent = profile.name;
  playerCardLine.textContent = `${profile.gender} / ${profile.race} / ${profile.background}`;
  playerRootValue.textContent = profile.spiritual_root;
  playerRootLine.textContent = `当前境界：${profile.realm} · 主修功法：${profile.main_technique}`;

  sidebarPlayerAvatar.textContent = avatarText;
  sidebarPlayerName.textContent = profile.name;
  sidebarPlayerMeta.textContent = `${profile.gender} / ${profile.race}`;
  sidebarRealmText.textContent = `${profile.realm} · ${profile.main_technique}`;
  controlBadge.textContent = `当前操控：${profile.name}`;
  currentIdentityNote.textContent = `${profile.name} / ${profile.spiritual_root} / ${profile.realm} / ${profile.main_technique}`;

  const noteText =
    storyPremise ||
    transitionRequirement ||
    explorationDrive ||
    (outlinePreview ? `近期章节线索：${outlinePreview}` : "") ||
    "这名角色尚在摸索自己的仙途，当前最重要的是观察、结交与积累。";

  identityNote.textContent = noteText;
  sidebarStatusText.textContent =
    normalizeDisplayText(state.handoff_reason, "") ||
    normalizeDisplayText(state.current_chapter_overview, "") ||
    "等待故事初始化，准备写下第一步行动。";
  playerLevelValue.textContent = stats.level;
  playerHpValue.textContent = stats.hp;
  playerExpValue.textContent = stats.exp;
  playerStateValue.textContent = stats.status;

  renderBackpack(profile.backpack);
}

function renderJsonPanel(payload, { label = "最新返回" } = {}) {
  latestJsonText = JSON.stringify(payload || {}, null, 2);
  parserJson.textContent = latestJsonText;
  jsonMeta.textContent = `${label} · ${formatDateTime(Date.now())}`;
  syncControlsFromState();
}

function setJsonCollapsed(nextCollapsed) {
  isJsonCollapsed = nextCollapsed;
  jsonPanel.classList.toggle("is-collapsed", isJsonCollapsed);
  jsonPanelBody.hidden = isJsonCollapsed;
  jsonToggleButton.textContent = isJsonCollapsed ? "展开" : "折叠";
  jsonToggleButton.setAttribute("aria-expanded", String(!isJsonCollapsed));
}

async function copyLatestJson() {
  if (!latestJsonText) {
    return;
  }

  const previousLabel = jsonCopyButton.textContent;
  try {
    await navigator.clipboard.writeText(latestJsonText);
    jsonCopyButton.textContent = "已复制";
  } catch (error) {
    jsonCopyButton.textContent = "复制失败";
  }

  window.setTimeout(() => {
    jsonCopyButton.textContent = previousLabel;
  }, 1200);
}

function renderState(state, { jsonLabel = "状态快照", jsonPayload = null } = {}) {
  latestState = state;
  populateProfileForm(state.player_profile);
  ensureSlotNameDraft();
  renderNarrationStyleControls(state);
  renderProfile(state);
  renderHints(state);
  renderHistory(state.history || []);
  renderParsedAct(state.player?.last_parsed_act);
  renderJsonPanel(jsonPayload || state, { label: jsonLabel });
  syncSidebarModeFromState(state);

  const chapterTitle = normalizeDisplayText(state.current_chapter_title, "开场章节");
  const chapterGoal =
    normalizeDisplayText(state.chapter_goal, "") ||
    normalizeDisplayText(state.chapter_transition_requirement, "") ||
    normalizeDisplayText(state.scene_goal, "") ||
    normalizeDisplayText(state.cultivation_goal, "") ||
    DEFAULT_SCENE_GOAL;
  const chapterHint =
    normalizeDisplayText(state.current_chapter_overview, "") ||
    normalizeDisplayText(state.chapter_transition_requirement, "") ||
    normalizeDisplayText(state.scene_goal, "") ||
    normalizeDisplayText(state.story_premise, "") ||
    normalizeDisplayText(state.beat_goal, "") ||
    "";

  sceneGoalValue.textContent = chapterGoal;
  sceneGoalHint.textContent = chapterHint ? `${chapterTitle} / ${chapterHint}` : chapterTitle;
  sceneChip.textContent = `${normalizeDisplayText(state.scene_location, DEFAULT_SCENE_LOCATION)} / ${normalizeDisplayText(state.scene_time, "时辰未明")} / ${normalizeDisplayText(state.scene_beat, "局势初开")}`;

  liveRound.textContent = `第 ${String(state.upcoming_round || 1).padStart(2, "0")} 轮`;
  liveMood.textContent = !state.story_initialized
    ? "正在准备开场叙事与可交互局面……"
    : state.scene_finished
    ? "当前场景已结束。"
    : normalizeDisplayText(state.handoff_reason, "") ||
      normalizeDisplayText(state.scene_end_reason, "") ||
      "等待你决定下一步行动。";
  tensionValue.textContent = String(state.tension_percent ?? 0);
  jsonTensionValue.textContent = String(state.tension_percent ?? 0);
  jsonRoundValue.textContent = `第 ${String(state.upcoming_round || 1).padStart(2, "0")} 轮`;
  jsonPlayerValue.textContent = normalizeDisplayText(
    state.player_name,
    normalizeProfile(state.player_profile || {}).name,
  );
  setText(parserStatus, normalizeDisplayText(state.parser_status, "待命"));
  runtimeModeText.textContent =
    normalizeDisplayText(state.handoff_reason, "") ||
    normalizeDisplayText(state.chapter_transition_requirement, "") ||
    normalizeDisplayText(state.current_chapter_overview, "") ||
    normalizeDisplayText(state.memory_summary, "") ||
    "局势正在推进，随时可以衔接你的下一次行动。";

  startSceneButton.textContent = state.story_initialized ? "重新开局" : "开局";
  restartSceneButton.textContent = canUsePersistence() ? "再开一局" : "重新开局";
  syncInputMeta();
  syncControlsFromState(state);
}

async function requestJson(url, options = {}) {
  const {
    timeoutMs = REQUEST_TIMEOUT_MS,
    timeoutMessage = "请求等待超过 300 秒，请稍后重试。",
    ...fetchOptions
  } = options;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
      },
      signal: controller.signal,
      ...fetchOptions,
    });

    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      if (!response.ok) {
        throw new Error("服务端返回了无法解析的响应。");
      }
    }

    if (!response.ok) {
      throw new Error(payload.error || "请求失败。");
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(timeoutMessage);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function renderRequestError(statusText, error) {
  const message = error?.message || "请求失败。";
  setText(parserStatus, statusText);
  runtimeModeText.textContent = message;
  liveMood.textContent = message;
  renderJsonPanel({ error: message }, { label: statusText });
}

function clearPlayerDraft({ resetPipeline = false } = {}) {
  playerInput.value = "";
  syncInputMeta();
  if (resetPipeline) {
    setPipelineState("capture");
  }
}

function buildResetPayload() {
  return {
    player_profile: {
      name: playerNameInput.value.trim(),
      gender: playerGenderInput.value.trim(),
      race: playerRaceInput.value.trim(),
      spiritual_root: playerSpiritualRootInput.value.trim(),
      realm: playerRealmInput.value.trim(),
      main_technique: playerMainTechniqueInput.value.trim(),
      background: playerBackgroundInput.value.trim(),
      backpack: latestState?.player_profile?.backpack || [],
    },
    narration_style_preset: narrationStylePresetInput.value,
  };
}

function isPersistenceDisabledError(error) {
  return String(error?.message || "").includes("数据库未配置");
}

function applyPlayerCollection(nextPlayers, { preferredPlayerId = null } = {}) {
  players = Array.isArray(nextPlayers) ? nextPlayers : [];

  const availableIds = new Set(
    players
      .map((item) => Number(item?.id || 0))
      .filter((value) => Number.isFinite(value) && value > 0),
  );

  if (preferredPlayerId && availableIds.has(Number(preferredPlayerId))) {
    setSelectedPlayer(preferredPlayerId);
  } else if (selectedPlayerId && !availableIds.has(Number(selectedPlayerId))) {
    setSelectedPlayer(null);
  }

  if (currentPlayerId && !availableIds.has(Number(currentPlayerId))) {
    currentPlayerId = null;
  }

  if (!selectedPlayerId && currentPlayerId && availableIds.has(Number(currentPlayerId))) {
    setSelectedPlayer(currentPlayerId);
  }

  if (!selectedPlayerId && players[0]?.id) {
    setSelectedPlayer(players[0].id);
  }

  renderSaveSlotList();
  syncControlsFromState();
}

function handlePersistenceUnavailable(error) {
  persistenceAvailable = false;
  players = [];
  currentPlayerId = null;
  setConnectedUser(null);
  setSelectedPlayer(null);
  setSaveStatus("数据库未启用", "danger");
  activeSaveMeta.textContent = error?.message || "后端当前没有配置数据库连接。";
  renderSaveSlotList();
  syncControlsFromState();
}

async function ensurePersistenceUser({ quiet = false, refresh = true } = {}) {
  const username = saveUsernameInput.value.trim();
  if (!username) {
    setConnectedUser(null);
    players = [];
    setSelectedPlayer(null);
    renderSaveSlotList();
    syncControlsFromState();
    if (!quiet) {
      setSaveStatus("请先填写账号", "warning");
    }
    return null;
  }

  try {
    const payload = await requestJson(API.ensureUser, {
      method: "POST",
      body: JSON.stringify({
        username,
        display_name: username,
      }),
    });

    persistenceAvailable = true;
    setConnectedUser(payload.user || null);
    setSaveStatus(`账号已连接：${payload.user?.display_name || payload.user?.username || username}`, "success");

    if (refresh) {
      await refreshPlayerSlots({ quiet: true, preferredPlayerId: selectedPlayerId });
    } else {
      renderSaveSlotList();
      syncControlsFromState();
    }

    return payload.user || null;
  } catch (error) {
    if (isPersistenceDisabledError(error)) {
      handlePersistenceUnavailable(error);
      return null;
    }
    if (!quiet) {
      setSaveStatus(error?.message || "账号连接失败", "danger");
    }
    throw error;
  }
}

async function refreshPlayerSlots({ quiet = false, preferredPlayerId = null } = {}) {
  if (!canUsePersistence()) {
    renderSaveSlotList();
    syncControlsFromState();
    return players;
  }

  try {
    const payload = await requestJson(`${API.players}?user_id=${encodeURIComponent(currentUser.id)}`);
    persistenceAvailable = true;
    applyPlayerCollection(payload.players, { preferredPlayerId });
    if (!quiet) {
      setSaveStatus(players.length ? `已加载 ${players.length} 个存档` : "账号已连接，暂无存档", players.length ? "success" : "warning");
    }
    return players;
  } catch (error) {
    if (isPersistenceDisabledError(error)) {
      handlePersistenceUnavailable(error);
      return [];
    }
    if (!quiet) {
      setSaveStatus(error?.message || "读取存档失败", "danger");
    }
    throw error;
  }
}

async function handleLoadSelectedPlayer() {
  if (isBusy || !canUsePersistence() || !selectedPlayerId) {
    return;
  }

  setBusy(true);
  setSaveStatus("正在载入存档", "warning");
  setText(parserStatus, "正在载入存档");
  runtimeModeText.textContent = "正在从数据库恢复角色、剧情角色和世界状态……";
  jsonMeta.textContent = "等待存档读取返回……";

  try {
    const response = await requestJson(API.load, {
      method: "POST",
      body: JSON.stringify({
        user_id: currentUser.id,
        player_id: selectedPlayerId,
      }),
    });

    persistenceAvailable = true;
    setCurrentPlayer(response.player?.id);
    renderState(response.state, {
      jsonLabel: "载入存档返回",
      jsonPayload: response,
    });
    clearPlayerDraft({ resetPipeline: true });
    setBackpackOpen(false);
    setPipelineState("capture");
    await refreshPlayerSlots({ quiet: true, preferredPlayerId: response.player?.id });
    setSaveStatus(`已载入：${response.player?.slot_name || `存档 #${response.player?.id}`}`, "success");
  } catch (error) {
    if (isPersistenceDisabledError(error)) {
      handlePersistenceUnavailable(error);
    } else {
      setSaveStatus(error?.message || "载入存档失败", "danger");
      renderRequestError("载入存档失败", error);
    }
  } finally {
    setBusy(false);
    syncInputMeta();
  }
}

async function handleSaveCurrentGame() {
  if (isBusy || !canUsePersistence() || !currentPlayerId) {
    return;
  }

  setBusy(true);
  setSaveStatus("正在写入存档", "warning");
  setText(parserStatus, "正在手动存档");
  runtimeModeText.textContent = "正在把当前会话快照写入数据库……";
  jsonMeta.textContent = "等待手动存档返回……";

  try {
    const activePlayer = resolveCurrentPlayer();
    const response = await requestJson(API.save, {
      method: "POST",
      body: JSON.stringify({
        user_id: currentUser.id,
        player_id: currentPlayerId,
        save_kind: "manual",
        save_label: `${activePlayer?.slot_name || deriveDefaultSlotName()} / 手动存档`,
      }),
    });

    persistenceAvailable = true;
    renderState(response.state, {
      jsonLabel: "手动存档返回",
      jsonPayload: response,
    });
    await refreshPlayerSlots({ quiet: true, preferredPlayerId: response.player?.id || currentPlayerId });
    setSaveStatus(`已保存：${response.player?.slot_name || `存档 #${currentPlayerId}`}`, "success");
  } catch (error) {
    if (isPersistenceDisabledError(error)) {
      handlePersistenceUnavailable(error);
    } else {
      setSaveStatus(error?.message || "手动存档失败", "danger");
      renderRequestError("手动存档失败", error);
    }
  } finally {
    setBusy(false);
    syncInputMeta();
  }
}

async function handleCreateNewGame() {
  if (isBusy) {
    return;
  }

  if (!canUsePersistence()) {
    return handleSceneBootstrapLegacy();
  }

  setBusy(true);
  ensureSlotNameDraft();
  const slotName = slotNameInput.value.trim() || deriveDefaultSlotName();
  setSaveStatus("正在创建新存档", "warning");
  setText(parserStatus, "正在创建新存档");
  runtimeModeText.textContent = "正在根据当前角色设定创建新的角色槽位……";
  jsonMeta.textContent = "等待新开存档返回……";

  try {
    const response = await requestJson(API.newGame, {
      method: "POST",
      timeoutMs: RESET_REQUEST_TIMEOUT_MS,
      timeoutMessage: "新开一局超过 300 秒，请稍后重试。",
      body: JSON.stringify({
        user_id: currentUser.id,
        slot_name: slotName,
        save_label: `${slotName} / 开局快照`,
        ...buildResetPayload(),
      }),
    });

    persistenceAvailable = true;
    setCurrentPlayer(response.player?.id);
    renderState(response.state, {
      jsonLabel: "新开存档返回",
      jsonPayload: response,
    });
    clearPlayerDraft();
    setSidebarMode("live");
    setBackpackOpen(false);
    setPipelineState("capture");
    await refreshPlayerSlots({ quiet: true, preferredPlayerId: response.player?.id });
    setSaveStatus(`新存档已创建：${response.player?.slot_name || slotName}`, "success");
  } catch (error) {
    if (isPersistenceDisabledError(error)) {
      handlePersistenceUnavailable(error);
      return handleSceneBootstrapLegacy();
    }
    setSaveStatus(error?.message || "创建新存档失败", "danger");
    renderRequestError("创建新存档失败", error);
  } finally {
    setBusy(false);
    syncInputMeta();
  }
}

function bootstrapPersistenceDraft() {
  const storedUsername = readStoredValue(PERSISTENCE_STORAGE_KEYS.username);
  const storedPlayerId = Number(readStoredValue(PERSISTENCE_STORAGE_KEYS.playerId) || 0);

  if (storedUsername) {
    saveUsernameInput.value = storedUsername;
  }
  if (Number.isFinite(storedPlayerId) && storedPlayerId > 0) {
    selectedPlayerId = storedPlayerId;
  }

  setSaveStatus(storedUsername ? "等待连接账号" : "未连接账号", "warning");
  ensureSlotNameDraft();
  renderSaveSlotList();
  syncControlsFromState();
}

async function loadState() {
  setBusy(true);
  jsonMeta.textContent = "正在加载初始状态……";
  try {
    const state = await requestJson(API.state);
    renderState(state, { jsonLabel: "初始化状态" });
    setPipelineState("capture");
  } catch (error) {
    renderRequestError("状态加载失败", error);
  } finally {
    setBusy(false);
    syncInputMeta();
  }
}

async function handleSubmit() {
  if (isBusy) {
    return;
  }

  const draft = playerInput.value.trim();
  if (!draft || !latestState?.story_initialized || latestState?.scene_finished) {
    playerInput.focus();
    return;
  }

  setBusy(true);
  setText(parserStatus, "正在接收输入");
  jsonMeta.textContent = "等待行动返回……";
  setPipelineState("capture");

  try {
    await sleep(120);
    setText(parserStatus, "正在解析意图");
    setPipelineState("parse");

    const state = await requestJson(API.action, {
      method: "POST",
      timeoutMs: ACTION_REQUEST_TIMEOUT_MS,
      timeoutMessage: "行动处理超过 300 秒，请稍后重试。",
      body: JSON.stringify({
        input: draft,
      }),
    });

    await sleep(120);
    setPipelineState("commit");
    renderState(state, { jsonLabel: "行动返回" });
    clearPlayerDraft();
  } catch (error) {
    renderRequestError("行动处理失败", error);
  } finally {
    setBusy(false);
    syncInputMeta();
  }
}

async function handleSceneBootstrap() {
  if (canUsePersistence()) {
    return handleCreateNewGame();
  }
  return handleSceneBootstrapLegacy();
}

async function handleSceneBootstrapLegacy() {
  if (isBusy) {
    return;
  }

  setBusy(true);
  setText(parserStatus, latestState?.story_initialized ? "正在重新开局" : "正在开局");
  runtimeModeText.textContent = "正在根据玩家档案生成当前场景……";
  jsonMeta.textContent = "等待开局返回……";

  try {
    const state = await requestJson(API.reset, {
      method: "POST",
      timeoutMs: RESET_REQUEST_TIMEOUT_MS,
      timeoutMessage: "开局过程超过 300 秒，请稍后重试。",
      body: JSON.stringify(buildResetPayload()),
    });

    currentPlayerId = null;
    clearPlayerDraft();
    renderState(state, { jsonLabel: latestState?.story_initialized ? "重新开局返回" : "开局返回" });
    setSidebarMode("live");
    setBackpackOpen(false);
    setPipelineState("capture");
    renderSaveSlotList();
  } catch (error) {
    renderRequestError("开局失败", error);
  } finally {
    setBusy(false);
    syncInputMeta();
  }
}

hintButtons.forEach((button) => {
  button.addEventListener("click", () => {
    playerInput.value = button.dataset.fill || "";
    setPipelineState("capture");
    syncInputMeta();
    playerInput.focus();
  });
});

narrationStylePresetInput.addEventListener("change", () => {
  updateNarrationStyleHint();
});

saveUsernameInput.addEventListener("input", () => {
  renderSaveSlotList();
  syncControlsFromState();
});

saveUsernameInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    ensurePersistenceUser().catch(() => {});
  }
});

slotNameInput.addEventListener("input", () => {
  syncControlsFromState();
});

saveSlotList.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const trigger = event.target.closest("[data-player-id]");
  if (!trigger || isBusy) {
    return;
  }
  setSelectedPlayer(trigger.dataset.playerId);
  renderSaveSlotList();
  syncControlsFromState();
});

playerInput.addEventListener("input", () => {
  if (!isBusy) {
    setPipelineState("capture");
  }
  syncInputMeta();
});

profileInputs.forEach((input) => {
  input.addEventListener("input", () => {
    if (!slotNameInput.value.trim()) {
      ensureSlotNameDraft({ force: true });
    }
    syncControlsFromState();
  });
});

playerInput.addEventListener("keydown", (event) => {
  if (event.isComposing) {
    return;
  }
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    handleSubmit();
  }
});

clearButton.addEventListener("click", () => {
  clearPlayerDraft({ resetPipeline: true });
});

ensureUserButton.addEventListener("click", () => {
  ensurePersistenceUser().catch(() => {});
});
refreshPlayersButton.addEventListener("click", () => {
  refreshPlayerSlots().catch(() => {});
});
loadPlayerButton.addEventListener("click", handleLoadSelectedPlayer);
newGameButton.addEventListener("click", handleCreateNewGame);
saveGameButton.addEventListener("click", handleSaveCurrentGame);
startSceneButton.addEventListener("click", handleSceneBootstrap);
restartSceneButton.addEventListener("click", handleSceneBootstrap);
editProfileButton.addEventListener("click", () => {
  setSidebarMode("setup");
  setBackpackOpen(false);
  playerNameInput.focus();
});
toggleBackpackButton.addEventListener("click", () => {
  setBackpackOpen(!isBackpackOpen);
});
submitButton.addEventListener("click", handleSubmit);
jsonCopyButton.addEventListener("click", copyLatestJson);
jsonToggleButton.addEventListener("click", () => {
  setJsonCollapsed(!isJsonCollapsed);
});

setJsonCollapsed(false);
setSidebarMode("setup");
setBackpackOpen(false);
setPipelineState("capture");
bootstrapPersistenceDraft();

async function initializeApp() {
  await loadState();
  if (saveUsernameInput.value.trim()) {
    try {
      await ensurePersistenceUser({ quiet: true });
    } catch (error) {
      setSaveStatus(error?.message || "读取存档入口失败", "danger");
    }
  }
}

syncInputMeta();
initializeApp();
