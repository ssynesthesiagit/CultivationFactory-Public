// Groups an ability's preset option pickers under the ability they belong to (owner 2026-10-12: "Blossom: Medicinal
// Blossom (1 CP)" and its siblings sat as separate top-level rows; they should be indented under "Cultivate Blossom").
// The server marks each picker with `parent`, the source_definition_id of its ability: a menu group carries it as
// `parent`, a sheet button as `parent` too (tabletop._auto_buttons, from a row's parameters.menu_parent). Used by the
// sheet Actions list (sheet.js) and the table action bar (tabletop.js renderActionBar). A picker still selects through
// its own row; nothing here changes what a button does.
// Users: static/tabletop/sheet.js, static/tabletop/tabletop.js. Tested by static/tabletop/option-groups.test.mjs.

/**
 * Split rows into top-level rows, each with its child pickers in list order. Only one level is supported: a row is a
 * child when its parent is in the list, is not the row itself, and is itself top-level. Every other row (no parent,
 * a missing parent, a self-parent, a parent that is itself a child, or a cycle) stays top-level, so no row can disappear.
 * `sourceOf` gives a row's ability id and `parentOf` the ability it belongs to. Two rows sharing one id (a stale custom
 * button alongside its fresh replacement, say) are never resolved as "the" parent for that id -- a child naming it stays
 * top-level instead of silently attaching to whichever of the two happened to come first.
 */
export function groupOptionRows(rows, sourceOf = row => row.source_definition_id, parentOf = row => row.parent) {
  const byId = new Map();
  const ambiguous = new Set();
  for (const row of rows) {
    const id = sourceOf(row);
    if (id == null) continue;
    if (byId.has(id)) ambiguous.add(id);
    else byId.set(id, row);
  }
  const parentRowOf = row => {
    const parentId = parentOf(row);
    if (!parentId || parentId === sourceOf(row) || ambiguous.has(parentId)) return null;
    return byId.get(parentId) || null;
  };
  const isChild = row => {
    const parent = parentRowOf(row);
    return Boolean(parent) && !parentRowOf(parent);
  };
  const children = new Map();
  for (const row of rows) {
    if (!isChild(row)) continue;
    if (!children.has(parentOf(row))) children.set(parentOf(row), []);
    children.get(parentOf(row)).push(row);
  }
  return rows.filter(row => !isChild(row)).map(row => ({group: row, children: children.get(sourceOf(row)) || []}));
}
