// Tabletop map editor (owner 2026-09-25): grid size, background, walls drawn as rectangles,
// circles, straight and freeform lines (blocking sight and movement, or sight only),
// team start spots and terrain.  The server converts walls to rules squares on save; the
// preview uses the same conversion (vision.js rasterizeWalls, parity-tested).

import {api, enc} from "./api.js?v=sol124-r25x2";
import {paintAmbientCell, withTimeOfDay, indoorSelectValue} from "./ambient_edit.js";
import {installGlossary} from "./newcomer.js?v=sol192";
installGlossary();
import {createBoard, OBJECT_FACE, treeCells} from "./board.js?v=ruler2";
import {opacityGrid, rasterizeWalls, visibleCells, bambooStands, mapCenterlines} from "./vision.js?v=rel6-2";
import {STYLES} from "./textures.js";
import {GROUPS as FLOOR_ART_GROUPS} from "./floor-art-indoor.js?v=son202r1f1";
import {previewTerrainZones} from "./mapeditor-zones.js?v=ruler1";
import {editorLightPreview} from "./mapeditor-light.js?v=lightpreview1";
import {createObjectTokenPointerHandler} from "./object-delete.js?v=r24";
import {createMapHistory} from "./map-history.js?v=r24";
import {editorObjectStats, objectFacing} from "./object-presentation.js?v=rel6-2";
import {TERRAIN_LOOKS} from "./terrain-art.js?v=sol196r1";
import {TREE_LOOKS} from "./tree-art.js?v=sol196r1";
import {DECOR, DECOR_BIOMES} from "./decor-art.js?v=sol196r1";
import {placeDecor} from "./decor-place.js?v=sol196r1";
import {arrangeObjects, layoutTokenFields, nudgeFor, squareRoom} from "./object-arrange.js?v=sol201";
import {WALL_LOOKS} from "./wall-art.js?v=sol214";
import {OPENING_KINDS, snapOpening, nearestOpeningSpot, rotateObject, openingRotation, openingOffset} from './wall-openings.js?v=sol195';
import {detectRoofRegions, roofSettings, setBuildingWallHeight} from './roof-regions.js?v=rel6-2';
import {editRoofField, writeRoofOpening, removeRoofOpening, roofOpeningKey} from './roof-editor.js?v=rel6-2';
import {wallHeightFt, roofHeightFt, heightInput, authorSceneryHeights, sceneryHeightFt, sceneryHeightText} from './map-heights.js';

const $ = selector => document.querySelector(selector);
const DRAW_TOOLS = new Set(["rect", "circle", "line", "freeform"]);
const KEYS = {v: "pan", r: "rect", c: "circle", l: "line", d: "freeform", x: "erase", 1: "start1", 2: "start2", t: "terrain", m: "material", g: "tree", o: "object", k: "decor", y: "eye"};
// Bamboo patches are this named terrain (combat/rules/terrain.json: difficult, lightly obscured), painted by the Trees tool.
const BAMBOO = "terrain:bamboo thicket";
// Named terrain a map may be painted with (GET /api/tabletop/terrains; combat/rules/terrain.json).
let TERRAINS = [];
// What every ground kind is called and what it does, from the same endpoint, so hovering a square in
// the editor says exactly what the table will say (combat/ground_text.py; the fight's state payload).
let GROUND = {};
let OBJECT_DEFAULTS = {};

const editor = {
  doc: null, tool: "rect", draft: null, history: [], future: [], dirty: false, hotWall: null, eye: null, painting: null,
  moving: null,  // a start spot being dragged: {team, index, cell}
  openingPreview: null,  // where a door, gate or window would snap for the pointer's current spot: {kind, cell, ...mount}
};
const history = createMapHistory(editor, () => render());

const board = createBoard($("#meViewport"), {
  onPointerDown: (event, point) => pointerDown(event, point),
  onPointerMove: (event, point) => pointerMove(event, point),
  onPointerUp: (event, point) => pointerUp(event, point),
  // The opening preview follows the pointer; leave the map and it clears.
  onCellHover: cell => { if (!cell && editor.doc && editor.openingPreview) { editor.openingPreview = null; render(); } },
  onTokenClick: id => tokenClick(id),
  onTokenPointerDown: createObjectTokenPointerHandler({getTool: () => editor.tool === 'object' ? 'pan' : editor.tool, getDocument: () => editor.doc,
    change: mutator => change(mutator), onOtherToken: (id, event) => objectTokenDown(id, event) || startPointerDown(id, event)}),
});

function toast(message, error = false) {
  const node = document.createElement("div");
  node.className = `tt-toast${error ? " is-error" : ""}`;
  node.textContent = message;
  $("#ttToasts").appendChild(node);
  setTimeout(() => node.remove(), 4200);
}

function blankMap() {
  return {
    map_id: null, display_name: "New map", width_squares: 24, height_squares: 16,
    background: {asset: null, opacity: 1, fit: "cover", style: "flagstone", seed: 1 + Math.floor(Math.random() * 1e6)},
    display: {grid_opacity: 0.35, detail: 1, grid_color: "#d8c9a3", blend: 0.5},
    walls: [], terrain: [], materials: [], trees: [], objects: [], terrain_numbers: {save_dc: 13, pb: 2},
    starts: {team1: [[1, 6], [1, 8], [1, 10]], team2: [[22, 6], [22, 8], [22, 10]]},
  };
}

// ------------------------------------------------------------------ rendering
function cellsFromTerrain(type) {
  return (editor.doc.terrain || []).filter(row => row.type === type).flatMap(row => row.cells);
}

function render({fit = false} = {}) {
  const doc = editor.doc;
  const {width_squares: width, height_squares: height} = doc;
  const cells = rasterizeWalls(doc.walls, width, height, doc.objects);
  const selected = (doc.objects || []).find(o=>o.id===editor.selectedObject);
  $('#meObjectSelected').textContent = selected ? `Selected: ${OBJECT_KINDS[selected.kind] || 'Object'}` : 'Click a placed object to edit it.';
  $('#meObjectRotate').disabled = !selected;
  $('#meObjectRemove').disabled = !selected;
  $('#meObjectAddHere').disabled = !selected;
  $('#meObjectOpen').disabled = !selected || !OPENING_KINDS.has(selected.kind);
  $('#meObjectOpen').checked = selected ? selected.door_open === 1 || selected.blocks === false : false;
  // A tree's trunk blocks movement and sight like a wall square (the server does the same: combat/tabletop.py rasterize).
  const walled = new Set(cells.blocked.map(([x, y]) => `${x},${y}`));
  for (const cell of (doc.trees || []).filter(t => sceneryHeightFt(t, 'tree') > 0 && !t.base_altitude_ft).flatMap(treeCells)) if (!walled.has(cell.join(","))) { walled.add(cell.join(",")); cells.blocked.push(cell); }
  // A large bamboo stand blocks sight (combat/tabletop.py rasterize does the same).
  const hidden = new Set(cells.sight.map(([x, y]) => `${x},${y}`));
  const bambooGround = new Set((doc.materials || []).filter(row => row.material === BAMBOO
    && sceneryHeightFt(row, 'material') > 0 && !row.base_altitude_ft).flatMap(row => row.cells.map(c => c.join(','))));
  for (const [x, y, size] of bambooStands(doc.materials)) {
    for (let dy = 0; dy < size; dy += 1) for (let dx = 0; dx < size; dx += 1) {
      const key = `${x + dx},${y + dy}`;
      if (bambooGround.has(key) && !walled.has(key) && !hidden.has(key)) { hidden.add(key); cells.sight.push([x + dx, y + dy]); }
    }
  }
  editor.cells = cells;
  const centerlineCells = mapCenterlines(doc);
  // Mounted closed objects fill the opening with the same full-cell barrier
  // used by objects.blocking_zones at the table; an open leaf contributes none.
  for (const object of doc.objects || []) if (object.mount_axis && object.blocks !== false && object.door_open !== 1 && !object.z && sceneryHeightFt(object, 'object') > 0) {
    if (!cells.blocked.some(([x,y])=>x===object.x&&y===object.y)) cells.blocked.push([object.x,object.y]);
  }
  board.setMap({
    width, height, centerlineCells,
    background: doc.background?.asset ? {url: `/api/tabletop/map-assets/${doc.background.asset}`, opacity: doc.background.opacity ?? 1, fit: doc.background.fit}
      : {url: null, opacity: 1, style: doc.background?.style || "flagstone", seed: doc.background?.seed || 1},
    display: {gridOpacity: doc.display?.grid_opacity ?? 0.35, detail: doc.display?.detail ?? 1, gridColor: doc.display?.grid_color, blend: doc.display?.blend ?? 0},
    walls: doc.walls.map(wall => ({...wall})), openings: doc.objects || [],
    objects: doc.objects || [],
    roofs: doc.roofs,
    trees: doc.trees || [],
    decor: doc.decor || [],
    cells: {blocked: $("#meGhost").checked ? cells.blocked : [], sight: $("#meGhost").checked ? cells.sight : [],
            cover: cellsFromTerrain("SIMPLE_COVER"), hazard: cellsFromTerrain("QI_HAZARD"), difficult: cellsFromTerrain("DIFFICULT")},
    ruleTerrain: doc.terrain || [],
    materials: doc.materials || [],
    ground: GROUND,
    floors: (doc.materials || []).filter(row => row.material.startsWith("floor:")).map(row => ({style: row.material.slice(6), cells: row.cells})),
  });
  // Named terrain painted on the map, drawn exactly as the fight's own areas will be.
  board.setLight(doc.display?.run_ambient ? editorLightPreview(doc) : null, null, {preview: true});
  // The controls show the document they edit, not whatever the HTML or the previous map left in them.
  $("#meTimeOfDay").value = doc.ambient?.time_of_day ?? "day";
  $("#meIndoorLight").value = indoorSelectValue(doc.ambient?.indoor_level);
  $("#meRunAmbient").checked = doc.display?.run_ambient === true;
  board.setZones(previewTerrainZones(doc.materials, TERRAINS, doc.natural_haze === true));
  $("#meTerrainDC").value = doc.terrain_numbers?.save_dc ?? 13;
  $("#meTerrainPB").value = doc.terrain_numbers?.pb ?? 2;
  if (editor.hotWall != null) board.element.querySelectorAll(".tt-walls .tt-wall")[editor.hotWall]?.classList.add("is-hot");
  const starts = [];
  for (const [team, spots] of Object.entries(doc.starts || {})) {
    spots.forEach(([sx, sy], index) => {
      const moving = editor.moving?.team === team && editor.moving.index === index ? editor.moving.cell : null;
      const [x, y] = moving || [sx, sy];
      starts.push({id: `${team}:${index}`, x, y, label: team === "team1" ? "1" : "2", name: `${team === "team1" ? "Team 1" : "Team 2"} start ${index + 1}`,
      color: team === "team1" ? "#5fb8e8" : "#e8795f", hp: 1, maxHp: 1});
    });
  }
  // Objects sharing a square are laid out by object-arrange.js (seeded by the map and the square, so the table matches).
  const layouts = objectLayouts();
  for (const object of doc.objects || []) {
    const facing = objectFacing(object, editor.cells.blocked);
    const presetName = object.name || OBJECT_KINDS[object.kind] || object.kind;
    const stats = editorObjectStats(object, presetName, OBJECT_DEFAULTS);
    const rotation = object.mount_axis ? openingRotation(object) : object.rotation;
    let layout = layouts.get(object.id);
    if (layout && editor.nudging?.id === object.id && editor.nudging.point) {  // follows the pointer while dragged
      const {point} = editor.nudging;
      layout = {...layout, cx: Math.max(layout.radius, Math.min(1 - layout.radius, point.x - object.x)),
                cy: Math.max(layout.radius, Math.min(1 - layout.radius, point.y - object.y))};
    }
    starts.push({id: `object:${object.id}`, x: object.x, y: object.y, name: object.name || OBJECT_KINDS[object.kind] || object.kind,
      kind: object.kind, open: object.door_open === 1 || object.blocks === false, state: object.state,
      interaction: object.interaction, door_locked: object.door_locked, door_jammed: object.door_jammed,
      rotation, ...openingOffset(object), facing, label: OBJECT_FACE[object.kind] || "▣", object: true,
      ...stats, color: "#a08a5c", selected: object.id === editor.selectedObject && Boolean(layout?.shared),
      height_ft: sceneryHeightFt(object, 'object'), altitude_ft: (object.z || 0) * 5,
      ...layoutTokenFields(layout, {rotation, facing})});
  }
  board.setTokens(starts);
  drawOpeningPreview();
  if (editor.eye) {
    const opaque = opacityGrid(width, height, [cells.blocked, cells.sight], centerlineCells);
    // The editor previews what its own eye reaches; it has no viewer rays, so it
    // asks for the square mask explicitly rather than an empty polygon union.
    board.setFog(visibleCells(width, height, opaque, [editor.eye]), null, {squareFog: true});
  } else board.setFog(null);
  board.setRoofView({gm: !editor.eye, viewers: editor.eye ? [editor.eye] : []});
  renderRoofControls();
  renderSceneryHeightControls();
  $("#meName").value = doc.display_name;
  $("#meWidth").value = width;
  $("#meHeight").value = height;
  $("#meOpacity").value = doc.background?.opacity ?? 1;
  $("#meDetail").value = doc.display?.detail ?? 1;
  $("#meGrid").value = doc.display?.grid_opacity ?? 0.35;
  $("#meBlend").value = doc.display?.blend ?? 0;
  $("#meGridColor").value = doc.display?.grid_color || "#d8c9a3";
  $("#meFit2").value = doc.background?.fit || "cover";
  $("#meStyle").value = doc.background?.style || "flagstone";
  $("#meStyle").disabled = $("#meReseed").disabled = Boolean(doc.background?.asset);
  $("#meStyle").title = doc.background?.asset ? "Remove the uploaded image to use a built-in floor" : "A built-in painted floor, used when no image is uploaded";
  $("#meDirty").textContent = editor.dirty ? "● unsaved changes" : doc.map_id ? "saved" : "";
  $("#meDelete").disabled = !doc.map_id;
  $("#meUndo").disabled = !editor.history.length;
  $("#meRedo").disabled = !editor.future.length;
  renderStats();
  if (fit) requestAnimationFrame(() => board.fit());
}

function renderStats() {
  const doc = editor.doc;
  const stats = [
    ["Size", `${doc.width_squares} × ${doc.height_squares} squares (${doc.width_squares * 5} × ${doc.height_squares * 5} ft)`],
    ["Walls", doc.walls.length], ["Wall squares", editor.cells.blocked.length], ["Sight-only squares", editor.cells.sight.length],
    ["Team 1 starts", doc.starts.team1.length], ["Team 2 starts", doc.starts.team2.length],
    ["Objects", (doc.objects || []).length], ["Trees", (doc.trees || []).length], ["Bamboo squares", (doc.materials || []).filter(row => row.material === BAMBOO).reduce((n, row) => n + row.cells.length, 0)],
  ];
  $("#meStats").innerHTML = stats.map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`).join("");
  const list = $("#meWallList");
  list.replaceChildren();
  doc.walls.forEach((wall, index) => {
    const item = document.createElement("li");
    // Each wall's look can be changed here (wall-art.js); "Plain stone" is the look walls have always had.
    item.innerHTML = `<span></span><select class="me-wall-look" aria-label="Wall look">${wallLookOptions()}</select><label>Height <input class="me-input me-num me-wall-height" type="number" min="0" step="1" aria-label="Wall height in feet"> ft</label><button class="tt-tool" type="button">Delete</button>`;
    const height = item.querySelector('input');
    height.value = wallHeightFt(wall);
    height.addEventListener('change', event => {
      const value = heightInput(event.target.value);
      if (value === null) { toast('Wall height must be a whole number of feet, zero or more.', true); render(); return; }
      change(doc => { doc.walls[index].height_ft = value; });
    });
    item.querySelector("select").value = wall.look || "";
    item.querySelector("select").addEventListener("change", event => change(doc => {
      if (event.target.value) doc.walls[index].look = event.target.value; else delete doc.walls[index].look;
    }));
    item.firstChild.textContent = `${index + 1}. ${{rect: "Rectangle", circle: "Circle", line: wall.points.length > 2 ? "Freeform" : "Line"}[wall.shape]} · ${wall.blocks === "sight" ? "sight only" : "solid"}${wall.shape !== "line" ? (wall.filled ? " · filled" : " · outline") : ""}`;
    item.addEventListener("mouseenter", () => { if (editor.hotWall !== index) { editor.hotWall = index; render(); } });
    item.addEventListener("mouseleave", () => { editor.hotWall = null; render(); });
    item.lastChild.addEventListener("click", () => change(doc => doc.walls.splice(index, 1)));
    list.appendChild(item);
  });
}

// ------------------------------------------------------------------ edits and history
function change(mutator) {
  history.change(doc => { mutator(doc); authorSceneryHeights(doc); });
}

function renderSceneryHeightControls() {
  const list = $('#meSceneryHeightList');
  list.replaceChildren();
  for (const [key, family] of [['objects', 'object'], ['trees', 'tree'], ['terrain', 'terrain'], ['materials', 'material']])
    (editor.doc[key] || []).forEach((row, index) => {
      if (family === 'material' && row.material !== BAMBOO) return;
      const name = family === 'object' ? row.name || OBJECT_KINDS[row.kind] || row.kind.replaceAll('_', ' ')
        : family === 'tree' ? `Tree (${TREE_LOOKS[row.look || 'broadleaf'] || 'broadleaf'})`
        : family === 'material' ? 'Bamboo thicket' : row.look?.replaceAll('_', ' ') || row.type.replaceAll('_', ' ').toLowerCase();
      const cell = [row.x, row.y];
      const count = row.cells ? new Set(row.cells.map(([x, y]) => `${x},${y}`)).size : 1;
      const scope = row.cells ? `group · ${count} ${count === 1 ? 'square' : 'squares'} · edits all ${count} together`
        : `1 ${family === 'tree' ? 'tree' : 'object'} · square ${cell[0] + 1}, ${cell[1] + 1}`;
      const item = document.createElement('li');
      item.innerHTML = `<span></span><label>Height <input class="me-input me-num me-scenery-height" type="number" min="0" step="1" aria-label="${escapeHtml(name + ' · ' + scope)} height in feet"> ft</label>`;
      item.firstChild.textContent = `${sceneryHeightText(row, family, name)} · ${scope}`;
      const input = item.querySelector('input');
      input.value = sceneryHeightFt(row, family);
      input.dataset.family = family;
      input.dataset.index = index;
      input.addEventListener('change', event => {
        const value = heightInput(event.target.value);
        if (value === null) { toast('Height must be a whole number of feet, zero or more.', true); render(); return; }
        change(doc => { doc[key][index].height_ft = value; });
      });
      list.appendChild(item);
    });
}

function undo() {
  history.undo();
}

function redo() {
  history.redo();
}

function setTool(tool) {
  editor.tool = tool;
  if (editor.doc && editor.openingPreview) { editor.openingPreview = null; render(); }
  for (const button of document.querySelectorAll(".me-tool")) button.classList.toggle("is-active", button.dataset.tool === tool);
  const viewport = $("#meViewport");
  viewport.classList.toggle("tool-draw", DRAW_TOOLS.has(tool) || tool.startsWith("start") || tool === "terrain" || tool === "material" || tool === "tree" || tool === "object" || tool === "decor" || tool === "eye" || tool === "light" || tool === "ambient");
  viewport.classList.toggle("tool-erase", tool === "erase");
  if (tool !== "eye" && editor.eye) { editor.eye = null; render(); }
  $("#meHint").textContent = {
    pan: "Drag to pan, wheel to zoom.",
    rect: "Drag to draw a rectangle wall.", circle: "Drag from the centre outwards to draw a circle wall.",
    line: "Drag to draw a straight wall.", freeform: "Drag to draw a freeform wall.",
    erase: "Click a wall or object to delete it.", start1: "Click squares to add or remove Team 1 start spots; drag a spot to move it. Extra fighters start next to these spots.",
    start2: "Click squares to add or remove Team 2 start spots; drag a spot to move it. Extra fighters start next to these spots.", terrain: "Click or drag to paint terrain squares.",
    tree: "Click to plant or remove a tree; bamboo is painted by dragging.",
    object: "Click a square to place the chosen object (small things can share a square); a door, gate or window snaps to the straight wall edge or middle nearest your pointer, and the map shows where it will land. Click a placed object to select it, Shift+click to add beside it, drag a shared one to nudge it. Q/E rotates; X erases.",
    decor: "Click a square to place the chosen scenery; click placed scenery to remove it.",
    material: "Click or drag to paint the chosen floor or terrain (one of each per square).",
    eye: "Click a square to see what a fighter standing there can see.",
    light: "Click to place a light; drag an existing light to move it. The eraser removes lights.",
    ambient: "Paint bright, dim or dark ambient light onto squares.",
  }[tool];
}

function snap(point) {
  const step = Number($("#meSnap").value);
  if (!step) return [Math.round(point.x * 100) / 100, Math.round(point.y * 100) / 100];
  return [Math.round(point.x / step) * step, Math.round(point.y / step) * step];
}

function clampPoint([x, y]) {
  return [Math.min(Math.max(x, 0), editor.doc.width_squares), Math.min(Math.max(y, 0), editor.doc.height_squares)];
}

function drawDraft() {
  const draft = editor.draft;
  board.setDraft(draft ? (layer, {drawWall}) => {
    const node = drawWall(layer, {shape: draft.shape, points: draft.points, filled: draft.filled, blocks: draft.blocks});
    node.setAttribute("class", `tt-draft-shape ${draft.shape === "line" ? "is-line" : ""}`);
  } : null);
}

// ------------------------------------------------------------------ pointer tools
function cellOf(point) {
  const x = Math.floor(point.x), y = Math.floor(point.y);
  return x >= 0 && y >= 0 && x < editor.doc.width_squares && y < editor.doc.height_squares ? [x, y] : null;
}

function pointerDown(event, point) {
  if (event.button !== 0 || editor.tool === "pan") return false;
  const tool = editor.tool;
  if (DRAW_TOOLS.has(tool)) {
    const start = clampPoint(snap(point));
    editor.draft = {shape: tool === "freeform" ? "line" : tool, freeform: tool === "freeform", points: [start, start],
                    filled: tool === "line" || tool === "freeform" ? false : $("#meFill").value === "filled", blocks: $("#meBlocks").value,
                    ...($("#meWallLook").value ? {look: $("#meWallLook").value} : {})};
    board.viewport.setPointerCapture(event.pointerId);
    drawDraft();
    return true;
  }
  if (tool === "erase") {
    const index = wallAt(point);
    if (index != null) change(doc => doc.walls.splice(index, 1));
    else { const light = (editor.doc.lights || []).findIndex(row => row.x === Math.floor(point.x) && row.y === Math.floor(point.y)); if (light >= 0) change(doc => doc.lights.splice(light, 1)); }
    return true;
  }
  const cell = cellOf(point);
  if (!cell) return true;
  if (tool === "start1" || tool === "start2") {
    const team = tool === "start1" ? "team1" : "team2";
    const blocked = editor.cells.blocked.some(([x, y]) => x === cell[0] && y === cell[1]);
    if (blocked) { toast("That square is a wall; start spots must be open ground.", true); return true; }
    change(doc => {
      const spots = doc.starts[team];
      const at = spots.findIndex(([x, y]) => x === cell[0] && y === cell[1]);
      if (at >= 0) spots.splice(at, 1);
      else {
        const other = team === "team1" ? "team2" : "team1";
        doc.starts[other] = doc.starts[other].filter(([x, y]) => !(x === cell[0] && y === cell[1]));
        if (spots.length < 12) spots.push(cell);
      }
    });
    return true;
  }
  if (tool === "tree") return treeDown(event, cell);
  if (tool === "object") return objectDown(cell, point);
  if (tool === "decor") return decorDown(cell);
  if (tool === "terrain" || tool === "material") {
    editor.history.push(JSON.stringify(editor.doc));
    editor.future = [];
    editor.painting = new Set();
    paint(cell);
    board.viewport.setPointerCapture(event.pointerId);
    return true;
  }
  if (tool === "eye") {
    editor.eye = {x: cell[0], y: cell[1]};
    render();
    return true;
  }
  if (tool === "light") {
    const current = (editor.doc.lights || []).find(row => row.x === cell[0] && row.y === cell[1]);
    if (current) { editor.dragLight = current.id; editor.dragLightFrom = [cell[0], cell[1]]; editor.dragLightTo = [cell[0], cell[1]]; board.viewport.setPointerCapture(event.pointerId); }
    else {
      const bright = Number($("#meLightBright").value), dim = Number($("#meLightDim").value);
      if (!Number.isInteger(bright) || !Number.isInteger(dim) || bright > dim) { toast("Bright radius must be no greater than the dim radius.", true); return true; }
      change(doc => { doc.lights = [...(doc.lights || []), {id: `light-${Date.now()}`, x: cell[0], y: cell[1], name: $("#meLightName").value || "Light", bright_ft: bright, dim_ft: dim, color: $("#meLightColor").value, magical: $("#meLightMagical").checked, lit: $("#meLightOn").checked}]; });
    }
    return true;
  }
  if (tool === "ambient") {
    change(doc => { doc.ambient_regions = paintAmbientCell(doc.ambient_regions, cell, Number($("#meAmbientLevel").value)); });
    return true;
  }
  return false;
}

function pointerMove(event, point) {
  if (editor.dragLight) { const cell = cellOf(point); if (cell) { editor.dragLightTo = cell; render(); } return true; }
  if (editor.nudging) { nudgeMove(event, point); return true; }
  if (editor.moving) {
    const cell = cellOf(point);
    if (cell && cell.join(",") !== editor.moving.cell.join(",")) { editor.moving.cell = cell; editor.moving.moved = true; render(); }
    return true;
  }
  if (editor.draft) {
    const next = clampPoint(editor.draft.freeform ? [Math.round(point.x * 100) / 100, Math.round(point.y * 100) / 100] : snap(point));
    const points = editor.draft.points;
    if (editor.draft.freeform) {
      const last = points[points.length - 1];
      if (Math.hypot(next[0] - last[0], next[1] - last[1]) >= 0.3 && points.length < 300) points.push(next);
    } else points[1] = next;
    drawDraft();
    return true;
  }
  if (editor.painting) {
    const cell = cellOf(point);
    if (cell) paint(cell);
    return true;
  }
  if (editor.tool === "erase") {
    const index = wallAt(point);
    if (index !== editor.hotWall) { editor.hotWall = index; render(); }
    return false;
  }
  if (editor.tool === "object") previewOpening(point);
  return false;
}

function pointerUp(_event, _point) {
  if (editor.dragLight) { const id = editor.dragLight, from = editor.dragLightFrom, to = editor.dragLightTo; editor.dragLight = editor.dragLightFrom = editor.dragLightTo = null; if (from && to && (from[0] !== to[0] || from[1] !== to[1])) change(doc => { const row = doc.lights.find(item => item.id === id); row.x = to[0]; row.y = to[1]; }); else render(); return true; }
  if (editor.nudging) { nudgeUp(); return true; }
  if (editor.moving) {
    const {team, index, cell, moved, from} = editor.moving;
    editor.moving = null;
    if (!moved || cell.join(",") === from.join(",")) {
      // A click, not a drag: the start tools remove the spot, as before.
      if (editor.tool === "start1" || editor.tool === "start2") change(doc => doc.starts[team].splice(index, 1));
      else render();
      return true;
    }
    if (editor.cells.blocked.some(([x, y]) => x === cell[0] && y === cell[1])) {
      toast("That square is a wall or a tree trunk; start spots must be open ground.", true);
      render();
      return true;
    }
    change(doc => {
      // Dropped on another start spot: the two swap places.
      for (const other of ["team1", "team2"]) {
        const at = doc.starts[other].findIndex(([x, y]) => x === cell[0] && y === cell[1]);
        if (at >= 0) doc.starts[other][at] = [...from];
      }
      doc.starts[team][index] = [...cell];
    });
    return true;
  }
  if (editor.draft) {
    const draft = editor.draft;
    editor.draft = null;
    drawDraft();
    let points = draft.points;
    if (draft.freeform) points = simplify(points);
    const [[x0, y0], [x1, y1]] = [points[0], points[points.length - 1]];
    const size = draft.shape === "rect" ? Math.min(Math.abs(x1 - x0), Math.abs(y1 - y0)) : Math.hypot(x1 - x0, y1 - y0);
    if ((draft.shape === "line" && points.length < 2) || (!draft.freeform && size < 0.25) || (draft.freeform && points.length < 2)) return true;
    const wall = {shape: draft.shape, points, filled: draft.filled, blocks: draft.blocks, ...(draft.look ? {look: draft.look} : {})};
    wall.height_ft = heightInput($('#meWallHeight').value) ?? wallHeightFt(wall);
    change(doc => doc.walls.push(wall));
    return true;
  }
  if (editor.painting) {
    editor.painting = null;
    editor.dirty = true;
    render();
    return true;
  }
  return false;
}

function simplify(points) {
  // Drop points that barely bend the line (keeps freeform walls light).
  if (points.length <= 2) return points;
  const out = [points[0]];
  for (let index = 1; index < points.length - 1; index += 1) {
    const [ax, ay] = out[out.length - 1], [bx, by] = points[index], [cx, cy] = points[index + 1];
    const cross = Math.abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax));
    if (cross > 0.08) out.push(points[index]);
  }
  out.push(points[points.length - 1]);
  return out;
}

// One floor and one named terrain per square: painting a square takes it from whatever of the same kind held it.
function paintMaterial(cell, choice = $("#meMaterial").value) {
  const family = choice.startsWith("erase:") ? choice.slice(6) : choice.split(":")[0];
  const materials = editor.doc.materials || (editor.doc.materials = []);
  for (const row of materials) {
    if (row.material.startsWith(`${family}:`)) row.cells = row.cells.filter(([x, y]) => !(x === cell[0] && y === cell[1]));
  }
  if (!choice.startsWith("erase:")) {
    let row = materials.find(entry => entry.material === choice);
    if (!row) { row = {material: choice, cells: []}; materials.push(row); }
    row.cells.push(cell);
  }
  editor.doc.materials = materials.filter(row => row.cells.length);
  render();
}

function paint(cell) {
  const key = cell.join(",");
  if (editor.painting.has(key)) return;
  editor.painting.add(key);
  if (editor.tool === "material") return paintMaterial(cell);
  if (editor.tool === "tree") return paintBamboo(cell);
  const type = $("#meTerrainType").value;
  const terrain = editor.doc.terrain || (editor.doc.terrain = []);
  for (const row of terrain) row.cells = row.cells.filter(([x, y]) => !(x === cell[0] && y === cell[1]));
  if (type !== "ERASE") {
    const look = $("#meTerrainLook").value || undefined;
    let row = terrain.find(entry => entry.type === type && (entry.look || "") === (look || ""));
    if (!row) { row = {type, ...(look ? {look} : {}), cells: []}; terrain.push(row); }
    row.cells.push(cell);
  }
  editor.doc.terrain = terrain.filter(row => row.cells.length);
  render();
}

function distanceToSegment(px, py, [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay;
  const t = dx || dy ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy))) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function wallAt(point) {
  const walls = editor.doc.walls;
  for (let index = walls.length - 1; index >= 0; index -= 1) {
    const wall = walls[index];
    const [[x0, y0], [x1, y1]] = wall.points;
    if (wall.shape === "rect") {
      const inside = point.x >= Math.min(x0, x1) && point.x <= Math.max(x0, x1) && point.y >= Math.min(y0, y1) && point.y <= Math.max(y0, y1);
      const corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
      const nearEdge = corners.slice(1).some((corner, i) => distanceToSegment(point.x, point.y, corners[i], corner) < 0.3);
      if ((wall.filled && inside) || nearEdge) return index;
    } else if (wall.shape === "circle") {
      const radius = Math.hypot(x1 - x0, y1 - y0), distance = Math.hypot(point.x - x0, point.y - y0);
      if ((wall.filled && distance <= radius) || Math.abs(distance - radius) < 0.3) return index;
    } else if (wall.points.slice(1).some((p, i) => distanceToSegment(point.x, point.y, wall.points[i], p) < 0.3)) return index;
  }
  return null;
}

// With the Objects tool or Pan: Shift+click on an object adds the picked object beside it in its square; dragging an
// object that shares its square nudges it within the square (saved as `nudge`, hundredths of a square).
function objectTokenDown(id, event) {
  if (!String(id).startsWith("object:") || event.button !== 0 || !["object", "pan"].includes(editor.tool)) return false;
  const object = (editor.doc.objects || []).find(row => row.id === Number(String(id).slice(7)));
  if (!object) return false;
  if (event.shiftKey && editor.tool === "object") { objectDown([object.x, object.y], board.cellAt(event.clientX, event.clientY, {continuous: true})); return true; }
  editor.selectedObject = object.id;
  if (!objectLayouts().get(object.id)?.shared) { render(); return true; }
  const layout = objectLayouts().get(object.id), at = board.cellAt(event.clientX, event.clientY, {continuous: true});
  // Where on the object it was grabbed, so it does not jump to put its centre under the pointer.
  editor.nudging = {id: object.id, startX: event.clientX, startY: event.clientY, point: null,
                    grab: {x: at.x - object.x - layout.cx, y: at.y - object.y - layout.cy}};
  board.viewport.setPointerCapture?.(event.pointerId);
  render();
  return true;
}

function nudgeMove(event, point) {
  const drag = editor.nudging;
  if (!drag.point && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 4) return;
  drag.point = {x: point.x - drag.grab.x, y: point.y - drag.grab.y};
  render();
}

function nudgeUp() {
  const drag = editor.nudging;
  editor.nudging = null;
  const object = (editor.doc.objects || []).find(row => row.id === drag.id);
  if (!drag.point || !object) { render(); return; }
  const layout = objectLayouts().get(object.id);
  const wanted = nudgeFor(drag.point, [object.x, object.y], layout, object.nudge);
  // Store only as far as it can go without touching a neighbour (object-arrange.js stops it there too).
  const seed = String(editor.doc.background?.seed ?? editor.doc.map_id ?? "");
  const place = nudge => arrangeObjects(editor.doc.objects.map(row => row.id === object.id ? {...row, nudge} : row), seed, OBJECT_DEFAULTS).get(object.id);
  const free = place(undefined), landed = place(wanted);
  const nudge = [Math.round((landed.cx - free.cx) * 100) || 0, Math.round((landed.cy - free.cy) * 100) || 0];
  change(doc => {
    const row = doc.objects.find(entry => entry.id === drag.id);
    if (nudge[0] || nudge[1]) row.nudge = nudge; else delete row.nudge;
  });
}

function tokenClick(_id) {
  if (String(_id).startsWith('object:') && editor.tool !== 'erase') {
    editor.selectedObject = Number(String(_id).slice(7)); render();
  }
  // Handled on pointer up (startPointerDown captures the pointer): a click removes the spot, a drag moves it.
}

// Start spots are picked up and moved (owner 2026-09-28: "pick up and move the starting spawn points rather than delete
// and replace"), in the start tools and with Pan.
function startPointerDown(id, event) {
  if (event.button !== 0 || !["pan", "start1", "start2"].includes(editor.tool)) return;
  const [team, index] = id.split(":");
  const from = editor.doc.starts[team]?.[Number(index)];
  if (!from) return;
  editor.moving = {team, index: Number(index), from: [...from], cell: [...from], moved: false};
  board.viewport.setPointerCapture(event.pointerId);
}

// ------------------------------------------------------------------ trees (owner 2026-09-28: "trees as an option both
// bamboo patches and larger trees").  A tree or great tree is a trunk (1 or 2x2 squares that block movement and sight)
// under a canopy that is only the look; a bamboo patch is painted "bamboo thicket" terrain (difficult, lightly obscured).
function treeAt(cell) {
  return (editor.doc.trees || []).findIndex(tree => treeCells(tree).some(([x, y]) => x === cell[0] && y === cell[1]));
}

function treeDown(event, cell) {
  const kind = $("#meTreeKind").value;
  if (kind === "bamboo" || kind === "clear") {
    editor.history.push(JSON.stringify(editor.doc));
    editor.future = [];
    editor.painting = new Set();
    paint(cell);
    board.viewport.setPointerCapture(event.pointerId);
    return true;
  }
  const at = treeAt(cell);
  if (at >= 0) { change(doc => doc.trees.splice(at, 1)); return true; }
  const tree = {x: cell[0], y: cell[1], size: kind === "great" ? 2 : 1, seed: 1 + Math.floor(Math.random() * 1e6)};
  // The kind of tree is only its look (tree-art.js); a broadleaf is saved without one, as trees always were.
  const look = $("#meTreeLook").value;
  if (look && look !== "broadleaf") tree.look = look;
  const squares = treeCells(tree);
  const {width_squares: width, height_squares: height} = editor.doc;
  if (squares.some(([x, y]) => x >= width || y >= height)) { toast("A great tree needs two by two squares inside the map.", true); return true; }
  const walls = new Set(rasterizeWalls(editor.doc.walls, width, height).blocked.map(([x, y]) => `${x},${y}`));
  const spots = new Set([...editor.doc.starts.team1, ...editor.doc.starts.team2].map(([x, y]) => `${x},${y}`));
  if (squares.some(square => walls.has(square.join(",")) || treeAt(square) >= 0)) { toast("A trunk needs open ground (no wall or other trunk).", true); return true; }
  if (squares.some(square => spots.has(square.join(",")))) { toast("A start spot is there; move it first.", true); return true; }
  change(doc => { doc.trees = [...(doc.trees || []), tree]; });
  return true;
}

// ------------------------------------------------------------------ objects (owner 2026-09-29, task O: destructible objects and
// structures "placeable on the map"): a door, gate, pillar, crate ... on one square.  Its armor class and hit points come from the
// 2024 object tables by material and size (combat/object_rules.py); the boxes below override them for this one object.
// Names, descriptions and picker groups all come from OBJECT_DEFAULTS (combat/object_rules.editor_defaults), never a
// second hand-kept list here -- 59+ kinds is too many to keep two copies of in sync (owner 2026-10-08 catalog).
let OBJECT_KINDS = {};
const OBJECT_GROUP_ORDER = ["structure", "container", "decor", "temple", "village", "fortress", "workshop", "nature", "water", "interior"];

function rebuildObjectPicker(query = "") {
  const presets = OBJECT_DEFAULTS.presets || {};
  const groups = OBJECT_DEFAULTS.groups || {};
  OBJECT_KINDS = Object.fromEntries(Object.entries(presets).map(([kind, row]) => [kind, row.name || kind]));
  const byGroup = {};
  for (const [kind, row] of Object.entries(presets)) (byGroup[row.group || "decor"] ||= []).push([kind, row]);
  const order = [...OBJECT_GROUP_ORDER.filter(group => byGroup[group]), ...Object.keys(byGroup).filter(group => !OBJECT_GROUP_ORDER.includes(group))];
  const select = $("#meObjectKind");
  const previous = select.value;
  const q = query.trim().toLowerCase();
  let html = "";
  for (const group of order) {
    const rows = byGroup[group].filter(([, row]) => !q || row.name.toLowerCase().includes(q));
    if (!rows.length) continue;
    html += `<optgroup label="${escapeHtml(groups[group] || group)}">${rows.map(([kind, row]) => `<option value="${kind}">${escapeHtml(row.name)}</option>`).join("")}</optgroup>`;
  }
  select.innerHTML = html || `<option value="" disabled selected>No matches</option>`;
  if ([...select.options].some(option => option.value === previous)) select.value = previous;
  updateObjectDesc();
}

function updateObjectDesc() {
  const row = (OBJECT_DEFAULTS.presets || {})[$("#meObjectKind").value];
  const threshold = row?.threshold;
  // Blank in the Damage threshold box does not mean "none" for every preset: some (bronze, worked stone,
  // packed fill) carry their own default (combat/object_rules.py presets), which a typed number overrides.
  $("#meObjectThreshold").placeholder = threshold ? String(threshold) : "none";
  const thresholdNote = threshold
    ? ` Leave the threshold box blank to keep this object's own damage threshold of ${threshold}: a hit dealing less than ${threshold} damage does nothing to it.`
    : "";
  $("#meObjectDesc").textContent = (row?.description || "") + thresholdNote;
}
$("#meObjectSearch").addEventListener("input", event => rebuildObjectPicker(event.target.value));
$("#meObjectKind").addEventListener("change", updateObjectDesc);

function objectsAt(cell) {
  return (editor.doc.objects || []).filter(object => object.x === cell[0] && object.y === cell[1]);
}

function objectLayouts() {
  // Seeded by the map's own look seed (saved with it from the start, so saving does not reshuffle) and the square.
  return arrangeObjects(editor.doc.objects || [], String(editor.doc.background?.seed ?? editor.doc.map_id ?? ""), OBJECT_DEFAULTS);
}

// Clicking a square with the Objects tool places the picked object there, beside any already in it when they all fit
// in the 5-foot square (object-arrange.js squareRoom); clicking an object selects it, Shift+click adds beside it.
// A door, gate or window is placed on a straight wall: it snaps to the wall line nearest the pointer inside the
// square (an edge or the middle), and says so in plain words when no wall runs through that square.
const OPENING_WORD = {door: "door", gate: "gate", window: "window"};
const OPENING_SPOT = {top: "top edge", bottom: "bottom edge", left: "left edge", right: "right edge"};

function openingMount(cell, point) {
  return snapOpening(cell, point, editor.doc.walls, {width: editor.doc.width_squares, height: editor.doc.height_squares});
}

function noWallMessage(kind, cell, point) {
  const spot = nearestOpeningSpot(cell, point);
  const place = spot === "middle" ? "through the middle of that square" : `along the ${OPENING_SPOT[spot]} of that square`;
  return `A ${OPENING_WORD[kind] || "door"} must sit on a straight wall. There is no wall ${place}; draw a straight wall there first, then place it.`;
}

function objectDown(cell, point = null) {
  const kind = $("#meObjectKind").value;
  // An unmatched search leaves the picker on its disabled "No matches" option (value ""); placing that
  // would save a blank kind, which the server quietly turns into an unrelated "custom" object (tabletop.py _objects).
  if (!kind || !(kind in OBJECT_KINDS)) { toast("Pick an object from the list first; the search has no match selected.", true); return true; }
  const {width_squares: width, height_squares: height} = editor.doc;
  if (cell[0] < 0 || cell[1] < 0 || cell[0] >= width || cell[1] >= height) return true;
  const at = point || {x: cell[0] + .5, y: cell[1] + .5};  // Shift+click and "Add beside" know only the square
  const placement = {kind, x: cell[0], y: cell[1]};
  let mount = null;
  if (OPENING_KINDS.has(kind)) {
    mount = openingMount(cell, at);
    if (!mount) { toast(noWallMessage(kind, cell, at), true); return true; }
    placement.x = mount.x; placement.y = mount.y;
    placement.mount_axis = mount.mount_axis; placement.mount_line = mount.mount_line;
  }
  if (treeAt([placement.x, placement.y]) >= 0 || (!mount && editor.cells.blocked.some(([x,y])=>x===cell[0]&&y===cell[1]))) {
    toast('Objects need open ground. A door, gate or window can be placed on a straight wall.', true); return true;
  }
  const room = squareRoom(objectsAt([placement.x, placement.y]), placement, OBJECT_DEFAULTS, OBJECT_KINDS);
  if (!room.ok) { toast(room.reason, true); return true; }
  const spots = new Set([...editor.doc.starts.team1, ...editor.doc.starts.team2].map(([x, y]) => `${x},${y}`));
  if (spots.has([placement.x, placement.y].join(","))) { toast("A start spot is there; move it first.", true); return true; }
  const object = {id: Math.max(0, ...(editor.doc.objects || []).map(row => row.id || 0)) + 1, ...placement};
  if (object.kind === 'door') Object.assign(object, {interaction:'simple_door', door_open:0, door_locked:0, door_jammed:0});
  if (mount) object.blocks = true;
  for (const [key, field] of [["hp", "#meObjectHp"], ["ac", "#meObjectAc"], ["threshold", "#meObjectThreshold"]]) {
    const value = Math.floor(Number($(field).value));
    if (value > 0) object[key] = value;
  }
  editor.selectedObject = object.id;
  editor.openingPreview = null;
  change(doc => { doc.objects = [...(doc.objects || []), object]; });
  return true;
}

// The pointer's live preview of where an opening will snap: the wall line under the pointer, drawn on the map
// while the Objects tool and an opening kind are chosen (mapeditor.css .tt-opening-preview).
function previewOpening(point) {
  const kind = $("#meObjectKind").value;
  const cell = point ? cellOf(point) : null;
  const mount = cell && OPENING_KINDS.has(kind) ? openingMount(cell, point) : null;
  const next = mount ? {kind, cell, ...mount} : null;
  if (JSON.stringify(next) === JSON.stringify(editor.openingPreview)) return;
  editor.openingPreview = next;
  render();
}

function drawOpeningPreview() {
  if (editor.draft) return;  // a wall being drawn owns the draft layer
  const preview = editor.openingPreview;
  board.setDraft(preview ? (layer, {svg, drawWall}) => {
    const at = preview.mount_line / 100;
    const points = preview.mount_axis === 'h' ? [[preview.cell[0], at], [preview.cell[0] + 1, at]]
                                              : [[at, preview.cell[1]], [at, preview.cell[1] + 1]];
    drawWall(layer, {shape: 'line', points, blocks: 'sight_and_movement'}, 'tt-opening-preview');
  } : null);
}

// ------------------------------------------------------------------ decor (owner 2026-10-08 biome packs, decor-art.js). A
// look-only piece goes in the map's `decor` list, which no rule reads. A piece marked (cover) or (difficult) is an ordinary
// cover or difficult terrain square whose look is that piece, so it plays exactly like the Terrain tool's squares.
function decorDown(cell) {
  const {width_squares: width, height_squares: height} = editor.doc;
  if (cell[0] < 0 || cell[1] < 0 || cell[0] >= width || cell[1] >= height) return true;
  const kind = $("#meDecorKind").value, turn = Number($("#meDecorTurn").value), seed = 1 + Math.floor(Math.random() * 1e6);
  change(doc => { placeDecor(doc, cell, kind, turn, seed); });
  return true;
}

function paintBamboo(cell) {
  if ($("#meTreeKind").value === "bamboo") return paintMaterial(cell, BAMBOO);
  const at = treeAt(cell);  // "Remove trees and bamboo": a trunk under the brush, and bamboo on the square
  if (at >= 0) editor.doc.trees.splice(at, 1);
  for (const row of editor.doc.materials || []) {
    if (row.material === BAMBOO) row.cells = row.cells.filter(([x, y]) => !(x === cell[0] && y === cell[1]));
  }
  editor.doc.materials = (editor.doc.materials || []).filter(entry => entry.cells.length);
  render();
}

// ------------------------------------------------------------------ files: open, save, delete, background
async function loadList(selected) {
  const select = $("#meMaps");
  const {maps, builtin, object_defaults} = await api("/api/tabletop/maps");
  OBJECT_DEFAULTS = object_defaults || {};
  rebuildObjectPicker($("#meObjectSearch").value);
  select.innerHTML = `<option value="new">— New map —</option>`
    + (maps.length ? `<optgroup label="Your maps">${maps.map(row => `<option value="map:${row.map_id}">${escapeHtml(row.display_name)} (${row.width_squares}×${row.height_squares})</option>`).join("")}</optgroup>` : "")
    + `<optgroup label="Start from a built-in arena">${builtin.map(row => `<option value="builtin:${escapeHtml(row.arena_id)}">Copy of ${escapeHtml(row.display_name)}</option>`).join("")}</optgroup>`;
  select.value = selected || "new";
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
}

async function open(value) {
  if (editor.dirty && !confirm("Discard unsaved changes to this map?")) { $("#meMaps").value = editor.doc.map_id ? `map:${editor.doc.map_id}` : "new"; return; }
  try {
    if (value === "new") editor.doc = blankMap();
    else if (value.startsWith("map:")) editor.doc = await api(`/api/tabletop/maps/${enc(value.slice(4))}`);
    else {
      const doc = await api(`/api/tabletop/builtin-maps/${value.slice(8)}`);
      editor.doc = {...doc, map_id: null, display_name: `Copy of ${doc.display_name}`};
    }
    delete editor.doc.cells;
    editor.doc.terrain ||= [];
    editor.doc.materials ||= [];
    editor.doc.terrain_numbers ||= {save_dc: 13, pb: 2};
    authorSceneryHeights(editor.doc);
    editor.history = []; editor.future = []; editor.dirty = value !== "new" && !value.startsWith("map:"); editor.eye = null;
    render({fit: true});
    window.history.replaceState(null, "", editor.doc.map_id ? `/tabletop/maps?map=${enc(editor.doc.map_id)}` : "/tabletop/maps");
  } catch (error) { toast(error.message, true); }
}

async function save() {
  const doc = {...editor.doc};
  delete doc.cells;
  try {
    const saved = await api("/api/tabletop/maps", {body: {map: doc}});
    delete saved.cells;
    editor.doc = saved;
    editor.dirty = false;
    await loadList(`map:${saved.map_id}`);
    render();
    window.history.replaceState(null, "", `/tabletop/maps?map=${enc(saved.map_id)}`);
    toast(`Saved “${saved.display_name}”. Pick it under Map when you create a fight on the table.`);
  } catch (error) { toast(error.message, true); }
}

async function remove() {
  if (!editor.doc.map_id || !confirm(`Delete the map “${editor.doc.display_name}”? Fights already played on it keep their copy.`)) return;
  try {
    await api(`/api/tabletop/maps/${enc(editor.doc.map_id)}`, {method: "DELETE"});
    editor.dirty = false;
    await loadList("new");
    await open("new");
    toast("Map deleted.");
  } catch (error) { toast(error.message, true); }
}

async function upload(file) {
  if (!file) return;
  if (file.size > 12 * 1024 * 1024) { toast("Images must be under 12 MB.", true); return; }
  try {
    const result = await api("/api/tabletop/map-assets", {raw: file, contentType: file.type});
    change(doc => { doc.background = {...(doc.background || {}), asset: result.asset}; });
    toast("Background uploaded.");
  } catch (error) { toast(error.message, true); }
}

// ------------------------------------------------------------------ controls
for (const button of document.querySelectorAll(".me-tool")) button.addEventListener("click", () => setTool(button.dataset.tool));
$("#meMaps").addEventListener("change", event => open(event.target.value));
$("#meSave").addEventListener("click", save);
$("#meDelete").addEventListener("click", remove);
$("#meUndo").addEventListener("click", undo);
$("#meRedo").addEventListener("click", redo);
$("#meFit").addEventListener("click", () => board.fit());
$("#meFullscreen").addEventListener("click", () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.());
$("#meGhost").addEventListener("change", () => render());
$("#meTimeOfDay").addEventListener("change", event => change(doc => { doc.ambient = withTimeOfDay(doc.ambient, event.target.value); }));
$("#meIndoorLight").addEventListener("change", event => change(doc => { doc.ambient = {...(doc.ambient || {}), ...(event.target.value ? {indoor_level: event.target.value} : {indoor_level: null})}; }));
$("#meRunAmbient").addEventListener("change", event => change(doc => { doc.display = {...(doc.display || {}), run_ambient: event.target.checked}; }));
$("#meUpload").addEventListener("change", event => upload(event.target.files[0]));
$("#meClearBg").addEventListener("click", () => change(doc => { doc.background = {...(doc.background || {}), asset: null}; }));
$("#meName").addEventListener("change", event => change(doc => { doc.display_name = event.target.value.trim() || "Untitled map"; }));
for (const [id, key, min, max] of [["#meWidth", "width_squares", 6, 80], ["#meHeight", "height_squares", 6, 60]]) {
  $(id).addEventListener("change", event => {
    const value = Math.max(min, Math.min(max, Math.round(Number(event.target.value) || min)));
    change(doc => {
      doc[key] = value;
      for (const team of ["team1", "team2"]) doc.starts[team] = doc.starts[team].filter(([x, y]) => x < doc.width_squares && y < doc.height_squares);
      doc.terrain = (doc.terrain || []).map(row => ({...row, cells: row.cells.filter(([x, y]) => x < doc.width_squares && y < doc.height_squares)})).filter(row => row.cells.length);
      doc.materials = (doc.materials || []).map(row => ({...row, cells: row.cells.filter(([x, y]) => x < doc.width_squares && y < doc.height_squares)})).filter(row => row.cells.length);
      doc.trees = (doc.trees || []).filter(tree => treeCells(tree).every(([x, y]) => x < doc.width_squares && y < doc.height_squares));
      if (doc.decor) doc.decor = doc.decor.filter(row => row.x < doc.width_squares && row.y < doc.height_squares);
    });
    board.fit();
  });
}
const slider = (id, apply) => $(id).addEventListener("change", event => change(doc => apply(doc, Number(event.target.value))));
slider("#meOpacity", (doc, value) => { doc.background = {...(doc.background || {}), opacity: value}; });
slider("#meDetail", (doc, value) => { doc.display = {...(doc.display || {}), detail: value}; });
slider("#meGrid", (doc, value) => { doc.display = {...(doc.display || {}), grid_opacity: value}; });
// Blend edges (owner 2026-09-28: "a way to blend the different terrains together"): painted floors feather into each other.
slider("#meBlend", (doc, value) => { doc.display = {...(doc.display || {}), blend: value}; });

// A building is selected by an interior square; settings persist in map data,
// while detection remains automatic for all maps that have no overrides.
function renderRoofControls() {
  const picker = $('#meRoofBuilding'), selected = picker.value;
  const regions = detectRoofRegions(board.map);
  picker.innerHTML = '<option value="all">All buildings</option>' + regions.map((r,i) =>
    `<option value="${r.id}">Building ${i+1} (square ${r.x+1}, ${r.y+1})</option>`).join('');
  picker.value = regions.some(r=>r.id===selected) ? selected : 'all';
  const region = regions.find(r=>r.id===picker.value);
  const settings = region ? roofSettings(region, editor.doc.roofs) : editor.doc.roofs || {};
  $('#meRoofEnabled').checked = settings.enabled !== false;
  $('#meRoofStyle').value = settings.style === 'red' ? 'red' : 'grey';
  $('#meRoofClimbCheck').value = ['slippery', 'few_handholds'].includes(settings.climb_check) ? settings.climb_check : 'none';
  $('#meBuildingHeight').value = region?.wall_height_ft ?? 10;
  $('#meRoofHeight').value = settings.height_ft ?? roofHeightFt(settings);
  const openingPicker = $('#meRoofOpening'), selectedOpening = openingPicker.value;
  const openings = (editor.doc.roofs?.openings || []).filter(row => !region || region.inside.has(roofOpeningKey(row)));
  openingPicker.innerHTML = '<option value="new">Add an opening</option>' + openings.map(row =>
    `<option value="${roofOpeningKey(row)}">${row.kind === 'skylight' ? 'Skylight' : 'Trapdoor'} (${row.x + 1}, ${row.y + 1}) · ${row.open ? 'open' : 'closed'}</option>`).join('');
  openingPicker.value = openings.some(row => roofOpeningKey(row) === selectedOpening) ? selectedOpening : 'new';
  renderRoofOpeningControls();
}
$('#meRoofBuilding').addEventListener('change', renderRoofControls);
function editRoofSetting(field, value) {
  const region = detectRoofRegions(board.map).find(r=>r.id===$('#meRoofBuilding').value);
  change(doc => {
    doc.roofs = {...(doc.roofs || {enabled: true, style: 'grey'})};
    if (!region) { doc.roofs[field] = value; return; }
    const rows = doc.roofs.regions = [...(doc.roofs.regions || [])];
    let row = rows.find(r=>region.inside.has(`${r.x},${r.y}`));
    // Store only edited fields: inherited/global settings are not local choices.
    if (!row) { row = {x: region.x, y: region.y}; rows.push(row); }
    row[field] = value;
  });
}
$('#meRoofEnabled').addEventListener('change', event => editRoofSetting('enabled', event.target.checked));
$('#meRoofStyle').addEventListener('change', event => editRoofSetting('style', event.target.value));
$('#meRoofClimbCheck').addEventListener('change', event => editRoofSetting('climb_check', event.target.value));
$('#meRoofHeight').addEventListener('change', event => {
  const value = heightInput(event.target.value);
  if (value === null) { toast('Roof height must be a whole number of feet, zero or more.', true); renderRoofControls(); return; }
  editRoofSetting('height_ft', value);
});
$('#meBuildingHeight').addEventListener('change', event => {
  const value = heightInput(event.target.value);
  if (value === null) { toast('Building height must be a whole number of feet, zero or more.', true); renderRoofControls(); return; }
  const regions = detectRoofRegions(board.map).filter(r => $('#meRoofBuilding').value === 'all' || r.id === $('#meRoofBuilding').value);
  change(doc => setBuildingWallHeight(doc, regions, value));
});

function renderRoofOpeningControls() {
  const key = $('#meRoofOpening').value;
  const row = (editor.doc.roofs?.openings || []).find(opening => roofOpeningKey(opening) === key);
  const region = detectRoofRegions(board.map).find(r => r.id === $('#meRoofBuilding').value);
  $('#meRoofOpeningX').max = editor.doc.width_squares;
  $('#meRoofOpeningY').max = editor.doc.height_squares;
  $('#meRoofOpeningX').value = (row?.x ?? region?.x ?? 0) + 1;
  $('#meRoofOpeningY').value = (row?.y ?? region?.y ?? 0) + 1;
  $('#meRoofOpeningKind').value = row?.kind || 'trapdoor';
  $('#meRoofOpeningOpen').checked = row?.open === true;
  $('#meRoofOpeningSave').textContent = row ? 'Save opening' : 'Add opening';
  $('#meRoofOpeningRemove').disabled = !row;
}
$('#meRoofOpening').addEventListener('change', renderRoofOpeningControls);
$('#meRoofOpeningSave').addEventListener('click', () => {
  const row = {x: Number($('#meRoofOpeningX').value) - 1, y: Number($('#meRoofOpeningY').value) - 1,
    kind: $('#meRoofOpeningKind').value, open: $('#meRoofOpeningOpen').checked};
  const previous = $('#meRoofOpening').value;
  try {
    // Validate before creating an undo entry, so a rejected square preserves
    // both the map and any redo history the author still has.
    const next = {...editor.doc};
    writeRoofOpening(next, detectRoofRegions(board.map), row, previous === 'new' ? null : previous);
    change(doc => { doc.roofs = next.roofs; });
    $('#meRoofOpening').value = roofOpeningKey(row);
    renderRoofOpeningControls();
  } catch (error) { toast(error.message, true); }
});
$('#meRoofOpeningRemove').addEventListener('click', () => {
  const key = $('#meRoofOpening').value;
  if (key !== 'new') change(doc => removeRoofOpening(doc, key));
});
$('#meWallLook').addEventListener('change', () => { $('#meWallHeight').value = wallHeightFt({look: $('#meWallLook').value}); });
$("#meGridColor").addEventListener("change", event => change(doc => { doc.display = {...(doc.display || {}), grid_color: event.target.value}; }));
$("#meFit2").addEventListener("change", event => change(doc => { doc.background = {...(doc.background || {}), fit: event.target.value}; }));
// Floors added by a dedicated art module (SON202: indoor floors/tiles, grass and forest variants) are grouped
// under their own plain-named optgroups in both pickers; every floor from before keeps its old flat listing.
const FLOOR_ART_STYLE_KEYS = new Set(FLOOR_ART_GROUPS.flatMap(group => Object.keys(group.styles)));
const floorGroupOptgroups = (valueFor, labelFor) => FLOOR_ART_GROUPS.map(group => `<optgroup label="${group.label}">`
  + Object.keys(group.styles).map(key => `<option value="${valueFor(key)}">${labelFor(key)}</option>`).join("") + "</optgroup>").join("");
$("#meStyle").innerHTML = Object.entries(STYLES).filter(([value]) => !FLOOR_ART_STYLE_KEYS.has(value))
  .map(([value, label]) => `<option value="${value}">${label}</option>`).join("")
  + floorGroupOptgroups(value => value, value => STYLES[value]);
// The Material brush (owner 2026-09-28: "a map editor mode so i can make maps with the materials and save them").
function materialOptions() {
  // A dirt road painted as a patch is plain dirt (textures.js paintFloor patch); the road itself is a map background.
  const floors = Object.entries(STYLES).filter(([value]) => !FLOOR_ART_STYLE_KEYS.has(value))
    .map(([value, label]) => `<option value="floor:${value}">${value === "dirt_road" ? "Dirt" : label}</option>`).join("");
  // optgroup cannot nest, so the new floor art's own groups (Indoor, Grass, Forest floor) sit beside the
  // original "Floor (look only)" group rather than inside it.
  const newFloors = floorGroupOptgroups(value => `floor:${value}`, value => STYLES[value]);
  // The terrain brush lists the ground by name; its rule is the same reading the table's hover card shows,
  // so the option carries that reading in full rather than a shorter third wording (OC13: the brush said
  // "lightly obscured" for Fire Terrain and never mentioned the save).
  const terrains = TERRAINS.map(row => `<option value="terrain:${escapeHtml(row.name)}" title="${escapeHtml((row.reading || [row.does]).join(" "))}">${escapeHtml(row.label)}</option>`).join("");
  const current = $("#meMaterial").value;
  $("#meMaterial").innerHTML = `<optgroup label="Floor (look only)">${floors}</optgroup>${newFloors}`
    + (terrains ? `<optgroup label="Named terrain (works in fights)">${terrains}</optgroup>` : "")
    + `<optgroup label="Erase"><option value="erase:floor">Erase floor patch</option><option value="erase:terrain">Erase named terrain</option></optgroup>`;
  if (current) $("#meMaterial").value = current;
}
$("#meTerrainLook").innerHTML = '<option value="">Auto (based on floor)</option>' + TERRAIN_LOOKS.map(look => '<option value="' + look + '">' + look.replaceAll("_", " ") + '</option>').join("");
$("#meDecorKind").innerHTML = Object.entries(DECOR_BIOMES).map(([biome, {name}]) => `<optgroup label="${name}">`
  + Object.entries(DECOR).filter(([, piece]) => piece.biome === biome)
    .map(([kind, piece]) => `<option value="${kind}">${piece.name}${piece.rule === "SIMPLE_COVER" ? " (cover)" : piece.rule === "DIFFICULT" ? " (difficult)" : ""}</option>`).join("")
  + "</optgroup>").join("");
function wallLookOptions() {
  return `<option value="">Plain stone</option>` + Object.entries(WALL_LOOKS).map(([look, name]) => `<option value="${look}">${name}</option>`).join("");
}
$("#meWallLook").innerHTML = wallLookOptions();
$("#meTreeLook").innerHTML = Object.entries(TREE_LOOKS).map(([look, name]) => `<option value="${look}">${name}</option>`).join("");
materialOptions();
api("/api/tabletop/terrains").then(result => { TERRAINS = result.terrains || []; GROUND = result.ground || {}; materialOptions(); if (editor.doc) render(); })
  .catch(() => toast("Could not load the named terrains; floors still work.", true));
const numberSetting = (id, key, low, high) => $(id).addEventListener("change", event => change(doc => {
  doc.terrain_numbers = {save_dc: 13, pb: 2, ...(doc.terrain_numbers || {}), [key]: Math.max(low, Math.min(high, Math.round(Number(event.target.value) || low)))};
}));
numberSetting("#meTerrainDC", "save_dc", 5, 30);
numberSetting("#meTerrainPB", "pb", 2, 9);
$("#meStyle").addEventListener("change", event => change(doc => { doc.background = {...(doc.background || {}), style: event.target.value}; }));
$("#meReseed").addEventListener("click", () => change(doc => { doc.background = {...(doc.background || {}), seed: 1 + Math.floor(Math.random() * 1e6)}; }));
// The style picker changes the shared app style (Settings > Appearance; /static/appearance-boot.js).
$("#meTheme").addEventListener("change", event => window.TianxiaAppearance?.setStyle(event.target.value));
window.TianxiaAppearance?.onChange(prefs => { $("#meTheme").value = prefs.style; });
function syncRulesOverlay() {
  const on = localStorage.getItem("tt-rules-overlay") === "true";
  const button = $("#meRulesOverlay");
  button.classList.toggle("is-on", on);
  button.setAttribute("aria-pressed", String(on));
}
$("#meRulesOverlay").addEventListener("click", () => {
  board.setRulesOverlay(localStorage.getItem("tt-rules-overlay") !== "true"); syncRulesOverlay();
});
syncRulesOverlay();

function editSelected(mutator) {
  if (!(editor.doc.objects || []).some(o=>o.id===editor.selectedObject)) return;
  change(doc=>mutator(doc.objects.find(o=>o.id===editor.selectedObject)));
}
function rotateSelected(delta=90) {
  editSelected(o=>{
    if (o.rotation == null && !o.mount_axis) o.rotation = {south:90,west:180,north:270}[objectFacing(o,editor.cells.blocked)] || 0;
    rotateObject(o,delta);
  });
}
$('#meObjectRotate').addEventListener('click', ()=>rotateSelected());
$('#meObjectAddHere').addEventListener('click', () => {
  const selected = (editor.doc.objects || []).find(o => o.id === editor.selectedObject);
  if (selected) objectDown([selected.x, selected.y]);
});
$('#meObjectRemove').addEventListener('click', ()=>change(doc=>{doc.objects=doc.objects.filter(o=>o.id!==editor.selectedObject);}));
$('#meObjectOpen').addEventListener('change', event=>editSelected(o=>{
  const open=event.target.checked;
  o.blocks=!open;
  if (o.kind==='door') Object.assign(o,{interaction:'simple_door',door_open:Number(open),door_locked:0,door_jammed:0});
}));
document.addEventListener("keydown", event => {
  if (event.target.closest("input, select, textarea")) return;
  if (event.shiftKey && event.key.toLowerCase() === "r") { event.preventDefault(); $("#meRulesOverlay").click(); return; }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); event.shiftKey ? redo() : undo(); return; }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); return; }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); save(); return; }
  if (!event.ctrlKey && !event.metaKey && ['q','e'].includes(event.key.toLowerCase())) {
    event.preventDefault(); rotateSelected(event.key.toLowerCase()==='q'?-90:90); return;
  }
  const tool = KEYS[event.key.toLowerCase()];
  if (tool) setTool(tool);
  if (event.key === "Escape" && editor.draft) { editor.draft = null; drawDraft(); }
});
window.addEventListener("beforeunload", event => { if (editor.dirty) { event.preventDefault(); event.returnValue = ""; } });

(async function start() {
  $("#meTheme").value = window.TianxiaAppearance?.current().style || "lacquer";
  const params = new URLSearchParams(location.search);
  const mapId = params.get("map");
  try {
    await loadList(mapId ? `map:${mapId}` : "new");
  } catch (error) { toast(error.message, true); }
  editor.doc = blankMap();
  if (mapId) await open(`map:${mapId}`);
  else render({fit: true});
  setTool("rect");
  window.mapEditor = {editor, board, save, open};  // for smoke tests
})();
