// Shared actual renderer for the headless DOM test and lead-only visual check.
const fs = require('node:fs');
const path = require('node:path');
const sheet = fs.readFileSync(path.join(__dirname, '../static/tabletop/sheet.js'), 'utf8');
function section(start, end) {
  const from = sheet.indexOf(start), to = sheet.indexOf(end, from + start.length);
  if (from < 0 || to <= from) throw Error(`Missing renderer boundary: ${start}`);
  return sheet.slice(from, to);
}
module.exports = `
const $ = id => document.getElementById(id);
const state = {summary: {}, sheet: {}, buttons: []};
const signed = n => String(n ?? 0), spoken = signed;
const icon = () => document.createElement('span');
const resourceText = r => r.name;
const clamp01 = v => Math.max(0, Math.min(1, v));
const norm = text => String(text || '').trim().toLowerCase();
${fs.readFileSync(path.join(__dirname, '../static/sheet_view_model.js'), 'utf8')}
${section('function h(tag, attrs, ...kids)', 'function icon(')}
${section('function walkingBox(', 'function renderSaves()')}
${section('function resourcePools(', 'function renderSaves()')}
${section('function renderDefenses()', 'function renderSkills()')}
`;
