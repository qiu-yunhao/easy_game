import { startRouter, register } from "./router.js";
import { renderEntry } from "./pages/entry.js";
import { renderLogin } from "./pages/login.js";

register("entry", renderEntry);
register("login", renderLogin);
register("select", (el) => { el.innerHTML = `<div class="route-select">选择页占位</div>`; });

const mount = document.getElementById("app");
startRouter(mount);
