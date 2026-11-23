// Each simulated tab links the entire shipped ESM graph against its own DOM,
// storage, clock and HTTP transport. No copied page code or mocked page helpers.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {setImmediate as tick} from 'node:timers/promises';
import {createContext, SourceTextModule, SyntheticModule} from 'node:vm';
import {installDOM} from './objects_dom_stub.mjs';

const entry = new URL('../static/tabletop/tabletop.js', import.meta.url);
const html = readFileSync(new URL('./tabletop.html', entry), 'utf8');
const bootReplies = {
  '/api/session': {token: 'test'},
  '/api/tabletop/conditions': {conditions: {}},
  '/api/tabletop/providers': {providers: []},
  '/api/combat/matches': [],
  '/api/combat/factory-characters': [],
  '/api/tabletop/maps': {maps: [], builtin: []},
};

export async function openTablePage({viewId, storage, preferences, request, inspect = []}) {
  const globals = {console, URL, URLSearchParams, DOMException, structuredClone};
  const document = installDOM(html, globals);
  const {location, window, history} = globals;
  const coveredBeforeScripts = document.body.classList.contains('is-viewer-pending');
  const urls = [], opens = [], unexpected = [];
  const start = new URL(`http://localhost/tabletop?view=${viewId}&fogSquares=1`);
  Object.assign(location, {search: start.search, origin: start.origin, href: start.href});
  history.replaceState = (_state, _title, url) => {
    urls.push(url);
    const next = new URL(url, location.origin);
    Object.assign(location, {search: next.search, href: next.href});
  };
  window.sessionStorage = storage;
  window.localStorage = globals.localStorage = {
    getItem: key => key === 'tt-dice' ? 'off' : preferences?.getItem(key) ?? null,
    setItem: (key, value) => preferences?.setItem(key, value),
  };
  window.open = (...args) => { opens.push(args); return null; };
  window.removeEventListener = () => {};

  const timers = new Map();
  let elapsed = 0, id = 0, poll;
  Object.assign(globals, {
    setTimeout(fn, ms = 0, ...args) { timers.set(++id, {at: elapsed + ms, run: () => fn(...args)}); return id; },
    clearTimeout(handle) { timers.delete(handle); },
    setInterval(fn, ms) { if (ms === 3000) poll = fn; return ++id; },
    requestAnimationFrame: fn => setImmediate(() => fn(performance.now())),
    cancelAnimationFrame: clearImmediate,
    async fetch(url, options) {
      let body = Object.hasOwn(bootReplies, url) ? bootReplies[url] : undefined;
      if (body === undefined) body = await request(url, options);
      if (body === undefined) { unexpected.push(url); throw Error(`Unexpected tabletop API request: ${url}`); }
      return new Response(JSON.stringify(body));
    },
  });
  const context = createContext(globals);
  const modules = new Map();
  const link = (specifier, parent) => load(new URL(specifier, parent.identifier));
  function load(url) {
    if (!modules.has(url.href)) {
      // Node's VM isolates each tab's browser globals. Optional test-only exports
      // observe real lexical state/functions without replacing any of them.
      const source = readFileSync(url, 'utf8');
      if (url.pathname.endsWith('.json')) {
        const value = JSON.parse(source);
        modules.set(url.href, new SyntheticModule(['default'], function () { this.setExport('default', value); }, {context, identifier: url.href}));
        return modules.get(url.href);
      }
      const observation = url.href === entry.href && inspect.length ? `\nexport { ${inspect.join(', ')} };\n` : '';
      modules.set(url.href, new SourceTextModule(source + observation, {
        context, identifier: url.href,
        initializeImportMeta: meta => { meta.url = url.href; },
        async importModuleDynamically(specifier, parent) {
          const child = link(specifier, parent);
          if (child.status === 'unlinked') await child.link(link);
          if (child.status === 'linked') await child.evaluate();
          return child;
        },
      }));
    }
    return modules.get(url.href);
  }
  const module = load(entry);
  await module.link(link);
  await module.evaluate();
  for (let i = 0; i < 100 && !window.tabletop; i++) await tick();
  assert.ok(window.tabletop, 'shipped tabletop page starts');
  await tick(); // let the empty lobby's startup reads finish
  document.getElementById('ttLobby').close();
  return {
    document, urls, opens, coveredBeforeScripts, ...window.tabletop, ...module.namespace,
    pollTable() { assert.ok(poll, 'page registered its idle poll'); return poll(); },
    async advance(ms) {
      const end = elapsed + ms;
      await tick();
      while (true) {
        const next = [...timers].filter(([, timer]) => timer.at <= end)
          .sort(([, a], [, b]) => a.at - b.at)[0];
        if (!next) break;
        const [handle, timer] = next;
        timers.delete(handle);
        elapsed = timer.at;
        timer.run();
        await tick();
      }
      elapsed = end;
    },
    checkRequests: () => assert.deepEqual(unexpected, [], 'all page requests are mocked'),
  };
}
