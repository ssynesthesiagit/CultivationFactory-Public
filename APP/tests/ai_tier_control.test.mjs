// Execute the real inspector render and tier click, without a browser or server.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installDOM} from './objects_dom_stub.mjs';

const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
const start = source.indexOf('function renderInspector() {');
assert.ok(start >= 0);
const renderSource = source.slice(start, source.indexOf('\n}', start) + 2);

for (const mode of ['MANUAL', 'SUGGESTED', 'LOCAL_AUTO', 'API_AUTO', 'MANUAL_AI_BRIDGE']) {
  for (const tier of ['TRICKY', 'MASTERMIND']) {
    test(`clicking ${tier} preserves stored ${mode}, not a display label`, async () => {
      const document = installDOM('<body><div id="ttInformation"></div><div id="ttInspector"></div></body>');
      const actor = {entity_id: 'fighter', display_name: 'Mira', primary_combatant: true,
        controller: 'Played by a model', ai_tier: tier === 'TRICKY' ? 'MASTERMIND' : 'TRICKY',
        hit_points: {current: 20, maximum: 20}};
      const stored = {fighter: mode, other: 'SUGGESTED'};
      const before = {...stored}, requests = [], notices = [];
      let savedTier = actor.ai_tier, refreshes = 0;
      const app = {selected: new Set(['fighter']), matchId: 'fight', state: {}, providers: [],
        seatStatus: {seats: {'model-seat': {provider_id: 'fake'}}}};
      const noop = () => {};
      const bindings = {
        app, document, $: selector => document.querySelector(selector),
        TianxiaSheetViewModel: {armorBreakdown: () => '', armorCard: () => ({})},
        sheetFor: async () => null,
        renderInformation: noop, currentViewer: () => ({status: 'gm'}), actors: () => [actor],
        isOwnedActor: () => true, hoverCard: {isOpen: false}, actorById: () => actor,
        projectOf: () => null, teamIndex: () => 0, TEAM_COLORS: ['red'], initials: () => 'M',
        pct: () => 100, concentrationCard: () => '', unseenByViewers: () => false,
        economyPills: () => '', shownCondition: () => false, playedByHtml: () => '',
        modelOwner: () => 'model-seat', providerLabel: () => 'Model', escapeHtml: String,
        openSeatLog: noop,
        movementLeft: () => '', flightText: () => '', board: {}, playedByWord: () => 'a model',
        isManualActor: () => false, controlOf: () => 'MODEL', presentation: () => ({terminal: false}),
        enc: encodeURIComponent, refresh: async () => { refreshes++; }, toast: text => notices.push(text),
        api: async (path, options) => {
          requests.push({path, options});
          if (!options?.body) {
            assert.equal(path, '/api/combat/matches/fight');
            return {metadata: {participant_control_modes: {...stored}}};
          }
          assert.equal(path, '/api/combat/matches/fight/controller-mode');
          assert.equal(options.body.actor_id, 'fighter');
          assert.equal(options.body.controller_mode, mode);
          stored.fighter = options.body.controller_mode;
          savedTier = options.body.ai_tier;
        },
      };
      const renderInspector = Function(...Object.keys(bindings), renderSource + '; return renderInspector;')(...Object.values(bindings));
      renderInspector();
      const button = document.querySelector(`[data-ai-tier="${tier}"]`);
      assert.ok(button, 'tier remains available on the mini sheet');
      await button.click();
      assert.deepEqual(notices, []);
      assert.equal(savedTier, tier);
      assert.deepEqual(stored, before, 'tier change must not hand the fighter to a different controller');
      assert.equal(refreshes, 1);
      assert.equal(requests.length, 2, 'read the stored modes before submitting a tier change');
    });
  }
}
