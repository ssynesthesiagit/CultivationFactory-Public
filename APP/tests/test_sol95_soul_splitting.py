"""Soul Splitting must never charge the table for an unimplemented soul asset."""
import hashlib
import json

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from combat.ext.soul_splitting import SOURCE, LABEL
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture, candidate


def spirit(bundles):
    doc = sheet([SOURCE], cl=17, primary='Resonance', key='WIS')
    doc['identity'].update(path='Spirit Awakening', display_name='Owner')
    bundles[0] = compile_character(doc, actor_id=OWNER)


@pytest.mark.parametrize('resonance', [0, 30])
def test_gm_rules_button_spends_nothing_and_creates_no_fragment_after_table_commit_reload(tmp_path, resonance):
    def prepare(bundles):
        spirit(bundles)
        pool = next(r for r in bundles[0]['actor_template']['resources'] if r['resource_id'] == 'resource:core.resonance')
        pool['initial'] = resonance
    combat, table, mid, _, commit = fixture(tmp_path, [SOURCE], bundle_transform=prepare)
    engine = combat._load_session(mid).mechanical.engine
    before = engine.state.actors[OWNER].model_dump(mode='json')
    assert before['resources']['resource:core.resonance'] == resonance
    actors = tuple(engine.state.actors)
    commit(candidate(table, mid, LABEL))
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    after = session.mechanical.engine.state.actors[OWNER].model_dump(mode='json')
    for field in ('resources', 'action_available', 'bonus_action_available', 'conditions', 'current_hp'):
        assert after[field] == before[field]
    assert tuple(session.mechanical.engine.state.actors) == actors
    assert session.mechanical.replay()['status'] == 'PASS'
    summaries = ' '.join(e['summary'] for e in TabletopService(fresh, tmp_path).events(mid, 0)['events'])
    assert 'Soul Splitting is GM-run' in summaries
    assert '8 Resonance' in summaries and 'creates no fragment' in summaries
    assert '4d10 Psychic' in summaries
    assert 'once on each of your turns' in summaries
    assert 'Spirit Awakening Path or Subpath feature or use Mind Spike' in summaries
    assert candidate(TabletopService(fresh, tmp_path), mid, LABEL)


def test_generated_table_button_text_is_a_rules_reference_not_a_kept_choice(tmp_path):
    """The reference stores nothing, so its button text must not promise a kept choice.

    tabletop.setting_button_description defaults to "Free choice, kept until you
    change it" for any setting_only action. That default is wrong for a rules
    reference: reading it selects nothing and configures no future activation.
    """
    from combat.ext.soul_splitting import REFERENCE_HEAD
    from combat.tabletop import auto_buttons, setting_button_description
    from tests.r1i_service_support import fixture

    combat, table, mid, _, _ = fixture(tmp_path, [SOURCE], bundle_transform=spirit)
    bundle = combat._load_session(mid).mechanical.engine.typed_bundle_documents[0]
    rows = {row['display_name']: row for row in bundle['action_catalog']}
    row = rows[LABEL]

    # The plug-in supplies its own accurate head through the documented parameter.
    assert row['parameters'].get('setting_description') == REFERENCE_HEAD
    head = setting_button_description(row, bundle).partition('\n\n')[0]
    assert head == REFERENCE_HEAD

    generated = [b for b in auto_buttons(bundle, {}) if b['label'] == LABEL]
    assert len(generated) == 1
    description = generated[0]['description']
    # It opens the rules and says plainly that nothing is chosen or kept.
    assert description.startswith(REFERENCE_HEAD)
    assert 'Rules reference, not a choice' in description
    assert 'selects nothing, keeps no setting' in description
    # The shared selector default would teach a persistent-state mechanic.
    for wrong in ('Free choice', 'kept until you change it', 'stays selected until',
                  'It stays selected', 'until you change it'):
        assert wrong not in description, wrong
    # ... and the printed ability it points at is still there.
    assert 'Split off one cultivated fragment' in description

    # The in-fight menu button is generated for the same row: it must not claim one either.
    service = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    menu = [a for a in service.state(mid)['menu']['actions'] if a['label'] == LABEL]
    assert len(menu) == 1
    for wrong in ('Free choice', 'kept until you change it', 'stays selected until',
                  'It stays selected', 'until you change it'):
        assert wrong not in menu[0]['description'], wrong


def test_authored_and_generated_expression_text_preserves_own_turn_restriction():
    from combat.ext.soul_splitting import EXPLANATION

    reviewed = json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/spirit.json').read_text())
    generated = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    for text in (EXPLANATION, ' '.join(reviewed['mechanics'][SOURCE]['riders']),
                 ' '.join(generated['mechanics'][SOURCE]['riders'])):
        assert 'once on each of your turns' in text
        assert 'Spirit Awakening Path or Subpath feature' in text
        assert 'Mind Spike' in text


@pytest.mark.parametrize('ask', [False, True])
def test_reference_is_not_an_activation_in_hostile_field_after_commit_reload(tmp_path, ask):
    from combat.ext.well_of_hours import WELL, FIELD
    from combat.ext.setting_choices import is_setting_action
    from tests.test_reaction_effects_r6 import _row

    def prepare(bundles):
        spirit(bundles)
        bundles[1] = compile_character(sheet([WELL], cl=17, primary='Resonance', key='WIS'), actor_id=FOE)
        # A plain technique responder, with no prerequisite other than range,
        # hostility and an available Reaction. It must never see this reference.
        row = _row('technique_used', [{'type': 'temp_hp', 'flat': 7}], range_ft=60)
        row['ask'] = ask
        bundles[2]['typed_reactions'].append(row)
        bundles[2]['reaction_plan']['ask'] = ask

    combat, table, mid, send, commit = fixture(tmp_path, [SOURCE], bundle_transform=prepare)
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    well = next(a for a in combat._load_session(mid).mechanical.engine.action_catalog.values()
                if a.display_name == 'The Well Has No Bottom')
    field_choice = next(c for c in combat.decision(mid)['context']['legal_candidates']
                        if c['source_definition_id'] == well.source_definition_id
                        and c.get('destination') == {'x': 3, 'y': 6})
    commit(field_choice['candidate_id'])
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])

    engine = CombatService(ROOT, tmp_path)._load_session(mid).mechanical.engine
    field = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == FIELD)
    zone = engine.state.zones[field.data['zone_id']]
    assert zone.active and engine._footprint_intersects(engine.state.actors[OWNER], zone.affected_cells)
    assert engine.state.actors[SECOND].reaction_available
    assert engine.grid.distance_ft(engine.state.actors[SECOND].position, engine.state.actors[OWNER].position) <= 60
    assert not engine.state.actors[OWNER].turn_flags.get(f'_round_c8_undertow:{FOE}')
    reference = next(a for a in engine.action_catalog.values() if a.display_name == LABEL)
    assert is_setting_action(reference)
    before = engine.state.model_dump(mode='json')
    rolls = [r.model_dump(mode='json') for r in engine.rolls]
    event_count = len(engine.events)
    result = send(candidate(table, mid, LABEL))
    assert result['status'] == 'COMMITTED'  # no Ask me prompt or automatic Reaction
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert {e.event_type for e in fresh.mechanical.engine.events[event_count:]} <= {'INTENT_ACCEPTED', 'PASSIVE_TRIGGERED'}
    after = fresh.mechanical.engine.state.model_dump(mode='json')
    # Only journal/version bookkeeping can change when a reference is read.
    for key in before:
        if key not in ('state_version', 'event_sequence'):
            assert after[key] == before[key], key
    assert [r.model_dump(mode='json') for r in fresh.mechanical.engine.rolls] == rolls
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_saved_unflagged_reference_is_not_offered_after_reload(tmp_path):
    def old_reference(bundles):
        spirit(bundles)
        reference = next(a for a in bundles[0]['action_catalog'] if a['display_name'] == LABEL)
        reference['parameters'].pop('setting_only')

    _, _, mid, _, _ = fixture(tmp_path, [SOURCE], bundle_transform=old_reference)
    fresh = CombatService(ROOT, tmp_path)
    assert not any(LABEL in g['label'] for g in TabletopService(fresh, tmp_path).state(mid)['menu']['actions'])
    assert fresh._load_session(mid).mechanical.replay()['status'] == 'PASS'


def test_gm_reference_is_excluded_from_builtin_ai_decisions(tmp_path):
    combat, _, mid, _, _ = fixture(tmp_path, [SOURCE], bundle_transform=spirit)
    engine = combat._load_session(mid).mechanical.engine
    policy, _ = PolicyLibrary(ROOT).for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    source_ids = {c.source_definition_id for c in context.legal_candidates}
    reference = next(a for a in engine.action_catalog.values() if a.display_name == LABEL)
    assert reference.source_definition_id not in source_ids


def test_old_saved_paid_placeholder_is_not_offered_after_reload(tmp_path, monkeypatch):
    def legacy(bundles):
        spirit(bundles)
        row = next(a for a in bundles[0]['action_catalog'] if a['display_name'] == LABEL)
        row.update(display_name='Soul Splitting', economy='ACTION', costs=[['resource:core.resonance', 8]])
        row['parameters']['typed'].pop('soul_splitting_reference')
        row['parameters']['typed']['effects'] = []
        row['parameters']['typed']['riders'] = ['The GM tracks the fragment.']
        row['parameters']['typed']['duration'] = {'kind': 'scene'}
    # Create a genuine pre-fix paid journal entry by isolating only this lane's
    # hook in the test registry. Production engine/classes remain untouched.
    from combat import ext
    from combat.ext.soul_splitting import refuse_legacy_placeholder
    with monkeypatch.context() as old_runtime:
        old_runtime.setitem(ext._HOOKS, 'candidate_allowed',
                            [f for f in ext._HOOKS['candidate_allowed'] if f is not refuse_legacy_placeholder])
        combat, table, mid, _, commit = fixture(tmp_path, [SOURCE], bundle_transform=legacy)
        commit(candidate(table, mid, 'Soul Splitting'))
    commit(table.state(mid)['menu']['end_turn'])
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    assert session.mechanical.replay()['status'] == 'PASS'
    # The stored catalog still contains the paid row; load has not rewritten it.
    old = next(a for a in session.mechanical.engine.action_catalog.values() if a.display_name == 'Soul Splitting')
    assert old.costs
    assert session.mechanical.engine.state.actors[OWNER].resources['resource:core.resonance'] == 22
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    assert not any('Soul Splitting' in g['label'] for g in TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(mid)['menu']['actions'])


def test_prior_saved_stock_ai_continuation_matches_base_commit():
    # Round 25 integrates on b221edf6. Exact baseline/current payload equality
    # was verified by R25-evidence/compare_soul.py before updating these goldens.
    from tests.test_hunt32_inert_replay import _capture
    assert hashlib.sha256(_capture()).hexdigest() == 'b47c250713be44d8950664c6bf86143c83a67f2d9f0083c0396e433f21bc1154'


@pytest.mark.parametrize('seed, expected', [
    ('SOL95-STOCK-1', 'd99347e1dbbdd030e5756a9407ec048d2db5c7bdc422124c98c344bc35c78a3b'),
    ('SOL95-STOCK-2', 'f6638a753f131fa4faed959f09313266943526d69994c6b3adcce6fe1bfe6f77'),
])
def test_stock_ai_decisions_events_rolls_and_state_match_reviewed_round25(seed, expected):
    # r25f-evidence/soul_attribution.json isolates the reviewed changes:
    # lock integration changes STOCK-1's scoring records at decisions 18/19,
    # with identical selected intents, state, events and rolls. H86 changes
    # STOCK-2 by passing an unavailable Lee Jia turn (first divergence event 51).
    # Keep the exact whole-capture regression for the resulting round-25 game.
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate4_controller import LocalDeterministicController
    engine = Gate4ControllerEngine(ROOT, match_seed=seed)
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
    decisions = []
    for _ in range(24):
        if engine.state.terminal_result:
            break
        policy, _ = policies.for_actor(engine.state.current_actor_id)
        choice = controller.choose_primary_action(build_decision_context(engine, policy, for_ai=True))
        decisions.append(choice.model_dump(mode='json'))
        engine.execute_intent(choice.intent)
    captured = json.dumps({'decisions': decisions, 'state': engine.state.model_dump(mode='json'),
                          'events': [e.model_dump(mode='json') for e in engine.events],
                          'rolls': [r.model_dump(mode='json') for r in engine.rolls]},
                         sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(captured).hexdigest() == expected
