// Read-only combat-log presentation. Used by tabletop.js; journal rows stay intact.
// Only map seeding records are grouped, never damage or player/ability changes.
function plural(name) {
  if (name.endsWith('shelf')) return name.slice(0, -1) + 'ves';
  if (/[^aeiou]y$/.test(name)) return name.slice(0, -1) + 'ies';
  if (/(ch|sh|x|z)$/.test(name)) return name + 'es';
  return name.endsWith('s') ? name : name + 's';
}

export function mapObjectFeed(rows, detail = false) {
  if (detail) return rows;
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
    result.push({...group[0], summary: `Breakable here: ${parts.join(', ')}.`,
      hover: group.map(row => row.summary).join('\n')});
  }
  return result;
}
