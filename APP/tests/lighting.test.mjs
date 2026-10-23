import test from "node:test";
import assert from "node:assert/strict";
import {decodeLightCells, paintLight} from "../static/tabletop/light_layer.js";

test("decodes the server's two-bit row-major light field", () => {
  // Four cells are stored least-significant pair first.
  assert.deepEqual([...decodeLightCells(btoa(String.fromCharCode(0b00111001)), 4)], [1, 2, 3, 0]);
});

test("shades only perceived cells and leaves remembered cells untouched", () => {
  const fills = [];
  const ctx = {clearRect(){}, fillRect(...args){fills.push([this.fillStyle, args]);},
    createRadialGradient(){throw Error("no sources expected");},
    set globalCompositeOperation(_) {}, set globalAlpha(_) {}, set filter(_) {}};
  paintLight(ctx, 2, 1, Uint8Array.of(0, 2), [], {cellSize: 10, perceived: Uint8Array.of(1, 0)});
  assert.equal(fills.length, 1);
  assert.match(fills[0][0], /0.62/);
});

test("soft source gradient falls off at the edge", () => {
  const stops = [], ctx = {clearRect(){}, fillRect(){}, createRadialGradient(){return {addColorStop:(at,color)=>stops.push([at,color])};},
    set globalCompositeOperation(_) {}, set globalAlpha(_) {}, set filter(_) {}};
  paintLight(ctx, 2, 2, new Uint8Array(4).fill(2), [{x:0,y:0,dim_ft:20,bright_ft:10,color:"#ffaa00"}], {cellSize:10});
  assert.deepEqual(stops.map(row=>row[0]), [0, .5, 1]);
});
