import { startRouter, register } from "./router.js";

register("entry", (el) => { el.innerHTML = `<div class="route-entry">入口占位</div>`; });
register("login", (el) => { el.innerHTML = `<div class="route-login">登录占位</div>`; });
register("select", (el) => { el.innerHTML = `<div class="route-select">选择页占位</div>`; });

const mount = document.getElementById("app");
startRouter(mount);
