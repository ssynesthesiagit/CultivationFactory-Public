"""Smoke BASE regressions through accepted table actions and cold disk replay."""
import copy
import json
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark
from tests.h1_support import sheet
from tests import test_auto43r1f1_smoke_table as T

ROOT = Path(__file__).resolve().parents[1]
OWNER, FOE, OTHER = T.OWNER, T.FOE, 'actor:factory.smoke-other'
RESPONSE = 'SMOKE_BASE_SMOKE_RESPONSES'


def test_blind_line_compiled_help_includes_other_creatures_without_manual_ally_limit():
    """The compiled help must agree with the automated third-party trigger."""
    from combat.tabletop_service import _combat_preview

    bundle = compile_character(sheet([T.VEIL, *T.BASES], cl=5, primary='Stamina'),
                               actor_id=OWNER)
    assert any(row['feature_id'] == RESPONSE for row in bundle['typed_reactions'])
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    mechanic = authority['mechanics'][RESPONSE]
    riders = '\n'.join(mechanic['riders'])
    help_text = '\n'.join(_combat_preview(mechanic)['gm'])
    for text in (riders, help_text):
        assert 'only for attacks against you' not in text
        assert 'GM handles its use when an attack against an ally' not in text
    assert 'you or another creature' in riders
    # The distinct, still-manual sight exception must remain disclosed.
    assert 'does not rely on sight or can see clearly through smoke' in riders
    assert 'GM checks this exception' in riders


def fight(tmp_path, *, other_team='team:a', ask=True, ai=False, cap_fixture=False, foreign_veil=False):
    ids = [OWNER, FOE, OTHER]
    bundles = []
    for aid in ids:
        owned = [T.VEIL, *T.BASES] if aid == OWNER else ([T.VEIL] if aid == OTHER and foreign_veil else [])
        doc = sheet(owned, cl=1 if cap_fixture else 5, primary='Stamina')
        doc['identity']['display_name'] = {OWNER: 'Smoke Keeper', FOE: 'Archer', OTHER: 'Companion'}[aid]
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 300
        if cap_fixture:
            doc['identity']['proficiency_bonus'] = 2
        if aid == FOE and ai:
            doc['ability_scores_and_statistics']['speed'] = {'walking_ft': 1}
        bundle = compile_character(doc, actor_id=aid, reaction_plan={'ask': ask if aid == OWNER else False})
        if aid == FOE:
            # A real ranged attack sealed into the fixture's bundle before genesis.
            action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
            action.update(source_definition_id='action:test.smoke_arrow', display_name='Arrow',
                          economy='ACTION', target_kind='HOSTILE_ENTITY' if ai else 'ANY_CREATURE',
                          range_ft=20 if ai else 60, costs=[])
            action['parameters'] = {'typed': {'effects': [{'type': 'attack', 'attack_kind': 'ranged',
                'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['piercing']}]}],
                'numbers': {'attack_bonus': 50, 'cl': 5}, 'duration': {'kind': 'instant'}, 'riders': []},
                'expected_damage': 100}
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        if aid == OWNER and cap_fixture:
            # Evented fixture setup, representing two older traces. The third
            # placement is the character's native Place Smoke Trace action.
            native = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Place Smoke Trace')
            setup = copy.deepcopy(native)
            setup.update(source_definition_id='action:test.older_soot', display_name='Existing soot',
                         target_kind='ANY_CREATURE', range_ft=60)
            setup['parameters'] = {'free_primary': True, 'typed': {**native['parameters']['typed'], 'effects': [
                {'type': 'mark', 'mark': 'Smoke Trace', 'applies_to': 'self',
                 'duration': {'kind': 'until_end_of_your_next_turn'}},
                {'type': 'mark', 'mark': 'Smoke Trace', 'applies_to': 'target',
                 'duration': {'kind': 'until_end_of_your_next_turn'}}]}}
            bundle['action_catalog'].append(setup)
            bundle['actor_template']['action_ids'].append(setup['source_definition_id'])
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    arena = copy.deepcopy(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    arena['terrain_regions'] = []
    teams = {OWNER: 'team:a', FOE: 'team:b', OTHER: other_team}
    mid = combat._finish_factory_match(bundles, ids, teams,
        {OWNER: {'x': 2 if ai else 3, 'y': 6}, FOE: {'x': 7, 'y': 6}, OTHER: {'x': 3, 'y': 7}}, arena,
        [OWNER], [FOE, OTHER], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='MGR-T14-SMOKE', display_name='Smoke BASE regression', maximum_rounds=8)['match_id']
    table = TabletopService(combat, tmp_path)
    advance(combat, table, mid, OWNER)
    return combat, table, mid


def advance(combat, table, mid, aid):
    for _ in range(12):
        if combat._load_session(mid).engine.state.current_actor_id == aid:
            return
        T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('actor never got a turn')


def use(combat, table, mid, label, *, target=None, at=None, take=False):
    c = next(c for c in combat._load_session(mid).engine.legal_candidates() if label in c.display_name
             and (target is None or target in c.target_ids)
             and (at is None or c.destination and (c.destination.x, c.destination.y) == at))
    return T._commit(table, mid, c.candidate_id, take=take)


def reload(combat, mid, tmp_path):
    state = combat._load_session(mid).engine.state.model_dump(mode='json')
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json') == state
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


@pytest.mark.parametrize('target', [OWNER, OTHER], ids=['self', 'ally'])
@pytest.mark.parametrize('veil', [True, False])
@pytest.mark.parametrize('accept', [True, False])
def test_blind_line_other_attacked_creature_table_consent_spend_reload(tmp_path, target, veil, accept):
    combat, table, mid = fight(tmp_path)
    if veil:
        use(combat, table, mid, 'Smoke Veil at', at=(5, 6))
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.source_definition_id == 'action:test.smoke_arrow' and target in c.target_ids)
    state = table.state(mid)
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, state['last_sequence'])
    if veil:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['context']['reactor_id'] == OWNER
        # Uncommitted preview cannot spend the player's trace or Reaction.
        parked = reload(combat, mid, tmp_path)
        assert bears_mark(parked.state.actors[FOE], OWNER, 'Smoke Trace')
        answer = {**prompt['context'], 'selection': 'USE' if accept else 'DECLINE'}
        result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                           candidate.state_version, state['last_sequence'], [answer])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid, tmp_path)
    paid = veil and accept
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Smoke Trace') is (not paid)
    assert engine.state.actors[OWNER].reaction_available is (not paid)
    roll = next(r for r in reversed(engine.rolls) if r.actor_id == FOE and r.reason.startswith('ATTACK:'))
    assert roll.mode == ('DISADVANTAGE' if paid else 'NORMAL')
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == RESPONSE]
    assert len(resolved) == int(paid)


def test_blind_line_attack_on_another_enemy_is_not_an_ally_only_trigger(tmp_path):
    combat, table, mid = fight(tmp_path, other_team='team:b')
    use(combat, table, mid, 'Smoke Veil at', at=(5, 6))
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.source_definition_id == 'action:test.smoke_arrow' and OTHER in c.target_ids)
    state = table.state(mid)
    result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                       candidate.state_version, state['last_sequence'])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    answer = {**prompt['context'], 'selection': 'USE'}
    result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                       candidate.state_version, state['last_sequence'], [answer])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid, tmp_path)
    assert not bears_mark(engine.state.actors[FOE], OWNER, 'Smoke Trace')
    assert not engine.state.actors[OWNER].reaction_available
    roll = next(r for r in reversed(engine.rolls) if r.actor_id == FOE and r.reason.startswith('ATTACK:'))
    assert roll.mode == 'DISADVANTAGE'


@pytest.mark.parametrize('accept', [True, False])
def test_blind_line_off_turn_ai_attack_keeps_owner_decision(tmp_path, accept):
    combat, table, mid = fight(tmp_path, ai=True)
    use(combat, table, mid, 'Smoke Veil at', at=(5, 6))
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    state = table.state(mid)
    result = table.auto_step(mid, state['last_sequence'])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == OWNER
    assert prompt['affected'] == 'Companion'
    parked = reload(combat, mid, tmp_path)
    assert parked.state.actors[OWNER].reaction_available
    answer = {**prompt['context'], 'selection': 'USE' if accept else 'DECLINE'}
    result = table.auto_step(mid, state['last_sequence'], [answer])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid, tmp_path)
    assert engine.state.actors[OWNER].reaction_available is (not accept)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Smoke Trace') is (not accept)


def test_native_trace_cap_owner_selects_newer_mark_and_reload(tmp_path):
    combat, table, mid = fight(tmp_path, cap_fixture=True)
    use(combat, table, mid, 'Existing soot', target=OTHER)
    before = reload(combat, mid, tmp_path)
    assert bears_mark(before.state.actors[OWNER], OWNER, 'Smoke Trace')
    assert bears_mark(before.state.actors[OTHER], OWNER, 'Smoke Trace')
    candidate = next(c for c in before.legal_candidates()
                     if c.display_name == 'Place Smoke Trace' and FOE in c.target_ids)
    state = table.state(mid)
    result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                       candidate.state_version, state['last_sequence'])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert 'Smoke Trace' in prompt['moment'] and 'Archer' in prompt['moment']
    options = prompt['choice']['options']
    assert len(options) == 2
    newer = next(o['id'] for o in options if 'Companion' in o['label'])
    parked = reload(combat, mid, tmp_path)
    assert bears_mark(parked.state.actors[OTHER], OWNER, 'Smoke Trace')
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [newer]}
    result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                       candidate.state_version, state['last_sequence'], [answer])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid, tmp_path)
    assert bears_mark(engine.state.actors[OWNER], OWNER, 'Smoke Trace')
    assert not bears_mark(engine.state.actors[OTHER], OWNER, 'Smoke Trace')
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Smoke Trace')


def test_blind_line_another_owners_veil_cannot_qualify_attack(tmp_path):
    combat, table, mid = fight(tmp_path, foreign_veil=True)
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, OTHER)
    use(combat, table, mid, 'Smoke Veil at', at=(5, 6))
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.source_definition_id == 'action:test.smoke_arrow' and OWNER in c.target_ids)
    state = table.state(mid)
    result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                       candidate.state_version, state['last_sequence'])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid, tmp_path)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Smoke Trace')
    assert engine.state.actors[OWNER].reaction_available
