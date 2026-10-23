"""Protection second pass through table transactions and fresh-service reload."""
import copy
import pytest
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.ext import protection, states
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import resolve

PR = 'tianxia.talent.protection.'
BASE = ['PROTECTION_BASE_WARD', 'PROTECTION_BASE_AEGIS', 'PROTECTION_BASE_ARMORED_AEGIS']
LASH = 'TAL_LIGHTNING_LIGHTNING_LASH'


def setup_payload(bundles):
    """Only setup actions vary; Sanctuary and Ward use the built authority."""
    for bundle in bundles:
        lash = next((a for a in bundle['action_catalog'] if a['display_name'].startswith('Lightning Lash')), None)
        if lash is None:
            continue
        for kind in ('damage', 'forced_movement', 'secret', 'named', 'teleport', 'unknown_named'):
            action = copy.deepcopy(lash)
            action.update(source_definition_id=lash['source_definition_id'] + '#setup_' + kind,
                          display_name='Setup ' + kind, economy='NONE', target_kind='SELF', range_ft=None,
                          costs=[], concentration=False)
            typed = action['parameters']['typed']
            typed.update(riders=[], duration={'kind': 'minutes', 'amount': 1, 'concentration': False})
            if kind == 'unknown_named':
                typed['source'] = 'UNKNOWN_PROTECTION_TEST'
                typed.pop('option_of', None)
            if kind == 'secret':
                typed['source_category'] = 'Secret Inheritance'
            effects = [{'type': 'damage', 'flat': 3, 'damage_types': ['fire'], 'applies_to': 'self'}] if kind != 'forced_movement' else [
                {'type': 'forced_movement', 'direction': 'away', 'distance_ft': 5, 'applies_to': 'target'}]
            typed['effects'] = [{'type': 'condition', 'condition': 'restrained', 'applies_to': 'self'}] if kind in ('named', 'unknown_named') else [
                {'type': 'ongoing', 'condition': 'setup_' + kind, 'applies_to': 'self', 'turn_start_effects': effects}]
            if kind == 'teleport':
                typed['effects'] = [{'type':'teleport', 'applies_to':'self', 'distance_ft':30}]
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        if bundle['actor_id'] == FOE:
            for label, effects in (
                ('hostile_force', [{'type':'ongoing', 'condition':'hostile_force', 'applies_to':'target',
                                    'turn_start_effects':[{'type':'forced_movement', 'applies_to':'target', 'direction':'away', 'distance_ft':5}]}]),
                ('concentration_hit', [{'type':'damage', 'applies_to':'target', 'flat':200, 'damage_types':['fire']}]),
            ):
                action = copy.deepcopy(lash)
                action.update(source_definition_id=lash['source_definition_id']+'#setup_'+label,
                              display_name='Setup '+label, economy='NONE', target_kind='HOSTILE_ENTITY', range_ft=60,
                              costs=[], concentration=False)
                action['parameters']['typed'].update(effects=effects, riders=[], range_ft=60,
                                                     duration={'kind':'minutes', 'amount':1, 'concentration':False})
                bundle['action_catalog'].append(action)
                bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def fresh(combat, mid, data):
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    loaded = CombatService(ROOT, data)._load_session(mid)
    assert loaded.engine.state.model_dump(mode='json') == before
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def make(tmp_path, *, positions=None, extra_talents=()):
    return fixture(tmp_path, [*BASE, PR+'peacebound', PR+'sanctuary_without_borders', *extra_talents],
                   foe_talents=[LASH], second_talents=[LASH], allies=[SECOND], wide=True,
                   positions=positions or {OWNER:{'x':3,'y':6}, FOE:{'x':4,'y':6}, SECOND:{'x':5,'y':6}},
                   bundle_transform=setup_payload, seed='A2PROTECTI')


def to_actor(table, mid, commit, who):
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == who:
            return
        commit(table.state(mid)['menu']['end_turn'])
    raise AssertionError('actor never reached')


def sanctuary(combat, table, mid, send, commit, *, ai=False):
    resolve(combat, mid, send, candidate(table, mid, 'Ward: Peacebound (Persistent)'),
            {'choice:needle.protection_ward_size':'20'})
    commit(table.state(mid)['menu']['end_turn'])
    to_actor(table, mid, commit, OWNER)
    cid = candidate(table, mid, 'Sanctuary Without Borders')
    if ai:
        force_ai_candidate(combat, mid, OWNER, cid)
    resolve(combat, mid, send, cid, {'choice:needle.sanctuary_ward':'$first'}, auto=ai)
    if ai:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[OWNER]
    running = states.active(engine, actor, 'sanctuary_without_borders')
    assert running is not None
    deadline = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.concentration_deadline'
                    and c.source_definition_id == running.source_definition_id)
    assert running.data['relief_deadline'] == deadline.expires_on


@pytest.mark.parametrize('kind', ['damage', 'forced_movement', 'named'])
def test_one_exact_relief_at_start_and_cold_reload(tmp_path, kind):
    combat, table, mid, send, commit = make(tmp_path)
    sanctuary(combat, table, mid, send, commit)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup '+kind))
    if kind == 'damage':
        commit(candidate(table, mid, 'Setup forced_movement'))
    engine = fresh(combat, mid, tmp_path)
    actor = engine.state.actors[SECOND]
    wanted = next(c.instance_id for c in actor.conditions.values() if c.condition_id.endswith('.'+ ('restrained' if kind=='named' else 'setup_'+kind)))
    to_actor(table, mid, commit, OWNER)
    # End the prior actor's turn until the ally's start raises its own choice.
    prompts = []
    for _ in range(4):
        cid = table.state(mid)['menu']['end_turn']
        _, offered = resolve(combat, mid, send, cid, {'choice:needle.protection_sanctuary':wanted})
        prompts.extend(offered)
        if table.state(mid)['menu']['actor_id'] == SECOND:
            break
    assert any(p['context']['reaction_source_id']=='choice:needle.protection_sanctuary' for p in prompts)
    actor = fresh(combat, mid, tmp_path).state.actors[SECOND]
    assert wanted not in actor.conditions
    if kind == 'damage':
        assert any(c.condition_id.endswith('.setup_forced_movement') for c in actor.conditions.values())
    # A second stored effect is untouched on later starts after benefit use.
    commit(candidate(table, mid, 'Setup damage'))
    to_actor(table, mid, commit, OWNER)
    to_actor(table, mid, commit, SECOND)
    assert any(c.condition_id.endswith('.setup_damage') for c in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions.values())


def test_ai_sanctuary_allies_and_enemies_in_range(tmp_path):
    combat, table, mid, send, commit = make(tmp_path)
    sanctuary(combat, table, mid, send, commit, ai=True)
    for who in (FOE, SECOND):
        to_actor(table, mid, commit, who)
        commit(candidate(table, mid, 'Setup damage'))
        commit(candidate(table, mid, 'Setup secret'))
    to_actor(table, mid, commit, OWNER)
    combat.set_controller_mode(mid, actor_id=SECOND, controller_mode='LOCAL_AUTO')
    to_actor(table, mid, commit, SECOND)
    combat.set_controller_mode(mid, actor_id=SECOND, controller_mode='MANUAL')
    engine = fresh(combat, mid, tmp_path)
    for who in (FOE, SECOND):
        assert any(c.condition_id.endswith('.setup_damage') for c in engine.state.actors[who].conditions.values()) == (who == FOE)
        assert any(c.condition_id.endswith('.setup_secret') for c in engine.state.actors[who].conditions.values())


def test_selected_ward_does_not_follow_replacement(tmp_path):
    combat, table, mid, send, commit = make(tmp_path)
    sanctuary(combat, table, mid, send, commit)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup damage'))
    to_actor(table, mid, commit, OWNER)
    resolve(combat, mid, send, candidate(table, mid, 'Ward: Peacebound (Persistent)'), {'choice:needle.protection_ward_size':'20'})
    to_actor(table, mid, commit, SECOND)
    assert any(c.condition_id.endswith('.setup_damage') for c in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions.values())


def move(table, mid, x, y):
    return next(row['candidate_id'] for row in table.state(mid)['menu']['moves']
                if row['destination']['x']==x and row['destination']['y']==y and row['destination'].get('z', 0)==0)


@pytest.mark.parametrize('decline', [False, True])
def test_first_entry_choice_and_decline_receipt(tmp_path, decline):
    combat, table, mid, send, commit = make(tmp_path)
    sanctuary(combat, table, mid, send, commit)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup damage'))
    engine = fresh(combat, mid, tmp_path)
    wanted = next(c.instance_id for c in engine.state.actors[SECOND].conditions.values() if c.condition_id.endswith('.setup_damage'))
    # Moving wholly inside grants no entry opportunity.
    _, prompts = resolve(combat, mid, send, move(table, mid, 6, 6), {})
    assert not any(p['context']['reaction_source_id']=='choice:needle.protection_sanctuary' for p in prompts)
    commit(move(table, mid, 8, 6))
    _, prompts = resolve(combat, mid, send, move(table, mid, 7, 6),
                         {'choice:needle.protection_sanctuary':None if decline else wanted})
    assert any(p['context']['reaction_source_id']=='choice:needle.protection_sanctuary' for p in prompts)
    assert (wanted in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions) == decline
    if decline:
        commit(move(table, mid, 8, 6))
        _, prompts = resolve(combat, mid, send, move(table, mid, 7, 6), {})
        assert not any(p['context']['reaction_source_id']=='choice:needle.protection_sanctuary' for p in prompts)
        assert wanted in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions
        to_actor(table, mid, commit, OWNER)
        to_actor(table, mid, commit, SECOND)
        assert wanted not in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions


def test_teleport_entry_uses_subject_choice_and_relief(tmp_path):
    combat, table, mid, send, commit = make(tmp_path)
    sanctuary(combat, table, mid, send, commit)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup damage'))
    wanted = next(c.instance_id for c in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions.values() if c.condition_id.endswith('.setup_damage'))
    resolve(combat, mid, send, candidate(table, mid, 'Setup teleport'), {'choice:needle.teleport_destination':'cell:8,6'})
    _, prompts = resolve(combat, mid, send, candidate(table, mid, 'Setup teleport'),
                         {'choice:needle.teleport_destination':'cell:7,6', 'choice:needle.protection_sanctuary':wanted})
    assert any(p['context']['reaction_source_id']=='choice:needle.protection_sanctuary' for p in prompts)
    assert wanted not in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions


def test_unknown_named_source_is_not_automatically_ended(tmp_path):
    combat, table, mid, send, commit = make(tmp_path)
    sanctuary(combat, table, mid, send, commit)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup unknown_named'))
    to_actor(table, mid, commit, OWNER)
    to_actor(table, mid, commit, SECOND)
    assert any(c.condition_id.endswith('.restrained') for c in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions.values())


def test_lost_concentration_ends_relief_but_keeps_persistent_ward(tmp_path):
    combat, table, mid, send, commit = make(tmp_path, positions={OWNER:{'x':3,'y':6}, FOE:{'x':12,'y':6}, SECOND:{'x':5,'y':6}})
    sanctuary(combat, table, mid, send, commit)
    engine = fresh(combat, mid, tmp_path)
    assert states.active(engine, engine.state.actors[OWNER], 'sanctuary_without_borders') is not None
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup damage'))
    to_actor(table, mid, commit, FOE)
    # Outside Peacebound Ward, a fixed 200-damage packet forces a Concentration
    # save against DC 100. The printed owner numbers cannot succeed on a d20.
    commit(candidate(table, mid, 'Setup concentration_hit', OWNER))
    engine = fresh(combat, mid, tmp_path)
    assert states.active(engine, engine.state.actors[OWNER], 'sanctuary_without_borders') is None
    assert protection.own_wards(engine, engine.state.actors[OWNER])
    to_actor(table, mid, commit, SECOND)
    assert any(c.condition_id.endswith('.setup_damage') for c in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions.values())


@pytest.mark.parametrize('protected', [False, True])
def test_real_ongoing_push_control_and_sanctuary_relief(tmp_path, protected):
    combat, table, mid, send, commit = make(tmp_path, extra_talents=[PR+'energy_resistance'])
    resolve(combat, mid, send, candidate(table, mid, 'Ward: Energy Resistance (Persistent)'),
            {'choice:needle.protection_ward_size':'20', 'choice:needle.protection_energy':'fire'})
    to_actor(table, mid, commit, FOE)
    commit(candidate(table, mid, 'Setup hostile_force', SECOND))
    engine = fresh(combat, mid, tmp_path)
    wanted = next(c.instance_id for c in engine.state.actors[SECOND].conditions.values() if c.condition_id.endswith('.hostile_force'))
    to_actor(table, mid, commit, OWNER)
    if protected:
        resolve(combat, mid, send, candidate(table, mid, 'Sanctuary Without Borders'), {'choice:needle.sanctuary_ward':'$first'})
    _, prompts = resolve(combat, mid, send, table.state(mid)['menu']['end_turn'], {'choice:needle.protection_sanctuary':wanted})
    actor = fresh(combat, mid, tmp_path).state.actors[SECOND]
    assert (wanted not in actor.conditions) == protected
    assert (actor.position.x, actor.position.y, actor.position.z) == (5 if protected else 6, 6, 0)
    assert any(p['context']['reaction_source_id']=='choice:needle.protection_sanctuary' for p in prompts) == protected
