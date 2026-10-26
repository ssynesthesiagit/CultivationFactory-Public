// Shared, read-only rule presentation for action help and the sheet library.
// All content becomes text nodes; printed rules never become executable HTML.
import {layoutText} from "./presentation.js?v=mmx104r2";
import {variantActionLabel} from "./attack-groups.js?v=variants1";

// The server's read-only history projection owns evidence-to-player wording.
// Never toast raw evidence, and never cut a reminder through a rule sentence.
export function riderNotice(events, noise) {
  const note = events.find(row => row.event_type === "GM_RIDER" && row.summary);
  return note && events.every(row => noise.has(row.event_type)) ? String(note.summary) : "";
}

export function cleanRules(text) {
  return String(text || "").replace(/<[^>]+>/g, "")
    .split("\n").filter(line => !/^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:Factory [\w -]+|Recommended Factory Realization|Split Review Decision|Split Candidate Buckets|Typing Status|Structure Source)\s*(?:\*\*)?\s*:/i.test(line))
    .join("\n").trim();
}

// Older payloads can repeat identical paragraphs in contextual and printed help.
export function uniqueRuleBlocks(text) {
  const seen = new Set();
  return String(text || "").split(/\n\s*\n/).filter(block => {
    const key = block.trim().toLowerCase().replace(/\s+/g, " ");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).join("\n\n");
}

export function additionalRuleText(own, extra) {
  const words = text => cleanRules(text).toLowerCase()
    .replace(/cp \(cultivation points, your path resource\)/g, "cp")
    .replace(/cultivation points \(your path resource\)/g, "cp")
    .replace(/\bcultivation points\b/g, "cp")
    .replace(/\bpb\b/g, "proficiency bonus")
    .replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const lines = cleanRules(extra).split("\n").filter(line => line.trim() && !/^\s*#/.test(line)
    && !/^\s*(?:\*\*)?Cost\s*:/i.test(line));
  return own && lines.length && lines.every(line => words(own).includes(words(line))) ? "" : extra || "";
}

// Resolve generated action names such as "Feature: Mode" to their own library
// entry first, then to the parent feature's printed rules with the mode named.
// Contextual help never replaces the printed rules: a row that already carries
// its own description still shows the distinct library entry underneath it.
export function rulesTextFor(sheet, row) {
  const presented = layoutText(row?.hover);
  const own = uniqueRuleBlocks(presented || cleanRules(row?.description));
  if (!sheet) return own;
  const printed = libraryTextFor(sheet, row);
  // A structured hover and a Markdown library card can contain the same rules
  // with different headings/line breaks. Compare their words before appending
  // the library body; keep genuinely additional rules and variant explanations.
  const duplicate = !additionalRuleText(own, printed);
  return uniqueRuleBlocks(own && printed && !duplicate && own !== printed ? `${own}\n\n${printed}` : own || printed);
}

// The library half of rulesTextFor, on its own, for rows that need it alone.
function libraryTextFor(sheet, row) {
  if (!sheet.textIndex) {
    const byButton = new Map(), byName = new Map();
    const visit = item => {
      const text = layoutText(item.hover) || cleanRules(item.text || item.summary);
      if (!text) return;
      if (item.button_id) byButton.set(item.button_id, text);
      if (!byName.has(String(item.name).toLowerCase())) byName.set(String(item.name).toLowerCase(), text);
    };
    for (const group of sheet.library?.groups || []) {
      for (const sphere of group.spheres || []) { visit(sphere); (sphere.entries || []).forEach(visit); }
      (group.entries || []).forEach(visit);
    }
    sheet.textIndex = {byButton, byName};
  }
  const index = sheet.textIndex;
  const label = String(row?.label || "");
  const ids = [row?.id, row?.variant_of, row?.combat?.source_definition_id]
    .filter(Boolean).flatMap(id => [String(id), `act:${id}`]);
  for (const id of ids) {
    const text = index.byButton.get(id);
    if (text) return text;
  }
  const normalized = label.toLowerCase();
  const exact = index.byName.get(normalized) || index.byName.get(normalized.replace(/ attack$/, ""));
  if (exact) return exact;
  const [feature, mode] = label.split(/:(.*)/s);
  const parent = mode && index.byName.get(feature.trim().toLowerCase());
  return parent ? `For ${mode.trim()}:\n\n${parent}` : "";
}

export function ruleSummary(text) {
  const lines = cleanRules(text).split("\n").map(line => line.trim());
  // A complete printed effect line, not a character-count cut through a rule.
  const line = lines.find(line => line && !/^(?:#|\||---|(?:\*\*)?(?:Action Type|Activation|Range|Area|Target|Duration|Cost|Prerequisite|Talent Type|Timing Detail|Time|Required Components)\s*:)/i.test(line));
  return (line || lines.find(line => line && !line.startsWith("#")) || "").replace(/\*\*|`/g, "");
}

export function renderRules(text, h, inline) {
  const lines = cleanRules(text).split("\n");
  const blocks = [];
  let list = null;
  const cells = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(cell => cell.trim());
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    if (!line.trim()) { list = null; continue; }
    if (line.trim().startsWith("|") && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || "")) {
      list = null;
      const head = cells(line);
      const body = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        body.push(h("tr", null, ...cells(lines[i]).map(cell => h("td", null, ...inline(cell)))));
        i++;
      }
      i--;
      blocks.push(h("table", {class: "rule-table"},
        h("thead", null, h("tr", null, ...head.map(cell => h("th", {scope: "col"}, ...inline(cell))))),
        h("tbody", null, ...body)));
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    const bullet = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (heading) { list = null; blocks.push(h("p", {class: "lib-h"}, ...inline(heading[2]))); }
    else if (bullet) {
      if (!list) { list = h("ul", {class: "lib-ul"}); blocks.push(list); }
      list.append(h("li", null, ...inline(bullet[1])));
    } else { list = null; blocks.push(h("p", null, ...inline(line.trim()))); }
  }
  if (/\bCP\b/.test(cleanRules(text))) blocks.unshift(h("p", {class: "rule-glossary"}, "CP means cultivation points. For a combat action, the cost on its button names the pool you spend."));
  return h("div", {class: "lib-text"}, ...blocks);
}

export function actionSummary(row, {includeRule = true} = {}) {
  const detail = row.detail || {};
  return [({ACTION: "Action", BONUS_ACTION: "Bonus action", REACTION: "Reaction", NONE: "No action", FREE: "Free"})[row.economy],
    detail.cost && `Cost: ${detail.cost}`, detail.range, detail.area, detail.save, detail.damage,
    includeRule ? ruleSummary(row.description) : "", detail.gm_riders ? "Some printed effects are not run by the table." : "",
    row.economy === "REACTION" ? reactionHelp() : ""].filter(Boolean).join(" · ");
}

// A hover card reads the complete rules once. Add only missing button metadata,
// distinct modifier instructions and the automation note, never a rules summary.
// Shared by the pop-out sheet and table action buttons; presentation only.
// Metadata is compared FIELD BY FIELD and by its COMPLETE value: a printed "Range: 15 feet"
// never hides this button's "5 feet", and a printed Bonus Action never hides a Reaction
// option's own activation. Two facts with one label but different values both survive.
export const ECONOMY_LABELS = {ACTION: "Action", BONUS_ACTION: "Bonus Action", REACTION: "Reaction", NONE: "No action", FREE: "Free", MOVE: "Move"};
const FIELD_ALIASES = {
  action: ["action", "action type", "activation", "type", "casting time"],
  cost: ["cost"], range: ["range"], area: ["area"], save: ["save", "saving throw"], damage: ["damage"],
  target: ["target", "targets"], duration: ["duration"],
};
export function factWords(value) {
  // A trailing explanation in brackets ("3 Resonance (your Path resource)") is not part of the value.
  return String(value || "").toLowerCase().replace(/\*\*|`/g, "").replace(/\s*\([^()]*\)\s*\.?$/, "")
    .replace(/\b(?:feet|foot|ft)\b\.?/g, "ft").replace(/[^\p{L}\p{N}+]+/gu, " ").trim();
}
// The printed "Label: value" fields of a rule text, by canonical field name.
export function printedFields(rules) {
  const out = {};
  for (const raw of String(rules || "").split("\n")) {
    const line = raw.replace(/\*\*|`/g, "").trim();
    const match = line.match(/^([A-Za-z][A-Za-z ]{0,20}?)\s*:\s*(.+)$/);
    if (!match) continue;
    const label = match[1].trim().toLowerCase();
    const field = Object.keys(FIELD_ALIASES).find(key => FIELD_ALIASES[key].includes(label));
    if (field) (out[field] ||= []).push(match[2].trim());
  }
  return out;
}
export function actionHoverText(row, {rules = rulesTextFor(null, row), extra = [], note = ""} = {}) {
  if (row.variant) row = {...row, label: variantActionLabel(row)};
  const words = text => String(text || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const printed = words(rules);
  const fields = printedFields(rules);
  const detail = row.detail || {};
  const economy = ECONOMY_LABELS[row.economy];
  const same = (field, value) => (fields[field] || []).some(item => factWords(item) === factWords(value));
  const metadata = [];
  if (economy && !same("action", economy)) metadata.push(economy);
  for (const [field, label, value] of [["cost", "Cost", detail.cost], ["range", "Range", detail.range],
      ["area", "Area", detail.area], ["save", "Save", detail.save], ["damage", "Damage", detail.damage]]) {
    if (value && !same(field, value)) metadata.push(`${label}: ${value}`);
  }
  const lines = [printed.includes(words(row.label)) ? "" : row.label, metadata.join(" · "), rules];
  const additions = [...extra, row.economy === "REACTION" ? reactionHelp() : "",
    note || (detail.gm_riders ? "Partly automated: some extra lines aren't automated yet, and the fight skips them." : "")];
  for (const text of additions) {
    if (text && !words(lines.join("\n")).includes(words(text))) lines.push(text);
  }
  return lines.filter(Boolean).join("\n\n");
}

export function reactionHelp() {
  return "Reactions happen when their trigger occurs, including on another creature's turn. With Ask me, choose Use or Pass when prompted; with automatic reactions, the table decides for you. AI-controlled creatures decide automatically.";
}

// ---------------------------------------------------------------------------------------------------------------
// Compact ability cards (owner 2026-10-08, SOL192): "most abilities on here are very wordy, we could probably do a
// rewrite of the tooltips that are more easy to digest and keep all the important info".
//
// The server attaches hover.digest, a deterministic re-arrangement of the owner's printed words
// (combat/tooltip_digest.py, hash-keyed to rules_text.json). The card leads with what the ability does, a facts row,
// outcome lines and the conditions it applies, and keeps the complete printed rules once, rendered, under "Full
// rules". The button's own live values (its activation, charged cost, range, save DC, damage) always win over the
// printed header, so a talent-changed button never shows its base card's numbers. A rule changed since the last
// digest build shows "Summary pending" and the full rules open. Presentation only.
const FACT_ORDER = ["Action", "Trigger", "Range", "Area", "Origin", "Target", "Duration", "Save", "Attack", "Damage",
  "Cost", "Limit", "Needs", "Time", "Prerequisite", "Type", "Tags"];

export function actionCardModel(row, {rules = rulesTextFor(null, row), extra = [], note = ""} = {}) {
  if (row.variant) row = {...row, label: variantActionLabel(row)};
  // A modifier/replacement variant's own text is authoritative: never summarise the base record for it.
  const digest = row.variant_of || row.modifier ? null : row.hover?.digest || null;
  const detail = row.detail || {};
  const ready = digest && digest.status && !["pending", "empty", "open"].includes(digest.status);
  // "open": the printed rules hold a scoped/several save or attack procedures, or per-option facts, that one facts
  // row cannot show exactly (SOL192r4). Header only (name + action type), no save chip, complete rules open.
  const headerOnly = digest?.status === "open";
  // Player text only: the same authoring-field filter as the full rules (cleanRules), applied to every digest line.
  const safe = text => cleanRules(text);
  const safeList = list => (list || []).map(safe).filter(Boolean);
  const facts = new Map();
  const put = (label, value) => { if (value && !facts.has(label)) facts.set(label, String(value)); };
  // Live button values first: they are what this character's button actually does.
  put("Action", ECONOMY_LABELS[row.economy]);
  put("Range", detail.range); put("Area", detail.area);
  if (detail.to_hit) put("Attack", `${detail.to_hit} to hit${detail.attacks > 1 ? ` ×${detail.attacks}` : ""}`);
  put("Save", detail.save); put("Damage", detail.damage); put("Cost", detail.cost);
  for (const [label, value] of (ready ? digest.facts || [] : [])) {
    if (label === "Save" && facts.has("Save")) continue;
    put(label, label === "Save" && !/save/i.test(value) ? `${value} save` : value);
  }
  // Without a digest the full rules are shown open: a fact the printed header already states, with the same
  // complete value, is not repeated above it (a different live value still is, as in actionHoverText).
  if (!ready && !headerOnly) {
    const printed = printedFields(rules);
    const key = {Action: "action", Cost: "cost", Range: "range", Area: "area", Save: "save", Damage: "damage"};
    for (const [label, value] of [...facts]) {
      // Always show the activation badge, even when Full rules repeats it.
      if (label !== 'Action' && key[label] && (printed[key[label]] || []).some(item => factWords(item) === factWords(value))) facts.delete(label);
    }
  }
  if (headerOnly) {
    // Open card: the button's activation, plus a printed fact only where the whole text states it exactly once
    // (one Range, one Target, one Cost, one Duration). Never a save chip (SOL192r4, owner 2026-10-08).
    // The engine's live Range / Area / Cost for THIS button win (Aligned Starbolt: 120 ft, not the printed 90);
    // a printed value is only the fallback. Save, damage and attack chips are dropped (a save may be scoped).
    for (const label of [...facts.keys()]) if (!["Action", "Range", "Area", "Cost"].includes(label)) facts.delete(label);
    const printed = printedFields(rules);
    for (const [field, label] of [["range", "Range"], ["area", "Area"], ["target", "Target"], ["duration", "Duration"], ["cost", "Cost"]]) {
      if (!facts.has(label) && (printed[field] || []).length === 1) facts.set(label, printed[field][0]);
    }
  }
  const ordered = [...facts].sort((a, b) => FACT_ORDER.indexOf(a[0]) - FACT_ORDER.indexOf(b[0]));
  const notes = [...extra, note || (detail.gm_riders ? "Partly automated: some extra lines aren't automated yet, and the fight skips them." : "")]
    .filter(Boolean);
  const help = row.economy === "REACTION" ? reactionHelp() : "";
  return {
    // An open full text that already starts with the ability's name does not need it twice.
    title: !ready && !headerOnly && factWords(String(rules || "").split("\n")[0].replace(/^#+\s*/, "")) === factWords(row.label) ? "" : row.label,
    // The printed heading is part of the rules: shown under the button name when the name does not already say it.
    printedName: ready && digest.name && !factWords(row.label).includes(factWords(digest.name)) ? safe(digest.name) : "",
    pending: digest?.status === "pending" ? "Summary pending: this rule changed since its summary was made. The full rules below are current." : "",
    summary: ready ? safe(digest.summary || "") : "",
    facts: ordered.map(([label, value]) => [label, safe(value)]).filter(([, value]) => value),
    outcomes: ready ? (digest.outcomes || []).map(([label, text]) => [label, safe(text)]).filter(([, text]) => text) : [],
    groups: ready ? (digest.groups || []).map(group => ({lead: safe(group.lead || ""), items: safeList(group.items)})) : [],
    rules: ready ? safeList(digest.rules) : [],
    // Subordinate printed sections (Willing / Unwilling Creature, Contesting Light, an optional augment) belong to
    // this ability and stay in the card, each under its own heading.
    // Compact body in PRINTED order (SOL192r7): text lines and results exactly as printed, never regrouped.
    ordered: ready ? (digest.ordered || []).map(([kind, label, value]) => [kind, label, safe(value)]).filter(([, , value]) => value) : [],
    sections: ready ? (digest.children || []).map(function part(child) {
      return {name: safe(child.name || ""), optional: Boolean(child.optional),
        facts: (child.facts || []).map(([label, value]) => [label, safe(value)]).filter(([, value]) => value),
        summary: safe(child.summary || ""),
        outcomes: (child.outcomes || []).map(([label, text]) => [label, safe(text)]).filter(([, text]) => text),
        groups: (child.groups || []).map(group => ({lead: safe(group.lead || ""), items: safeList(group.items)})),
        rules: safeList(child.rules), conditions: child.conditions || [],
        sections: (child.children || []).map(part)};
    }) : [],
    conditions: ready ? digest.conditions || [] : [],
    notes,
    howTo: help,
    full: {label: "Full rules", text: rules, open: !ready},
    finePrint: ready ? Number(digest.fine_print) || 0 : 0,
  };
}

// One DOM builder for every structured card (ability cards, the Armor Class card). Text nodes only.
export function renderTipCard(doc, model, {terms = []} = {}) {
  const el = (tag, cls, ...kids) => {
    const node = doc.createElement(tag);
    if (cls) node.className = cls;
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== "") node.append(kid?.nodeType || typeof kid === "object" ? kid : doc.createTextNode(String(kid)));
    return node;
  };
  const h = (tag, attrs, ...kids) => {
    const node = el(tag, attrs?.class || "", ...kids);
    for (const [key, value] of Object.entries(attrs || {})) if (key !== "class" && value != null) node.setAttribute(key, String(value));
    return node;
  };
  const inline = text => [String(text).replace(/\*\*|`/g, "")];
  const root = el("div", "tc");
  if (model.title) root.append(el("div", "tc-title", model.title));
  if (model.printedName) root.append(el("div", "tc-printed", model.printedName));
  if (model.headline) root.append(el("div", "tc-headline", model.headline));
  if (model.facts?.length) {
    // The activation reads on its own ("Bonus Action", "Reaction", "No action"); other facts carry their label.
    root.append(el("div", "tc-facts", ...model.facts.map(([label, value]) => label === "Action"
      ? el("span", "tc-fact tc-eco", value)
      : el("span", "tc-fact", el("span", "tc-k", label), " ", el("span", "tc-v", value)))));
  }
  if (model.pending) root.append(el("p", "tc-pending", model.pending));
  const body = (into, part, isChild) => {
    if (isChild && part.facts?.length) {
      into.append(el("div", "tc-facts", ...part.facts.map(([label, value]) =>
        el("span", "tc-fact", el("span", "tc-k", label), " ", el("span", "tc-v", value)))));
    }
    if (part.ordered?.length) {
      for (const [kind, label, text] of part.ordered) {
        into.append(kind === "outcome" ? el("p", "tc-line", el("b", "", `${label} `), ...emphasise(doc, text))
          : el("p", "tc-line", ...emphasise(doc, text)));
      }
    } else {
    if (part.summary) into.append(el("p", isChild ? "tc-line" : "tc-summary", part.summary));
    for (const [label, text] of part.outcomes || []) into.append(el("p", "tc-line", el("b", "", `${label}: `), text));
    for (const group of part.groups || []) {
      if (group.lead) into.append(el("p", "tc-line tc-lead", group.lead));
      into.append(el("ul", "tc-ul", ...(group.items || []).map(item => el("li", "", item))));
    }
    if (part.rules?.length) into.append(el("ul", "tc-ul tc-rules", ...part.rules.map(line => el("li", "", line))));
    }
    for (const [name, text] of part.conditions || []) {
      if (text) into.append(el("p", "tc-cond", el("b", "", `${name}: `), text));
    }
    for (const child of part.sections || []) {
      const block = el("div", "tc-section", el("div", "tc-sub", child.name, child.optional ? " (optional augment)" : ""));
      body(block, child, true);
      into.append(block);
    }
  };
  body(root, model, false);
  for (const line of model.lines || []) root.append(el("p", "tc-line", line));
  for (const line of model.notes || []) root.append(el("p", "tc-note", line));
  const said = root.textContent.toLowerCase();
  const fullText = String(model.full?.text || "");
  const extraTerms = terms.filter(term => term && !said.includes(String(term).toLowerCase())
    && !fullText.toLowerCase().includes(String(term).toLowerCase()));
  // Word help (Qi, Martial Focus, CL...) stays in this one card but folded: its names show, its definitions open on a click.
  if (extraTerms.length) {
    const names = extraTerms.map(term => (String(term).match(/^(?:An? )?(.{1,40}?)(?::| is | are | means )/) || [])[1] || "").filter(Boolean);
    root.append(el("details", "tc-terms", el("summary", "", names.length ? `Words used: ${names.join(", ")}` : "Words used"),
      ...extraTerms.map(term => el("p", "", term))));
  }
  if (model.howTo) {
    const how = el("details", "tc-more", el("summary", "", "How reactions work"), el("p", "", model.howTo));
    root.append(how);
  }
  if (fullText) {
    const details = el("details", "tc-full", el("summary", "", model.finePrint
      ? `${model.full.label} (${model.finePrint} more detail${model.finePrint === 1 ? "" : "s"})` : model.full.label));
    if (model.full.open) details.setAttribute("open", "");
    details.append(model.full.markdown === false ? el("div", "tc-plain", fullText) : renderReadableRules(doc, fullText));
    root.append(details);
  }
  return root;
}

// The ability card a trigger hands bindTipTargets: `element.tipCard = actionTipCard(row, options)`.
export function actionTipCard(row, options = {}) {
  const model = actionCardModel(row, options);
  return (doc, {terms} = {}) => renderTipCard(doc, model, {terms});
}


// ---------------------------------------------------------------------------------------------------------------
// Readable full rules (owner 2026-10-08: "Clarify the rules ... make sure they follow the game logic"). The printed
// text, every word in printed order, made easier to scan -- never summarised, dropped or reordered:
//   - each result / condition / timing clause ("Failed Save:", "On a hit,", "If ...,", "When ...,", "At the start
//     ...") starts its own line, its trigger in bold;
//   - dice, distances, DCs, durations and point costs in bold;
//   - printed lists and "...:" option groups as real bullet lists under their lead line; headings as headings;
//   - a line the owner wrote as a quotation (in-world flavour) sits behind a small "Lore" toggle, in place.
// Invariant (tests/test_sol192_tooltip_digest.py): the text content, with Lore expanded, equals the printed text.
const TRIGGER_START = /(?:(?:On an? |On the )?(?:[Ff]ailed|[Ss]uccessful) (?:[Ss]ave|[Ss]aving [Tt]hrow|[Cc]heck)s?\s*[:,]|On an? (?:hit|miss|success|failure|failed save|successful save)\s*[:,]|(?:Hit|Miss|Success|Failure)\s*:|If\b[^.,:;]{1,90},|When\b[^.,:;]{1,90},|Whenever\b[^.,:;]{1,90},|At the (?:start|end) of\b[^.,:;]{1,60},|Once per\b[^.,:;]{1,40}[,:])/;
const EMPHASIS = /(\b\d+d\d+(?:\s*[+\u2212-]\s*\d+)?\b|\bDC\s*\d+\b|\b\d+(?:[-\s](?:foot|feet|ft)\b)|\b\d+\s+(?:minutes?|hours?|rounds?|turns?|days?)\b|\b\d+\s+(?:CP|Qi|Stamina|Resonance)\b|[+\u2212-]\d+\b)/g;

// Text nodes and <b> elements for one printed line: a leading trigger in bold, numbers in bold. No word changes.
export function emphasise(doc, text) {
  const out = [];
  let rest = String(text);
  const lead = rest.match(new RegExp(`^${TRIGGER_START.source}`)) || rest.match(/^[A-Z][A-Za-z' ()-]{0,40}:(?=\s|$)/);
  if (lead) {
    const b = doc.createElement("b"); b.append(doc.createTextNode(lead[0])); out.push(b);
    rest = rest.slice(lead[0].length);
  }
  let last = 0;
  for (const match of rest.matchAll(EMPHASIS)) {
    if (match.index > last) out.push(doc.createTextNode(rest.slice(last, match.index)));
    const b = doc.createElement("b"); b.className = "tc-num"; b.append(doc.createTextNode(match[0])); out.push(b);
    last = match.index + match[0].length;
  }
  if (last < rest.length) out.push(doc.createTextNode(rest.slice(last)));
  return out;
}

// Split one printed line before each result/condition/timing clause, keeping every character.
export function clauseLines(line) {
  const parts = [];
  let rest = String(line);
  const boundary = new RegExp(`(?<=[.;!?])\\s*(?=${TRIGGER_START.source})`);
  for (;;) {
    const match = rest.slice(1).match(boundary);
    if (!match) { parts.push(rest); break; }
    const at = match.index + 1;
    parts.push(rest.slice(0, at));
    rest = rest.slice(at).replace(/^\s+/, "");
  }
  return parts.filter(part => part.trim());
}

export function renderReadableRules(doc, text) {
  const el = (tag, cls, ...kids) => {
    const node = doc.createElement(tag);
    if (cls) node.className = cls;
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== "") node.append(typeof kid === "object" ? kid : doc.createTextNode(String(kid)));
    return node;
  };
  const strip = line => line.replace(/\*\*|`/g, "");
  const lines = cleanRules(text).split("\n");
  const root = el("div", "lib-text tc-readable");
  let list = null;
  const cells = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(cell => strip(cell.trim()));
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i].trimEnd();
    if (!raw.trim() || /^\s*-{3,}\s*$/.test(raw)) { list = null; continue; }
    if (raw.trim().startsWith("|") && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || "")) {
      list = null;
      const head = cells(raw), body = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) { body.push(el("tr", "", ...cells(lines[i]).map(c => el("td", "", ...emphasise(doc, c))))); i++; }
      i--;
      root.append(el("table", "rule-table", el("thead", "", el("tr", "", ...head.map(c => el("th", "", c)))), el("tbody", "", ...body)));
      continue;
    }
    const line = strip(raw.trim());
    const heading = raw.match(/^\s*#{1,6}\s+(.*)$/);
    // "-", "*" and "\u2022" are bullet markup; a printed number ("1.", "5.") is kept, since text may refer to it.
    const bullet = raw.match(/^\s*[-*\u2022]\s+(.*)$/) || raw.match(/^\s*(\d+\.\s+.*)$/);
    if (heading) { list = null; root.append(el("p", "lib-h", strip(heading[1]))); continue; }
    if (bullet) {
      if (!list) { list = el("ul", "lib-ul"); root.append(list); }
      list.append(el("li", "", ...emphasise(doc, strip(bullet[1]))));
      continue;
    }
    // A printed "...;" run after a "...:" lead line is a list too (Chain Armor's benefits, Challenge's effects).
    if (list && list.semicolons && (/[;:]$/.test(list.lastItem || "") || /^[a-z]/.test(line))) {
      list.append(el("li", "", ...emphasise(doc, line))); list.lastItem = line; continue;
    }
    list = null;
    if (/^[\u201c"].*[\u201d"]$/.test(line)) {
      // The owner wrote this line as a quotation: in-world flavour. Kept in place, behind a "Lore" toggle.
      root.append(el("details", "tc-lore", el("summary", "", "Lore"), el("p", "", line)));
      continue;
    }
    for (const clause of clauseLines(line)) root.append(el("p", "tc-clause", ...emphasise(doc, clause)));
    if (/:$/.test(line) && /;$|^[a-z]/.test(strip((lines[i + 1] || "").trim()))) {
      list = el("ul", "lib-ul"); list.semicolons = true; list.lastItem = line; root.append(list);
    }
  }
  return root;
}
