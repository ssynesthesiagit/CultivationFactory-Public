"""Compiled owned source -> table intent -> committed state -> cold mechanical replay."""
from pathlib import Path
import pytest
from combat.gate5_service import CombatService
from combat.flight import profile
from tests import r1i_service_support as R
from tests import auto11_service_support as S

FEATURE = 'tianxia.subpath.qi.storm_soul_cultivator.feature.zephyr_s_step'
ME, FOE, SECOND = R.OWNER, R.FOE, R.SECOND
QI = 'resource:core.qi'
FLIGHT = 'condition:typed.storm_soul_zephyr_s_step_flight'


def fight(tmp_path, *, owned=True, dc=50, pb=4, cl=14, allies=(), **kw):
    return R.fixture(tmp_path, [FEATURE] if owned else [], owner_cl=cl,
        owner_dc=dc, owner_pb=pb, wide=True, allies=allies, **kw)[:3]


def cold(svc, mid):
    fresh = CombatService(svc.source_root, svc.userdata_root)
    assert fresh.replay(mid)['status'] == 'PASS'
    eng = fresh._load_session(mid).engine
    assert eng.state.model_dump(mode='json') == svc._load_session(mid).engine.state.model_dump(mode='json')
    return eng


def answer(kind='THUNDER', decline=False):
    def choose(p):
        source = p['context']['reaction_source_id']
        if source == 'choice:needle.zephyr.targets':
            if decline:
                return None
            return p['choice']['options'][0]['id']
        if source == 'choice:needle.zephyr.damage':
            return kind
        return None
    return choose


def cast(svc, table, mid):
    cid = R.candidate(table, mid, 'Zephyr')
    return S.play(table, mid, cid, answer=answer())


def move(svc, table, mid, x, y, *, kind='THUNDER', decline=False):
    cid = next(o['candidate_id'] for o in table.state(mid)['menu']['moves']
        if o['destination'] == {'x': x, 'y': y})
    return S.play(table, mid, cid, answer=answer(kind, decline))


def saves(eng):
    return [e for e in eng.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith(FEATURE)]


def test_activation_is_paid_self_grant_without_save_and_expires_at_owner_start(tmp_path):
    svc, table, mid = fight(tmp_path)
    before = cold(svc, mid)
    result, prompts = cast(svc, table, mid)
    assert result['status'] == 'COMMITTED'
    eng = cold(svc, mid); actor = eng.state.actors[ME]
    assert not saves(eng), 'Thunderhead must wait for committed movement'
    assert actor.resources[QI] == before.state.actors[ME].resources[QI] - 3
    assert not actor.bonus_action_available and actor.action_available
    assert eng._effective_speed(actor) == eng._effective_speed(before.state.actors[ME])
    assert profile(eng, actor).speed_ft == 50 and profile(eng, actor).hover
    c = next(c for c in actor.conditions.values() if c.condition_id == FLIGHT)
    assert c.expires_on == 'START_OF_SOURCE_NEXT_TURN'
    S.play(table, mid, table.state(mid)['menu']['end_turn'])
    # Other creatures' starts cannot expire the owner's grant.
    assert any(c.condition_id == FLIGHT for c in cold(svc, mid).state.actors[ME].conditions.values())
    for _ in range(8):
        if table.state(mid)['menu']['actor_id'] == ME:
            break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert not any(c.condition_id == FLIGHT for c in cold(svc, mid).state.actors[ME].conditions.values())


@pytest.mark.parametrize('kind', ['LIGHTNING', 'THUNDER'])
@pytest.mark.parametrize('dc,failed', [(50, True), (1, False)])
def test_first_committed_approach_delivers_chosen_save_once_and_reloads(tmp_path, kind, dc, failed):
    svc, table, mid = fight(tmp_path, dc=dc,
        positions={ME:{'x':3,'y':6}, FOE:{'x':5,'y':6}, SECOND:{'x':15,'y':6}})
    cast(svc, table, mid)
    assert not saves(cold(svc, mid))
    _, prompts = move(svc, table, mid, 4, 6, kind=kind)
    eng = cold(svc, mid); foe = eng.state.actors[FOE]
    assert len(saves(eng)) == 1 and saves(eng)[0].actor_id == FOE
    damage = [e for e in eng.events if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id.endswith(FEATURE)]
    assert len(damage) == 1
    assert damage[0].payload['damage_type'] == kind
    rolls = [e for e in eng.events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id.endswith(FEATURE)]
    assert len(rolls) == 1
    assert rolls[0].payload['expression'] == '3d8+0'
    rolled = rolls[0].payload['total']
    assert 500 - foe.current_hp == (rolled if failed else rolled // 2)
    denied = [c for c in foe.conditions.values() if c.condition_id == 'condition:typed.reaction_denied']
    assert bool(denied) == failed
    if failed:
        from combat.ext.effect_durations import token
        assert denied[0].expires_on == token('start', FOE, foe.turns_started + 1)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.zephyr.damage' for p in prompts)
    damage_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.zephyr.damage')
    assert foe.display_name in damage_prompt['moment']
    assert damage_prompt['affected'] == foe.display_name
    hp = foe.current_hp
    move(svc, table, mid, 3, 6)
    move(svc, table, mid, 4, 6)
    eng = cold(svc, mid)
    assert len(saves(eng)) == 1 and eng.state.actors[FOE].current_hp == hp
    assert all(p['context']['reaction_source_id'].startswith('choice:needle.zephyr.') for p in prompts)
    if failed:
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
        for _ in range(8):
            if table.state(mid)['menu']['actor_id'] == FOE:
                break
            S.play(table, mid, table.state(mid)['menu']['end_turn'])
        assert not any(c.condition_id == 'condition:typed.reaction_denied'
            for c in cold(svc, mid).state.actors[FOE].conditions.values())


def test_pb_caps_distinct_targets_and_ally_does_not_spend_cap(tmp_path):
    svc, table, mid = fight(tmp_path, pb=1,
        positions={ME:{'x':3,'y':6}, FOE:{'x':5,'y':6}, SECOND:{'x':8,'y':6}})
    cast(svc, table, mid)
    move(svc, table, mid, 4, 6)
    move(svc, table, mid, 7, 6)
    eng = cold(svc, mid)
    assert len(saves(eng)) == 1 and saves(eng)[0].actor_id == FOE
    c = next(c for c in eng.state.actors[ME].conditions.values() if c.condition_id == FLIGHT)
    assert c.data['affected'] == [FOE] and SECOND in c.data['seen']


def test_declining_first_approach_cannot_retry_and_allies_are_inert(tmp_path):
    svc, table, mid = fight(tmp_path, allies=(SECOND,),
        positions={ME:{'x':3,'y':6}, FOE:{'x':5,'y':6}, SECOND:{'x':4,'y':7}})
    cast(svc, table, mid)
    move(svc, table, mid, 4, 6, decline=True)
    move(svc, table, mid, 3, 6)
    move(svc, table, mid, 4, 6)
    eng = cold(svc, mid)
    assert not saves(eng)
    c = next(c for c in eng.state.actors[ME].conditions.values() if c.condition_id == FLIGHT)
    assert c.data['seen'] == [FOE] and c.data['affected'] == []


def test_wrong_owner_has_no_action_or_grant_and_occupied_endpoints_remain_illegal(tmp_path):
    svc, table, mid = fight(tmp_path, owned=False)
    assert not any('Zephyr' in g['label'] for g in table.state(mid)['menu']['actions'])
    assert not any(c.condition_id == FLIGHT for c in cold(svc, mid).state.actors[ME].conditions.values())
    move(svc, table, mid, 3, 7)
    assert not saves(cold(svc, mid))
    svc, table, mid = fight(tmp_path/'owned')
    cast(svc, table, mid)
    assert not any(o['destination'] == {'x':4,'y':6} for o in table.state(mid)['menu']['moves'])
    move(svc, table, mid, 6, 6)
    eng = cold(svc, mid)
    assert eng.state.actors[ME].position.x == 6
    # The occupied cells are transit permissions only; passage and terrain are
    # paid by native motion, with this feature's ignore-difficult exemption.
    events = [e for e in eng.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ME]
    assert events and events[-1].payload['cost_ft'] == 15
    assert any(p['x'] == 4 and p.get('z', 0) == 0 for p in events[-1].payload['path'])


def test_cl_boundary_is_checked_before_payment(tmp_path):
    svc, table, mid = fight(tmp_path, cl=13)
    assert not any('Zephyr' in g['label'] for g in table.state(mid)['menu']['actions'])
    actor = cold(svc, mid).state.actors[ME]
    assert actor.resources[QI] == 30 and actor.bonus_action_available


def test_open_air_flight_uses_fifty_foot_shared_budget_and_does_not_provoke(tmp_path):
    from combat.flight import remaining
    svc, table, mid = fight(tmp_path)
    cast(svc, table, mid)
    moves = table.state(mid)['menu']['moves']
    cid = next(o['candidate_id'] for o in moves if o['destination'] == {'x':3, 'y':6, 'z':10})
    result, prompts = S.play(table, mid, cid, answer=answer(decline=True))
    assert result['status'] == 'COMMITTED'
    assert all(p['context']['reaction_source_id'].startswith('choice:needle.zephyr.') for p in prompts)
    eng = cold(svc, mid); actor = eng.state.actors[ME]
    assert actor.position.z == 10 and profile(eng, actor).hover
    assert remaining(eng, actor, 'fly') == 0 and actor.movement_remaining_ft == 0
    assert not any(o['destination'] == {'x':3, 'y':6, 'z':11} for o in table.state(mid)['menu']['moves'])


def test_difficult_map_terrain_and_water_are_traversed_without_surcharge(tmp_path):
    svc, table, mid = fight(tmp_path, map_terrain=[
        {'type':'DIFFICULT', 'cells':[[4,6]]},
        {'terrain':'monsoon wall', 'cells':[[4,6]]}],
        positions={ME:{'x':3,'y':6}, FOE:{'x':10,'y':6}, SECOND:{'x':12,'y':6}})
    cast(svc, table, mid)
    move(svc, table, mid, 4, 6)
    eng = cold(svc, mid)
    events = [e for e in eng.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ME]
    assert events[-1].payload['cost_ft'] == 5
    assert eng.state.actors[ME].movement_remaining_ft == 25
    assert not saves(eng)


def concealed_fight(tmp_path):
    """A real acquired Greater Invisibility, committed before Zephyr activates."""
    svc, table, mid = fight(tmp_path,
        foe_talents=['tianxia.talent.illusion.greater_invisibility'],
        positions={ME:{'x':3,'y':6}, FOE:{'x':5,'y':6}, SECOND:{'x':15,'y':6}})
    while table.state(mid)['menu']['actor_id'] != FOE:
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    S.play(table, mid, R.candidate(table, mid, 'Greater Invisibility', target=FOE))
    S.play(table, mid, table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != ME:
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    from combat.target_knowledge import located
    eng = cold(svc, mid)
    assert not located(eng, eng.state.actors[ME], eng.state.actors[FOE])
    cast(svc, table, mid)
    return svc, table, mid


def test_automatic_unlocated_thunderhead_recipient_survives_reload_and_reentry(tmp_path):
    svc, table, mid = concealed_fight(tmp_path)
    cid = next(o['candidate_id'] for o in table.state(mid)['menu']['moves']
        if o['destination'] == {'x':4, 'y':6})
    # Fix only the primary move, leaving all reaction choices to the real AI.
    R.force_ai_candidate(svc, mid, ME, cid)
    result = table.auto_step(mid, table.state(mid)['last_sequence'])
    assert result['status'] == 'COMMITTED', result
    eng = cold(svc, mid)
    assert len(saves(eng)) == 1 and saves(eng)[0].actor_id == FOE
    hp = eng.state.actors[FOE].current_hp
    assert hp < 500
    c = next(c for c in eng.state.actors[ME].conditions.values() if c.condition_id == FLIGHT)
    assert c.data['seen'] == [FOE] and c.data['affected'] == [FOE]
    svc.set_controller_mode(mid, actor_id=ME, controller_mode='MANUAL')
    move(svc, table, mid, 3, 6)
    move(svc, table, mid, 4, 6)
    eng = cold(svc, mid)
    assert len(saves(eng)) == 1 and eng.state.actors[FOE].current_hp == hp


def test_unlocated_recipient_name_is_masked_in_every_thunderhead_prompt(tmp_path):
    import json
    svc, table, mid = concealed_fight(tmp_path)
    hidden_name = cold(svc, mid).state.actors[FOE].display_name
    _, prompts = move(svc, table, mid, 4, 6)
    assert len(prompts) == 2
    assert prompts[0]['choice']['options'][0] == {'id': FOE, 'label': 'Unseen hostile creature'}
    for prompt in prompts:
        assert hidden_name not in json.dumps(prompt), prompt
    assert 'Unseen hostile creature' in prompts[1]['moment']
    eng = cold(svc, mid)
    assert len(saves(eng)) == 1 and eng.state.actors[FOE].current_hp < 500
