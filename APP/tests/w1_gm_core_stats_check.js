'use strict';
const fs = require('fs');
const vm = require('vm');
const [appPath, viewPath, modelPath] = process.argv.slice(2);
if (!appPath || !viewPath || !modelPath) throw new Error('usage: node w1_gm_core_stats_check.js app.js view.json model.json');
const src = fs.readFileSync(appPath, 'utf8');
function extract(name) {
  const marker = `function ${name}`;
  const start = src.indexOf(marker);
  if (start < 0) throw new Error(`missing ${name}`);
  const closeParen = src.indexOf(')', start);
  const brace = src.indexOf('{', closeParen);
  let depth = 0, quote = null, escape = false;
  for (let i = brace; i < src.length; i += 1) {
    const ch = src[i];
    if (quote) { if (escape) escape = false; else if (ch === '\\') escape = true; else if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue; }
    if (ch === '{') depth += 1;
    if (ch === '}' && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error(`unterminated ${name}`);
}
const names = ['zucIsObject','zucArray','zucText','zucNum','zucFirst','zucDisplay','zucSkillRows','zucNormalizeSupportedCoreStats','zucDirectViewModelV2'];
const context = {console, ZUC_VIEW_SCHEMA: 'Tianxia_GM_Character_View_Model_v2', ZUC_PATCH_ID: 'W1', zucValidateModel: () => ({})};
vm.createContext(context);
vm.runInContext(names.map(extract).join('\n'), context);
const view = JSON.parse(fs.readFileSync(viewPath, 'utf8'));
const model = JSON.parse(fs.readFileSync(modelPath, 'utf8'));
function summarize(core) {
  const normalized = context.zucNormalizeSupportedCoreStats(core);
  return {
    hp: `${normalized.hp.current}/${normalized.hp.max}`,
    ac: normalized.ac.current,
    speed_ft: normalized.speed_ft,
    attack_bonus: normalized.attack_bonus,
    save_dc: normalized.save_dc,
    resource: `${normalized.primary_resource.name} ${normalized.primary_resource.current}/${normalized.primary_resource.max}`,
    abilities: Object.fromEntries(normalized.ability_scores.map(row => [row.ability, [row.score, row.modifier]])),
    skills: Object.fromEntries(normalized.skills.map(row => [row.name, row.bonus]))
  };
}
const fromView = summarize(view.core_stats);
const fromModel = summarize(model.stats);
const expected = {
  hp: '38/38', ac: 13, speed_ft: 30, attack_bonus: 6, save_dc: 14, resource: 'Qi 2/15',
  abilities: {STR:[8,-1],DEX:[16,3],CON:[14,2],INT:[17,3],WIS:[12,1],CHA:[8,-1]},
  skills: {Arcana:6,Deception:5,History:6,'Sleight of Hand':6}
};
if (JSON.stringify(fromView) !== JSON.stringify(expected)) throw new Error(`view mismatch ${JSON.stringify(fromView)}`);
if (JSON.stringify(fromModel) !== JSON.stringify(expected)) throw new Error(`v1 fallback mismatch ${JSON.stringify(fromModel)}`);
const direct = context.zucDirectViewModelV2([{name:'Tianxia_GM_Character_View_Model_v2.json', data:view}]);
if (direct.core_stats.hp.current !== 38 || direct.core_stats.ac.current !== 13) throw new Error('direct supported view was not normalized');
const roundTrip = JSON.parse(JSON.stringify(direct));
if (roundTrip.identity.display_name !== view.identity.display_name || roundTrip.core_stats.primary_resource.current !== 2) throw new Error('round-trip drift');
console.log(JSON.stringify({status:'PASS', fromView, fromModel, directIdentity:direct.identity.display_name}));
