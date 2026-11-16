// ATTACKLIST1: the smallest DOM the sheet's and the bar's attack-group code needs, so both can be run by node --test
// with no browser. It only implements what that code touches: elements, classes, dataset, attributes, children,
// closest() for a handful of selectors, and textContent. Everything else stays real: the code under test is the
// sheet.js / tabletop.js source itself, extracted by each test's vm harness.
export class FakeElement {
  constructor(tag = "div") {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parent = null;
    this.attributes = {};
    this.dataset = {};
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.style = {setProperty() {}};
    this.listeners = {};
  }
  get classList() {
    const self = this;
    const list = () => self.className.split(/\s+/).filter(Boolean);
    return {
      add: (...names) => { self.className = [...new Set([...list(), ...names])].join(" "); },
      remove: (...names) => { self.className = list().filter(name => !names.includes(name)).join(" "); },
      contains: name => list().includes(name),
      toggle: (name, force) => {
        const has = list().includes(name);
        const want = force === undefined ? !has : Boolean(force);
        self.className = want ? [...new Set([...list(), name])].join(" ") : list().filter(entry => entry !== name).join(" ");
        return want;
      },
    };
  }
  set classNameValue(value) { this.className = value; }
  append(...kids) {
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      if (kid instanceof FakeElement) { kid.parent = this; this.children.push(kid); }
      else this.children.push(String(kid));
    }
  }
  appendChild(kid) { this.append(kid); return kid; }
  prepend(kid) { kid.parent = this; this.children.unshift(kid); }
  replaceChildren(...kids) {
    for (const kid of this.children) if (kid instanceof FakeElement) kid.parent = null;
    this.children = [];
    this.append(...kids);
  }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this);
    this.parent = null;
  }
  get nextElementSibling() {
    if (!this.parent) return null;
    const index = this.parent.children.indexOf(this);
    return index < 0 ? null : (this.parent.children[index + 1] || null);
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "class") this.className = String(value);
    if (name.startsWith("data-")) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = String(value);
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  hasAttribute(name) { return name in this.attributes; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  matches(selector) {
    const test = String(selector).trim();
    if (test.startsWith("[") && test.endsWith("]")) {
      const raw = test.slice(1, -1);
      const [name, value] = raw.split("=");
      const key = name.startsWith("data-") ? name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase()) : null;
      const have = key ? this.dataset[key] : this.getAttribute(name);
      return value === undefined ? have != null : have === value.replace(/^["']|["']$/g, "");
    }
    if (test.startsWith(".")) return this.classList.contains(test.slice(1));
    return this.tagName === test.toUpperCase();
  }
  closest(selector) {
    let node = this;
    while (node) { if (node.matches && node.matches(selector)) return node; node = node.parent; }
    return null;
  }
  querySelectorAll(selector) {
    const parts = String(selector).split(/\s+/).filter(Boolean);
    const found = [];
    const walk = (node, index) => {
      for (const child of node.children) {
        if (!(child instanceof FakeElement)) continue;
        if (child.matches(parts[index])) {
          if (index === parts.length - 1) found.push(child);
          else walk(child, index + 1);
        } else walk(child, index);
      }
    };
    walk(this, 0);
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  get textContent() {
    return this.children.map(child => child instanceof FakeElement ? child.textContent : String(child)).join("");
  }
  set textContent(value) {
    for (const child of this.children) if (child instanceof FakeElement) child.parent = null;
    this.children = value === "" || value == null ? [] : [String(value)];
  }
}
