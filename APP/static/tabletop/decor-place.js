// Placing and removing biome pieces in the editor (decor-art.js), as a pure step on the map document so it can be
// tested without the page. A look-only piece goes in `decor`; a ruled piece is an ordinary cover or difficult terrain
// square whose look is that piece, grouped in rows by look and turn (a turn is only the look, never a rule).
import {DECOR} from "./decor-art.js?v=sol196r1";

// Returns "removed" when the square already held a piece (which is removed), "placed" when one was added, or null.
export function placeDecor(doc, cell, kind, turn = 0, seed = 1) {
  const {width_squares: width, height_squares: height} = doc;
  if (cell[0] < 0 || cell[1] < 0 || cell[0] >= width || cell[1] >= height) return null;
  const here = ([x, y]) => x === cell[0] && y === cell[1];
  const placed = (doc.decor || []).findIndex(row => here([row.x, row.y]));
  const ruled = (doc.terrain || []).findIndex(row => DECOR[row.look]?.rule && row.cells.some(here));
  if (placed >= 0 || ruled >= 0) {
    if (placed >= 0) doc.decor.splice(placed, 1);
    if (ruled >= 0) {
      doc.terrain[ruled].cells = doc.terrain[ruled].cells.filter(square => !here(square));
      doc.terrain = doc.terrain.filter(row => row.cells.length);
    }
    return "removed";
  }
  const piece = DECOR[kind];
  if (!piece) return null;
  const rotation = [90, 180, 270].includes(Number(turn)) ? Number(turn) : 0;
  if (piece.rule) {
    const row = (doc.terrain || []).find(entry => entry.type === piece.rule && entry.look === kind && (entry.rotation || 0) === rotation);
    if (row) row.cells.push([...cell]);
    else doc.terrain = [...(doc.terrain || []), {type: piece.rule, look: kind, ...(rotation ? {rotation} : {}), cells: [[...cell]]}];
    return "placed";
  }
  doc.decor = [...(doc.decor || []), {kind, x: cell[0], y: cell[1], seed, ...(rotation ? {rotation} : {})}];
  return "placed";
}
