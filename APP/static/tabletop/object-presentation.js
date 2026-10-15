// Shared map-object presentation helpers for the editor preview and combat table.
import {OBJECT_FACE} from "./object-art.js?v=sol201";
import {openingRotation, openingOffset} from './wall-openings.js?v=sol195';
import {arrangeObjects, layoutTokenFields} from "./object-arrange.js?v=sol201";

function cellKey(cell) {
  return Array.isArray(cell) ? `${cell[0]},${cell[1]}` : `${cell?.x},${cell?.y}`;
}

export function objectFacing(object, blockedCells = []) {
  if (object.facing || object.kind !== "door" || (object.rotation !== undefined && object.rotation !== null && object.rotation !== "" && Number(object.rotation) !== 0)) {
    return object.facing || null;
  }
  const blocked = new Set(blockedCells.map(cellKey));
  const horizontalWall = blocked.has(`${object.x - 1},${object.y}`) && blocked.has(`${object.x + 1},${object.y}`);
  const verticalWall = blocked.has(`${object.x},${object.y - 1}`) && blocked.has(`${object.x},${object.y + 1}`);
  return verticalWall && !horizontalWall ? "south" : null;
}

export function editorObjectStats(object, presetName, defaults = {}) {
  const preset = defaults.presets?.[object.kind] || defaults.presets?.custom;
  const resilient = object.resilient ?? preset?.resilient;
  const size = object.size || preset?.size;
  const defaultHp = defaults.sizes?.[size]?.[Number(Boolean(resilient))] ?? preset?.hp;
  const defaultAc = defaults.materials?.[object.material] ?? preset?.ac;
  const hp = Number(object.hp) > 0 ? Number(object.hp) : defaultHp ?? null;
  const ac = Number(object.ac) > 0 ? Number(object.ac) : defaultAc ?? null;
  const defaultThreshold = preset?.threshold ?? null;
  const threshold = Number(object.threshold) > 0 ? Number(object.threshold) : defaultThreshold;
  const hpDefault = object.size || object.resilient !== undefined
    ? "this object's size and whether it is fragile or sturdy"
    : `a ${presetName.toLowerCase()}`;
  const acDefault = object.material ? `${String(object.material).toLowerCase()} objects` : `a ${presetName.toLowerCase()}`;
  const stats = [];
  if (hp !== null) stats.push(`${hp} HP (${Number(object.hp) > 0 ? "override" : "default"})`);
  else stats.push(`HP uses the default for ${hpDefault}`);
  if (ac !== null) stats.push(`${ac} AC (${Number(object.ac) > 0 ? "override" : "default"})`);
  else stats.push(`AC uses the default for ${acDefault}`);
  // Most presets have none; naming the ones that do (bronze, worked stone, packed fill) keeps a blank
  // threshold box from reading as "none" when it actually shrugs off small hits (owner review 2026-10-08).
  if (threshold) stats.push(`Damage Threshold ${threshold} (${Number(object.threshold) > 0 ? "override" : "preset default"}): a hit dealing less than ${threshold} damage does nothing to it`);
  return {hp, maxHp: hp, detail: `${stats.join(" · ")}. Click to select it; use Rotate 90° or Q/E to turn it. Use Erase (X) to remove it.`};
}

// `mapSeed` (the map's look seed) seeds the layout of squares that several objects share (object-arrange.js); a lone object is unchanged.
export function tableObjectTokens(objects, targetIds, blockedCells, seen, width, mapSeed = "", perceived = null) {
  const layouts = arrangeObjects(objects, mapSeed);
  return (objects || []).map(object => {
    const facing = objectFacing(object, blockedCells);
    const rotation = object.mount_axis ? openingRotation(object) : object.rotation;
    return {
      id: object.id, x: object.x, y: object.y, name: object.name, kind: object.kind,
      open: object.open, state: object.state, rotation,
      ...openingOffset(object),
      facing, label: object.label || OBJECT_FACE[object.kind] || "▣", object: true,
      detail: object.detail, color: "#a08a5c", hp: object.hp, maxHp: object.max_hp,
      height_ft: object.height_ft,
      altitude_ft: object.altitude_ft,
      altitudeFt: object.altitude_ft ?? 0,
      targetable: targetIds.has(object.id),
      hidden: Boolean(seen && (perceived ? !perceived.has(object.id) : !seen[object.y * width + object.x])),
      ...layoutTokenFields(layouts.get(object.id), {rotation, facing}),
    };
  });
}
