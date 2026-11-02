"""Review regressions: player-owned AI-turn relief, volume and table wording."""
import pytest
from combat.ext import states
from tests.test_auto2_protection import (make, sanctuary, to_actor, fresh, setup_payload,
                                        PR, BASE, LASH, OWNER, FOE, SECOND)
from tests.r1i_service_support import fixture, candidate, force_ai_candidate
from tests.test_r1i_round3 import resolve
from combat.canonical import canonical_sha256


def unadvertised_payload(bundles):
    setup_payload(bundles)
    for bundle in bundles:
        if bundle['actor_id'] == SECOND:
            # An Ask-me character with no unrelated ownership. The setup Lash
            # only supplies attributable test effects; it must not mask enrollment.
            for row in bundle.get('typed_reactions', []):
                row.pop('ask', None)
            for row in bundle.get('typed_passives', []):
                row.pop('choice_owner', None)
        # A real native forced-movement setup action, with no response of its own.
        if bundle['actor_id'] == FOE:
            import copy
            action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['display_name']=='Setup hostile_force'))
            action.update(display_name='Setup entry pull', source_definition_id=action['source_definition_id']+'#entry')
            action['parameters']['typed']['effects'] = [
                {'type':'forced_movement', 'direction':'toward', 'distance_ft':5, 'applies_to':'target'}]
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def manual_recipient(tmp_path, *, entry=False):
    return fixture(tmp_path, [*BASE, PR+'energy_resistance', PR+'sanctuary_without_borders'],
        foe_talents=[LASH], second_talents=[LASH], allies=[SECOND], wide=True,
        positions={OWNER:{'x':3,'y':6}, FOE:{'x':6,'y':6}, SECOND:{'x':8 if entry else 5,'y':6}},
        bundle_transform=unadvertised_payload, seed='A2PROTECTIr1')


def energy_sanctuary(combat, table, mid, send, commit):
    resolve(combat, mid, send, candidate(table, mid, 'Ward: Energy Resistance (Persistent)'),
        {'choice:needle.protection_ward_size':'20','choice:needle.protection_energy':'fire'})
    commit(table.state(mid)['menu']['end_turn'])
    to_actor(table, mid, commit, OWNER)
    resolve(combat, mid, send, candidate(table, mid, 'Sanctuary Without Borders'),
        {'choice:needle.sanctuary_ward':'$first'})


@pytest.mark.parametrize('entry', [False, True])
@pytest.mark.parametrize('decline', [False, True])
def test_ai_step_preserves_unadvertised_manual_recipient_choice(tmp_path, entry, decline):
    combat, table, mid, send, commit = manual_recipient(tmp_path, entry=entry)
    fresh(combat, mid, tmp_path)
    assert SECOND not in combat._ask_reactors(combat._read_metadata(mid, combat._load_session(mid)), combat._load_session(mid))
    energy_sanctuary(combat, table, mid, send, commit)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup damage'))
    actor = fresh(combat, mid, tmp_path).state.actors[SECOND]
    wanted = next(c.instance_id for c in actor.conditions.values() if c.condition_id.endswith('.setup_damage'))
    assert not any(c.data.get('choice_owner') for c in actor.conditions.values())
    who = FOE if entry else OWNER
    to_actor(table, mid, commit, who)
    cid = candidate(table, mid, 'Setup entry pull', SECOND) if entry else table.state(mid)['menu']['end_turn']
    force_ai_candidate(combat, mid, who, cid)
    before, prompts = resolve(combat, mid, send, cid,
        {'choice:needle.protection_sanctuary':None if decline else wanted}, auto=True)
    relief = [p for p in prompts if p['context']['reaction_source_id']=='choice:needle.protection_sanctuary']
    assert relief and all(p['context']['reactor_id']==SECOND for p in relief)
    assert relief[0]['choice']['allow_decline'] is True
    actor = fresh(combat, mid, tmp_path).state.actors[SECOND]
    assert (wanted in actor.conditions) == decline
    if entry:
        assert (actor.position.x, actor.position.y, actor.position.z)==(7,6,0)


@pytest.mark.parametrize('z,inside', [(1, True), (5, False)])
def test_start_relief_uses_ward_volume(tmp_path, z, inside):
    combat, table, mid, send, commit = fixture(tmp_path,
        [*BASE, PR+'peacebound', PR+'sanctuary_without_borders'], foe_talents=[LASH],
        second_talents=[LASH], allies=[SECOND], wide=True, bundle_transform=flight_payload,
        positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},SECOND:{'x':5,'y':6}}, seed='A2PROTECTIr1-start')
    sanctuary(combat, table, mid, send, commit)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup flight'))
    commit(next(row['candidate_id'] for row in table.state(mid)['menu']['moves']
                if row['destination']=={'x':5,'y':6,'z':z}))
    commit(candidate(table, mid, 'Setup damage'))
    engine = fresh(combat, mid, tmp_path)
    actor = engine.state.actors[SECOND]
    assert actor.position.z == z
    wanted = next(c.instance_id for c in actor.conditions.values() if c.condition_id.endswith('.setup_damage'))
    from combat.spatial_areas import zone_contains
    zone = next(iter(engine.state.zones.values()))
    assert zone_contains(engine, actor, zone) == inside
    assert not engine._footprint_intersects(actor, zone.affected_cells)
    to_actor(table, mid, commit, OWNER)
    prompts = []
    for _ in range(4):
        _, offered = resolve(combat, mid, send, table.state(mid)['menu']['end_turn'],
            {'choice:needle.protection_sanctuary':wanted})
        prompts.extend(offered)
        if table.state(mid)['menu']['actor_id'] == SECOND:
            break
    assert table.state(mid)['menu']['actor_id'] == SECOND
    assert any(p['context']['reaction_source_id']=='choice:needle.protection_sanctuary' for p in prompts) == inside
    assert (wanted not in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions) == inside


def flight_payload(bundles):
    setup_payload(bundles)
    import copy
    for bundle in bundles:
        if bundle['actor_id'] != SECOND:
            continue
        action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['display_name']=='Setup damage'))
        action.update(display_name='Setup flight', source_definition_id=action['source_definition_id']+'#flight')
        action['parameters']['typed']['effects'] = [
            {'type':'general_flight', 'speed_ft':30, 'hover':True, 'applies_to':'self',
             'duration':{'kind':'minutes', 'amount':1}}]
        bundle['action_catalog'].append(action)
        bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_elevated_entry_relief_uses_landed_volume(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path,
        [*BASE, PR+'peacebound', PR+'sanctuary_without_borders'], foe_talents=[LASH],
        second_talents=[LASH], allies=[SECOND], wide=True, bundle_transform=flight_payload,
        positions={OWNER:{'x':3,'y':6},FOE:{'x':4,'y':6},SECOND:{'x':8,'y':6}}, seed='A2PROTECTIr1-flight')
    sanctuary(combat, table, mid, send, commit)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup flight'))
    commit(next(row['candidate_id'] for row in table.state(mid)['menu']['moves']
                if row['destination']=={'x':8,'y':6,'z':1}))
    commit(candidate(table, mid, 'Setup damage'))
    wanted = next(c.instance_id for c in fresh(combat, mid, tmp_path).state.actors[SECOND].conditions.values() if c.condition_id.endswith('.setup_damage'))
    cid = next(row['candidate_id'] for row in table.state(mid)['menu']['moves']
               if row['destination']=={'x':6,'y':6,'z':1})
    _, prompts = resolve(combat, mid, send, cid, {'choice:needle.protection_sanctuary':wanted})
    assert any(p['context']['reaction_source_id']=='choice:needle.protection_sanctuary' for p in prompts)
    actor = fresh(combat, mid, tmp_path).state.actors[SECOND]
    assert (actor.position.x,actor.position.y,actor.position.z)==(6,6,1)
    assert wanted not in actor.conditions


def test_sanctuary_condition_pill_scope_timing_lifetime(tmp_path):
    combat, table, mid, send, commit = make(tmp_path)
    sanctuary(combat, table, mid, send, commit)
    engine = fresh(combat, mid, tmp_path)
    running = states.active(engine, engine.state.actors[OWNER], 'sanctuary_without_borders')
    from combat.presentation import condition_label
    text = condition_label(running.condition_id, running.data)
    assert 'one ordinary condition' not in text
    for word in ('Frightened', 'Grappled', 'Restrained', 'starts its turn', 'first enters', 'Concentration', 'up to 1 minute', 'represented temporary', 'once'):
        assert word in text
    presentation = table.state(mid)['presentation']
    owner = next(a for a in presentation['actors'] if a['entity_id']==OWNER)
    assert any(c['display_name']==text for c in owner['conditions'])
