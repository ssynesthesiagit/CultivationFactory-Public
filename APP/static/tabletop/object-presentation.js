// Shared map-object presentation helpers for the editor preview and combat table.
import {OBJECT_FACE} from "./object-art.js?v=sol201";
import {openingRotation, openingOffset} from './wall-openings.js?v=sol195';
import {arrangeObjects, layoutTokenFields} from "./object-arrange.js?v=sol201";
import {AFTERIMAGE_DETAIL, isAfterimageMarker} from "./afterimage-ghost.js";
import {doorDetail} from "./door-interaction.js";

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

// A door is part of the building's outline, not hidden interior space. While its roof is drawn (which only happens
// when every viewer is outside the building) a door the server says the viewer perceives stays in the token layer, on
// top of the roof, as a marker: otherwise a closed roof hides the very thing that says how to get in. Fog still owns
// visibility through `hidden`, so a door the viewer has not perceived is never lifted out of the fog; remembered
// squares keep showing the door through the normal remembered-fog art.
export function doorMarkerAboveRoof(data) {
  return Boolean(data?.object && data.kind === "door" && data.interaction === "simple_door" && !data.hidden);
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
      // The table row's door state drives the leaf, padlock and bar marks (object-art.js) and the hover text.
      interaction: object.interaction, door_locked: object.door_locked, door_jammed: object.door_jammed,
      // A door's hover text says what a player can do with it in plain words (door-interaction.js).
      ac: object.ac,
      ...openingOffset(object),
      facing, label: object.label || OBJECT_FACE[object.kind] || "▣", object: true,
      // An Afterimage is drawn as a generic ghost (afterimage-ghost.js): no HP, no name plate, a fixed owner-neutral card.
      afterimage: isAfterimageMarker(object),
      detail: isAfterimageMarker(object) ? AFTERIMAGE_DETAIL
        : object.interaction === "simple_door" ? doorDetail(object) : object.detail, color: "#a08a5c",
      hp: isAfterimageMarker(object) ? null : object.hp, maxHp: isAfterimageMarker(object) ? null : object.max_hp,
      height_ft: object.height_ft,
      altitude_ft: object.altitude_ft,
      altitudeFt: object.altitude_ft ?? 0,
      targetable: targetIds.has(object.id),
      hidden: Boolean(seen && (perceived ? !perceived.has(object.id) : !seen[object.y * width + object.x])),
      ...layoutTokenFields(layouts.get(object.id), {rotation, facing}),
    };
  });
}
