import test from "node:test";
import assert from "node:assert/strict";
import {decodeLightCells, paintLight} from "../static/tabletop/light_layer.js";

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
  assert.equal(fills.length, 1);
});

test("editor preview can show authored lights against dark ambient", () => {
  const fills = [];
  paintLight(context(fills), 1, 1, Uint8Array.of(0), [{x:0,y:0,dim_ft:20,bright_ft:10}], {cellSize:10, clipSources:false});
  assert.equal(fills.length, 1);
});
