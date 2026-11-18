"""A2GBODSUB3: printed subpath effects through service commits and cold reload.

Synthetic sealed actions create combat triggers (Prone, named spiritual saves,
physical/magical holds), but all feature execution uses the shipped plug-ins.
"""
import copy
import pytest

from combat.canonical import canonical_sha256
from combat.flight import profile
from combat import posture
from combat.gate5_service import CombatService
from tests.worker2_support import fixture, candidate, reload, OWNER, ALLY, FOE
from tests.test_r9i_karma_persistence import act
from tests.hunt12_support import hit_dice

PREFIX = 'tianxia.subpath.body.'
IRON = 'tianxia.path.body_refining.feature.iron_fist'
STAMINA = 'resource:core.stamina'


def seal(bundle, name, effects, *, target='SELF', economy='NONE', numbers=None):
    source = 'action:test.a2bod3.' + bundle['actor_id'].rsplit('.', 1)[-1] + '.' + name.lower().replace(' ', '_')
    row = {'source_definition_id': source, 'display_name': name, 'owner_id': bundle['actor_id'],
           'economy': economy, 'resolution_kind': 'TYPED', 'target_kind': target,
           'range_ft': 120 if target != 'SELF' else None, 'parameters': {
               'player_only': True, 'typed': {'source': source, 'effects': copy.deepcopy(effects),
               'numbers': numbers or {'cl': 18, 'pb': 6, 'save_dc': 50, 'attack_bonus': 100, 'key_mod': 4},
               'duration': {'kind': 'instant'}, 'riders': []}}, 'costs': []}
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def setups(bundles):
    for bundle in bundles:
        seal(bundle, 'Test Prone', [{'type': 'condition', 'applies_to': 'self', 'condition': 'prone', 'duration': 'until_removed'}])
        for category in ('possession', 'forced_transformation', 'soul_affecting', 'unwilling_teleportation', 'ordinary'):
            seal(bundle, 'Test Save ' + category, [{'type': 'save', 'ability': 'cha',
                 'save_categories': [] if category == 'ordinary' else [category],
                 'on_fail': [{'type': 'damage', 'applies_to': 'target', 'flat': 1, 'damage_types': ['psychic']}]}], target='HOSTILE_ENTITY')
        for physical in (False, True):
            condition = {'type': 'condition', 'condition': 'grappled', 'duration': 'until_removed'}
            if physical:
                condition['hold_kind'] = 'ordinary_physical'
            seal(bundle, 'Test Hold ' + ('physical' if physical else 'magical'),
                 [{'type': 'save', 'ability': 'con', 'on_fail': [condition]}], target='HOSTILE_ENTITY')


def start(tmp_path, features, **kw):
    bundle_transform = kw.pop('bundle_transform', setups)
    return fixture(tmp_path, [], owner_features=[IRON, *features], cl=18, primary='Stamina',
                   owner_path='Body Refining', bundle_transform=bundle_transform, owner_dc=50,
                   foe_position={'x': 5, 'y': 6}, **kw)


def commit(table, mid, cid, picks=None, reactions=(), movement=None, seen=None):
    answers = []
    for _ in range(35):
        if movement is None:
            result = act(table, mid, cid, answers)
        else:
            state = table.state(mid); menu = state['menu']
            result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'],
                answers, movement_path=[p.model_dump(mode='json') for p in movement], movement_mode='walk', actor_id=OWNER)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result
        p = result['reaction']; rid = p['context']['reaction_source_id']
        if seen is not None:
            seen.append(rid)
        choice = (picks or {}).get(rid, 'first' if rid.startswith('choice:') else None)
        if any(key in rid for key in reactions):
            choice = 'first'
        answer = {**p['context'], 'selection': 'USE' if choice is not None and choice != 'decline' else 'DECLINE'}
        if choice is not None and choice != 'decline' and p.get('choice'):
            answer['option_ids'] = [p['choice']['options'][0]['id']] if choice == 'first' else list(choice)
        answers.append(answer)
    raise AssertionError('Too many choices')


def use(combat, table, mid, name, **kw):
    c = candidate(combat, mid, name, **kw)
    commit(table, mid, c.candidate_id)
    return c


def turn(table, mid, actor, picks=None):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return
        commit(table, mid, table.state(mid)['menu']['end_turn'], picks)
    raise AssertionError('No turn')


def moves(combat, mid, at):
    engine = combat._load_session(mid).engine
    return [c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination
            and (c.destination.x, c.destination.y, c.destination.z) == at]


@pytest.mark.parametrize('group,feature,name,speed,cost', [
    ('kensei', 'sword_saint_incarnation', 'Sword Saint Incarnation', 40, 7),
    ('kukishin', 'hollow_step', 'Hollow Step', 30, 3),
    ('kukishin', 'hollow_immortal', 'Hollow Immortal', 40, 7),
])
def test_native_flight_and_hover_survive_real_move_and_cold_reload(tmp_path, group, feature, name, speed, cost):
    combat, table, mid = start(tmp_path, [PREFIX + group + '.feature.' + feature])
    before = combat._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    use(combat, table, mid, name)
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    assert profile(engine, owner).speed_ft == speed and profile(engine, owner).hover
    assert owner.resources[STAMINA] == before - cost
    rows = moves(combat, mid, (3, 6, 1)); assert rows
    commit(table, mid, rows[0].candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.z == 1
    assert profile(engine, engine.state.actors[OWNER]).hover
    if feature == 'hollow_step':
        turn(table, mid, FOE); turn(table, mid, OWNER)
        engine = reload(tmp_path, mid)
        assert profile(engine, engine.state.actors[OWNER]).speed_ft == 0
        assert engine.state.actors[OWNER].position.z == 0


@pytest.mark.parametrize('group,feature,name', [
    ('kensei', 'sword_saint_incarnation', 'Sword Saint Incarnation'),
    ('kukishin', 'hollow_step', 'Hollow Step'),
    ('kukishin', 'hollow_immortal', None),
    ('shinobi', 'vanishing_flesh', 'Vanishing Flesh'),
])
def test_creature_passage_costs_double_and_forbids_occupied_endpoint(tmp_path, group, feature, name):
    combat, table, mid = start(tmp_path, [PREFIX + group + '.feature.' + feature],
        extra_allies=1, positions={OWNER: {'x': 0, 'y': 0}, ALLY: {'x': 0, 'y': 1},
            FOE: {'x': 1, 'y': 0}, 'actor:factory.worker2-ally3': {'x': 1, 'y': 1}})
    if name:
        use(combat, table, mid, name)
    assert not moves(combat, mid, (1, 0, 0))
    # Submit a player's explicit walking route, even when flight offers a shortcut.
    from combat.gate2_runtime_models import Position
    from combat.movement_routes import explicit_candidate
    engine = combat._load_session(mid).engine
    path = (Position(x=0, y=0), Position(x=1, y=0), Position(x=2, y=0))
    row = explicit_candidate(engine, OWNER, path, 'walk')
    assert row.movement_cost_ft == 15
    before = engine.state.actors[OWNER].movement_remaining_ft
    commit(table, mid, row.candidate_id, movement=path)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.x == 2
    assert engine.state.actors[OWNER].movement_remaining_ft == before - 15



def test_root_serpent_stands_for_five_feet(tmp_path):
    combat, table, mid = start(tmp_path, [PREFIX + 'seven_coiled_serpent_spine.feature.first_and_second_coils'])
    turn(table, mid, FOE)
    turn(table, mid, OWNER, {'choice:needle.serpent_coils': ['1']})
    use(combat, table, mid, 'Test Prone')
    engine = reload(tmp_path, mid); before = engine.state.actors[OWNER].movement_remaining_ft
    c = next(c for c in combat._load_session(mid).engine.legal_candidates()
             if c.source_definition_id == 'system:combat.stand_up')
    assert c.metadata['standing_cost_ft'] == 5
    commit(table, mid, c.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].movement_remaining_ft == before - 5
    assert not any(c.condition_id.endswith('.prone') for c in engine.state.actors[OWNER].conditions.values())


def test_seventh_coil_native_fly_speed_tracks_doubled_walking_speed(tmp_path):
    combat, table, mid = start(tmp_path, [PREFIX + 'seven_coiled_serpent_spine.feature.seventh_coil_heaven_swallowing_serpent'])
    turn(table, mid, FOE)
    turn(table, mid, OWNER, {'choice:needle.serpent_coils': ['7']})
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    assert profile(engine, owner).speed_ft == engine._effective_speed(owner) == 80
    rows = moves(combat, mid, (3, 6, 1)); assert rows
    commit(table, mid, rows[0].candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].position.z == 1


@pytest.mark.parametrize('category,mode', [('possession', 'ADVANTAGE'), ('forced_transformation', 'ADVANTAGE'),
                                         ('unwilling_teleportation', 'ADVANTAGE'), ('ordinary', 'NORMAL'),
                                         ('soul_affecting', 'NORMAL')])
def test_hollow_immortal_save_advantage_is_source_scoped(tmp_path, category, mode):
    combat, table, mid = start(tmp_path, [PREFIX + 'kukishin.feature.hollow_immortal'])
    turn(table, mid, FOE)
    use(combat, table, mid, 'Test Save ' + category, target=OWNER)
    engine = reload(tmp_path, mid)
    rolls = [r for r in engine.rolls if r.actor_id == OWNER and str(r.reason).startswith('SAVE:')]
    assert rolls and rolls[-1].mode == mode


@pytest.mark.parametrize('physical', [False, True])
def test_empty_world_only_rejects_physical_holds(tmp_path, monkeypatch, physical):
    hit_dice(monkeypatch, save_roll=1)
    combat, table, mid = start(tmp_path, [PREFIX + 'kukishin.feature.hollow_immortal'])
    use(combat, table, mid, 'Hollow Immortal')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Test Hold ' + ('physical' if physical else 'magical'), target=OWNER)
    engine = reload(tmp_path, mid)
    held = any(c.condition_id.endswith('.grappled') for c in engine.state.actors[OWNER].conditions.values())
    assert held is (not physical)


def attack_setups(bundles):
    setups(bundles)
    for bundle in bundles:
        for hit in (False, True):
            seal(bundle, 'Test Attack ' + ('hit' if hit else 'miss'), [{'type': 'attack', 'attack_kind': 'unarmed',
                'on_hit': [{'type': 'damage', 'applies_to': 'target', 'flat': 1, 'damage_types': ['bludgeoning']}]}],
                target='HOSTILE_ENTITY', numbers={'cl': 18, 'pb': 6, 'save_dc': 50, 'attack_bonus': 100 if hit else -100, 'key_mod': 4})


def attack_start(tmp_path, features):
    return fixture(tmp_path, [], owner_features=[IRON, *features], cl=18, primary='Stamina',
                   owner_path='Body Refining', bundle_transform=attack_setups, owner_dc=50,
                   positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 7}, FOE: {'x': 4, 'y': 6}})


def test_flowing_blade_step_is_available_after_an_off_turn_reaction_hit(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = attack_start(tmp_path, [PREFIX + 'kensei.feature.flowing_blade_stance'])
    use(combat, table, mid, 'Flowing Blade Stance')
    turn(table, mid, FOE)
    c = candidate(combat, mid, 'Test Attack miss', target=OWNER)
    commit(table, mid, c.candidate_id, {'choice:needle.flowing_blade_step': ['cell:3,5']})
    engine = reload(tmp_path, mid); owner = engine.state.actors[OWNER]
    assert (owner.position.x, owner.position.y) == (3, 5)
    assert not owner.reaction_available
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER for e in engine.events)


def test_hollow_step_normalized_procedure_consumes_both_benefits_on_a_miss(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = attack_start(tmp_path, [PREFIX + 'kukishin.feature.hollow_step'])
    use(combat, table, mid, 'Hollow Step')
    turn(table, mid, FOE); turn(table, mid, OWNER)
    use(combat, table, mid, 'Test Attack miss', target=FOE)
    engine = reload(tmp_path, mid)
    miss = [r for r in engine.rolls if str(r.reason).startswith('ATTACK') and r.actor_id == OWNER][-1]
    assert miss.mode == 'ADVANTAGE'
    assert not any(c.condition_id == 'condition:typed.hollow_step_strike' for c in engine.state.actors[OWNER].conditions.values())
    use(combat, table, mid, 'Test Attack hit', target=FOE)
    engine = reload(tmp_path, mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('ATTACK') and r.actor_id == OWNER][-1].mode == 'NORMAL'
    assert not any(e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER and '2d8' in str(e.payload.get('expression')) for e in engine.events)
    assert not any(c.condition_id == 'condition:typed.hollow_step_strike' for c in engine.state.actors[OWNER].conditions.values())


def test_empty_strike_spiritual_penalty_waits_for_a_qualifying_save(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = attack_start(tmp_path, [PREFIX + 'kukishin.feature.empty_strike'])
    c = candidate(combat, mid, 'Test Attack hit', target=FOE)
    # Printed paid-hit transport owns this choice; use the fourth option's ID.
    result = act(table, mid, c.candidate_id, [])
    answers = []
    for _ in range(20):
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        p = result['reaction']; options = p.get('choice', {}).get('options', [])
        option = next((o['id'] for o in options if 'possession' in o['label'].lower()), options[0]['id'] if options else None)
        answer = {**p['context'], 'selection': 'USE'}
        if options:
            answer['option_ids'] = [option]
        answers.append(answer)
        result = act(table, mid, c.candidate_id, answers)
    assert result['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.empty_strike_spiritual_save' for c in engine.state.actors[FOE].conditions.values())
    use(combat, table, mid, 'Test Save ordinary', target=FOE)
    engine = reload(tmp_path, mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('SAVE') and r.actor_id == FOE][-1].mode == 'NORMAL'
    assert any(c.condition_id == 'condition:typed.empty_strike_spiritual_save' for c in engine.state.actors[FOE].conditions.values())
    use(combat, table, mid, 'Test Save possession', target=FOE)
    engine = reload(tmp_path, mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('SAVE') and r.actor_id == FOE][-1].mode == 'DISADVANTAGE'
    assert not any(c.condition_id == 'condition:typed.empty_strike_spiritual_save' for c in engine.state.actors[FOE].conditions.values())


def test_empty_strike_penalizes_shipped_soul_severance_after_reload(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = attack_start(tmp_path, [PREFIX + 'kukishin.feature.empty_strike',
                                                  PREFIX + 'kukishin.feature.soul_severance'])
    c = candidate(combat, mid, 'Test Attack hit', target=FOE)
    result = act(table, mid, c.candidate_id, [])
    answers = []
    for _ in range(20):
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        options = prompt.get('choice', {}).get('options', [])
        option = next((item['id'] for item in options if 'possession' in item['label'].lower()),
                      options[0]['id'] if options else None)
        answer = {**prompt['context'], 'selection': 'USE'}
        if options:
            answer['option_ids'] = [option]
        answers.append(answer)
        result = act(table, mid, c.candidate_id, answers)
    assert result['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    saves = [roll for roll in engine.rolls if str(roll.reason).startswith('SAVE') and roll.actor_id == FOE]
    assert saves and saves[-1].mode == 'DISADVANTAGE'
    assert not any(c.condition_id == 'condition:typed.empty_strike_spiritual_save'
                   for c in engine.state.actors[FOE].conditions.values())


def test_phase_flesh_passage_remains_after_damage_reaction_and_reload(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = attack_start(tmp_path, [PREFIX + 'kukishin.feature.phase_flesh'])
    turn(table, mid, FOE)
    c = candidate(combat, mid, 'Test Attack hit', target=OWNER)
    commit(table, mid, c.candidate_id, reactions=('phase_flesh',))
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.phase_flesh' for c in engine.state.actors[OWNER].conditions.values())
    from combat.creature_passage import permission
    assert permission(engine, engine.state.actors[OWNER], engine.state.actors[FOE]) == 'difficult'


def test_shelter_standing_benefit_chooses_allied_recipients(tmp_path):
    combat, table, mid = start(tmp_path, [PREFIX + 'vermilion_gate_guardian_body.feature.guardian_at_the_gate',
        PREFIX + 'vermilion_gate_guardian_body.feature.shelter_behind_the_gate'])
    picks = {'choice:needle.threshold_orientation': ['north_south'],
             'choice:needle.threshold_center': ['cell:4,6']}
    turn(table, mid, FOE)
    turn(table, mid, OWNER, picks)
    turn(table, mid, FOE, picks)
    assert combat._load_session(mid).engine.state.actors[OWNER].turn_flags['_round_gate_thresholds'] == [[4, 5, 4, 7]]
    # Both are near the owner threshold, but the enemy gets no standing benefit.
    use(combat, table, mid, 'Test Prone')
    engine = reload(tmp_path, mid)
    enemy = next(c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.stand_up')
    assert enemy.metadata['standing_cost_ft'] == 15
    commit(table, mid, enemy.candidate_id)
    turn(table, mid, ALLY, picks)
    use(combat, table, mid, 'Test Prone')
    engine = reload(tmp_path, mid)
    ally = next(c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.stand_up')
    assert ally.metadata['standing_cost_ft'] == 5
    commit(table, mid, ally.candidate_id)
    assert any(e.event_type == 'STOOD_UP' and e.actor_id == ALLY and e.payload['cost_ft'] == 5 for e in reload(tmp_path, mid).events)


@pytest.mark.parametrize('answer,fallback,expected', [
    ('decline', 'confirm', 15), ('decline', 'decline', None), ('first', None, 5)])
def test_shelter_standing_waits_for_owner_decision_and_replays(tmp_path, answer, fallback, expected):
    combat, table, mid = start(tmp_path, [PREFIX + 'vermilion_gate_guardian_body.feature.guardian_at_the_gate',
        PREFIX + 'vermilion_gate_guardian_body.feature.shelter_behind_the_gate'])
    picks = {'choice:needle.threshold_orientation': ['north_south'],
             'choice:needle.threshold_center': ['cell:4,6']}
    turn(table, mid, FOE)
    turn(table, mid, OWNER, picks)
    turn(table, mid, FOE, picks)
    turn(table, mid, ALLY, picks)
    use(combat, table, mid, 'Test Prone')
    engine = reload(tmp_path, mid)
    candidate_stand = next(c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.stand_up')
    assert candidate_stand.metadata['standing_cost_ft'] == 5  # pure preview remains answer-free
    assert candidate_stand.metadata['standing_ordinary_cost_ft'] == 15
    assert candidate_stand.metadata['standing_discount_conditional'] is True
    prompted = []
    choices = {'choice:gate.shelter_standing': answer}
    if fallback is not None:
        choices['choice:combat.standing_fallback'] = ['confirm'] if fallback == 'confirm' else fallback
    result = commit(table, mid, candidate_stand.candidate_id,
                    picks=choices, seen=prompted)
    assert result['status'] == 'COMMITTED'
    fresh = reload(tmp_path, mid)
    stood = [e for e in fresh.events if e.event_type == 'STOOD_UP' and e.actor_id == ALLY]
    if expected is None:
        assert not stood
        assert fresh.state.actors[ALLY].movement_remaining_ft == 30
        assert posture.prone_conditions(fresh.state.actors[ALLY])
    else:
        assert stood and stood[-1].payload['cost_ft'] == expected
    assert 'choice:gate.shelter_standing' in prompted
    if fallback is not None:
        assert 'choice:combat.standing_fallback' in prompted



@pytest.mark.parametrize('answer,stands', [('first', True), ('decline', False)])
def test_shelter_low_budget_menu_and_standing_survive_service_reload(tmp_path, answer, stands):
    combat, table, mid = start(tmp_path, [PREFIX + 'vermilion_gate_guardian_body.feature.guardian_at_the_gate',
        PREFIX + 'vermilion_gate_guardian_body.feature.shelter_behind_the_gate'])
    picks = {'choice:needle.threshold_orientation': ['north_south'],
             'choice:needle.threshold_center': ['cell:4,6']}
    turn(table, mid, FOE)
    turn(table, mid, OWNER, picks)
    turn(table, mid, FOE, picks)
    turn(table, mid, ALLY, picks)
    # Spend 25 feet through accepted service move intents, staying by the Gate.
    # No persisted actor state or movement allowance is patched.
    for y in (7, 6, 7, 6, 7):
        move = moves(combat, mid, (4, y, 0))
        assert move and move[0].movement_cost_ft == 5
        commit(table, mid, move[0].candidate_id)
    use(combat, table, mid, 'Test Prone')
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert ally.movement_remaining_ft == 5 and posture.prone_conditions(ally)
    # Render the actual table menu from a fresh service, not just candidate metadata.
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    menu = table.state(mid)['menu']
    stand = next(row for row in menu['actions'] if row['source_definition_id'] == posture.SOURCE)
    assert stand['cost_label'] == ('Movement only — 5 ft with the owner’s approval; '
        'you have 5 ft left and cannot pay the ordinary 15 ft cost; no Action')
    prompted = []
    before_sequence = max(e.sequence for e in engine.events)
    commit(table, mid, stand['options'][0]['candidate_id'],
           picks={'choice:gate.shelter_standing': answer}, seen=prompted)
    assert prompted == ['choice:gate.shelter_standing']
    fresh = reload(tmp_path, mid)  # includes mechanical replay of the saved journal
    ally = fresh.state.actors[ALLY]
    assert ally.movement_remaining_ft == (0 if stands else 5)
    assert bool(posture.prone_conditions(ally)) is (not stands)
    events = [e for e in fresh.events if e.sequence > before_sequence and e.actor_id == ALLY]
    stood = [e for e in events if e.event_type == 'STOOD_UP']
    removed = [e for e in events if e.event_type == 'CONDITION_REMOVED'
               and e.payload.get('checkpoint') == 'STAND_UP']
    assert len(stood) == len(removed) == int(stands)
    if stands:
        assert stood[0].payload['cost_ft'] == 5
        assert stood[0].payload['movement_before'] == 5
        assert stood[0].payload['movement_after'] == 0


def _standing_fixture_with_ally_prone_action(bundles):
    setups(bundles)
    seal(bundles[2], 'Test Prone Ally', [{'type': 'condition', 'applies_to': 'target',
         'condition': 'prone', 'duration': 'until_removed'}], target='HOSTILE_ENTITY')


def test_manual_gate_owner_can_decline_during_ai_ally_turn_start(tmp_path):
    combat, table, mid = start(tmp_path, [PREFIX + 'vermilion_gate_guardian_body.feature.guardian_at_the_gate',
        PREFIX + 'vermilion_gate_guardian_body.feature.shelter_behind_the_gate'],
        bundle_transform=_standing_fixture_with_ally_prone_action)
    picks = {'choice:needle.threshold_orientation': ['north_south'],
             'choice:needle.threshold_center': ['cell:4,6']}
    turn(table, mid, FOE)
    turn(table, mid, OWNER, picks)
    turn(table, mid, FOE, picks)
    use(combat, table, mid, 'Test Prone Ally', target=ALLY)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    prompted = []
    commit(table, mid, table.state(mid)['menu']['end_turn'],
           picks={'choice:gate.shelter_standing': 'decline'}, seen=prompted)
    engine = reload(tmp_path, mid)
    stood = [e for e in engine.events if e.event_type == 'STOOD_UP' and e.actor_id == ALLY]
    assert stood and stood[-1].payload['cost_ft'] == 15
    assert 'choice:gate.shelter_standing' in prompted
    assert table.state(mid)['menu']['actor_id'] == ALLY


def test_ai_gate_owner_automatically_accepts_perceived_ally_standing_benefit(tmp_path):
    combat, table, mid = start(tmp_path, [PREFIX + 'vermilion_gate_guardian_body.feature.guardian_at_the_gate',
        PREFIX + 'vermilion_gate_guardian_body.feature.shelter_behind_the_gate'])
    picks = {'choice:needle.threshold_orientation': ['north_south'],
             'choice:needle.threshold_center': ['cell:4,6']}
    turn(table, mid, FOE)
    turn(table, mid, OWNER, picks)
    turn(table, mid, FOE, picks)
    turn(table, mid, ALLY, picks)
    use(combat, table, mid, 'Test Prone')
    engine = reload(tmp_path, mid)
    candidate_stand = next(c for c in engine.legal_candidates() if c.source_definition_id == 'system:combat.stand_up')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompted = []
    commit(table, mid, candidate_stand.candidate_id, seen=prompted)
    engine = reload(tmp_path, mid)
    stood = [e for e in engine.events if e.event_type == 'STOOD_UP' and e.actor_id == ALLY]
    assert stood and stood[-1].payload['cost_ft'] == 5
    assert 'choice:gate.shelter_standing' not in prompted


@pytest.mark.parametrize('integrated,constitution', [(False, False), (True, True), (True, False)])
def test_sword_saint_integrated_blade_range_is_applied_before_damage(tmp_path, monkeypatch, integrated, constitution):
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script
    original = Gate4ControllerEngine._resolve_attack_spec
    def nineteen(engine, *args, **kwargs):
        script(engine, [19, *([1] * 60)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', nineteen)
    features = [PREFIX + 'kensei.feature.sword_saint_incarnation']
    if integrated:
        features.append(PREFIX + 'kensei.feature.blade_fist')
    combat, table, mid = start(tmp_path, features, owner_kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'name': 'Dao', 'quantity': 1}]}}, positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    use(combat, table, mid, 'Sword Saint Incarnation')
    name = 'Dao (Saber / Broadsword) attack' + (' (Constitution)' if constitution else '')
    use(combat, table, mid, name, target=FOE)
    engine = reload(tmp_path, mid)
    resolved = [e for e in engine.events if e.event_type == 'ATTACK_CRITICAL_RESOLVED' and e.actor_id == OWNER]
    if integrated:
        assert resolved and resolved[-1].payload['critical_threshold'] == 19
        assert resolved[-1].payload['critical']
        assert any(e.event_type == 'DAMAGE_ROLLED' and e.actor_id == OWNER and e.payload.get('critical') for e in engine.events)
    else:
        assert not resolved


def test_closed_gate_posts_resist_force_damage_through_object_service_commit(tmp_path):
    def objects_setup(bundles):
        setups(bundles)
        seal(bundles[0], 'Test Force object', [{'type': 'object_damage', 'flat': 20, 'damage_types': ['force']}], target='OBJECT')
    combat, table, mid = fixture(tmp_path, [], owner_features=[IRON, PREFIX + 'vermilion_gate_guardian_body.feature.heaven_s_closed_gate'],
        cl=18, primary='Stamina', owner_path='Body Refining', bundle_transform=objects_setup, owner_dc=50)
    use(combat, table, mid, "Heaven's Closed Gate")
    engine = reload(tmp_path, mid)
    posts = [o for o in engine.state.objects.values() if o.object_kind == 'gate_post' and o.position.x >= 0 and o.position.y >= 0]
    assert posts
    obj = posts[0]; before = obj.current_hp
    use(combat, table, mid, 'Test Force object', target=obj.object_id)
    engine = reload(tmp_path, mid)
    assert engine.state.objects[obj.object_id].current_hp == before - 10


def test_empty_world_creature_emergence_advantage_is_consumed_by_a_miss(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    combat, table, mid = fixture(tmp_path, [], owner_features=[IRON, PREFIX + 'kukishin.feature.hollow_immortal'],
        cl=18, primary='Stamina', owner_path='Body Refining', bundle_transform=attack_setups,
        extra_allies=1, positions={OWNER: {'x': 0, 'y': 0}, ALLY: {'x': 0, 'y': 1},
            FOE: {'x': 1, 'y': 0}, 'actor:factory.worker2-ally3': {'x': 1, 'y': 1}})
    use(combat, table, mid, 'Hollow Immortal')
    from combat.gate2_runtime_models import Position
    from combat.movement_routes import explicit_candidate
    path = (Position(x=0, y=0), Position(x=1, y=0), Position(x=2, y=0))
    engine = reload(tmp_path, mid)
    assert not any(m.applies_to == 'NEXT_ATTACK' for m in engine.state.actors[OWNER].modifiers.values())
    row = explicit_candidate(engine, OWNER, path, 'walk')
    commit(table, mid, row.candidate_id, movement=path)
    engine = reload(tmp_path, mid)
    assert any(m.applies_to == 'NEXT_ATTACK' for m in engine.state.actors[OWNER].modifiers.values())
    use(combat, table, mid, 'Test Attack miss', target=FOE)
    engine = reload(tmp_path, mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('ATTACK') and r.actor_id == OWNER][-1].mode == 'ADVANTAGE'
    assert not any(m.applies_to == 'NEXT_ATTACK' for m in engine.state.actors[OWNER].modifiers.values())
    use(combat, table, mid, 'Test Attack hit', target=FOE)
    engine = reload(tmp_path, mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('ATTACK') and r.actor_id == OWNER][-1].mode == 'NORMAL'
