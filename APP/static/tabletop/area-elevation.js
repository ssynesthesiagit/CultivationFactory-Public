// Shared table /play area composition. Height is a presentation plane, not a
// new targeting or volume rule.
//
// Presentation-height contract (AURALAYER1 F3, finding 1). An area is drawn on
// exactly one plane:
//   1. Attached to a token -- an explicit `anchor_id`, or an aura that follows
//      its owner (`follows_owner`) -- uses that token's displayed height.
//      Merely owning an area (`follows_owner:false`) never lifts it when the
//      caster flies away.
//   2. Painted (`shape:'painted'`) is cell-defined: the recorded cells ARE the
//      area, so it sits on its own cells' plane, the lowest recorded cell. A
//      producer may centre such an area on its owner (verdant_chassis.py
//      `grove_ground` centres ground Living Claims on the flying owner), yet the
//      foliage is still planned and drawn on the ground; a claim painted on a
//      roof (its cells carry `z`) follows that roof's height.
//   3. Otherwise the area keeps its own center height, so an independently
//      placed area stays where it was cast.
// A ground cell serializes without `z` (gate2 Position omits a zero), so a
// missing height on a painted cell is ground.
import {creatureHeightFt} from './roof-regions.js?v=rel6-2';
import {wallLookMarkup, wallPatternDefs} from './wall-art.js?v=sol214';

const cellZ = cell => Array.isArray(cell) ? cell[2] : cell?.z;

// The plane of a cell-painted area: its lowest recorded cell, or `fallback`
// when it records no cells.
export function cellPlaneFt(zone, fallback = 0) {
  const cells = Array.isArray(zone?.affected_cells) ? zone.affected_cells : [];
  if (!cells.length) return fallback;
  return Math.min(...cells.map(cell => { const z = cellZ(cell); return Number.isFinite(z) ? z * 5 : 0; }));
}

export function areaHeightFt(zone, creatureAt = () => null) {
  const profile = zone.trigger_profile || {};
  const id = profile.anchor_id || (profile.follows_owner && zone.owner_id);
  const source = id && creatureAt(id);
  if (source) { const height = creatureHeightFt(source); return Number.isFinite(height) ? height : 0; }
  const height = profile.shape === 'painted'
    ? cellPlaneFt(zone, creatureHeightFt(zone.center || {}))
    : creatureHeightFt(zone.center || {});
  return Number.isFinite(height) ? height : 0;
}

// Use the same vector paths as the visible walls, including authored openings
// (the caller supplies wallPieces). Never mask an outline's whole bounding box.
export function wallSilhouette(wall, context) {
  const styled = wallLookMarkup(wall, context);
  if (styled) return `<defs>${wallPatternDefs()}</defs>${styled}`;
  const points = wall.points || [];
  const style = `fill="${wall.filled && wall.shape !== 'line' ? 'black' : 'none'}" stroke="black" stroke-width=".22" stroke-linecap="round" stroke-linejoin="round"`;
  if (wall.shape === 'rect' && points.length >= 2) {
    const [[x, y], [xx, yy]] = points;
    return `<rect x="${Math.min(x, xx)}" y="${Math.min(y, yy)}" width="${Math.abs(xx-x)}" height="${Math.abs(yy-y)}" rx=".06" ${style}/>`;
  }
  if (wall.shape === 'circle' && points.length >= 2) {
    const [[x, y], [xx, yy]] = points;
    return `<circle cx="${x}" cy="${y}" r="${Math.hypot(xx-x, yy-y)}" ${style}/>`;
  }
  return `<polyline points="${points.map(p => p.join(',')).join(' ')}" ${style}/>`;
}

// Board-sized alpha mask over the original, local material masks. Reuse actual
// scenery artwork, so roof eaves, apertures and object silhouettes stay exact.
// A lower occluder never cuts a hole in a higher area. Opacity preserves the GM's
// translucent roof view; a fully hidden roof contributes nothing.
export function areaOcclusionMask(width, height, elevation, occluders) {
  const covering = occluders.filter(row => row.top > elevation && row.opacity > 0 && row.markup);
  if (!covering.length) return 'none';
  const art = covering.map(row => `<g opacity="${row.opacity}">${row.markup}</g>`).join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><defs><filter id="black" filterUnits="userSpaceOnUse" x="0" y="0" width="${width}" height="${height}"><feColorMatrix type="matrix" values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0"/></filter><mask id="visible" maskUnits="userSpaceOnUse" x="0" y="0" width="${width}" height="${height}" style="mask-type:luminance"><rect width="${width}" height="${height}" fill="white"/><g filter="url(#black)">${art}</g></mask></defs><rect width="${width}" height="${height}" fill="white" mask="url(#visible)"/></svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
}
