"""Body subpath review regressions through table commits and cold replay."""
import pytest

from combat import ext, flight
from combat.ext import nine_star, sky_treading
from tests.cw2_service_support import add_action, seal
from tests.test_a2_body_subpaths_1 import setup, NINE, SKY, MARK, STAMINA
from tests.worker2_support import settle, reload, candidate, OWNER, ALLY, FOE


def end_current(table, mid, *, choices=None):
    menu = table.state(mid)['menu']
    if menu['manual']:
        return settle(table, mid, menu['end_turn'], choices=choices)
    from combat.gate4_adapters import ManualControllerAdapter
    combat = table.combat
    engine = combat._load_session(mid).engine
    end = next(c for c in engine.legal_candidates() if c.kind == 'END_TURN')
    real = combat.controller
    # Choose only the enclosing end-turn action; renewal still uses the real
    # built-in reaction chooser and the service's owner-scoped probe.
    combat.controller = ManualControllerAdapter(lambda context:(end.candidate_id,()),
        reaction_chooser=lambda context:real.choose_reaction(context).decision)
    try:
        return settle(table, mid, end.candidate_id, choices=choices, auto=True)
    finally:
        combat.controller = real


def next_owner(table, mid, *, choices=None):
    prompts = []
    for _ in range(12):
        prompts += end_current(table, mid, choices=choices)
        if table.state(mid)['menu']['actor_id'] == OWNER:
            return prompts
    raise AssertionError('Owner did not get another turn')


def start_tread(combat, table, mid):
    engine = combat._load_session(mid).engine
    jump = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination.z == 1)
    settle(table, mid, jump.candidate_id)


@pytest.mark.parametrize('mode,auto_others', [('MANUAL',False), ('MANUAL',True), ('LOCAL_AUTO',True)])
def test_tread_renewal_owner_choice_commit_reload(tmp_path, mode, auto_others):
    combat, table, mid = setup(tmp_path, [SKY+'tread_the_empty_sky'], owner_speed=50, ask=False)
    start_tread(combat, table, mid)
    before = reload(tmp_path, mid).state.actors[OWNER]
    assert before.resources[STAMINA] == 99 and before.position.z == 1
    hp = before.current_hp
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    if auto_others:
        for other in (ALLY, FOE):
            combat.set_controller_mode(mid, actor_id=other, controller_mode='LOCAL_AUTO')
    prompts = next_owner(table, mid)
    renewal = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.sky_tread']
    if mode == 'MANUAL':
        assert len(renewal) == 1
        assert renewal[0]['context']['reactor_id'] == OWNER
        assert 'turn is starting' in renewal[0]['moment']
    else:
        assert not renewal, 'The built-in AI must answer its own renewal automatically'
    engine = reload(tmp_path, mid); actor = engine.state.actors[OWNER]
    assert actor.resources[STAMINA] == 98 and actor.position.z == 1
    assert actor.current_hp == hp and flight.profile(engine, actor).speed_ft == 50
    assert len([c for c in actor.conditions.values() if c.condition_id == sky_treading.TREAD_HOLD]) == 1
    assert not any(c.source_definition_id == sky_treading.TREAD for c in engine.legal_candidates())
    payments = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.actor_id == OWNER and e.source_definition_id == sky_treading.TREAD]
    assert len(payments) == 2 and all(e.payload['amount'] == 1 for e in payments)
    end_current(table, mid)
    assert reload(tmp_path, mid).state.actors[OWNER].position.z == 1


@pytest.mark.parametrize('reason', ['decline', 'insufficient'])
def test_tread_unrenewed_hold_expires_commit_reload(tmp_path, reason):
    def prepare(bundles):
        add_action(bundles[0], 'Spend remaining Stamina',
                   [{'type':'spend_resource', 'resource_id':STAMINA, 'flat':99, 'applies_to':'self'}], target='SELF')
    combat, table, mid = setup(tmp_path, [SKY+'tread_the_empty_sky'], owner_speed=50, bundle_transform=prepare)
    start_tread(combat, table, mid)
    if reason == 'insufficient':
        settle(table, mid, candidate(combat, mid, 'Spend remaining Stamina').candidate_id)
    prompts = next_owner(table, mid, choices={'choice:needle.sky_tread':None})
    renewal = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.sky_tread']
    assert len(renewal) == (1 if reason == 'decline' else 0)
    engine = reload(tmp_path, mid); actor = engine.state.actors[OWNER]
    assert actor.position.z == 1 and flight.profile(engine, actor).speed_ft == 0
    assert actor.resources[STAMINA] == (99 if reason == 'decline' else 0)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={'choice:needle.sky_tread':None})
    engine = reload(tmp_path, mid); actor = engine.state.actors[OWNER]
    assert actor.position.z == 0
    assert not any(c.condition_id == sky_treading.TREAD_HOLD for c in actor.conditions.values())
    assert actor.resources[STAMINA] == (99 if reason == 'decline' else 0)


@pytest.mark.parametrize('case', ['airborne', 'grounded', 'below_marks', 'hook_removed'])
def test_constellation_actual_prone_attempt_commit_reload(tmp_path, monkeypatch, case):
    if case == 'hook_removed':
        monkeypatch.setitem(ext._HOOKS, 'condition_attempt',
                            [h for h in ext._HOOKS['condition_attempt'] if h is not nine_star.airborne_constellation])
    def prepare(bundles):
        add_action(bundles[0], 'Attempt Prone', [{'type':'condition', 'condition':'prone', 'applies_to':'self'}], target='SELF')
        add_action(bundles[0], 'Spend one Mark', [{'type':'spend_resource', 'resource_id':MARK, 'flat':1, 'applies_to':'self'}], target='SELF')
    combat, table, mid = setup(tmp_path, [NINE+'constellation_circuit', SKY+'body_crosses_heaven'], bundle_transform=prepare)
    if case != 'grounded':
        engine = combat._load_session(mid).engine
        lift = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination.z == 1)
        settle(table, mid, lift.candidate_id)
    if case == 'below_marks':
        settle(table, mid, candidate(combat, mid, 'Spend one Mark').candidate_id)
    before = reload(tmp_path, mid).state.actors[OWNER]
    assert before.position.z == (0 if case == 'grounded' else 1)
    assert before.resources[MARK] == (2 if case == 'below_marks' else 3)
    settle(table, mid, candidate(combat, mid, 'Attempt Prone').candidate_id)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert any(c.condition_id == 'condition:typed.prone' for c in actor.conditions.values()) == (case != 'airborne')


@pytest.mark.parametrize('case,z', [('protected',2), ('below_threshold',1), ('expired',2), ('hook_removed',2)])
def test_tread_actual_move_opportunity_boundary_commit_reload(tmp_path, monkeypatch, case, z):
    if case == 'hook_removed':
        monkeypatch.setitem(ext._HOOKS, 'opportunity_allowed',
                            [h for h in ext._HOOKS['opportunity_allowed'] if h is not sky_treading.tread_below])
    def prepare(bundles):
        # A sealed 10-foot melee reach creates a real leave-reach trigger even
        # with the mover 10 feet above the reactor. No engine method is replaced.
        foe = bundles[2]
        for row in foe['action_catalog']:
            if row['display_name'] == 'Opportunity Attack':
                row['range_ft'] = 10
                for effect in row['parameters']['typed']['effects']:
                    if effect.get('type') == 'attack':
                        effect['reach_ft'] = 10
        for row in foe['typed_reactions']:
            if row.get('block') == 'opportunity':
                row['reach_ft'] = 10
        seal(foe)
    combat, table, mid = setup(tmp_path, [SKY+'tread_the_empty_sky', SKY+'body_crosses_heaven'],
                              owner_speed=50, foe_position={'x':4,'y':6}, ally_position={'x':0,'y':0}, bundle_transform=prepare)
    engine = combat._load_session(mid).engine
    lift = next(c for c in engine.legal_candidates() if c.kind == 'MOVE'
                and (c.destination.x,c.destination.y,c.destination.z) == (3,6,z))
    settle(table, mid, lift.candidate_id)
    button = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == sky_treading.TREAD)
    settle(table, mid, button.candidate_id)
    if case == 'expired':
        next_owner(table, mid, choices={'choice:needle.sky_tread':None})
        next_owner(table, mid, choices={'choice:needle.sky_tread':None})
    engine = reload(tmp_path, mid); actor = engine.state.actors[OWNER]
    assert actor.position.z == z
    assert any(c.condition_id == sky_treading.TREAD_HOLD for c in actor.conditions.values()) == (case != 'expired')
    # Native shortest-path ties can rise another square while leaving reach.
    # Use the table's genuine waypoint transport to test a constant altitude.
    menu = table.state(mid)['menu']
    path = [{'x':x, 'y':6, 'z':z} for x in range(3,8)]
    quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], OWNER, path, 'fly')
    cid = quote['candidate']['candidate_id']
    prompts, answers = [], []
    for _ in range(8):
        result = table.commit_move_path(mid, cid, menu['decision_id'], menu['state_version'], OWNER,
                                        path, movement_mode='fly', reactions=answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        prompts.append(result['reaction'])
        answers.append({**result['reaction']['context'], 'selection':'DECLINE'})
    else:
        raise AssertionError('Movement did not commit')
    opportunities = [p for p in prompts if p['context']['reactor_id'] == FOE
                     and 'opportunity_attack' in p['context']['reaction_source_id']]
    assert bool(opportunities) == (case != 'protected')
    engine = reload(tmp_path, mid); actor = engine.state.actors[OWNER]
    assert (actor.position.x,actor.position.y,actor.position.z) == (7,6,z)
    moved = next(e for e in reversed(engine.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER)
    assert moved.payload['path'] == path
