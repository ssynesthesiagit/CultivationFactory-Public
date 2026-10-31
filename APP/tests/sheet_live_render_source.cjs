// Real sheet renderers, shared by the Node DOM harness and opt-in browser check.
const fs = require("node:fs");
const path = require("node:path");
const sheet = fs.readFileSync(path.join(__dirname, "../static/tabletop/sheet.js"), "utf8");
function section(start, end) {
  const from = sheet.indexOf(start);
  const to = sheet.indexOf(end, from + start.length);
  if (from < 0 || to <= from) throw new Error(`Missing sheet source boundary: ${start}`);
  return sheet.slice(from, to);
}
const source = [
  `const $ = id => document.getElementById(id);
   const state = {summary: {armor_class: 12, armor_note: "Lamellar armor", speed_ft: 30},
     sheet: {}, actor: null, connected: true};
   const app = {state: null};
   const signed = n => String(n ?? 0), spoken = signed;
   const clamp01 = n => Math.max(0, Math.min(1, n));
   const icon = () => document.createElement("span");
   const applyLegal = () => {};
   const economyPips = () => [];
   const showToken = () => {};`,
  fs.readFileSync(path.join(__dirname, "../static/tabletop/live-stats.mjs"), "utf8").replace("export function", "function"),
  section("function initials(", "function renderHeader()"),
  section("function renderHeader()", "// 2024 Carrying Capacity"),
  section("function h(tag, attrs, ...kids)", "function icon("),
  section("function walkingBox(", "function renderSaves()"),
  section("function resourcePools(", "function renderSaves()"),
  section("function renderDefenses()", "function renderSkills()"),
  section("function renderLive()", "// ------------------------------------------------------------------ channel"),
].join("\n");
module.exports = source;
if (require.main === module) process.stdout.write(JSON.stringify(source));
