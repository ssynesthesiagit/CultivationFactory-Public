// The tabletop board (owner 2026-09-25): background, grid, terrain, drawn walls, tokens,
// highlights, fog of war and effects, with pan and zoom.  Shared by the combat table and
// the map editor.  Board units are squares; one square is CELL pixels at zoom 1.

import {paintFloor, edgeTreatment, isArtificial} from "./textures.js";
import {wallPieces} from './wall-openings.js?v=sol195';
import {wallLook, wallLookMarkup, wallPatternDefs} from './wall-art.js?v=sol214';
import {terrainCellMarkup, terrainLook, terrainTooltip} from "./terrain-art.js?v=sol196r1";
import {OBJECT_FACE, objectArt} from "./object-art.js?v=sol201";
import {wallObjectArt} from './wall-object-art.js?v=sol217b';
import {treeScene} from "./tree-art.js?v=sol196r1";
import {createSpriteLayer} from "./scenery-raster.js?v=sol196r2";
import {decorScene} from "./decor-art.js?v=sol196r1";
import {groundCard} from "./ground-text.js?v=live-b3";
import {createHoverCard} from "./hovercard.js?v=sol192";
import {cellBounds, cellOutline, cellXY, darknessComposition, hashSeed, hatchPath, labelAnchor, normalizeLight, outlinePath, paintedGround, wallAxis, zoneList, zoneLook, zoneTooltip, zonePresentation} from "./zones.js?v=r25x2";
import {hazeTint, lightHazeStyle, materialBlend, materialLayers, paintLayer, paintMaterial, paintTile, paintWall, rgba, rgbOf} from "./zonepaint.js?v=sol196";
import {fogTokenCells, paintFogMask} from "./fog_polygon.js?v=live-b3";
import {detectRoofRegions, roofMapKey, insideRoof, roofOpacity, roofSettings} from './roof-regions.js?v=wallheight-1';
import {indexHeightCards} from './map-height-cards.js?v=mapheight-f1';
import {sceneryHeightText} from './map-heights.js';
import {roofMarkup} from './roof-art.js?v=uirel-1';

import {altitudeBadge} from './flight-ui.js?v=uirel-1';

export const CELL = 64;
let roofSerial = 0;

// Index every rule row that applies to a square so hover cards preserve overlapping rules.
export function ruleTerrainEntriesAt(rows, x, y, floorStyle) {
  const found = [];
  for (const row of rows || []) {
    if (!row || !Array.isArray(row.cells) || !["SIMPLE_COVER", "QI_HAZARD", "DIFFICULT"].includes(row.type)) continue;
    if (row.cells.some(cell => (Array.isArray(cell) ? cell[0] : cell.x) === x && (Array.isArray(cell) ? cell[1] : cell.y) === y)) {
      if (!found.some(entry => entry.type === row.type)) found.push({type: row.type, look: terrainLook({...row, type: row.type}, floorStyle)});
    }
  }
  return found;
}

export function ruleTerrainTransform(x, y) {
  return `translate(${x} ${y}) scale(${1 / CELL})`;
}

// Presentation only: a missing legal candidate is a refusal, not a guessed rule.
export function movementTooltip(explanation, {summary = false} = {}) {
  if (!explanation) return null;
  const lines = (explanation.reasons || []).map(reason => reason.message);
  if (summary) lines.unshift(`Speed ${explanation.effective_speed_ft} feet; ${explanation.movement_remaining_ft} feet of movement left this turn.`);
  else if (!explanation.available && !explanation.explained_refusal) lines.unshift("This square isn't an available destination this turn.");
  return {title: summary ? "Your movement this turn" : explanation.available ? "Movement cost" : "You can't move here", lines};
}

// The mark on a placed object's token (combat/rules/objects.json presets); the table and the map editor share it.
export {OBJECT_FACE};

// The squares a map tree's trunk fills (owner 2026-09-28): one for a tree, two by two for a great tree.
export function treeCells(tree) {
  const size = tree.size === 2 ? 2 : 1, out = [];
  for (let dy = 0; dy < size; dy += 1) for (let dx = 0; dx < size; dx += 1) out.push([tree.x + dx, tree.y + dy]);
  return out;
}

// How long a blink's fade lasts, in milliseconds. tabletop.css fades a blinking token, and the light it carries, with
// `opacity .18s ease`, and the board waits exactly this long before it puts the creature on the committed square: it is
// fully gone before it reappears, so it is never seen crossing the squares in between. The stylesheet and this number
// are one rule -- the tests read the stylesheet and check the two still agree.
export const BLINK_FADE_MS = 180;

// How a committed move is played, as data: a walk steps the recorded path square by square at one steady pace, and a
// teleport blinks once instead of sliding (owner 2026-10-03). The board's animateMove() walks these frames, and the
// tests check them without needing a browser.
export function moveFrames(path, {stepMs = 110, teleport = false} = {}) {
  if (!Array.isArray(path) || path.length < 2) return [];
  // A teleport has no route to walk: the creature is simply somewhere else afterwards. Its wait is the length of the
  // fade, not the pace of a walk, so that a quick AI teleport is not drawn before the creature has finished fading out.
  if (teleport) return [{kind: "blink", delayMs: BLINK_FADE_MS, to: path[path.length - 1]}];
  return path.slice(1).map(point => ({kind: "step", delayMs: stepMs, to: point}));
}
// Walls of air, cloud or light cast only a faint shadow (zonepaint.js raises them gently, too).
const AIRY = new Set(["wind", "smoke", "fog", "dust", "darkness", "spirit", "radiance", "illusion", "sound"]);
const SVG = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, parent = null) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) if (value !== undefined && value !== null) node.setAttribute(key, String(value));
  if (parent) parent.appendChild(node);
  return node;
}

function el(tag, className, parent = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (parent) parent.appendChild(node);
  return node;
}

export function initials(name) {
  const parts = String(name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return ((parts[0] || "?")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : (parts[0] || "")[1] || "")).toUpperCase();
}

export function createBoard(viewport, handlers = {}) {
  viewport.classList.add("tt-viewport");
  const board = el("div", "tt-board", viewport);
  const bg = el("div", "tt-bg", board);
  const floor = el("canvas", "tt-bg-floor", bg);  // built-in painted floor (textures.js)
  const bgImage = el("img", "tt-bg-image", bg);
  bgImage.alt = "";
  bgImage.decoding = "async";
  // Zones (owner 2026-09-27) sit in three bands: the material painted on the ground (under the
  // grid, so squares stay countable) with lights blended onto it; haze, smoke and darkness above
  // the walls; and the edges and names above those.  Walls raised by abilities stand with the map's
  // walls, above the grid, casting their shadow onto it.  All of it stays under the tokens: the
  // engine decides who is hidden, the table only shows where the effect is.
  const zoneGround = el("div", "tt-zones tt-zones-ground", board);
  const lightLayer = el("div", "tt-lights", board);
  const gridSvg = svg("svg", {class: "tt-layer tt-grid", preserveAspectRatio: "none"}, board);
  // Map decoration (decor-art.js): one bitmap under the rule terrain (scenery-raster.js), live SVG only as a fallback.
  const decorSvg = svg("svg", {class: "tt-layer tt-decor-layer", preserveAspectRatio: "none"}, board);
  const terrainSvg = svg("svg", {class: "tt-layer tt-terrain", preserveAspectRatio: "none"}, board);
  const wallSvg = svg("svg", {class: "tt-layer tt-walls", preserveAspectRatio: "none"}, board);
  // Trees (owner 2026-09-28, the map editor): canopies over the walls, under smoke, darkness and the tokens.
  const treeSvg = svg("svg", {class: "tt-layer tt-trees", preserveAspectRatio: "none"}, board);
  // Trees and decoration are painted once into bitmaps and only redrawn when they change (review fix 1: speed).
  const treeRaster = createSpriteLayer(document, board, treeSvg, "tt-tree-raster", treeSvg, CELL);
  const decorRaster = createSpriteLayer(document, board, decorSvg, "tt-decor-raster", decorSvg, CELL);
  const zoneWalls = el("div", "tt-zones tt-zones-walls", board);
  const zoneAir = el("div", "tt-zones tt-zones-air", board);
  const zoneLines = svg("svg", {class: "tt-layer tt-zone-lines", preserveAspectRatio: "none"}, board);
  const zoneLabels = el("div", "tt-zones tt-zone-labels", board);
  const markSvg = svg("svg", {class: "tt-layer tt-marks", preserveAspectRatio: "none"}, board);
  // Fog sits under the tokens: tokens you cannot see are hidden outright, and the ones you
  // can see stay crisp even at the edge of a shadow.
  const interiorTokens = el("div", "tt-tokens tt-roof-interior", board);
  const roofSvg = svg("svg", {class: "tt-layer tt-roofs", preserveAspectRatio: "none"}, board);
  const fog = el("canvas", "tt-fog", board);
  // Perceived air effects sit over the fog wash: a visible cloud must keep its
  // material colour even when it obscures the floor. setFog clips this band to
  // the engine's seen cells, so it never reveals an unexplored cloud elsewhere.
  const zoneClouds = el("div", "tt-zones tt-zones-clouds", board);
  zoneClouds.style.isolation = "isolate"; // keep cloud ordering below tokens
  const tokenLayer = el("div", "tt-tokens", board);
  const fx = el("div", "tt-fx", board);
  const draftSvg = svg("svg", {class: "tt-layer tt-draft", preserveAspectRatio: "none"}, board);

  const view = {x: 0, y: 0, zoom: 1};
  let map = {width: 20, height: 14};
  const tokens = new Map();  // id -> {node, data}
  let roofKey = '', roofRegions = [], roofNodes = [];
  let heightCards = new Map(), heightKey = '';
  let roofView = {gm: true, viewers: [], enabled: true, seen: null};
  // Each board gets unique paint IDs, including simultaneous editor/table previews.
  const roofPrefix = `roof-${++roofSerial}`;

  function setRoofView(next = {}) {
    roofView = {...roofView, ...next};
    // The table supplies the audience; animation supplies only its displayed
    // coordinates. Never add another token as a viewer here. The last received
    // actor row can still name the origin (or the final destination) while a
    // normal/forced move is crossing intermediate squares.
    const viewers = (roofView.viewers || []).map(viewer => {
      const entry = tokens.get(viewer.entity_id ?? viewer.id);
      return entry?.drawn ? {...viewer, position: {...viewer.position, x: entry.drawn.x, y: entry.drawn.y}} : viewer;
    });
    const opacities = roofRegions.map(region => roofOpacity(region, {...roofView, viewers}, map.roofs));
    roofNodes.forEach((node, i) => { node.style.opacity = String(opacities[i]); });
    for (const {node, data, drawn} of tokens.values()) {
      const displayed = drawn ? {...data, x: drawn.x, y: drawn.y} : data;
      const under = roofRegions.some((r,i) => opacities[i] > 0 && insideRoof(r, displayed));
      // A perceived creature stays crisp even when the viewer is outside, looking
      // through a door. This never overrides data.hidden from server perception.
      const perceived = !data.object && !data.item && !roofView.gm && roofView.seen && !data.hidden;
      const layer = under && !perceived ? interiorTokens : tokenLayer;
      if (node.parentNode !== layer) { node.remove(); layer.appendChild(node); }
    }
  }

  function drawRuleTerrain(cells = map.cells || {}) {
    ruleTerrainAt.clear();
    const rows = (map.ruleTerrain || map.terrain || []).filter(row => row && Array.isArray(row.cells));
    const types = [["SIMPLE_COVER", cells.cover], ["QI_HAZARD", cells.hazard], ["DIFFICULT", cells.difficult]];
    const indexedRows = [...rows, ...types.map(([type, legacyCells]) => ({type, cells: legacyCells || []}))];
    const explicit = new Map(types.map(([type]) => [type, new Set(rows.filter(row => row.type === type).flatMap(row => row.cells.map(cell => {
      const [x, y] = Array.isArray(cell) ? cell : [cell.x, cell.y]; return x + "," + y;
    })))]));
    for (const [type, legacyCells] of types) {
      const listed = rows.filter(row => row.type === type).flatMap(row => row.cells.map(cell => ({row, cell})));
      const seen = new Set();
      const paint = (cell, row = {}) => {
        const [x, y] = Array.isArray(cell) ? cell : [cell.x, cell.y];
        if (!Number.isFinite(x) || !Number.isFinite(y) || seen.has(x + "," + y)) return;
        seen.add(x + "," + y);
        const key = x + "," + y;
        ruleTerrainAt.set(key, ruleTerrainEntriesAt(indexedRows, x, y, map.background?.style));
        const node = svg("g", {transform: ruleTerrainTransform(x, y)}, terrainSvg);
        node.innerHTML = terrainCellMarkup(type, terrainLook({...row, type}, map.background?.style), rulesOverlay, 1 + Math.abs((x * 73856093) ^ (y * 19349663)) % 997, row.rotation);
      };
      for (const {row, cell} of listed) paint(cell, row);
      for (const cell of legacyCells || []) {
        const [x, y] = Array.isArray(cell) ? cell : [cell.x, cell.y];
        if (!explicit.get(type).has(x + "," + y)) paint(cell);
      }
    }
  }

  function applyView() {
    board.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
    viewport.style.setProperty("--tt-zoom", String(view.zoom));
    handlers.onView?.({...view});
  }

  // ------------------------------------------------------------ map
  function setMap(next) {
    map = {...next};
    const {width, height} = map;
    roofSvg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const nextRoofKey = roofMapKey(map) + JSON.stringify(map.roofs || {});
    if (roofKey !== nextRoofKey) {
      roofKey = nextRoofKey;
      roofRegions = detectRoofRegions(map);
      roofSvg.replaceChildren();
      roofNodes = roofRegions.map((region, i) => {
        const node = svg('g', {'data-roof': region.id, class: 'tt-roof'}, roofSvg);
        node.innerHTML = roofMarkup(region, roofSettings(region, map.roofs).style, `${roofPrefix}-${i}`);
        return node;
      });
      setRoofView();
    }
    const nextHeightKey = nextRoofKey + JSON.stringify([map.trees, map.ruleTerrain || map.terrain, map.materials]);
    if (heightKey !== nextHeightKey) {
      heightKey = nextHeightKey;
      heightCards = indexHeightCards(map, roofRegions);
    }
    board.style.width = `${width * CELL}px`;
    board.style.height = `${height * CELL}px`;
    for (const layer of [gridSvg, decorSvg, terrainSvg, wallSvg, treeSvg, zoneLines, markSvg, draftSvg]) {
      layer.setAttribute("viewBox", `0 0 ${width} ${height}`);
    }
    const display = map.display || {};
    const detail = display.detail ?? 1;
    const background = map.background || {};
    const floors = (map.floors || []).filter(row => row && row.style && (row.cells || []).length);
    const blend = Math.max(0, Math.min(1, Number(display.blend) || 0));
    const floorKey = background.url ? "" : `${background.style || "flagstone"}:${background.seed || 1}:${width}x${height}:${blend}:${JSON.stringify(floors)}`;
    bg.classList.toggle("tt-bg-procedural", !background.url && background.style === "plain");
    if (background.url) {
      if (bgImage.getAttribute("src") !== background.url) bgImage.src = background.url;
      bgImage.hidden = false;
      bgImage.style.objectFit = background.fit === "stretch" ? "fill" : "cover";
      floor.hidden = true;
    } else {
      bgImage.hidden = true;
      bgImage.removeAttribute("src");
      floor.hidden = background.style === "plain" && !floors.length;
      if (!floor.hidden && floor.dataset.key !== floorKey) {
        const painted = paintFloor(background.style || "flagstone", background.seed || 1, width, height);
        floor.width = painted.width;
        floor.height = painted.height;
        const context = floor.getContext("2d");
        context.clearRect(0, 0, floor.width, floor.height);
        if (background.style !== "plain") context.drawImage(painted, 0, 0);
        // Floor patches painted in the map editor (owner 2026-09-28): each square takes that floor's own texture; with
        // Blend edges up, a patch's edge feathers into its neighbours instead of stopping at the square's edge.
        // Owner 2026-10-08 ("sharper tile with a thin border" for artificial floors meeting anything else): that
        // feathering is only for natural-to-natural seams now. An artificial floor's edge -- against the
        // background, another patch or a bare natural square -- is crisp and gets a thin border instead. Per edge,
        // not per cell (SON202r2 review: a natural cell with one artificial neighbour was losing its blend on its
        // OTHER, natural-facing edges too): track which SIDE of each cell is crisp (textures.js's edgeTreatment,
        // data-driven per style), not just whether the cell touches a crisp seam anywhere.
        const pps = painted.width / width;
        const inBounds = (x, y) => x >= 0 && x < width && y >= 0 && y < height;
        const styleGrid = new Map();
        for (const row of floors) for (const [x, y] of row.cells) styleGrid.set(`${x},${y}`, row.style);
        const styleAt = (x, y) => (inBounds(x, y) ? styleGrid.get(`${x},${y}`) ?? (background.style || "flagstone") : null);
        const hardCells = new Set();
        const crispSides = new Map();
        const seams = [];
        for (let y = 0; y < height; y += 1) {
          for (let x = 0; x < width; x += 1) {
            const here = styleAt(x, y);
            for (const [dx, dy] of [[1, 0], [0, 1]]) {
              const there = styleAt(x + dx, y + dy);
              if (there === null || there === here) continue;
              const treatment = edgeTreatment(here, there);
              if (!treatment?.crisp) continue;
              hardCells.add(`${x},${y}`); hardCells.add(`${x + dx},${y + dy}`);
              seams.push({x, y, dx, dy, borderColor: treatment.borderColor});
              const hereSides = crispSides.get(`${x},${y}`) || {};
              const thereSides = crispSides.get(`${x + dx},${y + dy}`) || {};
              if (dx) { hereSides.right = true; thereSides.left = true; }
              else { hereSides.bottom = true; thereSides.top = true; }
              crispSides.set(`${x},${y}`, hereSides);
              crispSides.set(`${x + dx},${y + dy}`, thereSides);
            }
          }
        }
        const isFullyCrisp = (x, y) => {
          const sides = crispSides.get(`${x},${y}`);
          return !!(sides && sides.top && sides.right && sides.bottom && sides.left);
        };
        for (const row of floors) {
          const patch = paintFloor(row.style, background.seed || 1, width, height, {patch: true});
          // SON202r5 review (finding 1): an artificial destination never blends, full stop -- not just on its
          // crisp-seam sides, but everywhere, including cells with no seam at all (a solid interior, or a whole
          // map of one artificial style with no other style to seam against). The hard/soft split below decides
          // that per CELL from `hardCells`/`crispSides`, which are only populated where two DIFFERENT styles
          // actually meet -- so an artificial cell with no differing neighbour anywhere around it was never
          // added to `hardCells` (skipping the opaque pass entirely) while still landing in `soft` (since
          // `isFullyCrisp` is false when no side is marked crisp), where the later destination-out punch at
          // `isArtificial(styleAt(gx, gy))` below then erases it -- it IS that artificial destination. Short-
          // circuit on the row's own style, exactly like the `!blend` branch above, so an artificial row is
          // always fully opaque and never reaches the blur/punch pipeline regardless of its neighbours.
          if (!blend || isArtificial(row.style)) {
            for (const [x, y] of row.cells) context.drawImage(patch, x * pps, y * pps, pps, pps, x * pps, y * pps, pps, pps);
            continue;
          }
          const hard = row.cells.filter(([x, y]) => hardCells.has(`${x},${y}`));
          for (const [x, y] of hard) context.drawImage(patch, x * pps, y * pps, pps, pps, x * pps, y * pps, pps, pps);
          const soft = row.cells.filter(([x, y]) => !isFullyCrisp(x, y));
          if (!soft.length) continue;
          // Each soft cell blends only on its non-crisp sides: clip the blurred fill to a rect grown on the soft
          // sides but flush (no growth) on any crisp side, so a mixed cell's artificial-facing edge stays exactly
          // as hard as a pure-hard cell's while its other sides still feather like before. On a crisp side, this
          // clip confines the blur strictly within this cell's own already-opaque pixels (painted by the hard
          // pass above, same style, same source pixels) -- so it never bleeds past that edge, and blending the
          // same texture over itself there is a visual no-op regardless of the blur's own alpha falloff.
          //
          // The blur mask canvas only needs to cover the soft cells' own neighbourhood, not the whole floor:
          // a map with many small artificial/natural patches (every cell now potentially mixed, instead of only
          // the few cells that used to qualify as fully soft) made a full-floor-sized blurred canvas per row
          // noticeably slower without this, since Chromium's blur filter cost scales with canvas area.
          const grow = blend * 0.3 * pps;
          const margin = Math.ceil(grow + blend * 0.38 * pps * 1.5);
          let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
          for (const [x, y] of soft) {
            minX = Math.min(minX, x * pps); maxX = Math.max(maxX, (x + 1) * pps);
            minY = Math.min(minY, y * pps); maxY = Math.max(maxY, (y + 1) * pps);
          }
          const offsetX = Math.max(0, Math.floor(minX - margin)), offsetY = Math.max(0, Math.floor(minY - margin));
          const cw = Math.min(floor.width, Math.ceil(maxX + margin)) - offsetX;
          const ch = Math.min(floor.height, Math.ceil(maxY + margin)) - offsetY;
          const softCanvas = document.createElement("canvas");
          softCanvas.width = cw;
          softCanvas.height = ch;
          const mask = softCanvas.getContext("2d");
          mask.save();
          mask.beginPath();
          for (const [x, y] of soft) {
            const sides = crispSides.get(`${x},${y}`) || {};
            const left = sides.left ? 0 : grow;
            const right = sides.right ? 0 : grow;
            const top = sides.top ? 0 : grow;
            const bottom = sides.bottom ? 0 : grow;
            mask.rect(x * pps - left - offsetX, y * pps - top - offsetY, pps + left + right, pps + top + bottom);
          }
          mask.clip();
          mask.filter = `blur(${(blend * 0.38 * pps).toFixed(1)}px)`;
          mask.fillStyle = "#000";
          for (const [x, y] of soft) {
            mask.fillRect(x * pps - grow - offsetX, y * pps - grow - offsetY, pps + 2 * grow, pps + 2 * grow);
          }
          mask.restore();
          mask.globalCompositeOperation = "source-in";
          mask.drawImage(patch, -offsetX, -offsetY);
          // SON202r2 review (finding 1 continued): per-side growth only excludes a soft cell's direct N/E/S/W
          // crisp neighbour. A soft cell grown on two adjacent sides at once (e.g. top and right both natural)
          // still bulges into whatever cell sits at that outside corner -- including one it only touches
          // diagonally, or an L-shaped junction -- and that cell can be artificial even though it's never
          // checked as a "neighbour" by the edge scan above. Punch the exact, ungrown footprint of every such
          // cell (any direction, including diagonal) out of this blend before compositing, so a natural blend
          // can never end up inside an artificial cell's pixels regardless of which row paints last.
          //
          // SON202r3 review (finding 1): that punch must be destination-style-aware, not membership in
          // `hardCells` -- `hardCells` also holds every NATURAL cell that merely sits beside an artificial one
          // (both sides of a crisp seam are added there, so the edge scan loop can mark each side's own crisp
          // sides). Punching out a natural destination cell re-introduces the hard cut this lane exists to
          // remove: two natural cells that are only coincidentally both near an unrelated artificial floor would
          // lose their own soft blend. Re-derive artificialness straight from the destination cell's own style
          // instead, so only an actually-artificial destination ever gets clipped, and a natural destination
          // keeps receiving feathering from its natural neighbours in any direction.
          mask.globalCompositeOperation = "destination-out";
          mask.fillStyle = "#000";
          const gx0 = Math.floor(offsetX / pps), gx1 = Math.ceil((offsetX + cw) / pps);
          const gy0 = Math.floor(offsetY / pps), gy1 = Math.ceil((offsetY + ch) / pps);
          for (let gy = gy0; gy < gy1; gy += 1) {
            for (let gx = gx0; gx < gx1; gx += 1) {
              if (isArtificial(styleAt(gx, gy))) mask.fillRect(gx * pps - offsetX, gy * pps - offsetY, pps, pps);
            }
          }
          context.drawImage(softCanvas, offsetX, offsetY);
        }
        // Thin borders along every crisp seam, drawn last so a later patch never paints back over one.
        if (seams.length) {
          context.lineWidth = Math.max(1, pps * 0.05);
          context.lineCap = "square";
          for (const {x, y, dx, dy, borderColor} of seams) {
            context.strokeStyle = `rgb(${borderColor[0] | 0}, ${borderColor[1] | 0}, ${borderColor[2] | 0})`;
            context.beginPath();
            if (dx) { const edgeX = (x + 1) * pps; context.moveTo(edgeX, y * pps); context.lineTo(edgeX, (y + 1) * pps); }
            else { const edgeY = (y + 1) * pps; context.moveTo(x * pps, edgeY); context.lineTo((x + 1) * pps, edgeY); }
            context.stroke();
          }
        }
        floor.dataset.key = floorKey;
      }
    }
    bg.style.opacity = String(background.opacity ?? 1);
    bg.style.filter = `blur(${((1 - detail) * 4).toFixed(2)}px) saturate(${(0.35 + 0.65 * detail).toFixed(2)}) brightness(${(0.55 + 0.45 * detail).toFixed(2)})`;
    bg.style.setProperty("--tt-floor-contrast", String(0.25 + 0.75 * detail));

    // Grid
    gridSvg.replaceChildren();
    const defs = svg("defs", {}, gridSvg);
    const pattern = svg("pattern", {id: "tt-grid-cell", width: 1, height: 1, patternUnits: "userSpaceOnUse"}, defs);
    svg("path", {d: "M 1 0 L 0 0 0 1", fill: "none", stroke: display.gridColor || "#d8c9a3", "stroke-width": 0.025}, pattern);
    svg("rect", {x: 0, y: 0, width, height, fill: "url(#tt-grid-cell)", opacity: display.gridOpacity ?? 0.35}, gridSvg);
    svg("rect", {x: 0, y: 0, width, height, fill: "none", stroke: display.gridColor || "#d8c9a3", "stroke-width": 0.06, opacity: Math.min(1, (display.gridOpacity ?? 0.35) + 0.25)}, gridSvg);

    // Terrain (rules cells).  Blocked cells from vector walls are drawn faintly so the owner
    // sees exactly which squares the engine treats as walls.
    terrainSvg.replaceChildren();
    const cells = map.cells || {};
    const drawCells = (list, cls) => {
      for (const cell of list || []) {
        const [x, y] = Array.isArray(cell) ? cell : [cell.x, cell.y];
        svg("rect", {x, y, width: 1, height: 1, class: cls}, terrainSvg);
      }
    };
    // Map decoration (decor-art.js, owner 2026-10-08 biome packs): pure look, under the rule terrain, never in a rule.
    const decor = map.decor || [];
    decorRaster.draw(decor.length ? decorScene(decor) : null, [-1, -1, width + 2, height + 2], `${width}x${height}:${JSON.stringify(decor)}`);
    drawRuleTerrain(cells);
    const trunks = new Set((map.trees || []).flatMap(treeCells).map(([x, y]) => `${x},${y}`));
    const isTrunk = cell => trunks.has(Array.isArray(cell) ? `${cell[0]},${cell[1]}` : `${cell.x},${cell.y}`);
    const thin = new Set((map.centerlineCells || []).map(([x,y]) => `${x},${y}`));
    const fullCells = (cells.blocked || []).filter(c => !thin.has(Array.isArray(c) ? `${c[0]},${c[1]}` : `${c.x},${c.y}`));
    const drawn = map.walls && map.walls.length;
    drawCells(drawn ? fullCells : fullCells.filter(cell => !isTrunk(cell)), drawn ? "tt-cell-blocked-ghost" : "tt-cell-blocked");
    if (!drawn) drawCells((cells.blocked || []).filter(isTrunk), "tt-cell-blocked-ghost");
    drawCells(cells.sightGhost || cells.sight, "tt-cell-sight-ghost");

    drawTrees(map.trees || []);

    // Walls (vectors)
    wallSvg.replaceChildren();
    const wdefs = svg("defs", {}, wallSvg);
    const stone = svg("pattern", {id: "tt-stone", width: 1, height: 1, patternUnits: "userSpaceOnUse"}, wdefs);
    svg("rect", {x: 0, y: 0, width: 1, height: 1, class: "tt-stone-base"}, stone);
    svg("path", {d: "M0 .5 H1 M.5 0 V.5 M.25 .5 V1 M.75 .5 V1", class: "tt-stone-joints"}, stone);
    // Wall looks (wall-art.js): tile patterns for filled walls with a look, defined once.
    if ((map.walls || []).some(wall => wallLook(wall) && wall.filled && wall.shape !== "line")) svg("g", {}, wallSvg).innerHTML = `<defs>${wallPatternDefs()}</defs>`;
    for (const wall of map.walls || []) for (const piece of wallPieces(wall, map.openings)) drawWall(wallSvg, piece);
    if (!map.walls?.length) for (const cell of cells.blocked || []) {
      const [x, y] = Array.isArray(cell) ? cell : [cell.x, cell.y];
      if (trunks.has(`${x},${y}`)) continue;  // a tree's trunk is drawn by the tree
      svg("rect", {x: x + 0.04, y: y + 0.04, width: 0.92, height: 0.92, rx: 0.08, class: "tt-wall tt-wall-solid"}, wallSvg);
    }
    rebuildGroundIndex();
    resizeFog();
  }

  // ------------------------------------------------------------ ground (owner 2026-09-30)
  // "Hovering over the types of ground ... should bring up the type of material and its effects on
  // movement or anything else." What a square is made of is already here (map.floors patches, the
  // arena's terrain cells, walls and trees); the readable name-and-effect for each material kind
  // comes from the server catalog on map.ground (combat/ground_text.py), so no rule is guessed here.
  const groundStyles = new Map();   // "x,y" -> the floor style painted on that square
  // sight: squares that stop line of sight but can still be walked through (a screen / a sight-only
  // wall). Kept apart from blocked, which cannot be entered at all, so the card can say the difference.
  const groundCells = {cover: new Set(), hazard: new Set(), difficult: new Set(), blocked: new Set(), sight: new Set()};
  const groundTrunks = new Set();   // tree trunks: blocked, but read as a tree rather than a wall
  let groundCenterlines = new Set();  // bound geometry, empty for predecessor whole-cell fights
  const groundCellKey = cell => {
    const [x, y] = Array.isArray(cell) ? cell : [cell?.x, cell?.y];
    return Number.isInteger(x) && Number.isInteger(y) ? `${x},${y}` : "";
  };
  function rebuildGroundIndex() {
    groundCenterlines = new Set((map.centerlineCells || []).map(groundCellKey).filter(Boolean));
    groundStyles.clear();
    for (const row of map.floors || []) for (const cell of row.cells || []) groundStyles.set(groundCellKey(cell), row.style);
    for (const kind of ["cover", "hazard", "difficult", "blocked", "sight"]) {
      groundCells[kind] = new Set((map.cells?.[kind] || []).map(groundCellKey).filter(Boolean));
    }
    groundTrunks.clear();
    for (const tree of map.trees || []) for (const [x, y] of treeCells(tree)) groundTrunks.add(`${x},${y}`);
  }
  // The ground under a square: the material, plus any arena terrain cells or wall/tree on it.
  // A painted floor patch wins over the map's own base ground; ground-text.js turns this into the
  // card's {title, lines} so it stays testable without a DOM.
  // A named terrain the map painted is ground too (combat/zones.py map_zones; the map editor previews
  // the same areas), and it is a rule of its own rather than a texture -- so its name goes to the card
  // and the card says what that ground does instead of only what it is drawn as.
  function groundTerrains(key) {
    const names = [];
    for (const entry of zoneAt.get(key) || []) {
      if (!zonePresentation(entry.zone).mapTerrain) continue;   // only ground the map itself painted
      for (const name of entry.look.terrain || []) {
        if (name && !names.includes(name)) names.push(name);
      }
    }
    return names;
  }
  function groundTooltip(cell) {
    if (!cell) return null;
    const key = `${cell.x},${cell.y}`;
    return groundCard(cell, {
      style: groundStyles.get(key) || (map.background && !map.background.url ? map.background.style : null),
      terrain: groundTerrains(key)[0] || null,
      tree: groundTrunks.has(key),
      difficult: groundCells.difficult.has(key),
      hazard: groundCells.hazard.has(key),
      cover: groundCells.cover.has(key),
      blocked: groundCells.blocked.has(key),
      sight: groundCells.sight.has(key),
      centerline: groundCenterlines.has(key),
      catalog: map.ground,
    });
  }

  // Trees seen from above (tree-art.js): broadleaf by default, or the kind a tree's `look` names. Every kind follows
  // the same rules: the trunk squares (treeCells) block movement and sight in a fight; the crown is only the look.
  function drawTrees(list) {
    // A crown reaches up to about three squares past its trunk, so the layer runs that far past the map's edges.
    const {width = 1, height = 1} = map;
    treeRaster.draw(list.length ? treeScene(list) : null, [-3, -3, width + 6, height + 6], `${width}x${height}:${JSON.stringify(list)}`);
  }

  function drawWall(parent, wall, extraClass = "") {
    // A wall with a look (wall-art.js) is drawn in that look; one element per piece, still a .tt-wall for the editor.
    const styled = wallLookMarkup(wall);
    if (styled) {
      const group = svg("g", {class: `tt-wall tt-wall-styled ${wall.blocks === "sight" ? "is-sight" : "is-solid"} ${extraClass}`.trim()}, parent);
      group.innerHTML = styled;
      return group;
    }
    const cls = `tt-wall ${wall.blocks === "sight" ? "tt-wall-sight" : "tt-wall-solid"} ${wall.filled ? "tt-wall-filled" : "tt-wall-outline"} ${extraClass}`;
    const points = wall.points || [];
    if (wall.shape === "rect" && points.length >= 2) {
      const [[x0, y0], [x1, y1]] = points;
      return svg("rect", {x: Math.min(x0, x1), y: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0), rx: 0.06, class: cls}, parent);
    }
    if (wall.shape === "circle" && points.length >= 2) {
      const [[cx, cy], [ex, ey]] = points;
      return svg("circle", {cx, cy, r: Math.hypot(ex - cx, ey - cy), class: cls}, parent);
    }
    return svg("polyline", {points: points.map(p => p.join(",")).join(" "), class: `${cls} tt-wall-line${wall.door_join ? ' tt-wall-door-join' : ''}`}, parent);
  }

  // ------------------------------------------------------------ tokens
  // The hover card (owner 2026-09-27): name, hit points and conditions in red.
  // One card for the whole board (hovercard.js): the zone card and the token card are two looks on the SAME element,
  // so the owner's 2026-10-03 "hover it, move onto it, scroll it" card is one fix rather than one per card.
  // onClose: the card tells us when it goes away however it goes away -- Escape, a press elsewhere, or the pointer
  // staying off it too long. Whoever was describing a token puts that token's name here, and must be told, or the
  // next token update would put the same card back up after the player had dismissed it.
  const hover = createHoverCard({doc: document, win: window,
                                 onClose: () => { card.owner = null; card.movement = false; },
                                 onDismiss: () => cancelTipTimer()});
  const card = {node: hover.node, owner: null, movement: false};
  function showCard(entry, move = null) {
    const data = entry.data;
    if (data.item || data.hidden) { hideCard(); return; }
    // Each condition in red, with what it does (owner 2026-09-27: "a mechanical description of its effects").
    const pill = row => `<div class="tt-card-cond-row is-${row.tone || "debuff"}"><span class="tt-card-cond">${escapeText(row.name)}${row.stacks > 1 ? ` ×${row.stacks}` : ""}</span>`
      + (row.text ? `<span class="tt-card-cond-text">${escapeText(row.text)}</span>` : "") + "</div>";
    const section = creature => `<b>${escapeText(creature.name)}</b>${creature.lifeStatus ? `<span class="tt-card-hp">${escapeText(creature.lifeStatus)}</span>` : creature.hp != null && creature.maxHp != null ? `<span class="tt-card-hp">${creature.hp} / ${creature.maxHp} HP${creature.temp ? ` <span class="tt-card-temp">+${creature.temp} temporary</span>` : ""}${creature.down ? " · down" : ""}</span>` : ""}`
      + (creature.flightDetail ? `<span class="tt-card-none">${escapeText(creature.flightDetail)}</span>` : "")
      + (creature.object && creature.height_ft != null ? `<span class="tt-card-none">${escapeText(sceneryHeightText(creature, 'object', 'Height'))}</span>` : "")
      + (creature.object ? `<span class="tt-card-none">${escapeText(creature.detail || "")}</span>`
        : creature.lifeStatus === "Dead" ? "" : (creature.conditions || []).length ? `<div class="tt-card-conds">${creature.conditions.map(pill).join("")}</div>` : `<span class="tt-card-none">No conditions</span>`);
    const companion = data.ridingOn ? tokens.get(data.ridingOn)
      : [...tokens.values()].find(other => other.data.ridingOn === data.id && !other.data.hidden);
    let html = section(data);
    if (companion && !companion.data.hidden) {
      html += `<div class="tt-card-companion"><span class="tt-card-none">${data.ridingOn ? "Riding" : "Ridden by"} ${escapeText(companion.data.name)}</span>${section(companion.data)}</div>`;
    }
    // Long condition rules are cut to a few lines here; the mini sheet (click the token) shows each in full (owner
    // 2026-09-30: a Smoke Veil card ran off the map). The card scrolls now, and it never sits on the token.
    if (html.includes("tt-card-cond-text")) {
      html += `<span class="tt-card-none">Click the token for each effect's full rules.</span>`;
    }
    if (move) {
      html += `<div class="tt-card-companion tt-movement-tip"><b>${escapeText(move.title)}</b>${move.lines.map(line => `<span class="tt-card-none">${escapeText(line)}</span>`).join("")}</div>`;
    }
    const rect = entry.node.getBoundingClientRect();
    const box = {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom};
    card.node.className = "tt-hovercard tt-token-card";
    // Key the actual visible words: unrelated updates preserve the DOM (and selection), while changed words
    // use the shared card's in-place refresh, retaining scroll and deferring replacement during selection.
    hover.open({trigger: entry.node, anchor: {x: rect.left + rect.width / 2, y: rect.top},
                avoid: box, key: html,
                build: node => { node.innerHTML = html; }});
    // Ownership is recorded AFTER the card is up: opening the card closes whatever was in it, and the close tells us
    // to forget the old token. Recording it before would hand the board a token it had just been told to forget.
    card.owner = entry;
    card.movement = Boolean(move);
  }
  function hideCard() { hover.close(); }   // the close above forgets the token for us
  // Identity changes also dismiss ground/zone cards, which have no token owner,
  // and cancel a delayed tip before it can reopen content from the previous view.
  function closeHoverCard() { cancelTipTimer(); hover.close(); }
  const escapeText = text => String(text ?? "").replace(/[&<>"]/g, ch => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[ch]);

  function setTokens(list) {
    const wallArt = wallObjectArt(list, map.objects || []);
    const seen = new Set();
    for (const data of list) {
      seen.add(data.id);
      let entry = tokens.get(data.id);
      if (!entry) {
        const node = el("button", "tt-token", tokenLayer);
        node.type = "button";
        node.innerHTML = `<span class="tt-token-ring"></span><span class="tt-token-face"></span><span class="tt-token-hp"><i></i></span><span class="tt-token-name"></span><span class="tt-token-badge"></span><span class="tt-token-height" hidden></span><span class="tt-token-conds" hidden></span>`;
        node.addEventListener("pointerenter", () => { cancelTipTimer(); showCard(entry); });
        // Leaving the token does NOT close the card: the shared card's grace period and hover bridge decide, so the
        // pointer can travel onto the card and scroll it (owner 2026-10-03).
        node.addEventListener("pointerleave", () => { cancelTipTimer(); });
        node.addEventListener("focus", () => showCard(entry));
        node.addEventListener("blur", event => { if (card.owner === entry) hover.releaseFocus(event); });
        node.addEventListener("pointerdown", event => { cancelTip(); event.stopPropagation(); handlers.onTokenPointerDown?.(data.id, event); });
        node.addEventListener("click", event => { event.stopPropagation(); handlers.onTokenClick?.(entry.data.id, event); });
        node.addEventListener("dblclick", event => { event.stopPropagation(); handlers.onTokenDoubleClick?.(entry.data.id, event); });
        entry = {node, data};
        tokens.set(data.id, entry);
        placeToken(entry, data.x, data.y);
      }
      const offsetX = Number(data.offsetX) || 0, offsetY = Number(data.offsetY) || 0;
      // Against what is on the board, not against the last state received: a token that has already walked its
      // committed path is where this state wants it, so nothing is moved or replayed a second time.
      const moved = !entry.drawn || entry.drawn.x !== data.x || entry.drawn.y !== data.y
        || entry.drawn.offsetX !== offsetX || entry.drawn.offsetY !== offsetY;
      entry.data = data;
      const node = entry.node;
      // A creature bigger than one square (a Large mount, 2x2) is drawn across its squares; its rider sits on top of it,
      // centred over the mount (owner 2026-09-29: "a mount is a larger token; its rider's token shares the space and sits on top").
      const size = Math.max(1, Number(data.size) || 1);
      const height = Math.max(1, Number(data.height) || size), scale = Number(data.scale) || 1;
      node.style.width = `${size * scale * CELL}px`;
      node.style.height = `${height * scale * CELL}px`;
      node.classList.toggle("is-large", size > 1);
      node.classList.toggle("is-riding", Boolean(data.ridingOn));
      node.style.setProperty("--tt-team", data.color || "#c9a45c");
      const face = node.querySelector(".tt-token-face");
      const art = data.object ? (wallArt.get(data.id) || objectArt(data.kind, {open: data.open || data.state === "open", rotation: data.rotation, facing: data.facing})) : null;
      face.innerHTML = data.image ? "" : (art || "");
      // An object sharing its square (object-arrange.js) answers only where it is drawn, so its neighbours stay clickable.
      node.style.pointerEvents = data.shared ? "none" : "";
      if (data.shared) face.querySelector("svg")?.style.setProperty("pointer-events", "visiblePainted");
      if (!data.object || !art) face.textContent = data.image ? "" : (data.label || initials(data.name));
      face.toggleAttribute("data-long", face.textContent.length > 2);
      node.querySelector(".tt-token-face").style.backgroundImage = data.image ? `url("${data.image}")` : "";
      node.querySelector(".tt-token-name").textContent = data.name;
      node.querySelector(".tt-token-badge").textContent = data.badge || "";
      const ratio = data.maxHp ? Math.max(0, Math.min(1, data.hp / data.maxHp)) : 1;
      const bar = node.querySelector(".tt-token-hp i");
      bar.style.width = `${ratio * 100}%`;
      bar.className = ratio > 0.5 ? "hp-high" : ratio > 0.25 ? "hp-mid" : "hp-low";
      node.classList.toggle("is-current", Boolean(data.current));
      node.classList.toggle("is-selected", Boolean(data.selected));
      node.classList.toggle("is-targetable", Boolean(data.targetable));
      node.classList.toggle("is-down", Boolean(data.down));
      node.classList.toggle("is-hidden", Boolean(data.hidden));
      node.classList.toggle("is-unseen", Boolean(data.unseen));
      node.classList.toggle("is-yours", Boolean(data.yours));
      node.classList.toggle("is-item", Boolean(data.item));
      node.classList.toggle("is-object", Boolean(data.object));
      node.classList.toggle("has-object-art", Boolean(art));
      face.style.transform = data.object && !art ? `rotate(${Number(data.rotation)||0}deg)` : '';
      const ariaLabel = data.item ? data.name : data.object && data.hp == null
        ? `${data.name}. ${data.detail || "Uses the default hit points and Armor Class for this object."}`
        : `${data.name}, ${data.hp} of ${data.maxHp} hit points${data.current ? ", current turn" : ""}`;
      node.setAttribute("aria-label", ariaLabel);
      const altitude = node.querySelector(".tt-token-height");
      altitude.textContent = altitudeBadge(data);
      altitude.hidden = !altitude.textContent;
      node.classList.toggle("is-airborne", !altitude.hidden);
      altitude.title = `Height: ${data.altitudeFt || 0} ft above the battlefield floor`;
      if (!altitude.hidden) node.setAttribute("aria-label", `${ariaLabel}, height ${data.altitudeFt} feet above the battlefield floor`);
      if (data.item) node.title = data.name;
      else {
        node.removeAttribute("title");
        node.dataset.hoverCard = ""; // declare the custom card before glossary pointer events
      }
      const conds = node.querySelector(".tt-token-conds");
      conds.hidden = !(data.conditions || []).length;
      conds.textContent = (data.conditions || []).length > 1 ? String(data.conditions.length) : "";
      setTokenLight(entry, data.hidden ? null : normalizeLight(data.light));
      if (moved && !entry.animating) placeToken(entry, data.x, data.y);
    }
    for (const [id, entry] of tokens) if (!seen.has(id)) { entry.node.remove(); removeNodes([entry.light]); tokens.delete(id); }
    setRoofView();
    // Refresh only after both members of a mounted stack have their latest HP/conditions. Only a card that is
    // actually up gets refreshed: a token the player dismissed with Escape or a press elsewhere is no longer ours to
    // bring back on the next update.
    if (hover.isOpen && card.owner) tokens.has(card.owner.data.id)
      ? showCard(card.owner, card.movement ? movementTooltip(movement?.summary, {summary: true}) : null)
      : hideCard();
  }

  function placeToken(entry, x, y) {
    const dx = Number(entry.data?.offsetX) || 0, dy = Number(entry.data?.offsetY) || 0;  // a rider is drawn over its mount's centre
    entry.node.style.transform = `translate(${(x + dx) * CELL}px, ${(y + dy) * CELL}px)`;
    // Where the token is actually drawn, kept apart from entry.data (the last state the fight sent). A move
    // animation walks the token to the square the fight committed to before that state arrives, and this is what
    // lets the arriving state see it has nothing left to move (owner 2026-10-03: "it moves forward then jumps back
    // before loading then finally moving super fast to the location").
    entry.drawn = {x, y, offsetX: dx, offsetY: dy};
    if (entry.light) entry.light.style.transform = lightTransform(x + dx, y + dy);
    // Roof entry and exit follow the same drawn waypoint, including a teleport's
    // single landing. A later state refresh is not needed to update the roof.
    setRoofView();
  }

  // A token carrying a light (a Ghost Lantern summon, a torch): the glow follows the token.
  function setTokenLight(entry, light) {
    const key = light ? `${light.radiusCells}:${light.color}:${light.level}` : "";
    if (key === (entry.lightKey || "")) return;
    if (entry.light) fadeOut([entry.light]);
    entry.light = light ? lightNode(light, entry.data.x, entry.data.y) : null;
    entry.lightKey = key;
    if (entry.light) fadeIn([entry.light]);
  }

  // A teleport blinks: the token fades out where it stood and fades back in on the square the fight committed to, and
  // the light it carries goes with it. The run that started a blink owns it, so a move that takes over mid-blink cannot
  // be drawn half-hidden, and a run that is overtaken hands its blink back unless the run that replaced it blinks too.
  function setBlink(entry, on, run) {
    if (on) {
      entry.blinkRun = run;
      entry.node.classList.add("is-blinking");
      if (entry.light) entry.light.classList.add("is-blinking");
    } else if (run == null || entry.blinkRun === run) {
      entry.blinkRun = 0;
      entry.node.classList.remove("is-blinking");
      if (entry.light) entry.light.classList.remove("is-blinking");
    }
  }

  // Make the browser apply the styles set so far, so a blink is really drawn invisible before the creature changes
  // square, and give the renderer a frame. requestAnimationFrame runs before the paint, so one callback is not yet a
  // drawn frame: the second one is. That is what lets a teleport keep the is-blinking transform 0s rule through the
  // relocation and the frame that draws it, so the destination cannot be animated into.
  const settle = node => { void node.offsetWidth; };
  // Hidden tabs can suspend frames indefinitely. Presentation must still release the caller's busy/AI loop;
  // visibility changes and a bounded fallback finish the wait without claiming a paint happened.
  const nextFrame = () => new Promise(resolve => {
    if (document.hidden) { resolve(); return; }
    let frame, timer, finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      cancelAnimationFrame(frame);
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      resolve();
    };
    const onVisibility = () => { if (document.hidden) finish(); };
    document.addEventListener("visibilitychange", onVisibility);
    frame = requestAnimationFrame(finish);
    timer = setTimeout(finish, 100);
  });

  // A committed move is played once, at a steady pace, along the path the fight recorded, and it stops on the square
  // the fight committed to (owner 2026-10-03: "it moves forward then jumps back before loading then finally moving
  // super fast to the location"). The state that arrives afterwards asks for that same square, so there is nothing
  // left to move and nothing is replayed. Human moves, AI moves and forced moves all arrive here the same way.
  async function animateMove(id, path, {stepMs = 110, teleport = false} = {}) {
    const entry = tokens.get(id);
    if (!entry) return;
    const frames = moveFrames(path, {stepMs, teleport});
    if (!frames.length) return;
    // A second move for the same token takes over from the first, so two walks never fight over one position.
    const run = (entry.animationRun || 0) + 1;
    entry.animationRun = run;
    const landing = frames[frames.length - 1].to;
    entry.animating = true;
    entry.node.classList.add("is-moving");
    // The replacement owns visibility immediately; do not wait for the old fade timer to wake up.
    setBlink(entry, false);
    if (teleport) {
      // A blink must not slide: clearing the inline duration lets the is-blinking rule's transform 0s win.
      entry.node.style.transitionDuration = "";
      if (entry.light) entry.light.style.transitionDuration = "";
    } else {
      entry.node.style.transitionDuration = `${stepMs}ms`;
      if (entry.light) entry.light.style.transitionDuration = `${stepMs}ms`;
    }
    // Being overtaken is checked after every await, not only before it: a move that starts during a blink's fade out
    // must not put the creature back on the square it was leaving, or clear a newer blink (the superseded run returns
    // and lets go of its own blink, so the move that replaced it is drawn from the beginning).
    const overtaken = () => setBlink(entry, false, run);
    for (const frame of frames) {
      if (entry.animationRun !== run) { overtaken(); return; }  // a newer move owns the token now
      if (frame.kind === "blink") {
        settle(entry.node);
        if (entry.light) settle(entry.light);
        setBlink(entry, true, run);
        // Start the opacity transition before starting its clock, including for a newly drawn token/light.
        settle(entry.node);
        if (entry.light) settle(entry.light);
        await new Promise(resolve => setTimeout(resolve, frame.delayMs));  // fade out where it stood
        if (entry.animationRun !== run) { overtaken(); return; }
        settle(entry.node);                                              // ...drawn invisible, and the slide is off
        placeToken(entry, frame.to.x, frame.to.y);                        // and it reappears on the committed square
        await nextFrame();                                               // one frame to draw it there...
        if (entry.animationRun !== run) { overtaken(); return; }
        await nextFrame();                                               // ...and one more, so the square is on the board
        if (entry.animationRun !== run) { overtaken(); return; }
        // A suspended frame is not a paint. Commit the destination's zero-duration transform before restoring
        // transitions, so a hidden/slow tab cannot later slide from the origin when it becomes visible.
        settle(entry.node);
        if (entry.light) settle(entry.light);
        setBlink(entry, false, run);                                      // before lifting the blink, which would
        continue;                                                        // otherwise restart the 0.18s slide
      }
      placeToken(entry, frame.to.x, frame.to.y);
      await new Promise(resolve => setTimeout(resolve, frame.delayMs));
    }
    if (entry.animationRun !== run) { overtaken(); return; }
    entry.animating = false;
    placeToken(entry, landing.x, landing.y);
    entry.node.classList.remove("is-moving");
    setBlink(entry, false, run);
    entry.node.style.transitionDuration = "";
    if (entry.light) entry.light.style.transitionDuration = "";
  }

  // ------------------------------------------------------------ highlights
  function setHighlights({moves = [], path = [], areas = [], areaCells = [], line = null, targets = [], pending = null} = {}) {
    markSvg.replaceChildren();
    // A move on its way (owner 2026-09-28: "show the way is clicked like an outline of the movement but let it load before
    // moving"): the path and a pulsing outline where the token is going, until the fight answers.
    if (pending) {
      if ((pending.path || []).length > 1) svg("polyline", {points: pending.path.map(p => `${p.x + 0.5},${p.y + 0.5}`).join(" "), class: "tt-mark-path is-pending"}, markSvg);
      svg("circle", {cx: pending.destination.x + 0.5, cy: pending.destination.y + 0.5, r: 0.42, class: "tt-mark-pending"}, markSvg);
    }
    // The token that is on its way breathes faintly and stays exactly where it stands. It is not moved ahead of the
    // fight, so there is nothing to snap back from and nothing to replay (owner 2026-10-03).
    for (const [id, entry] of tokens) entry.node.classList.toggle("is-pending", Boolean(pending) && id === pending.actorId);
    for (const cell of moves) svg("rect", {x: cell.x + 0.06, y: cell.y + 0.06, width: 0.88, height: 0.88, rx: 0.12, class: "tt-mark-move"}, markSvg);
    for (const cell of areaCells) svg("rect", {x: cell.x, y: cell.y, width: 1, height: 1, class: "tt-mark-area"}, markSvg);
    for (const center of areas) svg("path", {d: `M${center.x + 0.5} ${center.y + 0.18} L${center.x + 0.82} ${center.y + 0.5} L${center.x + 0.5} ${center.y + 0.82} L${center.x + 0.18} ${center.y + 0.5} Z`, class: "tt-mark-center"}, markSvg);
    for (const cell of targets) {
      const width = cell.width || 1, height = cell.height || 1, scale = cell.scale || 1;
      svg("ellipse", {cx: cell.x + (cell.offsetX || 0) + width * scale / 2, cy: cell.y + (cell.offsetY || 0) + height * scale / 2,
        rx: width / 2 + 0.12, ry: height / 2 + 0.12, class: "tt-mark-target"}, markSvg);
    }
    if (path.length > 1) svg("polyline", {points: path.map(p => `${p.x + 0.5},${p.y + 0.5}`).join(" "), class: "tt-mark-path"}, markSvg);
    if (line) svg("line", {x1: line.from.x + 0.5, y1: line.from.y + 0.5, x2: line.to.x + 0.5, y2: line.to.y + 0.5, class: `tt-mark-line ${line.blocked ? "is-blocked" : ""}`}, markSvg);
  }

  // ------------------------------------------------------------ fog
  function resizeFog() {
    fog.width = map.width * CELL;
    fog.height = map.height * CELL;
  }

  // seen: Uint8Array (1 = visible) or null for no fog; explored: Uint8Array of remembered cells.
  let zoneSeen = null;
  function setFog(seen, explored = null, geometry = {}) {
    setRoofView({seen});
    zoneSeen = seen;
    const context = fog.getContext("2d");
    context.clearRect(0, 0, fog.width, fog.height);
    fog.hidden = !seen;
    const cells = [];
    if (seen) for (let i = 0; i < seen.length; i++) if (seen[i]) cells.push([i % map.width, Math.floor(i / map.width)]);
    const airMask = seen ? zoneMask(cells, 0, 0, map.width, map.height, 0) : "none";
    // zoneMask is 16 px per square; stretch once over the 64 px/square board.
    Object.assign(zoneClouds.style, {maskImage: airMask, webkitMaskImage: airMask,
      maskSize: "100% 100%", webkitMaskSize: "100% 100%",
      maskRepeat: "no-repeat", webkitMaskRepeat: "no-repeat",
      maskPosition: "0 0", webkitMaskPosition: "0 0"});
    if (!seen) return;
    const scale = CELL;
    context.fillStyle = "rgba(7,9,14,0.933)";
    context.fillRect(0, 0, fog.width, fog.height);
    if (explored) {
      context.fillStyle = "rgba(7,9,14,0.588)";
      for (let index = 0; index < explored.length; index += 1) if (explored[index] && !seen[index])
        context.fillRect((index % map.width) * scale, Math.floor(index / map.width) * scale, scale, scale);
    }
    const mask = document.createElement("canvas");
    mask.width = fog.width; mask.height = fog.height;
    const m = mask.getContext("2d");
    paintFogMask(m, map.width, map.height, seen, {
      ...geometry, tokenCells: fogTokenCells([...tokens.values()].map(entry => entry.data)),
    }, scale);
    context.globalCompositeOperation = "destination-out";
    context.drawImage(mask, 0, 0);
    context.globalCompositeOperation = "source-over";
  }


  // ------------------------------------------------------------ zones and lights (owner 2026-09-27)
  // presentation.zones -> painted materials, haze, darkness, light, edges, names and a tooltip.
  // A zone is rebuilt only when its squares or look change (a zone that follows its owner moves),
  // and fades in and out between refreshes.
  const zones = new Map();    // zone_id -> {signature, nodes, zone, look, owner, cells}
  const mapTerrain = zone => zonePresentation(zone, rulesOverlay).mapTerrain;
  let rulesOverlay = false;
  try { rulesOverlay = localStorage.getItem("tt-rules-overlay") === "true"; } catch (_error) { /* storage off */ }
  let lastZones = [], lastZoneOptions = {};
  const zoneAt = new Map();   // "x,y" -> [entry] for the tooltip
  const ruleTerrainAt = new Map(); // "x,y" -> every static movement, hazard, or cover rule
  const tileCache = new Map();
  let zoneRound = 0;

  function fadeIn(nodes) {
    for (const node of nodes) node.classList.add("tt-zone-enter");
    requestAnimationFrame(() => requestAnimationFrame(() => { for (const node of nodes) node.classList.remove("tt-zone-enter"); }));
  }

  function fadeOut(nodes) {
    for (const node of nodes) if (node) node.classList.add("tt-zone-leave");
    setTimeout(() => removeNodes(nodes), 600);
  }

  function removeNodes(nodes) { for (const node of nodes) node?.remove(); }

  const lightTransform = (x, y) => `translate(${(x + 0.5) * CELL}px, ${(y + 0.5) * CELL}px)`;

  function lightNode(light, x, y) {
    const node = el("div", `tt-light is-${light.level}`, lightLayer);
    const size = light.radiusCells * 2 * CELL, rgb = rgbOf(light.color);
    node.style.width = node.style.height = `${size}px`;
    node.style.margin = `${-size / 2}px 0 0 ${-size / 2}px`;
    // Bright light holds its strength well out and then falls off; dim light is a soft wash.
    node.style.background = light.level === "dim"
      ? `radial-gradient(circle closest-side, ${rgba(rgb, 0.4)}, ${rgba(rgb, 0.24)} 40%, ${rgba(rgb, 0.08)} 78%, ${rgba(rgb, 0)})`
      : `radial-gradient(circle closest-side, ${rgba(rgb, 0.78)}, ${rgba(rgb, 0.55)} 30%, ${rgba(rgb, 0.3)} 62%, ${rgba(rgb, 0.1)} 86%, ${rgba(rgb, 0)})`;
    node.style.transform = lightTransform(x, y);
    return node;
  }

  function zoneMask(cells, x0, y0, w, h, blur = 3) {
    // Exactly the zone's squares as ONE shape, feathered only at its outer edge so the area reads as a single
    // cloud (owner 2026-10-06: darkness looked like "lots of little squares"). The squares used to be inset and
    // filled one by one; a canvas filter blurs each fill separately, so every square became its own soft blob
    // with a gap around it. One path, one fill, one blur. (A wall's shadow still asks for a wider feather.)
    const scale = 16, canvas = document.createElement("canvas");
    canvas.width = w * scale;
    canvas.height = h * scale;
    const context = canvas.getContext("2d");
    context.filter = `blur(${blur}px)`;
    context.fillStyle = "#fff";
    context.beginPath();
    for (const [x, y] of cells) context.rect((x - x0) * scale, (y - y0) * scale, scale, scale);
    context.fill();
    return `url(${canvas.toDataURL()})`;
  }

  function tileUrl(kind, seed, tint, size) {
    const key = `${kind}:${seed}:${tint}:${size}`;
    if (!tileCache.has(key)) {
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = size;
      paintTile(canvas.getContext("2d"), kind, size, seed, tint);
      tileCache.set(key, `url(${canvas.toDataURL()})`);
    }
    return tileCache.get(key);
  }

  function zoneCanvas(spec) {
    const canvas = el("canvas", "tt-zone-canvas");
    canvas.width = Math.round(spec.w * spec.ppc);
    canvas.height = Math.round(spec.h * spec.ppc);
    return canvas;
  }

  // One animated layer: a zone-sized canvas (flames, arcs, rings) or a seamless drifting tile.
  function zoneLayer(layer, spec, kit, tint) {
    let node;
    if (layer.canvas) {
      node = zoneCanvas(spec);
      paintLayer(node.getContext("2d"), layer.canvas, spec, layer.variant || 0, kit);
    } else {
      const span = (layer.cells || 3) * CELL;
      node = el("div", "tt-zone-tile");
      // A few variants per kind are enough to break repetition, and they stay cached.
      node.style.backgroundImage = tileUrl(layer.tile, (spec.seed % 3) + (layer.variant || 0) * 7, layer.tint || tint, Math.min(256, span));
      node.style.backgroundSize = `${span}px ${span}px`;
      node.style.inset = `${-span}px`;
      node.style.setProperty("--tt-dx", `${(layer.dx || 0) * span}px`);
      node.style.setProperty("--tt-dy", `${(layer.dy || 0) * span}px`);
    }
    node.classList.add("tt-zone-fx", `tt-anim-${layer.anim}`);
    node.style.animationDuration = `${layer.duration}s`;
    if (layer.delay) node.style.animationDelay = `${-layer.delay}s`;
    if (layer.reverse) node.style.animationDirection = "reverse";
    if (layer.opacity !== undefined) node.style.opacity = String(layer.opacity);
    if (layer.blend) node.style.mixBlendMode = layer.blend;
    if (layer.lo !== undefined) { node.style.setProperty("--tt-lo", String(layer.lo)); node.style.setProperty("--tt-hi", String(layer.hi ?? 1)); }
    if (layer.anim === "spin" || layer.anim === "ripple") node.style.transformOrigin = `${(kit.cx - spec.x0) * CELL}px ${(kit.cy - spec.y0) * CELL}px`;
    return node;
  }

  // Haze over a zone: an even wash of the tint plus drifting cloud tiles in the same tint.
  function hazeLayers(parent, spec, kit, tint, fill, drifts) {
    el("div", "tt-zone-fill", parent).style.background = rgba(tint, fill);
    for (const drift of drifts) parent.appendChild(zoneLayer({anim: "drift", ...drift, tint}, spec, kit, tint));
  }

  // How dark a Darkness is drawn (owner 2026-10-03 03:38: "a more transparent darkness for regular darkness and still
  // slightly transparent but almost pitch black for pure darkness ... for snagging/clinging darkness we could have dark
  // tentacles you can barely see waving in the area"). The area's own typed rows say which one applies
  // (combat/ext/tabik_dark.py); this only draws it, and never changes what can be seen. The shares of the look
  // that the ground and the air each spend are darknessComposition's -- zones.js, which also says what an area
  // with no look is drawn with.
  const DARKNESS_TINT = [4, 4, 10];
  // A faint charcoal-violet highlight remains visible over the opaque near-black veil.
  // Its strokes still ride inside the air group's existing opacity budget.
  const DARKNESS_STRAND_TINT = [72, 64, 88];
  function darknessLayers(parent, look, spec, kit, wall) {
    const dark = darknessComposition(look.darknessLook, {wall: Boolean(wall)});
    // No look: another sphere's darkness, or an area saved before the engine said which one it gets. It is drawn
    // exactly as it always was -- the same flat wash in the air, over the same material on the ground.
    if (!dark) {
      hazeLayers(parent, spec, kit, DARKNESS_TINT, wall ? 0.42 : 0.8,
                 [{tile: "haze", cells: 4, dx: -1, dy: 1, duration: 44, opacity: 0.85}]);
      return;
    }
    // This look's share of its own budget, spent on the veil in the air; the material on the ground spends the
    // other half (the ground box, in buildZone). The drifting haze and the tentacles ride inside that share
    // instead of on top of it, so the two layers together hide the look's fill rather than one layer of a
    // bigger stack -- and the tentacles stay as faint as "barely see" asks for.
    parent.style.opacity = String(dark.air);
    el("div", "tt-zone-fill", parent).style.background = rgba(DARKNESS_TINT, 1);
    if (look.darknessTentacles || look.darknessLook === "tentacles") {
      // Alternate between endpoints: fractional tile travel cannot reset seamlessly like full-tile drift.
      for (const drift of [
        {tile: "tentacles", cells: 4, dx: 0.3, dy: 0.45, duration: 27, opacity: 0.55},
        {tile: "tentacles", cells: 3, dx: -0.35, dy: 0.3, duration: 36, opacity: 0.4, variant: 1},
      ]) parent.appendChild(zoneLayer({anim: "sway", ...drift, tint: DARKNESS_STRAND_TINT}, spec, kit, DARKNESS_STRAND_TINT));
    } else {
      parent.appendChild(zoneLayer({anim: "drift", tile: "haze", cells: 4, dx: -1, dy: 1, duration: 44, opacity: 0.85,
                                    tint: DARKNESS_TINT}, spec, kit, DARKNESS_TINT));
    }
  }

  function buildZone(zone, look, cells, teamColor) {
    const pad = 1, bounds = cellBounds(cells);
    const x0 = bounds.minX - pad, y0 = bounds.minY - pad, w = bounds.width + pad * 2, h = bounds.height + pad * 2;
    // Canvas pixels per square: up to half the board's 64, fewer for big zones (build time and memory); map scenery
    // (a bamboo grove) up to the board's full 64, since it is looked at closely and never animates.
    const sharp = mapTerrain(zone);
    const ppc = Math.max(10, Math.min(sharp ? 64 : 32, Math.floor(Math.sqrt(600000 / (w * h)))));
    const spec = {x0, y0, w, h, ppc, seed: hashSeed(zone.zone_id), cells, center: zone.center, radius: Number(zone.radius_cells) || 0, color: rgbOf(look.color)};
    const mask = zoneMask(cells, x0, y0, w, h);
    const edgeColor = teamColor || look.color;
    const wall = look.wall;
    const box = (className, image = mask) => {
      const node = el("div", `tt-zone ${className}`);
      Object.assign(node.style, {left: `${x0 * CELL}px`, top: `${y0 * CELL}px`, width: `${w * CELL}px`, height: `${h * CELL}px`, maskImage: image, webkitMaskImage: image});
      return node;
    };
    const nodes = [];

    // A wall (owner 2026-09-27) stands up: its shadow falls on the floor below and to the right, away
    // from the light.  Smoke and darkness, which only hide, cast none.
    if (wall && wall.kind !== "screen") {
      const [dx, dy, alpha] = wall.kind === "solid" ? [0.2, 0.4, 0.78] : [0.1, 0.2, 0.55];
      const airy = AIRY.has(look.material) ? 0.45 : 1;
      const shadow = box("tt-zone-wall-shadow", zoneMask(cells, x0, y0, w, h, 5));
      shadow.style.transform = `translate(${dx * CELL}px, ${dy * CELL}px)`;
      shadow.style.background = `rgba(0, 0, 0, ${alpha * airy})`;
      zoneWalls.appendChild(shadow);
      nodes.push(shadow);
    }

    // The ground: the material itself, over the floor (for a wall: the material raised into a barrier).
    const ground = box(`tt-zone-ground tt-mat-${look.material}${wall ? ` tt-zone-wall is-${wall.kind}` : ""}`);
    if (materialBlend(look.material)) ground.style.mixBlendMode = materialBlend(look.material);
    const paint = zoneCanvas(spec);
    const kit = paintMaterial(paint.getContext("2d"), look.material, spec);
    if (wall) paintWall(paint.getContext("2d"), look.material, spec, wall, wallAxis(cells));
    // Smoke and darkness walls stay a cloud: the floor shows faintly through.
    if (wall?.kind === "screen") ground.style.opacity = "0.86";
    // A Darkness the engine gave a look spends that look's darkness across this material AND the veil in the
    // air (darknessLayers), so the floor still shows through the two together instead of the material alone
    // hiding it. An area with no look keeps the material exactly as it is.
    const dark = darknessComposition(look.darknessLook, {wall: Boolean(wall)});
    if (dark) ground.style.opacity = String(dark.ground);
    ground.appendChild(paint);
    const tint = hazeTint(look.material, spec.color);
    // Obscuring haze reads lighter than the ground it hangs over (except darkness, which is black).
    const haze = tint[0] + tint[1] + tint[2] < 90 ? tint : tint.map(value => value + (255 - value) * 0.3);
    // A formation's turning rings or a ripple circle a point; along a wall they would only smear.
    const layers = materialLayers(look.material).filter(layer => !wall || (layer.anim !== "spin" && layer.anim !== "ripple"));
    for (const layer of layers) ground.appendChild(zoneLayer(layer, spec, kit, tint));
    (wall ? zoneWalls : zoneGround).appendChild(ground);
    nodes.push(ground);

    // Scenery painted on the map (owner 2026-09-29, a bamboo grove): its own look is the obscurement and the rough
    // ground, so no haze, hatching, edge or name is laid over it; its tooltip still says what it does.
    const presentation = zonePresentation(zone, rulesOverlay);
    const scenery = presentation.mapTerrain && !rulesOverlay;
    const painted = paintedGround(zone);
    // The air: magical darkness and obscurement cover the floor, the grid and the walls.
    if (!scenery && (look.darkness || look.obscured)) {
      // A recognized Darkness look gets a wider feather than the grid's own, so its edge fades instead of stepping
      // (owner 2026-10-03 03:38: "a clearly see-through dark veil ... soft edges").
      // Untagged or unrelated darkness keeps the original mask, just like its original opacity.
      const air = box(`tt-zone-air is-${look.darkness ? "dark" : look.obscured}`,
                      look.darkness && dark ? zoneMask(cells, x0, y0, w, h, 3) : mask);
      // Darkness must not paint over another area's smoke, dust or mist merely
      // because its row was received later. Preserve each area's merged mask.
      air.style.zIndex = look.darkness ? "0" : "1";
      if (look.darkness) darknessLayers(air, look, spec, kit, wall);
      if (look.obscured === "heavy") {
        hazeLayers(air, spec, kit, look.darkness ? [10, 10, 16] : haze, 0.62, [
          {tile: "heavy", cells: 4, dx: 1, dy: 1, duration: 40, opacity: 0.95},
          {tile: "clouds", cells: 3, dx: -1, dy: 0, duration: 58, opacity: 0.75, variant: 1},
        ]);
      } else if (look.obscured === "light") {
        const style = lightHazeStyle(zone, look, spec.color, haze);
        hazeLayers(air, spec, kit, style.tint, style.fill, style.drifts);
      }
      // Leave darkness below the zone rims, labels and movement marks as before.
      // Other obscuring materials have their own perceived cloud band over it.
      (look.darkness ? zoneAir : zoneClouds).appendChild(air);
      nodes.push(air);
    }

    if (scenery) return nodes;
    // Edge (in the owner's team colour), hatching where movement costs double, and the name.
    const edgeClass = presentation.mapTerrain ? " tt-zone-edge-map" : presentation.softRim ? " tt-zone-edge-natural" : "";
    const group = svg("g", {class: `tt-zone-edge${edgeClass}`}, zoneLines);
    group.style.setProperty("--tt-zone-team", edgeColor);
    if (presentation.hatch && look.difficult) {
      // A dark underline keeps the hatch readable on pale materials (ash, ice) as well as dark ones.
      const hatch = hatchPath(cells);
      svg("path", {d: hatch, class: `tt-zone-hatch-shadow is-${look.difficult}`}, group);
      svg("path", {d: hatch, class: `tt-zone-hatch is-${look.difficult}`, style: look.difficult === "hostile" ? `stroke: ${edgeColor}` : null}, group);
    }
    // A wall's edge says what it stops: a plain hard dark rim for a wall no one walks through (its
    // owner's colour stays on its name), a broken edge for a wall that only hides (long dashes) or only
    // shelters and slows (short dashes).
    // Map scenery remains frameless even when its rules overlay is shown.
    if (!painted) {
      const outline = outlinePath(cellOutline(cells)), kindClass = wall ? ` is-wall is-wall-${wall.kind}` : "";
      svg("path", {d: outline, class: `tt-zone-halo${kindClass}${presentation.softRim ? " tt-zone-soft-rim" : ""}`}, group);
      if (wall?.kind !== "solid" || presentation.softRim) svg("path", {d: outline, class: `tt-zone-outline${kindClass}${presentation.softRim ? " tt-zone-soft-rim" : ""}`, stroke: edgeColor}, group);
    }
    nodes.push(group);

    const label = el("div", "tt-zone-label", zoneLabels);
    label.textContent = look.name;
    if (!presentation.label) label.classList.add("tt-zone-label-hover");
    label.style.setProperty("--tt-zone-team", edgeColor);
    const anchor = labelAnchor(cells);
    label.style.left = `${anchor.x * CELL}px`;
    label.style.top = `${anchor.y * CELL}px`;
    label.classList.toggle("is-inside", anchor.y <= 0);
    nodes.push(label);

    if (look.light && zone.center) nodes.push(lightNode(look.light, zone.center.x, zone.center.y));
    return nodes;
  }

  // zones: presentation.zones.  round: the current round (for rounds left).  teamOf(owner_id)
  // returns the owner's team colour, or {color, owner} to also name the owner in the tooltip.
  function setZones(list, {round = 0, teamOf = null} = {}) {
    lastZones = list; lastZoneOptions = {round, teamOf};
    zoneRound = Number(round) || 0;
    const seen = new Set();
    for (const zone of zoneList(list)) {
      seen.add(zone.zone_id);
      const look = zoneLook(zone);
      const team = teamOf ? teamOf(zone.owner_id) : null;
      const teamColor = typeof team === "string" ? team : team?.color || null;
      const cells = zone.affected_cells.map(cellXY)
        .filter(([x, y]) => Number.isInteger(x) && Number.isInteger(y) && x >= 0 && y >= 0 && x < map.width && y < map.height);
      if (!cells.length) continue;
      const signature = JSON.stringify([cells, look, teamColor, zone.center, zone.radius_cells]);
      let entry = zones.get(zone.zone_id);
      if (entry && entry.signature !== signature) { fadeOut(entry.nodes); entry = null; }
      if (!entry) {
        entry = {signature, edgeColor: teamColor || look.color, nodes: buildZone(zone, look, cells, teamColor)};
        zones.set(zone.zone_id, entry);
        fadeIn(entry.nodes);
      }
      Object.assign(entry, {zone, look, cells, owner: typeof team === "object" && team ? team.owner || null : null,
                            foe: typeof team === "object" && team ? Boolean(team.foe) : null});
    }
    for (const [id, entry] of zones) if (!seen.has(id)) { fadeOut(entry.nodes); zones.delete(id); }
    zoneAt.clear();
    for (const entry of zones.values()) for (const [x, y] of entry.cells) {
      const key = `${x},${y}`;
      if (!zoneAt.has(key)) zoneAt.set(key, []);
      zoneAt.get(key).push(entry);
    }
    tipKey = "";
  }
  function setRulesOverlay(enabled) {
    rulesOverlay = Boolean(enabled);
    try { localStorage.setItem("tt-rules-overlay", String(rulesOverlay)); } catch (_error) { /* storage off */ }
    setMap(map);
    for (const [id, entry] of zones) { fadeOut(entry.nodes); zones.delete(id); }
    setZones(lastZones, lastZoneOptions);
  }

  // Hovering a zone names it and says what it does. It is the shared hover card, so it stays up while the pointer
  // travels onto it, scrolls there and can be selected (owner 2026-10-03), and a long one (Darkness and its four
  // riders, then a Court) scrolls instead of running off the bottom of the screen.
  const ZONE_TIP_DELAY_MS = 900;
  // Ground alone waits longer before its card appears (owner 2026-09-30: hovering the types of ground
  // "2 seconds actually"), so a plain square's material card never flashes under a moving pointer.
  const GROUND_TIP_DELAY_MS = 2000;
  const tip = hover.node;
  let movement = null;
  function setMovementExplanation(next) {
    if (next === movement) return;
    if (JSON.stringify(next) !== JSON.stringify(movement)) cancelTip();
    movement = next || null;
  }
  let tipKey = "";
  function hideTip() {
    for (const entry of zones.values()) for (const node of entry.nodes) node.classList?.remove("is-hovered");
    tipKey = "";
    if (hover.interacting) return;   // keep the text being read/selected; token movement still resets the summary
    if (card.owner && !card.movement && hover.ownsPointer()) return;
    if (card.movement && card.owner) showCard(card.owner);
    else hideCard();
  }
  // The screen box of the square under the pointer: the card is placed beside it and never on top of it.
  function cellScreenBox(cell) {
    if (!cell) return null;
    const rect = viewport.getBoundingClientRect();
    const size = CELL * view.zoom;
    const left = rect.left + view.x + cell.x * size;
    const top = rect.top + view.y + cell.y * size;
    return {left, top, right: left + size, bottom: top + size};
  }
  function showTip(event) {
    // Token hover keeps the creature's HP, conditions and companion together.
    // Occupied tokens never inherit their square's destination/zone card.
    if (event.tokenId) {
      hideTip();
      const entry = tokens.get(event.tokenId);
      if (entry && event.tokenId === movement?.summary?.actor_id) {
        showCard(entry, movementTooltip(movement.summary, {summary: true}));
      }
      return;
    }
    const cell = event.buttons ? null : cellAt(event.clientX, event.clientY);
    const ground = groundTooltip(cell);
    const structures = cell && (!zoneSeen || zoneSeen[cell.y * map.width + cell.x])
      ? heightCards.get(`${cell.x},${cell.y}`) : null;
    const found = cell && (!zoneSeen || zoneSeen[cell.y * map.width + cell.x]) ? zoneAt.get(`${cell.x},${cell.y}`) : null;
    const terrain = cell ? ruleTerrainAt.get(`${cell.x},${cell.y}`) : null;
    for (const entry of zones.values()) for (const node of entry.nodes) node.classList?.toggle("is-hovered", !rulesOverlay && (found || []).includes(entry) && node.classList.contains("tt-zone-label-hover"));
    const move = movementTooltip(cell && movement?.destinations?.[`${cell.x},${cell.y}`]);
    if (!found?.length && !move && !terrain?.length && !ground && !structures?.length) { hideTip(); return; }
    const key = `${cell?.x},${cell?.y}|${event.tokenId || ""}|${(found || []).map(entry => entry.zone.zone_id).join("|")}|${(terrain || []).map(entry => entry.type).join("|")}|${ground ? ground.title : ""}|${JSON.stringify(move)}|${JSON.stringify(structures || [])}`;
    const build = node => {
      node.replaceChildren();
      for (const card of structures || []) {
        const item = el('div', 'tt-zone-tip-item', node);
        el('b', '', item).textContent = card.title;
        for (const line of card.lines) el('span', '', item).textContent = line;
      }
      if (move) {
        const item = el("div", "tt-zone-tip-item tt-movement-tip", node);
        el("b", "", item).textContent = move.title;
        for (const line of move.lines) el("span", "", item).textContent = line;
      }
      if (ground) {
        const item = el("div", "tt-zone-tip-item tt-ground-tip", node);
        el("b", "", item).textContent = ground.title;
        for (const line of ground.lines) el("span", "", item).textContent = line;
      }
      for (const rule of terrain || []) {
        const info = terrainTooltip(rule.type);
        if (info) {
          const item = el("div", "tt-zone-tip-item", node);
          el("b", "", item).textContent = info.title;
          el("span", "", item).textContent = info.line;
        }
      }
      for (const entry of found || []) {
        const {title, lines} = zoneTooltip(entry.zone, entry.look, {round: zoneRound, owner: entry.owner, foe: entry.foe});
        const item = el("div", "tt-zone-tip-item", node);
        const heading = el("b", "", item);
        heading.textContent = title;
        heading.style.setProperty("--tt-zone-team", entry.edgeColor);
        for (const line of lines) el("span", "", item).textContent = line;
      }
    };
    // bridge: "card" - this card belongs to the square the pointer is resting on, not to an element, so moving to
    // the next square dismisses it while moving onto the card keeps it.
    tip.className = "tt-hovercard tt-zone-tip";
    hover.open({anchor: {x: event.clientX, y: event.clientY}, avoid: cellScreenBox(cell), bridge: "card",
                key: tipKey === key ? null : key, build: tipKey === key ? null : build});
  }

  // ------------------------------------------------------------ effects
  function floatText(x, y, text, kind = "damage") {
    const node = el("div", `tt-float tt-float-${kind}`, fx);
    node.textContent = text;
    node.style.left = `${(x + 0.5) * CELL}px`;
    node.style.top = `${y * CELL}px`;
    setTimeout(() => node.remove(), 1600);
  }

  function flashLine(from, to, kind = "attack") {
    const line = svg("line", {x1: from.x + 0.5, y1: from.y + 0.5, x2: to.x + 0.5, y2: to.y + 0.5, class: `tt-flash tt-flash-${kind}`}, draftSvg);
    setTimeout(() => line.remove(), 700);
  }

  function setDraft(builder) {
    draftSvg.replaceChildren();
    if (builder) builder(draftSvg, {svg, drawWall});
  }

  // ------------------------------------------------------------ pan and zoom
  function clampZoom(value) { return Math.min(4, Math.max(0.15, value)); }

  function zoomBy(factor, clientX, clientY) {
    const rect = viewport.getBoundingClientRect();
    const px = (clientX ?? rect.left + rect.width / 2) - rect.left;
    const py = (clientY ?? rect.top + rect.height / 2) - rect.top;
    const next = clampZoom(view.zoom * factor);
    view.x = px - (px - view.x) * (next / view.zoom);
    view.y = py - (py - view.y) * (next / view.zoom);
    view.zoom = next;
    applyView();
  }

  function fit() {
    const rect = viewport.getBoundingClientRect();
    const zoom = clampZoom(Math.min(rect.width / (map.width * CELL), rect.height / (map.height * CELL)) * 0.96);
    view.zoom = zoom;
    view.x = (rect.width - map.width * CELL * zoom) / 2;
    view.y = (rect.height - map.height * CELL * zoom) / 2;
    applyView();
  }

  function centerOn(x, y) {
    const rect = viewport.getBoundingClientRect();
    view.x = rect.width / 2 - (x + 0.5) * CELL * view.zoom;
    view.y = rect.height / 2 - (y + 0.5) * CELL * view.zoom;
    applyView();
  }

  function cellAt(clientX, clientY, {continuous = false} = {}) {
    const rect = viewport.getBoundingClientRect();
    const bx = (clientX - rect.left - view.x) / (CELL * view.zoom);
    const by = (clientY - rect.top - view.y) / (CELL * view.zoom);
    if (continuous) return {x: bx, y: by};
    const x = Math.floor(bx), y = Math.floor(by);
    return x >= 0 && y >= 0 && x < map.width && y < map.height ? {x, y} : null;
  }

  let drag = null;
  viewport.addEventListener("wheel", event => {
    event.preventDefault();
    zoomBy(Math.exp(-event.deltaY * 0.0015), event.clientX, event.clientY);
  }, {passive: false});
  viewport.addEventListener("contextmenu", event => event.preventDefault());
  viewport.addEventListener("pointerdown", event => {
    if (handlers.onPointerDown?.(event, cellAt(event.clientX, event.clientY, {continuous: true})) === true) return;
    drag = {id: event.pointerId, sx: event.clientX, sy: event.clientY, vx: view.x, vy: view.y, moved: false, button: event.button};
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener("pointermove", event => {
    if (handlers.onPointerMove?.(event, cellAt(event.clientX, event.clientY, {continuous: true})) === true) return;
    if (drag && drag.id === event.pointerId) {
      const dx = event.clientX - drag.sx, dy = event.clientY - drag.sy;
      if (!drag.moved && Math.hypot(dx, dy) > 5) { drag.moved = true; viewport.classList.add("is-panning"); }
      if (drag.moved) { view.x = drag.vx + dx; view.y = drag.vy + dy; applyView(); }
      return;
    }
    handlers.onCellHover?.(cellAt(event.clientX, event.clientY), event);
  });
  const endDrag = event => {
    if (handlers.onPointerUp?.(event, cellAt(event.clientX, event.clientY, {continuous: true})) === true) { drag = null; return; }
    if (!drag || drag.id !== event.pointerId) return;
    const wasClick = !drag.moved && drag.button === 0;
    drag = null;
    viewport.classList.remove("is-panning");
    if (wasClick) handlers.onCellClick?.(cellAt(event.clientX, event.clientY), event);
  };
  viewport.addEventListener("pointerup", endDrag);
  viewport.addEventListener("pointercancel", () => { drag = null; viewport.classList.remove("is-panning"); });
  viewport.addEventListener("pointerleave", () => handlers.onCellHover?.(null));
  // The zone card waits for the pointer to rest, like the browser's own tooltip (owner 2026-09-30: instant, it covered
  // the Darkness they were trying to move through); moving on hides it until the pointer rests again.
  // Exception (owner 2026-10-03): moving ONTO the card, or across the gap between the square and the card, keeps it
  // up. Only moving to another square, or off the map, dismisses it. The shared card owns the actual closing.
  let tipTimer = null;
  const cancelTipTimer = () => { clearTimeout(tipTimer); tipTimer = null; };
  const cancelTip = () => { cancelTipTimer(); hideTip(); };
  viewport.addEventListener("pointermove", event => {
    cancelTipTimer();
    const tokenId = [...tokens].find(([, entry]) => entry.node === event.target?.closest?.(".tt-token"))?.[0];
    // The token is part of the hover bridge, but resting on it must still schedule its movement summary.
    if (!tokenId && hover.ownsPointer({x: event.clientX, y: event.clientY})) return;
    hideTip();
    if (drag?.moved || event.buttons) return;
    const cell = cellAt(event.clientX, event.clientY);
    const key = cell ? `${cell.x},${cell.y}` : "";
    const quick = Boolean((key && zoneAt.get(key)?.length) || (key && movement?.destinations?.[key]));
    if (!tokenId && !quick && !groundTooltip(cell) && !(key && ruleTerrainAt.get(key)?.length) && !heightCards.has(key)) return;
    const rest = {clientX: event.clientX, clientY: event.clientY, buttons: 0, tokenId};
    tipTimer = setTimeout(() => { tipTimer = null; showTip(rest); }, quick || tokenId ? ZONE_TIP_DELAY_MS : GROUND_TIP_DELAY_MS);
  });
  viewport.addEventListener("pointerleave", event => {
    cancelTipTimer();
    hover.releasePointer(event);
  });
  viewport.addEventListener("pointerdown", cancelTip);
  viewport.addEventListener("wheel", cancelTip, {passive: true});

  applyView();
  return {
    element: board, viewport, setMap, setTokens, setRoofView, closeHoverCard, setZones, setRulesOverlay, setMovementExplanation, animateMove, setHighlights, setFog, floatText, flashLine, setDraft,
    zoomBy, fit, centerOn, cellAt, drawWall, get view() { return {...view}; }, get map() { return map; },
    tokenNode: id => tokens.get(id)?.node,
  };
}
