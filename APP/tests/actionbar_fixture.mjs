// Synthetic, network-free bar fixture shared by the Node contract and the lead-only browser check.
// Runs the shipped bar renderers; only service/state dependencies are substituted.
import {actionHoverText, actionTipCard, rulesTextFor, additionalRuleText, cleanRules, renderRules, renderTipCard, actionSummary} from '../static/tabletop/rules.js';
import {layoutText} from '../static/tabletop/presentation.js';
import {attackGroupView, groupAttackRows, renderVariantGroups} from '../static/tabletop/attack-groups.js';
import {economySections, economyPills} from '../static/tabletop/action-economy.js';
import {bindPress} from '../static/tabletop/kept-bar.js';
import {renderFightSetup} from '../static/tabletop/fight-setup-prompt.js';

export const plainRules = 'Action Type: Action\nRange: 5 feet\n'
  + Array.from({length: 40}, (_, i) => `Rule ${i + 1}: Keep this complete instruction readable.`).join('\n')
  + '\nFinal rule: every choice remains available.';

export async function renderBarFixture(document, bar, source, hover) {
  const piece = name => {
    const start = source.search(new RegExp(`(?:async )?function ${name}\\(`));
    if (start < 0) throw new Error('Missing shipped function: ' + name);
    return source.slice(start, source.indexOf('\n}', start) + 2);
  };
  const rows = [
    {id: 'carded', label: 'Broken-Rhythm Strike: Unarmed Strike', group: 'attacks', hover},
    {id: 'plain', label: 'Plain training strike', group: 'actions', description: plainRules},
  ].map(row => ({...row, kind: 'combat', economy: 'ACTION', combat: {source_definition_id: row.id},
    detail: {to_hit: '+5', damage: '1d6 + 3', range: '5 ft', attacks: 1}}));
  const extra = [
    {source_definition_id: 'extra-carded', label: 'Extra carded strike', hover},
    {source_definition_id: 'extra-plain', label: 'Extra plain strike', description: plainRules},
  ].map(row => ({...row, economy: 'ACTION', options: [{option_id: row.source_definition_id}]}));
  // Also exercise a carded non-attack sheet action (drawButton rather than attackWeaponCard).
  rows.push({...rows[0], id: 'sheet-carded', label: 'Sheet carded strike', group: 'actions',
    combat: {source_definition_id: 'sheet-carded'}});
  const actor = {entity_id: 'training', display_name: 'Training fighter', position: {x: 0, y: 0},
    turn_state: {action: true, bonus_action: true, reaction: true}};
  const menu = {actor_id: actor.entity_id, actions: [
    ...rows.map(row => ({source_definition_id: row.id, label: row.label, economy: row.economy})), ...extra,
  ], moves: [], end_turn: 'end'};
  const app = {state: {menu, button_states: {}}, menu, seatStatus: null, matchId: 'synthetic'};
  const pressed = [];
  const env = {
    document, app, $: () => bar,
    presentation: () => ({current_actor_id: actor.entity_id}), currentViewer: () => ({ready: true}),
    actorById: () => actor, modelOwner: () => null, serverDriving: () => false,
    isManualActor: () => true, automaticSlot: () => false,
    sheetFor: async () => ({buttons: rows, library: {groups: []}}),
    movementLeft: () => '30 ft', moveHeight: () => 0, roofLevelsAt: () => [], board: {map: {}},
    // Availability is synthetic service input here, not the presentation contract under test.
    reasonFor: () => '', draftOptionRows: () => [], markActive() {}, menuInspectionKey: () => 'synthetic',
    appendActionBarRankedChoice: (bar, menu, {html}) => bar.appendChild(html),
    bindPress, renderFightSetup, actionHoverText, actionTipCard, rulesTextFor, additionalRuleText, cleanRules,
    renderRules, renderTipCard, actionSummary,
    layoutText, attackGroupView, groupAttackRows, renderVariantGroups, economySections, economyPills,
    runButton: row => pressed.push(row.id), useGroup: row => pressed.push(row.source_definition_id),
    actOnce: id => pressed.push(id),
  };
  const render = new Function(...Object.keys(env),
    'let menuLoadingTimer = null; let menuLoadingActor = null;\n'
    + (source.includes('function actionRules(') ? piece('actionRules') + '\n' : '')
    + ['buttonDetail', 'costTag', 'noteAttackSent', 'attackWeaponCard', 'renderActionBar'].map(piece).join('\n')
    + '\nreturn renderActionBar;')(...Object.values(env));
  await render(bar);
  return {pressed, rows, extra};
}
