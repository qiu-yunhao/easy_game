import { startRouter, register } from "./router.js";
import { renderEntry } from "./pages/entry.js";
import { renderSelect } from "./pages/select.js";

register("entry", renderEntry);
register("select", renderSelect);

const mount = document.getElementById("app");
startRouter(mount);
