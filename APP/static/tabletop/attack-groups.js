// ATTACKLIST1 -- nested per-weapon attack groups for the Action list (presentation only).
//
// Owner-approved design (feedback desk FD-18): Long Tongling's ATTACKS section listed every weapon copy as its own flat
// row -- "Biao Qiang (Javelin) attack", "... thrown", "Batter: ... thrown", "Batter: ... thrown + Brutal Strike",
// "Batter: ...", each "(one attack; choose the rest)" -- so a fighter with a Jian, a Xi Jian and four javelins produced
// about fifty rows and no weapon could be found among them.
//
// This module is the shared reading of those rows for both surfaces, the pop-out sheet's Actions tab (sheet.js) and
// the table's action bar (tabletop.js): one group per weapon (or per non-weapon source), identical copies merged, and
// the weapon's modes and add-ons as chips under it. It never invents, renames or rewrites an id: every chip carries the
// exact "act:" source id the server compiled, so the table still receives the same button it received before this file
// existed. Presentation only -- no ids, legality or payments change here.
//
// The compiled ids this reads (combat/factory_compiler.py, combat/ext/thrown_equipment.py, combat/ext/special_attacks.py):
//   action:typed.<hash>.weapon.<item>                a weapon row; ".copy2"..".copyN" one per identical copy
//   ...#thrown                                       the thrown delivery of the same weapon
//   ....batter / ...#thrown.batter                   the Batter special attack (melee or thrown delivery)
//   ...+<hash>                                       an add-on such as Brutal Strike (row.variant_of names its base)
//   ....rider.<hash>.on.toggle                       a talent that changes the attack (row.parent names its base)
//   ....attack_action_rest                           one more attack of a started Attack action (combat/ext/special_attacks.py)
//   ....attack_action_begin                          start the Attack action with one attack, choosing the rest as you go

const ADD_ON = /\+[0-9a-f]{6,}$/;
const REST = /\.attack_action_rest$/;
const BEGIN = /\.attack_action_begin$/;
const COPY = /\.copy(\d+)$/;
const PARENTHETICAL = /\s*\((?:rest of the Attack action|one attack; choose the rest|replace remaining attacks)\)\s*$/i;

// The source id a button stands for, without the "act:" the sheet and the bar put in front of it.
export function attackSource(row) {
  const id = String(row?.combat?.source_definition_id || row?.source_definition_id || row?.id || "");
  return id.replace(/^act:/, "");
}

// Variant rows name their executable source by action_id (prefight options carry no combat block). Legacy weapon rows
// keep attackSource above unchanged, so a weapon row without a source id is still never grouped by a stray action_id.
function variantSource(row) {
  const id = String(row?.combat?.source_definition_id || row?.source_definition_id || row?.action_id || row?.id || "");
  return id.replace(/^act:/, "");
}

// The parts of one attack source id. Every field is read-only: callers never rebuild an id from them.
export function readAttack(source) {
  const text = String(source || "");
  const rest = REST.test(text);
  const begin = BEGIN.test(text);
  let body = text.replace(REST, "").replace(BEGIN, "");
  const add = ADD_ON.exec(body);
  const addOn = add ? add[0].slice(1) : "";
  if (add) body = body.slice(0, -add[0].length);
  let batter = false;
  if (/\.batter$/.test(body)) { batter = true; body = body.slice(0, -".batter".length); }
  const hash = body.indexOf("#");
  const variantText = hash < 0 ? "" : body.slice(hash + 1);
  if (hash >= 0) body = body.slice(0, hash);
  const tokens = variantText ? variantText.split(".").filter(Boolean) : [];
  if (tokens.includes("batter")) batter = true;
  const thrown = tokens.includes("thrown") || tokens.includes("throwing");
  const variant = tokens.filter(token => !["batter", "thrown", "throwing"].includes(token)).join(".");
  // "....rider.<hash>.on.toggle": one setting shared by every delivery and copy of the weapon that carries it.
  const rider = /\.rider\.([0-9a-f]{6,})(?:\.|$)/.exec(text);
  const copyMatch = COPY.exec(body);
  const copy = copyMatch ? Number(copyMatch[1]) : 1;
  const family = copyMatch ? body.slice(0, -copyMatch[0].length) : body;
  return {source: text, family, copy, batter, thrown, variant, addOn, rider: rider ? rider[1] : "", rest, begin};
}

// The weapon's (or ability's) own name, read off the row label: never off an id, so a renamed record still reads.
export function attackName(row, family = "") {
  let text = String(row?.label || "");
  text = text.replace(PARENTHETICAL, "").replace(/\s*\(copy \d+\)/i, "").replace(/^Batter:\s*/i, "");
  text = text.split(/\s+attack:\s+/i)[0];
  text = text.replace(/\s+(?:attack|thrown)$/i, "").trim();
  if (text) return text;
  const tail = String(family).split(".").filter(Boolean).pop() || "";
  return tail.replace(/[._-]+/g, " ").replace(/\b\w/g, letter => letter.toUpperCase()).trim() || "Attack";
}

function chipKeyOf(mode) {
  return [mode.variant, mode.batter ? "batter" : "", mode.thrown ? "thrown" : "", mode.addOn].join("|");
}

// Where a chip sits under its weapon: the plain attack first, then the other deliveries, then the special attacks,
// then what they add on, then the standing talents.
function chipRank(chip) {
  if (chip.mode.addOn) return 5;
  if (chip.mode.batter) return chip.mode.thrown ? 3 : 2;
  if (chip.mode.thrown) return 1;
  if (chip.mode.variant) return 2;
  return 0;
}

function groupHasThrown(group) {
  return group.chips.some(chip => chip.mode.thrown);
}

const copyOf = row => readAttack(attackSource(row)).copy;
const byCopy = (a, b) => copyOf(a) - copyOf(b);

// One group per weapon (or per non-weapon source), identical copies merged: the whole ATTACKS section, read.
// A row that already sits under another row (its "parent": "Heaven-Shaking Batter" On/Off, an augment choice) is not an
// attack of its own and is not folded here; the engine keeps one switch per attack row, so the sheet still draws each
// switch as its own small row under the weapon it changes.
export function groupAttackRows(rows) {
  const groups = new Map();
  for (const row of rows || []) {
    if (!row || row.parent || row.attack_modifier) continue;
    const own = readAttack(attackSource(row));
    const family = own.family;
    let group = groups.get(family);
    if (!group) {
      group = {key: family, rows: [], copies: new Map(), chips: new Map()};
      groups.set(family, group);
    }
    group.rows.push(row);
    const key = chipKeyOf(own);
    let chip = group.chips.get(key);
    if (!chip) {
      chip = {key, mode: own, rows: []};
      group.chips.set(key, chip);
    }
    chip.rows.push(row);
    if (!group.copies.has(own.copy)) group.copies.set(own.copy, []);
    group.copies.get(own.copy).push(row);
  }
  const out = [];
  for (const group of groups.values()) {
    group.chips.forEach(chip => chip.rows.sort(byCopy));
    group.chips = [...group.chips.values()].sort((a, b) => chipRank(a) - chipRank(b)
      || String(a.rows[0]?.label || "").localeCompare(String(b.rows[0]?.label || "")));
    group.baseRow = (group.chips.find(chip => chipRank(chip) === 0) || group.chips[0] || {rows: []}).rows[0] || null;
    group.name = group.baseRow ? attackName(group.baseRow, group.key) : attackName(null, group.key);
    group.copiesTotal = group.copies.size;
    out.push(group);
  }
  return out;
}

// "Melee 5 ft / Thrown 120 ft / Batter": the chip's own name, then only the numbers that differ from the weapon's
// plain attack (its reach is always worth reading, so the range is always there).
export function chipLabel(group, chip) {
  if (chip.mode.addOn) {
    const named = chip.rows[0]?.modifier?.name;
    if (named) return "+ " + named;
    const tail = /\+ ([^+]*)$/.exec(String(chip.rows[0]?.label || ""));
    return "+ " + (tail ? tail[1] : chip.mode.addOn).trim();
  }
  if (chip.mode.variant) {
    const text = String(chip.rows[0]?.label || "");
    const after = /\s+attack:\s+(.+)$/i.exec(text);
    if (after) return after[1].replace(/\s*\(copy \d+\)/i, "").trim();
    return chip.mode.variant.replace(/[._-]+/g, " ").replace(/\b\w/g, letter => letter.toUpperCase()).trim();
  }
  if (chip.mode.batter) return chip.mode.thrown ? "Batter (thrown)" : "Batter";
  if (chip.mode.thrown) return "Thrown";
  return groupHasThrown(group) ? "Melee" : "Attack";
}

// The numbers under the chip name: its reach always, then only what differs from the weapon's plain attack, so the
// same numbers are never printed twice on one group. An add-on (Brutal Strike) prints the numbers the rules lane
// already put on its row; this file never reads rules text to invent one.
export function chipDetail(group, chip) {
  const row = chip.rows[0] || {};
  const detail = row.detail || {};
  const base = (group.baseRow && group.baseRow.detail) || {};
  const parts = [];
  if (detail.range) parts.push(String(detail.range));
  if (detail.to_hit && detail.to_hit !== base.to_hit) parts.push(String(detail.to_hit).replace("-", "\u2212") + " to hit");
  if (detail.save && detail.save !== base.save) parts.push(String(detail.save));
  if (detail.damage && detail.damage !== base.damage) parts.push(String(detail.damage));
  if (Number(detail.attacks) > 1) parts.push(detail.attacks + " attacks");
  if (detail.cost) parts.push(String(detail.cost));
  return parts.join(" \u00b7 ");
}

// Which row a plain click on this chip sends: the whole Action if the Action is still free, else the next attack of
// an Attack action already under way, else the start of one, else the first row so the table's own reason can be shown.
// Copies are tried in order, so a spent copy hands over to the next one.
export function chipChoice(chip, usable = () => true) {
  const rows = chip.rows.filter(row => usable(row));
  const full = rows.find(row => { const read = readAttack(attackSource(row)); return !read.rest && !read.begin; });
  const begin = rows.find(row => readAttack(attackSource(row)).begin);
  const rest = rows.find(row => readAttack(attackSource(row)).rest);
  // A continuation row is the more specific next step: once the Attack action has started, the server stops
  // offering "begin", and "rest" is what the next attack actually is.
  return {rows, full, begin, rest, row: full || rest || begin || chip.rows[0] || null,
    available: Boolean(full || begin || rest)};
}

// The first click when the Attack action holds more than one attack: "use all N attacks on this, or choose each?"
// Only asked when both answers exist -- a fighter with one attack, or one whose Action is already spent, is never asked.
export function chipAsk(choice) {
  if (!choice || !choice.full || !choice.begin) return null;
  const attacks = Math.max(1, ...[choice.full, choice.begin].map(row => Number(row.detail?.attacks) || 1));
  return attacks > 1 ? {attacks, allRow: choice.full, eachRow: choice.begin} : null;
}

// How many attacks the weapon's Attack action holds, and how many are still to come this turn. "spent" is what this
// surface saw spent since the Action was last free; without that count the group says "attacks left" rather than a
// number it cannot know (a reload in the middle of a turn).
export function attackTally(group, {usable = () => true, spent = 0} = {}) {
  const attacks = Math.max(1, ...group.rows.map(row => Number(row.detail?.attacks) || 0));
  const copiesUsed = [...group.copies.keys()].filter(copy => group.copies.get(copy).some(row => usable(row)));
  const plain = group.chips.find(chip => chipRank(chip) === 0) || null;
  const full = plain ? Boolean(chipChoice(plain, usable).full) : false;
  const rest = group.rows.some(row => readAttack(attackSource(row)).rest && usable(row));
  let left = 0;
  let known = true;
  if (attacks <= 1) { left = 0; known = true; }
  else if (full) { left = attacks; known = true; }
  else if (rest) { left = Math.max(0, attacks - Math.max(1, spent)); known = spent > 0; }
  else { left = 0; known = true; }
  return {attacks, copiesUsed: copiesUsed.length, copies: group.copies.size, left, known, full, rest};
}

// The complete view of one group for a surface to draw: nothing here is DOM, so the sheet and the bar draw the same
// reading and the tests can run it without a browser.
export function attackGroupView(group, {usable = () => true, spent = 0} = {}) {
  const tally = attackTally(group, {usable, spent});
  const chips = group.chips.map(chip => {
    const choice = chipChoice(chip, usable);
    const row = choice.row || chip.rows[0] || null;
    return {
      key: chip.key, kind: chip.mode.addOn ? "addon" : "attack",
      label: chipLabel(group, chip), detail: chipDetail(group, chip),
      rows: chip.rows, choice, ask: chipAsk(choice),
      row, rowId: row?.id || null, available: choice.available,
      source: row ? "act:" + attackSource(row) : null,
    };
  });
  return {key: group.key, name: group.name, rows: group.rows, chips, tally,
    copies: tally.copies, copiesUsed: tally.copiesUsed,
    left: tally.left, leftKnown: tally.known, attacks: tally.attacks};
}


// Structured ability families reuse this module and the existing attack-card/chip
// presentation. Unlike legacy weapon ids, variant identity is NEVER parsed.
export function groupVariantRows(rows) {
  const families = new Map();
  for (const row of rows) {
    if (row.variant) families.set(row.variant.base_key, row.variant.base_label);
  }
  const groups = new Map();
  for (const row of rows) {
    const source = variantSource(row);
    const key = row.variant?.base_key || (families.has(source) ? source : row);
    if (!groups.has(key)) groups.set(key, {key, name: row.variant?.base_label || families.get(source), rows: []});
    groups.get(key).rows.push(row);
  }
  return [...groups.values()];
}

export function variantChoiceLabel(row) {
  return row.variant?.choices?.map(part => part.label).join(' + ') || 'Standard';
}

export function variantActionLabel(row) {
  if (!row.variant) return row.label;
  const selected = row.variant.choices?.map(part => part.label).join(' + ');
  return row.variant.base_label + (selected ? ' — ' + selected : '');
}

export function renderVariantGroups(doc, rows, renderRow) {
  return groupVariantRows(rows).map(group => {
    if (!group.name) return renderRow(group.rows[0]);
    const card = doc.createElement('details');
    card.className = 'attack-group action-variant-group';
    card.dataset.variantGroup = group.key;
    const heading = doc.createElement('summary');
    heading.textContent = group.name;
    const chips = doc.createElement('div');
    chips.className = 'attack-chips';
    for (const row of group.rows) {
      // Labels are a view; handlers still receive the original executable id.
      chips.appendChild(renderRow({...row, label: variantChoiceLabel(row),
        variant: row.variant || {base_key: group.key, base_label: group.name, choices: []}}, row));
    }
    card.appendChild(heading);
    card.appendChild(chips);
    return card;
  });
}
