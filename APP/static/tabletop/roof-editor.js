// Map authoring helpers. Coordinates are zero-based in saved map data; editor
// controls display them as one-based squares. Combat normalizes this same schema.
import {roofSettings} from './roof-regions.js?v=rel6-2';

export const roofOpeningKey = row => `${row.x},${row.y}`;

export function editRoofField(doc, region, field, value) {
  doc.roofs = {...(doc.roofs || {enabled: true, style: 'grey'})};
  if (!region) {
    if (value == null) delete doc.roofs[field]; else doc.roofs[field] = value;
    return;
  }
  const rows = doc.roofs.regions = (doc.roofs.regions || []).map(row => ({...row}));
  let row = rows.find(candidate => region.inside.has(roofOpeningKey(candidate)));
  if (!row) { row = {x: region.x, y: region.y}; rows.push(row); }
  if (value == null) delete row[field]; else row[field] = value;
  doc.roofs.regions = rows.filter(candidate => Object.keys(candidate).length > 2);
}

export function writeRoofOpening(doc, regions, opening, previousKey = null) {
  const {x, y, kind} = opening;
  if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 || x >= doc.width_squares || y >= doc.height_squares) {
    throw new Error('Choose a square inside the map.');
  }
  if (!['trapdoor', 'skylight'].includes(kind)) throw new Error('Choose a trapdoor or skylight.');
  if (!regions.some(region => roofSettings(region, doc.roofs).enabled && region.inside.has(`${x},${y}`))) {
    throw new Error('Place the opening on an enabled building roof.');
  }
  const row = {x, y, kind, open: opening.open === true};
  doc.roofs = {...(doc.roofs || {enabled: true, style: 'grey'}), openings: [
    ...(doc.roofs?.openings || []).filter(other => roofOpeningKey(other) !== previousKey && roofOpeningKey(other) !== roofOpeningKey(row)), row,
  ]};
  return row;
}

export function removeRoofOpening(doc, key) {
  doc.roofs = {...(doc.roofs || {}), openings: (doc.roofs?.openings || []).filter(row => roofOpeningKey(row) !== key)};
}
