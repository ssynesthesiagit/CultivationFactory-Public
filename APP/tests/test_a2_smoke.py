"""A2SMOKE: accepted service intents, table choices and fresh-service reloads."""
import copy
from pathlib import Path
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import response_limits
from tests.h1_support import sheet
from tests import test_auto43r1f1_smoke_table as T

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = T.OWNER, T.FOE
VEIL = T.VEIL
CHOKE = 'TAL_SMOKE_BLACK_LUNG_CLOUD'
LUNG = 'TAL_SMOKE_ASHEN_LUNG_SEALS_THE_DRAGON_CRY'


def fight(tmp_path, talents, *, dc=50, physiology=None, voiced=True, technique='save', ask=False, sense=None, unperceiving=False):
    docs = [sheet([VEIL, *T.BASES, *talents], cl=15, dc=dc, primary='Stamina',
                  score=50 if 'TAL_SMOKE_ASHEN_BLINDFOLD' in talents else 14),
            sheet([], cl=15, dc=15, primary='Stamina')]
    if physiology is not None:
        docs[1]['identity']['physiology'] = {'breath_dependent': physiology}
    bundles = []
    for actor_id, doc in zip((ME, FOE), docs):
        doc['identity']['display_name'] = 'Smoke Keeper' if actor_id == ME else 'Fire Caller'
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 300
        bundle = compile_character(doc, actor_id=actor_id, reaction_plan={'ask': ask if actor_id == ME else False})
        # Test fixtures are sealed once before genesis, never runtime substitutions.
        if actor_id == FOE:
            if sense:
                bundle['senses'] = {'rows': [{'feature_id': 'test:printed-sense', 'sense': sense, 'range_ft': 60, 'when': 'always'}]}
            action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
            attack = {'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 2,
                      'on_hit': [{'type': 'damage', 'damage_types': ['fire'], 'flat': 2}]}
            save = {'type': 'save', 'ability': 'dex', 'on_fail': [{'type': 'damage', 'damage_types': ['fire'], 'flat': 2}], 'on_success': []}
            action.update(source_definition_id='action:test.voice', display_name='Declared Breath Technique',
                          economy='ACTION', target_kind='HOSTILE_ENTITY', range_ft=60,
                          costs=[['resource:core.stamina', 1]])
            action['parameters'] = {'typed': {'source': 'TAL_BERSERKER_RIFT_STRIKE' if unperceiving else 'test:breath', 'effects': [attack if technique == 'attack' else save],
                'requires_hearing': voiced and not unperceiving, 'numbers': {'cl': 15, 'pb': 5, 'save_dc': 15, 'attack_bonus': 50},
                'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 4}
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        if actor_id == ME and unperceiving:
            action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
            action.update(source_definition_id='action:test.blind_deaf', display_name='Lose sight and hearing',
                          economy='NONE', target_kind='SELF', costs=[], range_ft=None)
            action['parameters'] = {'typed': {'effects': [
                {'type': 'condition', 'condition': 'blinded', 'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'},
                {'type': 'condition', 'condition': 'deafened', 'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}],
                'numbers': {'cl': 15}, 'duration': {'kind': 'instant'}, 'riders': []}}
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    arena = copy.deepcopy(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    arena['terrain_regions'] = []
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME: 'team:a', FOE: 'team:b'},
        {ME: {'x': 3, 'y': 6}, FOE: {'x': 5, 'y': 6}}, arena, [ME], [FOE],
        control_modes={ME: 'MANUAL', FOE: 'MANUAL'}, match_seed='A2SMOKE-SERVICE',
        display_name='Smoke service regression', maximum_rounds=8)['match_id']
    table = TabletopService(combat, tmp_path)
    advance(combat, table, mid, ME)
    return combat, table, mid


def advance(combat, table, mid, actor):
    for _ in range(12):
        if combat._load_session(mid).engine.state.current_actor_id == actor:
            return
        T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('turn never arrived')


def candidate(combat, mid, label, *, at=None, target=None):
    return next(c for c in combat._load_session(mid).engine.legal_candidates()
        if label in c.display_name and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
        and (target is None or target in c.target_ids))


def use(combat, table, mid, label, *, at=None, target=None):
    c = candidate(combat, mid, label, at=at, target=target)
    return T._commit(table, mid, c.candidate_id, take=True)


def reload(combat, mid, tmp_path):
    live = combat._load_session(mid).engine.state.model_dump(mode='json')
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode='json') == live
    assert fresh.verify()['status'] == 'PASS'
    assert fresh.mechanical.replay()['status'] == 'PASS'
    assert not any('BAD' in e.event_type for e in fresh.engine.events)
    return fresh.engine


@pytest.mark.parametrize('breathes', [True, False])
@pytest.mark.parametrize('dc,failed', [(50, True), (-50, False)])
def test_choking_creation_physiology_outcome_and_expiry(tmp_path, breathes, dc, failed):
    combat, table, mid = fight(tmp_path, [CHOKE], dc=dc, physiology=breathes)
    use(combat, table, mid, 'Black-Lung Cloud', at=(5, 6))
    engine = reload(combat, mid, tmp_path)
    assert not any(r.actor_id == FOE and r.reason.startswith('SAVE:') for r in engine.rolls)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    engine = reload(combat, mid, tmp_path)
    rolls = [r for r in engine.rolls if r.actor_id == FOE and r.reason.startswith('SAVE:')]
    assert rolls and rolls[-1].mode == ('NORMAL' if breathes else 'ADVANTAGE')
    foe = engine.state.actors[FOE]
    assert any(c.condition_id == 'condition:typed.poisoned' for c in foe.conditions.values()) is failed
    assert engine._effective_speed(foe) == (foe.speed_ft if failed else max(0, foe.speed_ft - 10))
    # Each subsequent owner's nominal start retires choking but keeps the veil.
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, ME)
    engine = reload(combat, mid, tmp_path)
    zone, = [z for z in engine.state.zones.values() if z.active]
    assert 'smoke_choking_until_owner_turn' not in zone.trigger_profile


@pytest.mark.parametrize('paid', [False, True])
def test_moving_veil_optional_choking_cost_and_reload(tmp_path, paid):
    combat, table, mid = fight(tmp_path, [CHOKE])
    use(combat, table, mid, 'Smoke Veil at', at=(5, 6))
    before = reload(combat, mid, tmp_path).state.actors[ME].resources['resource:core.stamina']
    label = 'move and choke' if paid else 'Smoke Veil: move it'
    use(combat, table, mid, label, at=(6, 6))
    engine = reload(combat, mid, tmp_path)
    zone, = [z for z in engine.state.zones.values() if z.active]
    assert (zone.center.x, zone.center.y) == (6, 6)
    assert bool(zone.trigger_profile.get('smoke_choking_until_owner_turn')) is paid
    assert engine.state.actors[ME].resources['resource:core.stamina'] == before - int(paid)


def test_paid_movement_help_survives_service_execution_and_cold_reload(tmp_path):
    combat, table, mid = fight(tmp_path, [CHOKE])
    use(combat, table, mid, 'Smoke Veil at', at=(5, 6))
    reload(combat, mid, tmp_path)
    for service in (combat, CombatService(ROOT, tmp_path)):
        menu = TabletopService(service, tmp_path).state(mid)['menu']
        group = next(g for g in menu['actions'] if 'move and choke' in g['label'])
        help_text = group['description']
        for phrase in ('Bonus Action', '1 Stamina', 'Constitution saving throw',
                       'Poisoned on a failure', 'Speed reduced by 10 feet on a success',
                       "either result lasts until that creature's next turn starts",
                       'first entry each turn', 'Advantage'):
            assert phrase in help_text
        assert 'CP' not in help_text
    # TabletopService commits through the session's execute_intent path.
    use(combat, table, mid, 'move and choke', at=(6, 6))
    reload(combat, mid, tmp_path)


@pytest.mark.parametrize('dc,failed', [(50, True), (-50, False)])
@pytest.mark.parametrize('technique', ['save', 'attack'])
def test_dragon_cry_pending_technique_paid_failure_or_scoped_success(tmp_path, dc, failed, technique):
    combat, table, mid = fight(tmp_path, [LUNG], dc=dc, technique=technique)
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    engine = reload(combat, mid, tmp_path)
    owner_cp = engine.state.actors[ME].resources['resource:core.stamina']
    caster_cp = engine.state.actors[FOE].resources['resource:core.stamina']
    # Explicit session intent as well as the table/service setups above.
    session = combat._load_session(mid)
    c = candidate(combat, mid, 'Declared Breath Technique', target=ME)
    session.submit_intent(ActionIntent(intent_id=f'a2-cry:{session.engine.state.state_version}',
        actor_id=c.actor_id, decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids),
        primary_decision_record=None, reaction_provider=None)
    engine = reload(combat, mid, tmp_path)
    assert engine.state.actors[ME].resources['resource:core.stamina'] == owner_cp - 5
    assert engine.state.actors[FOE].resources['resource:core.stamina'] == caster_cp - 1
    rolls = [r for r in engine.rolls if 'action:test.voice' in r.reason and (r.reason.startswith('SAVE:') or r.reason.startswith('ATTACK:'))]
    if failed:
        assert not rolls
    else:
        modes = [r.mode for r in rolls]
        assert modes and set(modes) == {'ADVANTAGE' if technique == 'save' else 'DISADVANTAGE'}
        assert not any(c.condition_id.endswith('pending_technique_modes') for c in engine.state.actors[FOE].conditions.values())
    assert engine.state.actors[ME].reaction_available is False
    # The next use after the owner's turn gets no policy from this activation.
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, ME)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    prior = len(combat._load_session(mid).engine.rolls)
    use(combat, table, mid, 'Declared Breath Technique', target=ME)
    engine = reload(combat, mid, tmp_path)
    assert all(r.mode == 'NORMAL' for r in engine.rolls[prior:] if 'action:test.voice' in r.reason)


def test_unvoiced_technique_does_not_trigger_dragon_cry(tmp_path):
    combat, table, mid = fight(tmp_path, [LUNG], voiced=False)
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    before = combat._load_session(mid).engine.state.actors[ME].resources['resource:core.stamina']
    use(combat, table, mid, 'Declared Breath Technique', target=ME)
    engine = reload(combat, mid, tmp_path)
    assert engine.state.actors[ME].resources['resource:core.stamina'] == before
    assert engine.state.actors[ME].reaction_available


def test_response_group_shared_by_bonus_action_and_reaction(tmp_path):
    combat, table, mid = fight(tmp_path, [T.BLACKEN])
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    use(combat, table, mid, 'Follow the Soot', target=FOE)
    engine = reload(combat, mid, tmp_path)
    assert not response_limits.available(engine, engine.state.actors[ME], 'smoke')
    from combat import typed_reactions
    from combat.ext.fight_ownership import block_rows
    row = block_rows(engine, engine.state.actors[ME], 'smoke_fire_soot')[0]
    assert not typed_reactions.can_use_reaction(engine, engine.state.actors[ME], engine.state.actors[FOE], row)
    assert engine.state.actors[ME].reaction_available  # allowance is separate from Reaction economy
    for _ in range(3):
        if combat._load_session(mid).engine.state.round_number > engine.state.round_number:
            break
        T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    new = reload(combat, mid, tmp_path)
    assert response_limits.available(new, new.state.actors[ME], 'smoke')
    assert not any(c.condition_id == response_limits.CONDITION for c in new.state.actors[ME].conditions.values())


@pytest.mark.parametrize('accept', [False, True])
def test_dragon_cry_player_consent_names_actual_action_and_preserves_declined_cost(tmp_path, accept):
    combat, table, mid = fight(tmp_path, [LUNG], ask=True)
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    before = combat._load_session(mid).engine.state.actors[ME].resources['resource:core.stamina']
    c = candidate(combat, mid, 'Declared Breath Technique', target=ME)
    state = table.state(mid)
    result = table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'])
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert 'Fire Caller' in prompt['moment'] and 'Declared Breath Technique' in prompt['moment']
    assert 'Reaction' in prompt['moment'] and '5' in prompt['moment']
    parked = reload(combat, mid, tmp_path)
    assert parked.state.actors[ME].resources['resource:core.stamina'] == before
    answer = T._answer(prompt, take=accept)
    result = table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], [answer])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid, tmp_path)
    assert engine.state.actors[ME].resources['resource:core.stamina'] == before - (5 if accept else 0)
    assert engine.state.actors[ME].reaction_available is (not accept)


@pytest.mark.parametrize('dc,failed', [(50, True), (-50, False)])
@pytest.mark.parametrize('sense', [None, 'blindsight', 'truesight', 'tremorsense'])
def test_ashen_blindfold_scoped_sight_senses_next_attack_and_expiry(tmp_path, dc, failed, sense):
    from combat import senses, zones
    combat, table, mid = fight(tmp_path, ['TAL_SMOKE_ASHEN_BLINDFOLD'], dc=dc,
                                technique='attack', voiced=False, sense=sense)
    use(combat, table, mid, 'Smoke Veil at', at=(3, 6))
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    use(combat, table, mid, 'Declared Breath Technique', target=ME)
    engine = reload(combat, mid, tmp_path)
    foe, owner = engine.state.actors[FOE], engine.state.actors[ME]
    restricted = any(c.condition_id == 'condition:typed.zone_view_restriction' for c in foe.conditions.values())
    # The keeper's strong CON holds concentration across both test attacks.
    assert restricted is failed
    assert senses.perceives(engine, foe, owner) is (not failed or sense in ('blindsight', 'truesight'))
    assert senses.perceives(engine, owner, foe)  # restriction belongs to the attacker
    from combat.gate2_runtime_models import Position
    assert senses.perceives_cell(engine, foe, Position(x=10, y=6))  # ray away from the caster's veil
    assert senses.perceives_cell(engine, foe, Position(x=3, y=6, z=4))  # ray above the cube
    if sense == 'tremorsense':
        assert senses.pinpoints(engine, foe, owner)
    rolls = [r for r in engine.rolls if r.actor_id == FOE and r.reason.startswith('ATTACK:')]
    assert len(rolls) == 2
    if failed and sense not in ('blindsight', 'truesight'):
        assert rolls[-1].mode == 'DISADVANTAGE'
    assert all(z.trigger_profile.get('obscured') == 'light' for z in engine.state.zones.values() if z.active)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, ME)
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    engine = reload(combat, mid, tmp_path)
    assert not any(c.condition_id == 'condition:typed.zone_view_restriction' for c in engine.state.actors[FOE].conditions.values())
    assert senses.perceives(engine, engine.state.actors[FOE], engine.state.actors[ME])



def test_dragon_cry_cannot_answer_an_unperceived_declaration(tmp_path):
    combat, table, mid = fight(tmp_path, [LUNG], unperceiving=True)
    use(combat, table, mid, 'Place Smoke Trace', target=FOE)
    use(combat, table, mid, 'Lose sight and hearing')
    engine = reload(combat, mid, tmp_path)
    from combat.typed_executor import cant_hear
    from combat import senses
    assert cant_hear(engine.state.actors[ME])
    assert not senses.perceives(engine, engine.state.actors[ME], engine.state.actors[FOE])
    before = engine.state.actors[ME].resources['resource:core.stamina']
    T._commit(table, mid, table.state(mid)['menu']['end_turn'])
    advance(combat, table, mid, FOE)
    use(combat, table, mid, 'Declared Breath Technique', target=ME)
    engine = reload(combat, mid, tmp_path)
    assert engine.state.actors[ME].resources['resource:core.stamina'] == before
    assert engine.state.actors[ME].reaction_available
