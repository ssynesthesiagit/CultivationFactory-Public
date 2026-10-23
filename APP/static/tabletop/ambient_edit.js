// Pure rules behind the map editor's ambient controls (docs/specs/LIGHTING_SPEC.md §7.3). The editor does not
// derive light; these helpers only decide what the authored map says.

const SELECT_LEVEL = ["dark", "dim", "bright"];

// Painting a square sets its ambient level by moving it into the one region of that level. The square is removed
// from every other region first, so it holds exactly one authored value and a later paint always wins (repainting
// and undo then never depend on which region the square used to belong to).
export function paintAmbientCell(regions, cell, level, makeId = () => "ambient-" + Date.now()) {
  const [x, y] = cell;
  const kept = [];
  for (const region of regions || []) {
    const cells = (region.cells || []).filter(([cx, cy]) => !(cx === x && cy === y));
    if (cells.length) kept.push({...region, cells});
  }
  let target = kept.find(row => row.level === level);
  if (!target) {
    target = {id: makeId(), name: "Ambient light", level, cells: []};
    kept.push(target);
  }
  target.cells = [...target.cells, [x, y]];
  return kept;
}

// Changing the time of day re-derives the level from it. A stored level would otherwise outlive the time it was
// derived from (the save writes one), and the next time change would keep playing the old level.
export function withTimeOfDay(ambient, timeOfDay) {
  const {level, ...rest} = ambient || {};
  return {...rest, time_of_day: timeOfDay};
}

// The indoor select shows the server's stored number as its option name ("" means "use time of day").
export function indoorSelectValue(indoorLevel) {
  if (indoorLevel == null || indoorLevel === "") return "";
  if (typeof indoorLevel === "string") return SELECT_LEVEL.includes(indoorLevel) ? indoorLevel : "";
  return SELECT_LEVEL[indoorLevel] ?? "";
}
