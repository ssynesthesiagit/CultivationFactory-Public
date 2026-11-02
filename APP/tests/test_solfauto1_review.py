"""SOLFAUTO1: real table choices, transaction rollback, journal replay and cold reload.

Synthetic affliction/save setup runs inside accepted Hold transactions, so replay
sees the same setup. No GUI or live userdata is used.
"""
import pytest

from combat import ext
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h48_table_support import OWNER, FOE, fixture, candidate, assert_reload_verify_replay
from tests.test_tabletop_hunt6 import on_hold, HOLD
from tests.test_auto1_paths_a import MERIDIAN, TEMPERED, STAMINA, _meridian_fight


def cold(combat, mid, path):
    fresh = CombatService(combat.source_root, path)
    return fresh, TabletopService(fresh, path), fresh._load_session(mid).engine


def automatic_action(combat, source):
    """Choose one deterministic primary action; preserve the real reaction policy."""
    original = combat.controller

    class Controller:
        def choose_primary_action(self, context):
            choice = next(c for c in context.legal_candidates if c.source_definition_id == source)
            return ManualControllerAdapter(lambda _: (choice.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    combat.controller = Controller()


@pytest.mark.parametrize('use,dc', [(False, 1), (True, 1), (True, 99)])
@pytest.mark.parametrize('name', ['poisoned', 'disease'])
def test_meridian_end_turn_choice_commit_reload(tmp_path, monkeypatch, use, dc, name):
    from combat.ext import needle
    from combat.ext.choice_costs import Payment

    original_ask = needle.ask
    quoted = []

    def capture_payment(*args, **kwargs):
        quoted.append(kwargs)
        return original_ask(*args, **kwargs)

    monkeypatch.setattr(needle, 'ask', capture_payment)
    combat, table, mid, send, commit = fixture(tmp_path, [], seed=f'SOLF-M-{use}-{dc}-{name}',
                                             path_features=[MERIDIAN], primary='Stamina')

    def afflict(engine):
        if engine.state.current_actor_id == OWNER:
            engine._apply_condition(engine.state.actors[OWNER], 'condition:typed.' + name,
                                    'test:affliction', FOE, expires_on='UNTIL_REMOVED',
                                    data={'origin_save': {'ability': 'CON', 'dc': dc},
                                          'repeat_save': {'ability': 'CON', 'dc': dc, 'when': 'start'}})

    on_hold(monkeypatch, afflict)
    commit(candidate(table, mid, 'Hold'))
    combat, table, engine = cold(combat, mid, tmp_path)
    before = engine.state.model_dump(mode='json')
    stamina = engine.state.actors[OWNER].resources[STAMINA]
    menu = table.state(mid)['menu']

    def end(answers=()):
        return table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'], 0, list(answers))

    result = end()
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['cost'] == '1 Stamina'
    assert quoted[-1].get('payment') == Payment(STAMINA, 1)
    assert quoted[-1].get('feature_id') == MERIDIAN
    assert 'No printed rule summary' not in prompt['summary']
    assert prompt['context']['reactor_id'] == OWNER
    assert 'Meridian Reinforcement' in prompt['trigger']
    assert 'poison or disease' in prompt['trigger'] and 'end of this turn' in prompt['trigger']
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    # The pending prompt and uncommitted state survive an independent service load.
    combat, table, _ = cold(combat, mid, tmp_path)
    assert end()['reaction'] == prompt
    answer = {**prompt['context'], 'selection': 'USE' if use else 'DECLINE',
              'option_ids': [prompt['choice']['options'][0]['id']] if use else []}
    assert end([answer])['status'] == 'COMMITTED'
    assert_reload_verify_replay(combat, mid, tmp_path)
    _, _, engine = cold(combat, mid, tmp_path)
    actor = engine.state.actors[OWNER]
    assert actor.resources[STAMINA] == stamina - int(use)
    assert any(c.condition_id == 'condition:typed.' + name for c in actor.conditions.values()) == (not use or dc == 99)
    if use:
        stamp = actor.turn_flags['_round_meridian_reinforcement']
        assert type(stamp) is int and stamp == before['round_number']
        rolls = [r for r in engine.rolls if r.reason.startswith('SAVE:passive:meridian_reinforcement')]
        assert len(rolls) == 1 and rolls[0].mode == 'ADVANTAGE'


def test_meridian_compiled_passive_retains_display_name():
    from combat.ext.meridian_reinforcement import meridian_block

    row = meridian_block('meridian_reinforcement', {'name': 'Meridian Reinforcement'},
                         {'feature_id': MERIDIAN}, {})[0]
    assert row['name'] == 'Meridian Reinforcement'


def test_ai_meridian_decides_automatically(tmp_path, monkeypatch):
    combat, table, mid, send, commit = fixture(tmp_path, [], seed='SOLF-AI-M', path_features=[MERIDIAN], primary='Stamina')
    on_hold(monkeypatch, lambda engine: engine._apply_condition(
        engine.state.actors[OWNER], 'condition:typed.poisoned', 'test:poison', FOE,
        expires_on='UNTIL_REMOVED', data={'repeat_save': {'ability': 'CON', 'dc': 1, 'when': 'start'}}))
    commit(candidate(table, mid, 'Hold'))
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine = combat._load_session(mid).engine
    end = next(c for c in engine.legal_candidates() if c.display_name == 'End turn')
    automatic_action(combat, end.source_definition_id)
    assert table.auto_step(mid, 0)['status'] == 'COMMITTED'
    assert_reload_verify_replay(combat, mid, tmp_path)
    assert not any(c.condition_id == 'condition:typed.poisoned'
                   for c in combat._load_session(mid).engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('ai_turn', [False, True])
def test_discipline_ask_me_on_player_and_ai_turns(tmp_path, monkeypatch, ai_turn):
    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import ActionDefinition
    from tests.r10_fixup_support import fixed_dice

    def hazards(bundles):
        # A real fixture action imposes a Dexterity save. It has no damage or
        # side effects: the test isolates the rescue decision at the table.
        for bundle in bundles:
            actor_id = bundle['actor_id']
            action = ActionDefinition(
                source_definition_id='action:test.save_hazard.' + actor_id,
                display_name='Training hazard', owner_id=actor_id, economy='ACTION',
                resolution_kind='TYPED', target_kind='SELF' if actor_id == OWNER else 'HOSTILE_ENTITY',
                range_ft=30, parameters={'expected_damage': 0, 'typed': {
                    'effects': [{'type': 'save', 'ability': 'DEX',
                                 'applies_to': 'self' if actor_id == OWNER else 'target',
                                 'on_fail': [], 'on_success': []}],
                    'numbers': {'save_dc': 4}, 'duration': {'kind': 'instant'}, 'riders': []}})
            bundle['action_catalog'].append(action.model_dump(mode='json'))
            bundle['actor_template']['action_ids'].append(action.source_definition_id)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, mid, send, commit = fixture(tmp_path, [], seed=f'SOLF-D-{ai_turn}', path_features=[TEMPERED],
                                             primary='Stamina', bundle_transform=hazards)
    group = next(g for g in table.state(mid)['menu']['actions'] if 'Tempered Response: Dexterity' in g['label'])
    assert '1 Stamina' in group['description'] and 'once per round' in group['description']
    assert 'cannot replace' in group['description']
    commit(candidate(table, mid, 'Tempered Response: Dexterity'))
    assert_reload_verify_replay(combat, mid, tmp_path)
    combat, table, engine = cold(combat, mid, tmp_path)
    assert not any('defensive_discipline' in c.source_definition_id for c in engine.legal_candidates())
    if ai_turn:
        commit = lambda cid: table.act(mid, cid, table.state(mid)['menu']['decision_id'],
                                      table.state(mid)['menu']['state_version'], 0, [])
        assert commit(table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
        active = table.state(mid)['menu']['actor_id']
        combat.set_controller_mode(mid, actor_id=active, controller_mode='LOCAL_AUTO')
        automatic_action(combat, 'action:test.save_hazard.' + active)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')

    fixed_dice(monkeypatch, [1] * 20)
    menu = table.state(mid)['menu']
    cid = None if ai_turn else candidate(table, mid, 'Training hazard')

    def trigger(answers=()):
        return (table.auto_step(mid, 0, list(answers)) if ai_turn else
                table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers)))

    result = trigger()
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == OWNER
    assert prompt['reaction'] == 'Tempered Response'
    assert prompt['affected'] == 'Owner'
    assert prompt['action'] == 'Training hazard'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    assert trigger([{**prompt['context'], 'selection': 'USE'}])['status'] == 'COMMITTED'
    assert_reload_verify_replay(combat, mid, tmp_path)
    _, _, engine = cold(combat, mid, tmp_path)
    held = next(c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id.startswith('condition:typed.defensive_discipline:'))
    assert held.data['ability'] == 'DEX'
    # Rows are narrowed lazily before saves after a cold load. Verify the actual
    # committed rescue and its saved result, rather than an idle compiled default.
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == TEMPERED
               for e in engine.events)
    saved = next(e.payload for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED')
    assert saved['success'] is True


@pytest.mark.parametrize('data', [
    {'origin_save': {'ability': 'CON', 'dc': 1}},
    {'repeat_save': {'ability': 'CON', 'dc': 1}, 'ordinary_saves_cannot_remove': True},
    {'repeat_save': {'ability': 'CON', 'dc': 1, 'successes_required': 3}},
    {'repeat_save': {'ability': 'CON', 'dc': 1}, 'successes_required': 3, 'successes': 1},
])
def test_unknown_or_restricted_repeat_contract_is_not_spent_or_cured(data):
    engine, actor = _meridian_fight(dc=1)
    held = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.poisoned')
    held.data = data
    ext.run('turn_end', engine, actor)
    assert held.instance_id in actor.conditions and actor.resources[STAMINA] == 60


@pytest.mark.parametrize('disadvantage,mode', [(False, 'ADVANTAGE'), (True, 'NORMAL')])
def test_actual_paid_repeat_mode_and_cancellation(disadvantage, mode):
    engine, actor = _meridian_fight(dc=1)
    if disadvantage:
        engine._apply_condition(actor, 'condition:typed.test_save_penalty', 'test:penalty', actor.entity_id,
                                expires_on='UNTIL_REMOVED', data={'rule': {'save_mode': {'CON': 'DISADVANTAGE'}}})
    ext.run('turn_end', engine, actor)
    assert next(r for r in engine.rolls if r.reason.startswith('SAVE:passive:meridian_reinforcement')).mode == mode


def test_meridian_preserves_exhaustion_advantage_and_uncovered_progress():
    from combat.typed_reactions import rules
    engine, actor = _meridian_fight(dc=1)
    roll = engine._roll_save(actor, 'CON', 1, 'test:exertion', roll_context={'named': ['exhaustion']})
    assert roll.mode == 'ADVANTAGE'
    assert not any('multiple successful saves' in line or 'original effect would end' in line
                   for line in rules()['features'][MERIDIAN]['covers'])


def test_discipline_cannot_be_selected_on_later_turns_or_after_action():
    from tests import test_riders_c7 as C7

    engine = C7.fight(C7.bundle([TEMPERED], cl=1), foe=C7._typed_foe())
    actor = engine.state.actors[C7.ME]
    actor.turns_started = 1
    assert any('defensive_discipline' in c.source_definition_id for c in engine.legal_candidates())
    actor.action_available = False
    assert not any('defensive_discipline' in c.source_definition_id for c in engine.legal_candidates())
    actor.action_available = True
    actor.turns_started = 2
    assert not any('defensive_discipline' in c.source_definition_id for c in engine.legal_candidates())
