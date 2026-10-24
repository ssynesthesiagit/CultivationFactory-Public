"""Chain Body uses acquired sheet records, real table intents and cold replay.

No effect/trigger/ownership receipts are injected into a running fight.
"""
import json
import zipfile

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_riders_c7 import sheet, ROOT, CHAIN, WHIP
from tests.test_lock2_persistence import act

OWNER_PROJECT = 'c4a10000-0000-4000-8000-000000000001'
TARGET_PROJECT = 'c4a10000-0000-4000-8000-000000000002'
OWNER = FACTORY_ACTOR_PREFIX + OWNER_PROJECT
TARGET = FACTORY_ACTOR_PREFIX + TARGET_PROJECT


def acquired_fight(tmp_path, features, *, cl=18, target_talents=(), target_at=(4, 4), target_mods=None,
                   ask_reactions=False, objects=()):
    for name, ids in [('chain-owner', features), ('chain-target', [])]:
        document = sheet([CHAIN + fid for fid in ids], cl=cl, items=(WHIP,), spheres={},
                         mods=target_mods if name == 'chain-target' else None)
        if name == 'chain-target':
            document['spheres_and_talents']['learned_talent_record_ids'] = list(target_talents)
        document['identity']['display_name'] = name
        path = tmp_path / 'portable_characters' / (OWNER_PROJECT if name == 'chain-owner' else TARGET_PROJECT)
        path.mkdir(parents=True)
        with zipfile.ZipFile(path / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    service = CombatService(ROOT, tmp_path)
    if ask_reactions:
        from combat.tabletop import ButtonStore
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(OWNER_PROJECT, {'mode': 'ask'}, set())
    service.tabletop_maps.save({'display_name': 'Chain evidence yard', 'width_squares': 16, 'height_squares': 12,
        'walls': [], 'objects': list(objects), 'starts': {'team1': [[3, 4]], 'team2': [list(target_at)]}})
    mid = service.create_factory_match(project_ids=[OWNER_PROJECT], opponent_actor_ids=[TARGET],
        control_modes={OWNER: 'MANUAL', TARGET: 'MANUAL'},
        arena_id='battlefield:map.chain-evidence-yard', match_seed='CHAIN-NATIVE-58')['match_id']
    table = TabletopService(service, tmp_path)
    while table.state(mid)['menu']['actor_id'] != OWNER:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    return service, table, mid


def commit(table, mid, source, *, choose=None, choose_index=None, destination=None):
    """Commit one table intent. ``choose`` names a printed option; ``choose_index`` picks the
    option at that printed position instead, for a label the public copy scrambles (8+ words)."""
    state = table.state(mid)
    menu = state['menu']
    # Main's menu ranks the weapon's Grapple/Trip alternatives independently.
    # A tether setup needs an ordinary strike, without a second movement bar.
    group = next(g for g in menu['actions'] if source in g['source_definition_id']
                 and (source != '.weapon.' or not any(tag in g['source_definition_id']
                      for tag in ('#grapple', '#trip', '.pickup'))))
    option = next((o for o in group['options'] if destination is None or o.get('destination') == destination), None)
    assert option is not None, group
    candidate = option['candidate_id']
    answers = []
    for _ in range(24):
        result = table.act(mid, candidate, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            options = prompt['choice']['options']
            if choose in {o['id'] for o in options}:
                answer['option_ids'] = [choose]
            elif choose_index is not None:
                answer['option_ids'] = [options[choose_index]['id']]
            else:
                answer['option_ids'] = [options[0]['id']]
        answers.append(answer)
    raise AssertionError('unbounded reaction prompts')


def cold(service, mid):
    loaded = CombatService(ROOT, service.userdata_root)._load_session(mid)
    assert loaded.verify()['status'] == 'PASS'
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def test_meridian_records_source_and_removal_contract_after_native_hit(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration'])
    for _ in range(8):
        commit(table, mid, '.weapon.', choose='tether')
        engine = cold(service, mid)
        held = [c for c in engine.state.actors[TARGET].conditions.values()
                if c.condition_id == 'condition:typed.meridian_tether']
        if held:
            condition = held[0]
            assert condition.source_actor_id == OWNER
            assert condition.source_definition_id == CHAIN + 'chain_body_integration'
            assert condition.data['source_cl'] == 18
            assert condition.data['sense_ft'] == 60
            assert condition.data['hostile_forced'] == 0
            assert 'END_OF_SOURCE_TURN_AT:' in condition.expires_on
            return
        for _ in range(2):
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
    raise AssertionError('no qualifying committed chain hit')


def test_prison_records_source_dc_and_separate_radius_after_commit(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['heaven_binding_prison'])
    commit(table, mid, 'heaven_binding_prison')
    engine = cold(service, mid)
    held = [c for c in engine.state.actors[TARGET].conditions.values()
            if c.condition_id == 'condition:typed.prison_tether']
    assert held
    assert held[0].data['source_cl'] == 18
    assert held[0].data['dc'] == 50
    assert held[0].data['radius_ft'] == 30


def native_tether(service, table, mid):
    for _ in range(8):
        commit(table, mid, '.weapon.', choose='tether')
        engine = cold(service, mid)
        held = [c for c in engine.state.actors[TARGET].conditions.values()
                if c.condition_id == 'condition:typed.meridian_tether']
        if held:
            return engine
        for _ in range(2):
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
    raise AssertionError('no qualifying committed chain hit')


def test_release_is_source_owned_free_and_replays(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration'])
    native_tether(service, table, mid)
    before = cold(service, mid).state.actors[OWNER].resources['resource:core.stamina']
    commit(table, mid, 'release_meridian_tether')
    engine = cold(service, mid)
    assert not any(c.condition_id == 'condition:typed.meridian_tether'
                   for c in engine.state.actors[TARGET].conditions.values())
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == before
    assert not any('release_meridian_tether' in g['source_definition_id'] for g in table.state(mid)['menu']['actions'])


def test_unowned_source_is_inert_after_committed_weapon_attack(tmp_path):
    service, table, mid = acquired_fight(tmp_path, [])
    commit(table, mid, '.weapon.')
    engine = cold(service, mid)
    assert not any(c.condition_id in {'condition:typed.meridian_tether', 'condition:typed.prison_tether'}
                   for actor in engine.state.actors.values() for c in actor.conditions.values())
    assert not any('release_meridian_tether' in a.source_definition_id for a in engine.action_catalog.values())


def test_network_willing_step_inside_reach_uses_one_normal_reaction(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration', 'thousand_link_meridian_network'],
                                       ask_reactions=True)
    native_tether(service, table, mid)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state = table.state(mid)
    menu = state['menu']
    assert menu['actor_id'] == TARGET
    move = next(m for m in menu['moves'] if m['destination'] == {'x': 4, 'y': 5})
    answers = []
    for _ in range(24):
        result = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            answer['option_ids'] = [prompt['choice']['options'][0]['id']]
        answers.append(answer)
    assert result['status'] == 'COMMITTED'
    engine = cold(service, mid)
    assert not engine.state.actors[OWNER].reaction_available
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER
               and e.sequence > state['last_sequence']]
    assert len(attacks) == 1
    assert sum('LEAVE_REACH' in str(answer.get('checkpoint', '')) for answer in answers) == 1


def test_prison_spatial_departure_uses_its_saved_dc_before_placement(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['heaven_binding_prison'], target_talents=['TAL_SPACE_FOLD_STEP'])
    commit(table, mid, 'heaven_binding_prison')
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    before = cold(service, mid)
    target = before.state.actors[TARGET]
    start = target.position.model_dump(mode='json')
    assert any(c.condition_id == 'condition:typed.prison_tether' for c in target.conditions.values())
    commit(table, mid, 'TAL_SPACE_FOLD_STEP', choose='cell:8,4', destination={'x': 8, 'y': 4})
    engine = cold(service, mid)
    assert engine.state.actors[TARGET].position.model_dump(mode='json') == start
    assert not engine.state.actors[TARGET].bonus_action_available
    assert engine.state.actors[TARGET].resources['resource:core.stamina'] == target.resources['resource:core.stamina'] - 1
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == TARGET]
    assert len(checks) == 1 and checks[0].payload['dc'] == 50
    assert checks[0].payload['success'] is False
    # The printed outcome is Failed Spatial Movement: the creature stays where it was and its activation and costs
    # are still spent. The log names that outcome instead of a bare "movement fails".
    said = [str(e.payload.get('log') or '') for e in engine.events
            if e.event_type == 'PASSIVE_TRIGGERED' and e.source_definition_id == checks[0].source_definition_id]
    assert any('Failed Spatial Movement' in line and 'stays where it was' in line for line in said), said


def test_prison_spatial_gate_only_stops_departures_outside_the_cylinder(tmp_path):
    """Boundary control for the prison's exit Cultivation Check: only spatial movement that would END outside the
    cylinder is gated, so the same creature's teleport inside the prison costs nothing."""
    from combat.ext import chain_tethers
    from combat.ext.move_limits import tether as bound_radius
    from combat.gate2_runtime_models import Position

    service, table, mid = acquired_fight(tmp_path, ['heaven_binding_prison'], target_talents=['TAL_SPACE_FOLD_STEP'])
    commit(table, mid, 'heaven_binding_prison')
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = cold(service, mid)
    target = engine.state.actors[TARGET]
    held = next(c for c in target.conditions.values() if c.condition_id == 'condition:typed.prison_tether')
    center, radius = bound_radius(engine, held, target)
    start = target.position
    checks = lambda: [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == TARGET
                      and e.payload.get('skill') == 'Cultivation Check']
    assert chain_tethers.tether_teleport(engine, target, start, Position(x=center.x, y=center.y, z=start.z), 'WILLING') is None
    assert checks() == []
    outside = Position(x=center.x + 20, y=center.y, z=center.z)
    assert engine.grid.distance_ft(outside, center) > radius
    assert chain_tethers.tether_teleport(engine, target, start, outside, 'WILLING') is False
    assert len(checks()) == 1


def test_source_walking_away_does_not_invent_hostile_forced_movement(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration'], target_at=(3, 3))
    native_tether(service, table, mid)
    state = table.state(mid)
    menu = state['menu']
    move = next(m for m in menu['moves'] if m['destination'] == {'x': 3, 'y': 10})
    answers = []
    for _ in range(24):
        result = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'USE'}
        if prompt.get('choice'):
            answer['option_ids'] = [prompt['choice']['options'][0]['id']]
        answers.append(answer)
    assert result['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = cold(service, mid)
    assert any(c.condition_id == 'condition:typed.meridian_tether'
               for c in engine.state.actors[TARGET].conditions.values())


def test_drag_resolves_one_native_creature_collision_with_its_dexterity_save(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration', 'drag_the_heavens'])
    engine = native_tether(service, table, mid)
    before = {aid: engine.state.actors[aid].current_hp for aid in (OWNER, TARGET)}
    stamina = engine.state.actors[OWNER].resources['resource:core.stamina']
    commit(table, mid, 'drag_the_heavens', choose='Pull 20 Feet')
    engine = cold(service, mid)
    assert engine.state.actors[TARGET].position.model_dump(mode='json') == {'x': 4, 'y': 4}
    assert engine.state.actors[TARGET].current_hp == before[TARGET] - 6
    assert engine.state.actors[OWNER].current_hp == before[OWNER] - 6
    assert engine.state.actors[OWNER].resources['resource:core.stamina'] == stamina - 1
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert len(saves) == 1
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
             and e.actor_id == TARGET and e.payload.get('forced')]
    assert moves and moves[-1].payload['source_actor_id'] == OWNER
    assert len(moves[-1].payload['path']) == 1
    assert next(c for c in engine.state.actors[TARGET].conditions.values()
                if c.condition_id == 'condition:typed.meridian_tether').data['hostile_forced'] == 0


def test_owner_senses_its_tethers_direction_at_the_start_of_its_turn(tmp_path):
    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration'])
    native_tether(service, table, mid)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    engine = cold(service, mid)
    senses = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED' and e.actor_id == OWNER
              and 'Meridian Tether: you sense' in str((e.payload or {}).get('log') or '')]
    assert senses, [(e.event_type, e.payload) for e in engine.events[-10:]]
    assert 'to the east' in senses[-1].payload['log']


def _chain_ids(features):
    """Subpath role names get this Subpath's prefix; a full path-feature id (Refined Iron Fist, Heavenly Fist) is used as is."""
    return [feature if feature.startswith('tianxia.') else CHAIN + feature for feature in features]


def _chain_engine(features, *, cl):
    from tests.test_riders_c7 import bundle, fight

    return fight(bundle(_chain_ids(features), cl=cl, items=(WHIP,)))


def test_refined_iron_fist_makes_the_integrated_chain_count_as_magical():
    from combat import typed_reactions

    me = 'actor:factory.c7'

    def counts(engine):
        weapon = next(action for action in engine.action_catalog.values()
                      if action.owner_id == me and '#integrated_con' not in action.source_definition_id
                      and (action.parameters.get('typed') or {}).get('source') == WHIP)
        return typed_reactions._counts_as_mundane(engine, {**weapon.parameters['typed'], 'mundane': True}, me)

    assert counts(_chain_engine(['chain_body_integration', 'tianxia.path.body_refining.feature.refined_iron_fist'], cl=5)) is False
    assert counts(_chain_engine(['chain_body_integration'], cl=5)) is True


def test_heavenly_fist_adds_force_to_the_integrated_chain_and_the_strike_commits_it():
    from tests.test_riders_c7 import answers, force_d20, payloads
    from combat.gate2_runtime_models import ActionIntent

    engine = _chain_engine(['chain_body_integration', 'tianxia.path.body_refining.feature.heavenly_fist'], cl=18)
    me = engine.state.actors['actor:factory.c7']
    foe = next(actor for actor in engine.state.actors.values() if actor.team_id != me.team_id)
    foe.armor_class = -50
    weapon = next(action for action in engine.action_catalog.values()
                  if action.owner_id == me.entity_id and '#integrated_con' not in action.source_definition_id
                  and (action.parameters.get('typed') or {}).get('source') == WHIP)
    assert 'FORCE' in (weapon.parameters['typed'].get('weapon') or {}).get('damage_types', [])
    answers(engine, {'heavenly_fist_type': ['FORCE']})
    force_d20(engine, 15, 15)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == me.entity_id
                     and foe.entity_id in (c.target_ids or ())
                     and not any(tag in c.source_definition_id for tag in ('#grapple', '#trip', '.pickup'))
                     and c.source_definition_id in engine.action_catalog
                     and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source') == WHIP)
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id='chain-force', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=me.entity_id,
        target_ids=candidate.target_ids, destination=candidate.destination))
    assert any(str(packet.get('damage_type')).upper() == 'FORCE' for packet in payloads(engine.events[start:], 'DAMAGE_COMMITTED'))


def test_heavenly_fist_doubles_chain_damage_to_an_unattended_object():
    from tests.test_riders_c7 import bundle, fight
    from combat.gate2_runtime_models import ActionIntent

    def attack(features):
        engine = fight(bundle(_chain_ids(features), cl=18, items=(WHIP,)),
                       objects=[{'id': 1, 'kind': 'crate', 'x': 4, 'y': 7, 'hp': 999, 'ac': 1, 'threshold': 20, 'unattended': True}])
        me = engine.state.actors['actor:factory.c7']
        action = next(a for a in engine.action_catalog.values()
                      if a.owner_id == me.entity_id and (a.parameters.get('typed') or {}).get('object_weapon_source') == WHIP)
        candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id
                         and 'object:map.1' in (c.target_ids or ()))
        before = engine.state.objects['object:map.1'].current_hp
        engine.execute_intent(ActionIntent(intent_id='chain-object', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=me.entity_id,
            target_ids=candidate.target_ids, destination=candidate.destination))
        rolled = [r for r in engine.rolls if str(r.reason).startswith('DAMAGE:') and ':object:' in str(r.reason)]
        return before - engine.state.objects['object:map.1'].current_hp, rolled[-1].total

    damage, rolled = attack(['chain_body_integration', 'tianxia.path.body_refining.feature.heavenly_fist'])
    assert damage == 2 * rolled  # double damage and Damage Threshold ignored
    control, _ = attack(['chain_body_integration'])
    assert control == 0  # the ordinary instance is under the object's Damage Threshold of 20


def test_prison_central_anchor_stats_and_appearance_damage_are_native(tmp_path):
    crate = {'id': 1, 'kind': 'crate', 'x': 2, 'y': 2, 'hp': 999, 'ac': 1, 'threshold': 0}
    service, table, mid = acquired_fight(tmp_path, ['heaven_binding_prison'], objects=(crate,))
    commit(table, mid, 'heaven_binding_prison')
    engine = cold(service, mid)
    anchor = next(obj for obj in engine.state.objects.values()
                  if 'anchor' in str((obj.component or {}).get('name') or '').lower())
    assert anchor.ac == 50
    assert anchor.maximum_hp == 90 and anchor.current_hp == 90
    assert {'BLUDGEONING', 'PIERCING', 'SLASHING'} <= set((anchor.component or {}).get('resist') or ())
    assert {'POISON', 'PSYCHIC'} <= set(anchor.damage_immunities or ())
    assert (anchor.component or {}).get('blocks') is False
    zone = next(z for z in engine.state.zones.values()
                if z.source_definition_id.endswith(CHAIN + 'heaven_binding_prison'))
    assert anchor.position == zone.center
    damaged = engine.state.objects['object:map.1']
    rolls = [r for r in engine.rolls if str(r.reason).startswith('DAMAGE:') and ':object' in str(r.reason)]
    assert rolls and 999 - damaged.current_hp == rolls[-1].total


def test_destroying_the_prison_anchor_ends_its_zone_restraint_and_tethers(tmp_path):
    from combat.ext.objects import deal

    service, table, mid = acquired_fight(tmp_path, ['heaven_binding_prison'])
    commit(table, mid, 'heaven_binding_prison')
    engine = cold(service, mid)
    anchor = next(obj for obj in engine.state.objects.values()
                  if 'anchor' in str((obj.component or {}).get('name') or '').lower())
    assert any(c.condition_id == 'condition:typed.prison_tether'
               for c in engine.state.actors[TARGET].conditions.values())
    deal(engine, engine.state.actors[OWNER], anchor, [(999, 'BLUDGEONING')], CHAIN + 'heaven_binding_prison')
    assert not any(c.condition_id == 'condition:typed.prison_tether'
                   for c in engine.state.actors[TARGET].conditions.values())
    assert not any(c.condition_id == 'condition:typed.restrained' and c.source_definition_id == CHAIN + 'heaven_binding_prison'
                   for c in engine.state.actors[TARGET].conditions.values())
    assert not any(z.active for z in engine.state.zones.values()
                   if z.source_definition_id.endswith(CHAIN + 'heaven_binding_prison'))


def test_rotation_interrupted_by_a_new_obstruction_resolves_one_collision(monkeypatch, tmp_path):
    from combat.ext import rider_movement

    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration', 'drag_the_heavens'])
    engine = native_tether(service, table, mid)
    before = {aid: engine.state.actors[aid].current_hp for aid in (OWNER, TARGET)}
    calls = []

    def interrupted(inner_engine, target, path, source, source_actor):
        calls.append(list(path))
        target.position = path[1]
        if len(path) > 2:  # something new moved into the route after it was chosen
            source_actor.position = path[2]

    monkeypatch.setattr(rider_movement, 'forced_route', interrupted)
    # Fourth printed failed-save result (the rotation); its label is eight words, which the public
    # copy scrambles, so pick it by printed position there and by name on the private tree.
    commit(table, mid, 'drag_the_heavens', choose='Swing It to a Space Within 20 Feet', choose_index=3)
    engine = cold(service, mid)
    assert calls and len(calls[-1]) > 2
    assert engine.state.actors[TARGET].current_hp == before[TARGET] - 6
    assert engine.state.actors[OWNER].current_hp == before[OWNER] - 6
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]) == 1


def test_severance_category_ends_both_tethers_through_the_shared_end_effect_route(tmp_path):
    from combat import typed_executor
    from combat.ext import end_effect

    service, table, mid = acquired_fight(tmp_path, ['chain_body_integration'])
    engine = native_tether(service, table, mid)
    category = {'categories': ['cultivation_binding'], 'select': 'any', 'on_success': 'end'}
    target = engine.state.actors[TARGET]
    assert end_effect.found(engine, target, category)
    action = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith('.release_meridian_tether'))
    ctx = typed_executor.Context(engine, engine.state.actors[OWNER], action, None,
                                 {'numbers': {'cl': 18}, 'source': CHAIN + 'chain_body_integration', 'effects': []}, [target], target)
    typed_executor.run_effects(ctx, [{'type': 'end_effect', 'applies_to': 'target', **category}])
    assert not any(c.condition_id == 'condition:typed.meridian_tether' for c in target.conditions.values())
