import { navigate } from "../router.js";
export function renderEntry(el) {
  el.innerHTML = `
    <section class="entry-hero">
      <div class="entry-pulse"></div>
      <h1 class="entry-title">Stagebound</h1>
      <p class="entry-sub">修仙叙事台</p>
      <button class="button button-primary entry-enter" type="button">进入</button>
    </section>`;
  el.querySelector(".entry-enter").addEventListener("click", () => navigate("select"));
}
