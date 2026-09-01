async function postJson(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败：${res.status}`);
  return data;
}
async function getJson(path) {
  const res = await fetch(path);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败：${res.status}`);
  return data;
}

export const api = {
  ensureUser: (username) => postJson("/api/users/ensure", { username }),
  listPlayers: (userId) => getJson(`/api/players?user_id=${encodeURIComponent(userId)}`),
  getState: () => getJson("/api/state"),
  action: (input) => postJson("/api/action", { input }),
  setAuto: (enabled) => postJson("/api/auto", { enabled }),
  autoStep: (maxBeats) => postJson("/api/auto/step", { max_beats: maxBeats }),
  reset: (payload) => postJson("/api/reset", payload),
  newGame: (payload) => postJson("/api/new-game", payload),
  save: (payload) => postJson("/api/save", payload),
  load: (payload) => postJson("/api/load", payload),
  listTemplates: () => getJson("/api/templates"),
  templateDetail: (id) => getJson(`/api/templates/${id}`),
  importTemplate: (payload) => postJson("/api/templates/import", payload),
  selectTemplate: (templateId) => postJson("/api/templates/select", { template_id: templateId }),
  listWorldSettings: () => getJson("/api/world-settings"),
  worldSettingTemplate: (tag) => getJson(`/api/world-settings/${encodeURIComponent(tag)}`),
  startWorldBuilder: (genreTag) => postJson("/api/world-builder/start", genreTag ? { genre_tag: genreTag } : {}),
  resumeWorldBuilder: () => postJson("/api/world-builder/start", { resume: true }),
  getWorldBuilderDraft: () => getJson("/api/world-builder/draft"),
  answerWorldBuilder: (payload) => postJson("/api/world-builder/answer", payload),
  applyWorldBuilder: () => postJson("/api/world-builder/apply", {}),
  addWorldBuilderReference: (templateId, referenceQuery) => postJson("/api/world-builder/reference", { template_id: templateId, reference_query: referenceQuery || "" }),
  writerReview: () => getJson("/api/writer-review"),
  approveWriterReview: (draft) => postJson("/api/writer-review/approve", { draft }),
  rewriteWriterReview: (draft, guidance) => postJson("/api/writer-review/rewrite", { draft, guidance }),
};
