// Minimal permissive DOM stub sufficient for executing app.js top-level wiring
// plus renderOwnerSheet / renderCharacterLibrary under the real fixture.
class ClassList {
  constructor(backing = new Set()) { this._set = backing; }
  add(...names) { names.forEach(n => this._set.add(n)); }
  remove(...names) { names.forEach(n => this._set.delete(n)); }
  toggle(name, force) {
    const want = force === undefined ? !this._set.has(name) : Boolean(force);
    if (want) this._set.add(name); else this._set.delete(name);
    return want;
  }
  contains(name) { return this._set.has(name); }
}
let idCounter = 0;
// A browser query answers with a NodeList: indexable, iterable, with .length
// and .item(), and deliberately no .map()/.find()/.filter(). Handing the
// renderer an Array instead would hide every place that treats a query result
// like an Array -- the exact shape a real browser refuses at runtime.
class NodeListLike {
  constructor(items) {
    this._items = [...items];
    this.length = this._items.length;
    this._items.forEach((item, index) => { this[index] = item; });
  }
  item(index) { return this._items[index] ?? null; }
  forEach(callback, thisArg) { this._items.forEach(callback, thisArg); }
  entries() { return this._items.entries(); }
  keys() { return this._items.keys(); }
  values() { return this._items.values(); }
  [Symbol.iterator]() { return this._items[Symbol.iterator](); }
}
class FakeElement {
  constructor(tag = "div") {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this._classSet = new Set();
    this.dataset = {};
    this.classList = new ClassList(this._classSet);
    this.attributes = {};
    this.style = {};
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.nodeType = 1;
    this.parentNode = null;
    this.id = `auto-${idCounter++}`;
  }
  get className() { return [...this._classSet].join(" "); }
  set className(v) { this._classSet = new Set(String(v).split(/\s+/).filter(Boolean)); this.classList = new ClassList(this._classSet); }
  get childElementCount() { return this.children.length; }
  get firstChild() { return this.children[0] || null; }
  append(...nodes) { for (const n of nodes) this.appendChild(n); }
  appendChild(node) {
    if (node && typeof node.appendChild === "function" || node instanceof FakeElement) {
      // Ordinary DOM moves remove/reinsert the subtree, losing its focus even
      // within the same parent. Reuse remove() so append and insert agree.
      if (node.parentNode) node.remove();
      node.parentNode = this; this.children.push(node);
    } else if (node && typeof node === "object") {
      this.children.push(node);
    }
    return node;
  }
  insertBefore(node, reference) {
    if (node && typeof node.appendChild === "function" || node instanceof FakeElement) {
      if (node.parentNode) node.remove();
      node.parentNode = this;
      const at = reference ? this.children.indexOf(reference) : -1;
      if (at < 0) this.children.push(node); else this.children.splice(at, 0, node);
    } else if (node && typeof node === "object") {
      this.children.push(node);
    }
    return node;
  }
  replaceChildren(...nodes) {
    for (const child of this.children) {
      if (!(child instanceof FakeElement)) continue;
      child.parentNode = null;
      // A browser drops focus the moment the focused node leaves the document.
      gmBlurIfDetached(child);
    }
    this.children = []; nodes.forEach(n => this.appendChild(n));
  }
  cloneNode(deep = false) {
    const clone = new FakeElement(this.tagName);
    for (const key of ["id", "className", "textContent", "value", "hidden", "disabled", "tabIndex", "title"]) {
      clone[key] = this[key];
    }
    clone.attributes = {...this.attributes};
    clone.dataset = {...this.dataset};
    clone.style = {...this.style};
    // Browser clones copy markup, but never event listeners or parent pointers.
    if (deep) this.children.forEach(child => clone.appendChild(child.cloneNode ? child.cloneNode(true) : {...child}));
    return clone;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === "id") this.id = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, handler) { (this._handlers ||= {})[type] ||= []; this._handlers[type].push(handler); }
  removeEventListener() {}
  dispatchEventOfType(type, event = {}) {
    for (const h of (this._handlers?.[type] || [])) h({target: event.target || this, preventDefault() {}, stopPropagation() {}, ...event});
  }
  click() { this.dispatchEventOfType("click"); }
  focus() { documentStub.activeElement = this; }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter(child => child !== this);
    this.parentNode = null;
    gmBlurIfDetached(this);
  }
  closest(selector) { return matchSimple(this, selector) ? this : null; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const out = [];
    const walk = node => { for (const child of node.children || []) { if (matchSimple(child, selector)) out.push(child); walk(child); } };
    walk(this);
    return new NodeListLike(out);
  }
}
function dataKey(name) { return name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()); }
function matchSimple(el, selector) {
  if (!el || !el.classList) return false;
  if (!el._classSet && Array.isArray(el.classList._set)) el._classSet = el.classList._set;
  // supports "#id", ".cls", "[data-x]", "tag", and compound ".a.b" used in code
  const parts = selector.split(",").map(s => s.trim()).filter(Boolean);
  return parts.some(sel => {
    if (sel.startsWith("#")) return el.id === sel.slice(1);
    if (sel.startsWith("[") && sel.endsWith("]")) {
      const inner = sel.slice(1, -1);
      const eq = inner.indexOf("=");
      if (eq === -1) return inner.startsWith("data-") ? el.dataset[dataKey(inner)] !== undefined : el.attributes[inner] !== undefined;
      const key = inner.slice(0, eq), val = inner.slice(eq + 1).replace(/^['"]|['"]$/g, "");
      if (key.startsWith("data-")) return el.dataset[dataKey(key)] === val;
      return el.attributes[key] === val;
    }
    return sel.split(".").filter(Boolean).every(cls => el._classSet.has(cls));
  });
}
const registry = new Map();
const ensure = id => { if (!registry.has(id)) registry.set(id, new FakeElement()); return registry.get(id); };
// Is this node still part of the page? A node is in the document when walking up
// its parents reaches a registered page element (or the body) rather than stopping
// at a detached root. Ordinary append/insertBefore moves temporarily detach a
// subtree, so focus is lost before it is reinserted, even within the same parent.
function gmIsInDocument(node) {
  let top = node;
  while (top && top.parentNode) top = top.parentNode;
  return Boolean(top) && (top === documentStub.body || (registry.has(top.id) && registry.get(top.id) === top));
}
// A browser hands focus to the page body as soon as the focused node leaves the
// document. Without this, a renderer could detach every card on each poll and the
// stub would still report the detached control as focused, hiding the loss.
function gmBlurIfDetached(removed) {
  if (gmIsInDocument(removed)) return;
  const focused = documentStub.activeElement;
  if (!focused) return;
  for (let node = focused; node; node = node.parentNode) {
    if (node === removed) { documentStub.activeElement = null; return; }
  }
}
const documentStub = {
  createElement: tag => new FakeElement(tag),
  createDocumentFragment: () => new FakeElement("fragment"),
  getElementById: id => ensure(id),
  querySelector: sel => { const all = documentStub.querySelectorAll(sel); return all[0] || null; },
  querySelectorAll: sel => {
    const out = [];
    for (const el of registry.values()) { if (matchSimple(el, sel)) out.push(el); out.push(...walkAll(el, sel)); }
    function walkAll(node, s) { const acc = []; for (const c of node.children || []) { if (matchSimple(c, s)) acc.push(c); acc.push(...walkAll(c, s)); } return acc; }
    return new NodeListLike(out);
  },
  addEventListener() {}, body: new FakeElement("body"), activeElement: null,
};
module.exports = {documentStub, FakeElement, NodeListLike, registry, ensure};
