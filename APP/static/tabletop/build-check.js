// Deploy check (owner 2026-10-21). The server stamps every table module with its build id (?v=<build>) and sends the
// same id in X-Factory-Build on every response. A page whose modules are older than the server reloads itself once,
// with a plain banner, so it never runs half-old and half-new code.
const RELOAD_KEY = "factory-table-reloaded-build";
let announced = false;

export function ownBuild(url = import.meta.url) {
  return new URL(url).searchParams.get("v") || "";
}

// Returns true when the page is stale and a reload has been scheduled.
export function checkBuild(served, own = ownBuild(), {reload = () => globalThis.location?.reload(), storage = globalThis.sessionStorage} = {}) {
  if (!served || !own || served === own) return false;
  if (announced) return true;
  announced = true;
  // Reload only once per served build, so a server that still reports a mismatch cannot loop the page.
  if (storage?.getItem(RELOAD_KEY) === served) {
    showBanner("The game was updated. Refresh this page to continue.");
    return true;
  }
  storage?.setItem(RELOAD_KEY, served);
  showBanner("The game was updated — reloading…");
  setTimeout(reload, 600);
  return true;
}

function showBanner(text) {
  const doc = globalThis.document;
  if (!doc?.body) return;
  let banner = doc.getElementById("ttBuildBanner");
  if (!banner) {
    banner = doc.createElement("div");
    banner.id = "ttBuildBanner";
    banner.setAttribute("role", "status");
    banner.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:2147483000;padding:8px 12px;text-align:center;background:#2b2116;color:#f4e7c5;font:14px system-ui,sans-serif";
    doc.body.append(banner);
  }
  banner.textContent = text;
}
