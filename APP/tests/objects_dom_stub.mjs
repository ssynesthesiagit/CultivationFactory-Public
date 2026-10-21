// Test-only DOM for importing the unmodified editor/table/board entry points.
// It models markup, listeners and token state; it does not claim visual layout.
// A real DOM turns a string child into a Text node. Without this, rendering any
// rules text through append()/appendChild() threw instead of producing a node, so
// whole production render paths (an ability's rules card, for one) were untestable.
// A text node matches no selector and has no children, like the real thing.
function textNode(text) {
  return {nodeType: 3, parentNode: null, children: [], textContent: String(text),
    matches: () => false};
}
export class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {};
    this.style = {setProperty() {}}; this.listeners = new Map(); this._value = ''; this._selected = false; this.textContent = '';
    this.classList = {add: (...v) => v.forEach(x => this.classes.add(x)),
      remove: (...v) => v.forEach(x => this.classes.delete(x)), contains: x => this.classes.has(x),
      toggle: (x, force) => { const on = force ?? !this.classes.has(x); on ? this.classes.add(x) : this.classes.delete(x); return on; }};
    this.classes = new Set();
  }
  set className(v) { this.classes = new Set(v.split(/\s+/).filter(Boolean)); }
  get className() { return [...this.classes].join(' '); }
  set innerHTML(html) {
    this.html = html; this.children = [];
    const stack = [this];
    for (const match of html.matchAll(/<(\/)?([\w-]+)([^>]*)>/g)) {
      if (match[1]) { if (stack.length > 1) stack.pop(); continue; }
      const node = new Element(match[2]);
      for (const attr of match[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) node.setAttribute(attr[1], attr[2] ?? '');
      stack.at(-1).appendChild(node);
      if (!['input', 'img', 'br', 'hr'].includes(match[2]) && !match[3].endsWith('/')) stack.push(node);
    }
  }
  get innerHTML() { return this.html || ''; }
  // <select>.value reflects whichever <option> is selected (explicitly, or the first one when parsed
  // markup selects none, matching real DOM default-selection); <option>.value tracks its "value" attribute.
  get options() { return this.tagName === 'SELECT' ? this.querySelectorAll('option') : undefined; }
  get value() {
    if (this.tagName === 'SELECT') {
      const options = this.options;
      return (options.find(o => o._selected) ?? options[0])?._value ?? '';
    }
    return this._value ?? '';
  }
  set value(v) {
    if (this.tagName === 'SELECT') { for (const o of this.options) o._selected = (o._value ?? '') === v; return; }
    this._value = v;
  }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k === 'class') this.className = String(v);
    if (k === 'id') this.id = v;
    if (k.startsWith('data-')) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
    if (this.tagName === 'OPTION' && k === 'value') this._value = v;
    if (this.tagName === 'OPTION' && k === 'selected') this._selected = true;
  }
  getAttribute(k) { return this.attributes[k] ?? null; }
  hasAttribute(k) { return k in this.attributes; }
  toggleAttribute(k, force) { const on = force ?? !this.hasAttribute(k); on ? this.setAttribute(k, '') : this.removeAttribute(k); return on; }
  removeAttribute(k) { delete this.attributes[k]; }
  appendChild(node) { if (typeof node !== 'object' || node === null) node = textNode(node); node.parentNode = this; this.children.push(node); return node; }
  append(...nodes) { nodes.forEach(n => this.appendChild(n)); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  get firstChild() { return this.children[0]; }
  get lastChild() { return this.children.at(-1); }
  // Native DOM nodes expose the same child list as childNodes (a string child was
  // already appended as a text node), so production renderers may use either.
  get childNodes() { return this.children; }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(n => n !== this); }
  matches(s) {
    if (s.startsWith('#')) return this.id === s.slice(1);
    if (s.startsWith('.')) return s.slice(1).split('.').every(c => this.classes.has(c));
    if (s.startsWith('[')) { const [, key, value] = s.match(/^\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]$/) || []; return key && (value ? this.getAttribute(key) === value : this.hasAttribute(key)); }
    return this.tagName.toLowerCase() === s;
  }
  querySelectorAll(selector) {
    const result = [];
    const matches = node => selector.split(',').some(s => {
      const parts = s.trim().split(/\s+/); if (!node.matches(parts.pop())) return false;
      let parent = node.parentNode;
      while (parts.length) { const part = parts.pop(); while (parent && !parent.matches(part)) parent = parent.parentNode; if (!parent) return false; parent = parent.parentNode; }
      return true;
    });
    const walk = n => n.children.forEach(child => { if (matches(child)) result.push(child); walk(child); });
    walk(this); return result;
  }
  querySelector(s) { return this.querySelectorAll(s)[0] || null; }
  closest(s) { return s.split(',').some(v => this.matches(v.trim())) ? this : this.parentNode?.closest(s) || null; }
  addEventListener(type, fn) { if (!this.listeners.has(type)) this.listeners.set(type, []); this.listeners.get(type).push(fn); }
  removeEventListener(type, fn) { this.listeners.set(type, (this.listeners.get(type) || []).filter(listener => listener !== fn)); }
  contains(node) { for (; node; node = node.parentNode) if (node === this) return true; return false; }
  async dispatch(type, details = {}) {
    const event = {target: this, button: 0, buttons: 0, preventDefault() {}, stopPropagation() {}, ...details};
    await Promise.all((this.listeners.get(type) || []).map(fn => fn(event)));
  }
  click() { return this.dispatch('click'); }
  getBoundingClientRect() {
    if (this.classList.contains('tt-hovercard')) {
      const left = parseFloat(this.style.left) || 0, top = parseFloat(this.style.top) || 0;
      return {left, top, right: left + 180, bottom: top + 40, width: 180, height: 40};
    }
    return {left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600};
  }
  get offsetHeight() { return 40; }
  get offsetWidth() { return 180; }
  get clientHeight() { return 600; }
  get clientWidth() { return 800; }
  get scrollHeight() { return 0; }
  getContext(kind) {
    if (kind !== '2d') return null;
    // Drawing calls are inert: only DOM and event wiring are under test.
    return new Proxy({createImageData: (w, h) => ({data: new Uint8ClampedArray(w * h * 4)}),
      getImageData: (x, y, w, h) => ({data: new Uint8ClampedArray(w * h * 4)}),
      createLinearGradient: () => ({addColorStop() {}}), createRadialGradient: () => ({addColorStop() {}}),
      measureText: text => ({width: text.length * 6})}, {get: (obj, key) => obj[key] ?? (() => {})});
  }
  // A canvas that can be read back, so code that bakes a painted zone into a background image
  // (board.js zoneMask) runs to completion. The bytes are never asserted on.
  toDataURL() { return 'data:image/png;base64,'; }
  setPointerCapture() {}
  releasePointerCapture() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
}

export function installDOM(html) {
  const root = new Element('html'); root.innerHTML = html;
  const document = Object.assign(root, {body: root.querySelector('body') || root, head: root.querySelector('head') || root, documentElement: root,
    getElementById: id => root.querySelector(`#${id}`),
    createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag),
    createDocumentFragment: () => new Element('fragment')});
  const history = {replaceState() {}};
  const localStorage = {getItem: () => null, setItem() {}};
  // Browsers expose storage on window; production reads it through window[name]
  // (fog memory, appearance preferences), so the stub must match.
  const window = {document, history, innerWidth: 800, innerHeight: 600, localStorage, addEventListener() {}};
  Object.assign(globalThis, {document, window, history, localStorage, location: {search: ''},
    confirm: () => true, requestAnimationFrame: () => 0, cancelAnimationFrame() {},
    setInterval: () => 0, setTimeout: () => 0});
  return document;
}
