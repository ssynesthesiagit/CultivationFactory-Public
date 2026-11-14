// Read-only combat-log presentation. Used by tabletop.js; journal rows stay intact.
// Only map seeding records are grouped, never damage or player/ability changes.
function plural(name) {
  if (name.endsWith('shelf')) return name.slice(0, -1) + 'ves';
  if (/[^aeiou]y$/.test(name)) return name.slice(0, -1) + 'ies';
  if (/(ch|sh|x|z)$/.test(name)) return name + 'es';
  return name.endsWith('s') ? name : name + 's';
}

export function mapObjectFeed(rows) {
  const placement = row => row.event_type === 'OBJECT_UPDATED' && !row.actor_id
    && row.source_definition_id === 'system:battlefield.object'
    && row.raw?.payload?.object && !row.raw.payload.damage;
  const result = [];
  for (let i = 0; i < rows.length;) {
    if (!placement(rows[i])) { result.push(rows[i++]); continue; }
    const group = [], kinds = new Map();
    while (i < rows.length && placement(rows[i])) {
      const row = rows[i++], object = row.raw.payload.object;
      const name = String(object.component?.name || object.object_kind || 'object').replaceAll('_', ' ').toLowerCase();
      const key = JSON.stringify([name, object.ac, object.maximum_hp]);
      const kind = kinds.get(key) || {name, ac: object.ac, hp: object.maximum_hp, count: 0};
      kind.count += 1;
      kinds.set(key, kind);
      group.push(row);
    }
    const parts = [...kinds.values()].map(({name, ac, hp, count}) =>
      `${count} ${count === 1 ? name : plural(name)} (AC ${ac}, ${hp} HP)`);
    const summary = `Breakable here: ${parts.join(', ')}.`;
    result.push({...group[0], summary, hover: group.map(row => row.summary).join('\n'),
      brief: {group: `map:${group[0].event_sequence}`, kind: 'clause', text: summary}});
  }
  return result;
}

// The default Combat log: one entry per action (owner 2026-11-13, FEEDSUMMARY1). Each row's `brief`
// (combat/feed_brief.py) names its group -- one action, with everything inside it, or one turn change --
// and what it adds: a headline, a turn header, a sentence, or nothing new. Consecutive rows of one group
// fold into one entry, starting from `last` (the entry already at the bottom of the log), so an action whose
// rows arrive in two fetches still ends as one entry. A row without a brief is its own entry, never dropped.
// Returns the entries this call created or changed, in order; every row is kept on its entry for the detail.
export function foldSummary(last, rows) {
  const touched = [];
  for (const row of rows) {
    const brief = row.brief || {group: null, kind: 'clause', text: row.summary};
    const joins = last && last.kind !== 'turn' && brief.kind !== 'turn' && brief.group != null && last.group === brief.group;
    if (!joins) {
      last = {group: brief.group ?? null, kind: brief.kind === 'turn' ? 'turn' : 'action', text: brief.text || '', parts: [], rows: []};
      touched.push(last);
    } else if (!touched.includes(last)) touched.push(last);
    last.rows.push(row);
    if (brief.kind === 'head') last.parts.push({head: brief, row});
    else if (brief.kind === 'clause' && brief.text) last.parts.push({text: String(brief.text), row});
  }
  return touched;
}

// An entry as text pieces: the actor and targets plain, the ability bold, then each outcome sentence (with its row,
// for the colour and roll hover the feed already uses). An entry with no pieces has nothing to show yet.
export function summaryPieces(entry) {
  if (entry.kind === 'turn') return [{text: entry.text}];
  const pieces = [];
  for (const part of entry.parts) {
    if (pieces.length) pieces.push({text: ' '});
    if (part.head) {
      const {actor, targets, ability} = part.head;
      pieces.push({text: `${actor}${targets ? ` → ${targets}` : ''}: `}, {text: ability, strong: true}, {text: '.'});
    } else pieces.push({text: part.text, row: part.row});
  }
  return pieces;
}
