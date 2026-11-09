"""Distinct Sanctuary decisions and deferred mounted entry through real sessions."""
import pytest
from combat.ext import states, protection, mounts
from combat.spatial_areas import zone_contains
from tests.r1i_service_support import fixture, candidate, OWNER, FOE, SECOND
from tests.test_auto2_protection import BASE, PR, LASH, setup_payload, to_actor, fresh
from tests.test_r1i_round3 import resolve
from tests.r10_fixup_support import fixed_dice

TALENTS = [*BASE, PR+'energy_resistance', PR+'sanctuary_without_borders']
CHOICE = 'choice:needle.protection_sanctuary'


def activate(combat, table, mid, send, commit, who, size='20'):
    to_actor(table, mid, commit, who)
    resolve(combat, mid, send, candidate(table, mid, 'Ward: Energy Resistance (Persistent)'),
            {'choice:needle.protection_ward_size':size, 'choice:needle.protection_energy':'fire'})
    commit(table.state(mid)['menu']['end_turn'])
    to_actor(table, mid, commit, who)
    resolve(combat, mid, send, candidate(table, mid, 'Sanctuary Without Borders'),
            {'choice:needle.sanctuary_ward':'$first'})


@pytest.mark.parametrize('entry', [False, True])
def test_overlapping_owners_decline_first_accept_second(tmp_path, entry):
    combat, table, mid, send, commit = fixture(tmp_path, TALENTS, foe_talents=TALENTS,
        second_talents=[LASH], allies=[FOE, SECOND], wide=True, bundle_transform=setup_payload,
        positions={OWNER:{'x':3,'y':6}, FOE:{'x':4,'y':6}, SECOND:{'x':9 if entry else 5,'y':6}},
        seed='A2PROTECTIr3-overlap')
    activate(combat, table, mid, send, commit, OWNER)
    activate(combat, table, mid, send, commit, FOE)
    to_actor(table, mid, commit, SECOND)
    commit(candidate(table, mid, 'Setup named'))
    engine = fresh(combat, mid, tmp_path)
    wanted = next(c.instance_id for c in engine.state.actors[SECOND].conditions.values() if c.condition_id.endswith('.restrained'))
    if entry:
        # Relief condition already active outside the wards: use teleport, which permits restraint.
        cid = candidate(table, mid, 'Setup teleport')
    else:
        order = engine.state.initiative_order
        to_actor(table, mid, commit, order[order.index(SECOND)-1])
        cid = table.state(mid)['menu']['end_turn']
    answers, prompts = [], []
    for _ in range(16):
        result = send(cid, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        assert send(cid, answers)['reaction'] == p
        # Pending choices survive a genuinely fresh service reconstruction.
        fresh(combat, mid, tmp_path)
        answer = {**p['context'], 'selection':'DECLINE'}
        if p['context']['reaction_source_id'] == CHOICE:
            prompts.append(p)
            if len(prompts) == 2:
                answer.update(selection='USE', option_ids=[wanted])
        elif p['context']['reaction_source_id'] == 'choice:needle.teleport_destination':
            answer.update(selection='USE', option_ids=['cell:7,6'])
        answers.append(answer)
    else:
        raise AssertionError('too many prompts')
    assert len(prompts) == 2, prompts
    assert prompts[0]['context']['checkpoint'] != prompts[1]['context']['checkpoint']
    engine = fresh(combat, mid, tmp_path)
    offered_owners = []
    for p in prompts:
        owner_id = next(who for who in (OWNER, FOE)
                        if states.active(engine, engine.state.actors[who], 'sanctuary_without_borders').instance_id
                        in p['context']['checkpoint'])
        offered_owners.append(owner_id)
        text = p['moment']
        assert engine.state.actors[owner_id].display_name in text
        assert ('enters the Ward' if entry else 'starts its turn') in text
        assert p['context']['reactor_id'] == SECOND
    assert set(offered_owners) == {OWNER, FOE}
    assert wanted not in engine.state.actors[SECOND].conditions
    for index, who in enumerate(offered_owners):
        running = states.active(engine, engine.state.actors[who], 'sanctuary_without_borders')
        used = engine.state.actors[who].turn_flags.get(f'protection_sanctuary_round_used:{running.instance_id}', [])
        assert (SECOND in used) == (index == 1)



@pytest.mark.parametrize('decline', [False, True])
def test_deferred_overrun_entry_relief_keeps_outside_fall(tmp_path, monkeypatch, decline):
    combat, table, mid, send, commit = fixture(tmp_path,
        ['BEASTMASTERY_BASE_RIDER_PACKAGE', 'TAL_BEASTMASTERY_RUN_DOWN', LASH],
        foe_talents=['TAL_GRAVITY_CRUSHING_FIELD'], second_talents=TALENTS,
        allies=[SECOND], wide=True, bundle_transform=setup_payload,
        positions={OWNER:{'x':2,'y':11}, FOE:{'x':4,'y':11}, SECOND:{'x':7,'y':7}},
        seed='A2PROTECTIr3-deferred')
    activate(combat, table, mid, send, commit, SECOND, size='20')
    to_actor(table, mid, commit, FOE)
    cid = next(o['candidate_id'] for g in table.state(mid)['menu']['actions'] if g['label']=='Crushing Field'
               for o in g['options'] if o.get('destination')=={'x':6,'y':10})
    commit(cid)
    to_actor(table, mid, commit, OWNER)
    commit(candidate(table, mid, 'Setup damage'))
    engine = fresh(combat, mid, tmp_path)
    wanted = next(c.instance_id for c in engine.state.actors[OWNER].conditions.values() if c.condition_id.endswith('.setup_damage'))
    mount_id = mounts.mount_of(engine, engine.state.actors[OWNER]).entity_id
    zone_id = protection.own_wards(engine, engine.state.actors[SECOND])[0].zone_id
    assert states.active(engine, engine.state.actors[SECOND], 'sanctuary_without_borders') is not None
    assert not zone_contains(engine, engine.state.actors[OWNER], engine.state.zones[zone_id])
    fixed_dice(monkeypatch, [19, 1] + [1]*100)
    _, prompts = resolve(combat, mid, send, candidate(table, mid, 'Mount: Overrun (Action)', FOE),
                         {CHOICE:None if decline else wanted})
    relief = [p for p in prompts if p['context']['reaction_source_id']==CHOICE]
    assert len(relief) == 1 and relief[0]['context']['reactor_id']==OWNER
    engine = fresh(combat, mid, tmp_path)
    rider = engine.state.actors[OWNER]
    charge = next(e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==OWNER and e.payload.get('overrun'))
    fall = next(e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==OWNER and e.payload.get('thrown_from')==mount_id)
    from combat.gate2_runtime_models import Position
    assert zone_contains(engine, rider, engine.state.zones[zone_id], at=Position(**charge.payload['destination']))
    assert not zone_contains(engine, rider, engine.state.zones[zone_id])
    assert rider.position.model_dump(mode='json') == fall.payload['destination']
    assert fall.payload['forced'] is True and fall.payload['path'][0] == charge.payload['destination']
    assert mounts.mount_of(engine, rider) is None
    assert (wanted in rider.conditions) == decline
    assert 'Second' in relief[0]['moment'] and 'enters the Ward' in relief[0]['moment']
