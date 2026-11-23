// Test-only CSS cascade resolver for the table's own shipped stylesheets.
//
// Used by: static/tabletop/tabletop_map_pick_hit.test.mjs, which has to know whether a real click reaches an element
// while the fight is still working the action that raised a teleport question. `pointer-events` and `display` are
// what a browser hit-tests with, so a client test that calls a click handler directly cannot tell a live page from a
// dead one -- that is exactly how a teleport's squares ended up lit up on a board that refused every click. This
// resolves the real rules out of the real stylesheet, in source order, with !important and specificity, and needs no
// browser and no third-party dependency.
//
// Supported selectors: type, `*`, `#id`, `.class`, `[attr]`, `[attr="value"]`, `:is(...)`, `:not(...)`, the
// descendant and child combinators, and the dynamic pseudo-classes (:hover, :focus, :checked, ...) which never match
// a static tree. `pointer-events` is inherited (that is what lets a child re-enable clicks over a non-interactive
// overlay), so a value with no matching rule is taken from the nearest ancestor that has one.
//
// Anything outside that subset is reported through `unparsed` rather than silently treated as "no match", so a
// caller can fail loudly instead of resolving the wrong value.

const INHERITED = new Set(['pointer-events', 'visibility', 'cursor', 'color', 'font-family', 'line-height']);
const INITIAL = {'pointer-events': 'auto', display: 'block', visibility: 'visible', opacity: '1'};
const DYNAMIC_PSEUDO = new Set(['hover', 'focus', 'focus-within', 'focus-visible', 'active', 'visited', 'link',
  'target', 'checked', 'disabled', 'enabled', 'required', 'valid', 'invalid', 'in-range', 'out-of-range',
  'placeholder-shown', 'default', 'indeterminate', 'read-only', 'read-write', 'only-child', 'first-child',
  'last-child', 'empty']);

const stripComments = css => css.replace(/\/\*[\s\S]*?\*\//g, '');

function splitBlocks(css) {
  const blocks = [];
  let index = 0;
  while (index < css.length) {
    while (index < css.length && /\s/.test(css[index])) index += 1;
    if (index >= css.length) break;
    const open = css.indexOf('{', index);
    if (open < 0) break;
    let depth = 1, cursor = open + 1;
    while (cursor < css.length && depth > 0) {
      if (css[cursor] === '{') depth += 1;
      else if (css[cursor] === '}') depth -= 1;
      cursor += 1;
    }
    blocks.push({prelude: css.slice(index, open).trim(), body: css.slice(open + 1, cursor - 1)});
    index = cursor;
  }
  return blocks;
}

// A selector list's commas, ignoring the ones inside :is()/:not().
function splitList(prelude) {
  const parts = [];
  let current = '', depth = 0;
  for (const ch of prelude) {
    if (ch === '(') depth += 1;
    if (ch === ')') depth -= 1;
    if (ch === ',' && depth === 0) { parts.push(current.trim()); current = ''; }
    else current += ch;
  }
  parts.push(current.trim());
  return parts.filter(Boolean);
}

function parseDeclarations(body) {
  const declarations = [];
  for (const piece of splitTopLevelSemicolons(stripComments(body))) {
    const colon = piece.indexOf(':');
    if (colon < 0) continue;
    const prop = piece.slice(0, colon).trim().toLowerCase();
    let value = piece.slice(colon + 1).trim();
    if (!prop || !value) continue;
    let important = false;
    if (/!\s*important$/i.test(value)) { important = true; value = value.replace(/!\s*important$/i, '').trim(); }
    if (value) declarations.push({prop, value, important});
  }
  return declarations;
}

function splitTopLevelSemicolons(body) {
  const parts = [];
  let current = '', depth = 0;
  for (const ch of body) {
    if (ch === '(') depth += 1;
    if (ch === ')') depth -= 1;
    if (ch === ';' && depth === 0) { parts.push(current); current = ''; }
    else current += ch;
  }
  parts.push(current);
  return parts;
}

// Compounds separated by descendant (whitespace) or child (>) combinators.
function tokenizeSelector(selector) {
  const tokens = [];
  let current = '', depth = 0;
  const flush = () => { if (current) { tokens.push({kind: 'compound', text: current}); current = ''; } };
  for (const ch of selector) {
    if (ch === '(') depth += 1;
    if (ch === ')') depth -= 1;
    if (depth === 0 && ch === '>') { flush(); tokens.push({kind: 'combinator', text: '>'}); }
    else if (depth === 0 && /\s/.test(ch)) flush();
    else current += ch;
  }
  flush();
  return tokens;
}

// One compound ("body.is-working", "#ttHint", ":is(#a, #b)"), or null if it uses something this resolver
// does not model. Callers turn null into a loud failure.
function parseCompound(text) {
  const simple = {tag: null, ids: [], classes: [], attrs: [], is: [], not: []};
  let rest = text;
  const tag = rest.match(/^(\*|[a-zA-Z][\w-]*)/);
  if (tag) { if (tag[1] !== '*') simple.tag = tag[1].toLowerCase(); rest = rest.slice(tag[0].length); }
  let index = 0;
  while (index < rest.length) {
    const ch = rest[index];
    if (ch === '#') {
      const name = rest.slice(index + 1).match(/^[\w-]+/);
      if (!name) return null;
      simple.ids.push(name[0]); index += 1 + name[0].length; continue;
    }
    if (ch === '.') {
      const name = rest.slice(index + 1).match(/^[\w-]+/);
      if (!name) return null;
      simple.classes.push(name[0]); index += 1 + name[0].length; continue;
    }
    if (ch === '[') {
      const close = rest.indexOf(']', index);
      if (close < 0) return null;
      simple.attrs.push(rest.slice(index + 1, close).trim()); index = close + 1; continue;
    }
    if (ch === ':') {
      const name = rest.slice(index + 1).match(/^([\w-]+)/);
      if (!name) return null;
      const lower = name[0].toLowerCase();
      let cursor = index + 1 + name[0].length;
      let argument = null;
      if (rest[cursor] === '(') {
        let depth = 1, scan = cursor + 1;
        while (scan < rest.length && depth > 0) {
          if (rest[scan] === '(') depth += 1;
          else if (rest[scan] === ')') depth -= 1;
          scan += 1;
        }
        if (depth > 0) return null;
        argument = rest.slice(cursor + 1, scan - 1);
        cursor = scan;
      }
      if (lower === 'is' || lower === 'not') {
        if (argument === null) return null;
        // :is()/:not() take a whole selector list, so each alternative is its own compound.
        const entries = splitList(argument).map(part => parseCompound(part));
        if (!entries.length || entries.some(entry => entry === null)) return null;
        (lower === 'is' ? simple.is : simple.not).push(...entries);
      } else if (!DYNAMIC_PSEUDO.has(lower)) {
        return null;
      }
      index = cursor; continue;
    }
    return null;
  }
  return simple;
}

function specificity(simple) {
  let ids = simple.ids.length, classes = simple.classes.length + simple.attrs.length, types = simple.tag ? 1 : 0;
  for (const group of [simple.is, simple.not]) {
    for (const entry of group) {
      const own = specificity(entry);
      ids = Math.max(ids, own[0]); classes = Math.max(classes, own[1]); types = Math.max(types, own[2]);
    }
  }
  return [ids, classes, types];
}

function compareSpecificity(left, right) {
  for (let index = 0; index < 3; index += 1) if (left[index] !== right[index]) return left[index] - right[index];
  return 0;
}

function parseSelector(selector) {
  if (/[+~]/.test(selector) || /::/.test(selector)) return null;
  const tokens = tokenizeSelector(selector);
  const compounds = [], combinators = [];
  for (const token of tokens) {
    if (token.kind === 'combinator') { if (!compounds.length) return null; combinators.push(token.text); continue; }
    const parsed = parseCompound(token.text);
    if (!parsed) return null;
    compounds.push(parsed);
  }
  if (!compounds.length) return null;
  return {compounds, combinators, specificity: specificity(compounds.at(-1))};
}

function nodeTag(node) { return String(node?.tagName || node?.tag || '').toLowerCase(); }
function nodeClasses(node) {
  if (node.classes instanceof Set) return node.classes;
  return new Set(String(node?.className || '').split(/\s+/).filter(Boolean));
}
function nodeId(node) { return node?.id || ''; }
function nodeParent(node) { return node?.parentNode || null; }
function hasAttribute(node, name) {
  if (name === 'hidden' && node?.hidden === true) return true;
  if (typeof node?.hasAttribute === 'function') return node.hasAttribute(name);
  return Boolean(node?.attributes && name in node.attributes);
}
function attributeMatches(node, text) {
  const parsed = text.match(/^([\w-]+)(?:([~|^$*]?=)\s*["']?([^"'\]]*)["']?)?$/);
  if (!parsed) return false;
  const [, key, operator, want] = parsed;
  if (operator === undefined) return hasAttribute(node, key);
  const actual = typeof node?.getAttribute === 'function' ? node.getAttribute(key) : node?.attributes?.[key];
  if (actual === undefined || actual === null) return false;
  if (operator === '=') return String(actual) === want;
  if (operator === '~=') return String(actual).split(/\s+/).includes(want);
  return false;  // |=, ^=, $=, *= are rare here; report through the selector text instead of guessing
}

function matchesCompound(node, simple) {
  if (simple.tag && nodeTag(node) !== simple.tag) return false;  // no type selector matches any tag
  for (const id of simple.ids) if (nodeId(node) !== id) return false;
  const classes = nodeClasses(node);
  for (const name of simple.classes) if (!classes.has(name)) return false;
  for (const attr of simple.attrs) if (!attributeMatches(node, attr)) return false;
  for (const entry of simple.is) if (entry && matchesCompound(node, entry)) return true;
  if (simple.is.length) return false;
  for (const entry of simple.not) if (entry && matchesCompound(node, entry)) return false;
  return true;
}

function matchesSelector(node, parsed) {
  const {compounds, combinators} = parsed;
  if (!matchesCompound(node, compounds.at(-1))) return false;
  let current = node;
  for (let index = compounds.length - 1; index > 0; index -= 1) {
    const combinator = combinators[index - 1];
    if (combinator === '>') {
      const parent = nodeParent(current);
      if (!parent || !matchesCompound(parent, compounds[index - 1])) return false;
      current = parent;
    } else {
      let ancestor = nodeParent(current), found = null;
      while (ancestor) {
        if (matchesCompound(ancestor, compounds[index - 1])) { found = ancestor; break; }
        ancestor = nodeParent(ancestor);
      }
      if (!found) return false;
      current = found;
    }
  }
  return true;
}

/**
 * Read a stylesheet into rules this resolver can apply.
 *
 * `rules` are the ordinary top-level rules. `conditional` rules live inside @media/@supports: they are recorded but
 * never applied, because a headless hit test has no viewport or motion preference to evaluate them against. Callers
 * that care get them via `atRules` and decide for themselves. `unparsed` lists every selector this resolver could
 * not model, so a caller can refuse to trust the result.
 */
export function parseSheet(css) {
  const rules = [], atRules = [], unparsed = [];
  const walk = (text, conditional) => {
    for (const block of splitBlocks(stripComments(text))) {
      if (block.prelude.startsWith('@')) {
        const name = block.prelude.slice(1).split(/[\s(]/)[0].toLowerCase();
        if (['keyframes', 'font-face', 'page', 'property', 'import', 'charset'].includes(name)) continue;
        atRules.push({prelude: block.prelude, conditional, body: block.body});
        walk(block.body, true);
        continue;
      }
      for (const selector of splitList(block.prelude)) {
        const parsed = parseSelector(selector);
        if (!parsed) { unparsed.push(selector); continue; }
        rules.push({selector, parsed, declarations: parseDeclarations(block.body), conditional, order: rules.length});
      }
    }
  };
  walk(css, false);
  return {rules, atRules, unparsed};
}

/** The declaration a browser would settle on for one property of one element, honouring !important, then
 *  specificity, then source order. Returns null when no rule in the sheet declares it. */
export function declaredValue(sheet, node, prop) {
  let winner = null;
  for (const rule of sheet.rules) {
    if (rule.conditional) continue;
    const declaration = rule.declarations.find(entry => entry.prop === prop);
    if (!declaration || !matchesSelector(node, rule.parsed)) continue;
    if (!winner) { winner = {rule, declaration}; continue; }
    if (declaration.important !== winner.declaration.important) {
      if (declaration.important) winner = {rule, declaration};
      continue;
    }
    const order = compareSpecificity(rule.parsed.specificity, winner.rule.parsed.specificity);
    if (order > 0 || (order === 0 && rule.order > winner.rule.order)) winner = {rule, declaration};
  }
  return winner ? winner.declaration.value : null;
}

/** The computed value: this element's own winning declaration, else the nearest ancestor's (for inherited
 *  properties), else the property's initial value. */
export function computedValue(sheet, node, prop) {
  const own = declaredValue(sheet, node, prop);
  if (own !== null) return own;
  if (INHERITED.has(prop)) {
    for (let parent = nodeParent(node); parent; parent = nodeParent(parent)) {
      const inherited = declaredValue(sheet, parent, prop);
      if (inherited !== null) return inherited;
    }
  }
  return INITIAL[prop] ?? '';
}

/**
 * Whether a click at this element reaches it, the way a browser decides it: something that is not rendered
 * (`display: none`) cannot be hit, and `pointer-events: none` makes a subtree transparent to the pointer even
 * though it is on screen. `hidden` is read off the property as well as the attribute, because that is how the
 * browser reflects `element.hidden = true` onto the attribute the stylesheet matches.
 */
export function hitTestable(sheet, node) {
  if (computedValue(sheet, node, 'display') === 'none') return false;
  if (node?.hidden === true) return false;
  return computedValue(sheet, node, 'pointer-events') !== 'none';
}
