import test from "node:test";
import assert from "node:assert/strict";
import {installDOM} from "./objects_dom_stub.mjs";
import {decodeLightCells, paintLight} from "../static/tabletop/light_layer.js";
import {createBoard} from "../static/tabletop/board.js";

installDOM("<body></body>");

function fighter(x, y, light) {
  return {id: "a", x, y, name: "Test Fighter", hp: 10, maxHp: 10, object: false, kind: null, image: "", label: "",
    light, hidden: false, current: false, selected: false, targetable: false, down: false, unseen: false,
    yours: true, item: false, conditions: [], color: "#ffffff", size: 1, height: 1, scale: 1, badge: ""};
}

const context = (fills, stops = []) => ({clearRect(){}, fillRect(...args){fills.push([this.fillStyle, args]);},
  createRadialGradient(){return {addColorStop:(at,color)=>stops.push([at,color])};},
  save(){}, beginPath(){}, rect(){}, clip(){}, restore(){},
  set globalCompositeOperation(_) {}, set globalAlpha(_) {}, set filter(_) {}});

test("decodes the server's two-bit row-major light field", () => {
  assert.deepEqual([...decodeLightCells(btoa(String.fromCharCode(0b00111001)), 4)], [1, 2, 3, 0]);
});

test("shades only perceived cells and leaves remembered cells untouched", () => {
  const fills = [];
  paintLight(context(fills), 2, 1, Uint8Array.of(0, 2), [], {cellSize: 10, perceived: Uint8Array.of(1, 0)});
  assert.equal(fills.length, 1);
  assert.match(fills[0][0], /0.62/);
});

test("source glow is clipped to perceived cells with resolved light", () => {
  const fills = [], clips = [];
  const ctx = context(fills);
  ctx.rect = (...args) => clips.push(args);
  paintLight(ctx, 3, 1, Uint8Array.of(2, 0, 2), [{x:0,y:0,dim_ft:20,bright_ft:10,color:"#ffaa00"}],
    {cellSize:10, perceived:Uint8Array.of(1,1,0)});
  assert.deepEqual(clips, [[0,0,10,10]]);
  assert.equal(fills.length, 2); // one source glow plus shading of the lit-zero perceived cell
});

test("an actor light (radius_ft, level) paints the same glow as a map light", () => {
  const fills = [];
  paintLight(context(fills), 1, 1, Uint8Array.of(2),
    [{x: 0, y: 0, radius_ft: 20, color: "#ffaa00", level: "bright"}], {cellSize: 10, perceived: Uint8Array.of(1)});
  assert.equal(fills.length, 1); // a lit square needs no shading, so the one fill is the glow
});

test("a source with no usable radius never reaches the gradient", () => {
  const radii = [];
  const ctx = context([]);
  ctx.createRadialGradient = (x0, y0, r0, x1, y1, r1) => {
    assert.ok(Number.isFinite(r1), `gradient radius ${r1} is not a finite number`);
    radii.push(r1);
    return {addColorStop() {}};
  };
  paintLight(ctx, 1, 1, Uint8Array.of(2), [
    {x: 0, y: 0, dim_ft: Infinity, bright_ft: 10},
    {x: 0, y: 0, dim_ft: "far"},
    {x: 0, y: 0, radius_ft: -5},
    {x: 0, y: 0},
  ], {cellSize: 10, perceived: Uint8Array.of(1)});
  assert.deepEqual(radii, []);
});

test("editor preview can show authored lights against dark ambient", () => {
  const fills = [];
  paintLight(context(fills), 1, 1, Uint8Array.of(0), [{x:0,y:0,dim_ft:20,bright_ft:10}], {cellSize:10, clipSources:false});
  assert.equal(fills.length, 2); // source glow, then the dark-ambient shading pass
});

test("a creature glow is a DOM node beside the light-field canvas, not canvas fallback content", () => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  createBoard(host).setTokens([fighter(1, 1, {radius_ft: 20, color: "#ffd28a", level: "bright"})]);
  const glow = host.querySelector(".tt-light");
  assert.ok(glow, "the torch has a glow node");
  assert.equal(glow.parentNode.tagName, "DIV", "a canvas drops its DOM children as fallback content, so the glow would not be drawn");
  assert.ok(glow.parentNode.classes.has("tt-lights"), "the glow lives in the light layer");
  const fields = [...glow.parentNode.querySelectorAll("canvas")];
  assert.equal(fields.length, 1, "the server light field keeps its one canvas in the same layer");
  assert.ok(fields[0].classes.has("tt-light-field"));
});
