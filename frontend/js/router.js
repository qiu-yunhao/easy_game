const routes = {};
export function register(name, renderFn) { routes[name] = renderFn; }
export function navigate(name) { window.location.hash = `#/${name}`; }
function current() {
  const h = window.location.hash.replace(/^#\//, "");
  return h || "entry";
}
export function startRouter(mountEl) {
  const render = () => {
    const name = current();
    const fn = routes[name] || routes["entry"];
    mountEl.innerHTML = "";
    fn(mountEl);
  };
  window.addEventListener("hashchange", render);
  render();
}
