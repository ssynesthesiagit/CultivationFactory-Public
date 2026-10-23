"""Thousand-Mile Legs: imported source sheets, native table commits and recovery.

These combat regressions supply source-backed initial character sheets. They
do not certify the upstream character-creation acquisition workflow.
"""
import json

import pytest

from combat import flight, falling, roof_movement
from combat.gate2_runtime_models import Position
from tests.test_body_refining_choices import (
    ROOT, IRON_FIST, STOMPING_STEP, EXTRA_ATTACK, LEGS, ME, FOE, FIST, FOE_PROJECT,
    sheet, install, act, options, until_my_turn, reload_and_replay, stomp,
)
from combat.ext.athletics import VAULTER
from combat.ext.qi_subpaths_five import FEATHER
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

# Literal dynamic inputs needed by the safe exporter, not replacement policies.
RUNTIME_INPUTS = (
    'combat/rules/feature_blocks.json',
    'combat/rules/feature_blocks.d/riders_c7.json',
    'combat/rules/feature_blocks.d/body.json',
    'combat/rules/typed_conditions.json',
    'combat/rules/terrain.json',
    'static/tabletop/map-heights.json',
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
    'authority/typed_mechanics/rules_text.json',
)


def game(root, *, owns=True, walls=False, liquid=False, difficult=False, cl=3, foe_x=8, talents=(), kit=None,
         features=()):
    owner = sheet(path=((IRON_FIST, STOMPING_STEP, LEGS) if owns else (IRON_FIST, STOMPING_STEP)) + tuple(features),
                  cl=cl, talents=talents)
    if kit is not None:
        owner['equipment'] = [kit]
    if cl >= 5:
        owner['path_and_subpath']['path_feature_record_ids'].append(EXTRA_ATTACK)
    owner['identity']['proficiency_bonus'] = 2 if cl < 5 else 3
    stats = owner['ability_scores_and_statistics']
    for row in stats['abilities']:
        if row['ability'] == 'STR':
            row.update(score=14, modifier=2)
    stats['initiative'] = {'bonus': 100}
    stats['hit_points']['maximum'] = 100
    install(root, FIST, owner)
    install(root, FOE_PROJECT, sheet(path=(), cl=3, ac=0, name='Training opponent'))
    combat = CombatService(ROOT, root)
    doc = {'display_name': 'Thousand mile native yard', 'width_squares': 18, 'height_squares': 12,
           'starts': {'team1': [[3, 4]], 'team2': [[foe_x, 4]]}, 'walls': [], 'terrain': []}
    if walls:
        doc['walls'] = [{'shape': 'line', 'points': [[4, 2], [4, 8]],
                        'blocks': 'sight_and_movement', 'height_ft': 20}]
    if liquid:
        doc['terrain'].append({'type': 'LIQUID', 'height_ft': 10,
                               'cells': [[x, y] for x in (1, 2) for y in (3, 4, 5)]})
    if difficult:
        doc['terrain'].append({'type': 'DIFFICULT', 'cells': [[5, 4], [6, 4]]})
    saved = combat.tabletop_maps.save(doc)
    match = combat.create_factory_match(project_ids=[FIST], opponent_actor_ids=[FOE],
        control_modes={ME: 'MANUAL', FOE: 'MANUAL'}, arena_id='battlefield:map.' + saved['map_id'],
        match_seed='THOUSAND-MILE-NATIVE', maximum_rounds=8)
    mid = match['match_id']
    until_my_turn(combat, mid)
    return combat, TabletopService(combat, root), mid


def move(combat, table, mid, xyz, mode='walk'):
    e = combat._load_session(mid).engine
    c = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination == Position(x=xyz[0], y=xyz[1], z=xyz[2])
             and c.metadata.get('movement_mode', 'walk') == mode)
    act(table, mid, c.candidate_id, table.state(mid)['menu'], lambda p: None)
    return c


def test_reviewed_authority_keeps_the_whole_record_and_no_gm_rider():
    """The compiled authority row is this ability's mechanics record.

    It must leave no clause to the GM (the old traversal rider is gone) and it must stay fully typed
    instead of falling back to a rider. Only structural fields are read: the public export rewrites
    the printed prose (rules_text.json's digest and the row's description both change there), so a
    literal text assertion is not portable (F13RSC finding 2).
    """
    row = json.loads((ROOT / RUNTIME_INPUTS[-2]).read_text())['mechanics'][LEGS]
    assert row['riders'] == []
    assert row['coverage'] == 'FULL' and row['typing_status'] == 'reviewed_final'
    effects = row['effects']
    assert len(effects) == 1
    assert (effects[0]['type'], effects[0]['kind'], effects[0]['role']) == ('path_passive', 'sky_treading', 'legs')


def test_calculated_height_multiplier_is_inside_the_final_tripling(tmp_path):
    """Strength 14 + Light as a Feather (score height x3 = 15 feet) + Thousand-Mile Legs.

    The printed procedure triples the calculated height, so the running-start-free 15-foot jump becomes
    45 feet (9 grid steps). Counting the feather's ten extra feet as a separate fixed-distance grant
    instead quoted 25 feet (5 steps), because the extra feet escaped the final multiplier.
    """
    combat, table, mid = game(tmp_path, features=(FEATHER,))
    e = combat._load_session(mid).engine
    a = e.state.actors[ME]
    assert flight.jump_measure(e, a) == (14, 15, 0)
    assert flight.jump_steps(e, a, (a.position,)) == 9  # 45 feet


def test_standing_long_and_high_jumps_use_final_feet_and_native_payment(tmp_path):
    combat, table, mid = game(tmp_path)
    e = combat._load_session(mid).engine
    a = e.state.actors[ME]
    assert e._effective_speed(a) == 40
    assert flight.horizontal_jump_feet(e, a) == 42
    assert flight.jump_steps(e, a, (a.position,)) == 3  # (3 + STR +2) *3 =15, not rounded before tripling
    before = a.movement_remaining_ft
    move(combat, table, mid, (3, 4, 3), 'jump')
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].position.z == 0
    assert e.state.actors[ME].movement_remaining_ft == before - 15


def test_long_jump_is_a_native_route_and_does_not_extend_its_movement_budget(tmp_path):
    combat, table, mid = game(tmp_path)
    e = combat._load_session(mid).engine
    start = e.state.actors[ME].position
    move(combat, table, mid, (10, 6, 0), 'jump')
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].movement_remaining_ft == 5
    assert e.state.actors[ME].position != start


@pytest.mark.parametrize('choice', ['dash', 'disengage'])
def test_step_wall_liquid_support_expires_and_falls_after_reload(tmp_path, choice):
    combat, table, mid = game(tmp_path, walls=True, liquid=True)
    e = combat._load_session(mid).engine
    assert not any(c.destination and c.destination.z for c in e.legal_candidates() if c.metadata.get('movement_mode') == 'climb')
    stomp(table, combat, mid, choice)
    move(combat, table, mid, (3, 4, 2), 'climb')
    e = reload_and_replay(tmp_path, combat, mid)
    a = e.state.actors[ME]
    assert a.position.z == 2 and falling.supported(e, a) and not a.climbing
    assert flight.profile(e, a).speed_ft == 0
    assert roof_movement.profile(e, a).speed_ft == 40
    move(combat, table, mid, (2, 4, 2))
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].position == Position(x=2, y=4, z=2)
    # The grant names physical surfaces; it never supplies unrestricted air.
    assert not falling.supported(e, e.state.actors[ME], Position(x=0, y=4, z=2))
    act(table, mid, table.state(mid)['menu']['end_turn'], table.state(mid)['menu'], lambda p: None)
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].position.z == 0
    assert any(row.event_type == 'MOVEMENT_COMMITTED' and row.source_definition_id == 'system:combat.falling' for row in e.events)
    assert not any(c.source_definition_id == LEGS for c in e.state.actors[ME].conditions.values())


def test_no_owner_no_surface_capability_or_jump_multiplier(tmp_path):
    combat, table, mid = game(tmp_path, owns=False, walls=True, liquid=True)
    stomp(table, combat, mid, 'dash')
    e = reload_and_replay(tmp_path, combat, mid)
    a = e.state.actors[ME]
    assert e._effective_speed(a) == 30
    assert flight.horizontal_jump_feet(e, a) == 7
    assert flight.jump_steps(e, a, (a.position,)) == 0
    assert not falling.supported(e, a, Position(x=2, y=4, z=2))
    assert not roof_movement.profile(e, a).terrain_faces


@pytest.mark.parametrize('followup', ['walk', 'jump'])
def test_voluntary_twenty_feet_hit_pb_step_after_damage_once_per_turn(tmp_path, followup):
    combat, table, mid = game(tmp_path, difficult=True, cl=5)
    stomp(table, combat, mid, 'dash')
    e = combat._load_session(mid).engine
    assert next(c for c in e.legal_candidates() if c.destination == Position(x=7, y=4)
                and c.metadata.get('movement_mode', 'walk') == 'walk').movement_cost_ft == 20
    move(combat, table, mid, (7, 4, 0))
    e = reload_and_replay(tmp_path, combat, mid)
    a = e.state.actors[ME]
    remaining = a.movement_remaining_ft
    strike = next(c for c in e.legal_candidates() if c.source_definition_id.endswith('.natural.iron_fist') and FOE in c.target_ids)
    start = len(e.events)
    def answer(prompt):
        if prompt['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step':
            assert any(row['label'].startswith('Jump ') for row in prompt['choice']['options'])
            # Every offered route, including horizontal jump routes, must stay
            # within the follow-up's five-foot grant.
            origin = e.state.actors[ME].position
            for row in prompt['choice']['options']:
                coords = row['id'].removeprefix('cell:').split(':')[0].split(',')
                x, y = map(int, coords[:2])
                z = int(coords[2]) if len(coords) > 2 else origin.z
                distance = max(abs(x-origin.x), abs(y-origin.y), abs(z-origin.z)) * e.grid.square_size_ft
                assert distance <= 5, row
            if followup == 'jump':
                return [row['id'] for row in prompt['choice']['options']
                        if row['label'] == 'Jump to 7,4 at 5 ft. altitude']
            return ['cell:7,5']
        return options(prompt)[:1] if prompt.get('choice') else None
    prompts = act(table, mid, strike.candidate_id, table.state(mid)['menu'], answer)
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step' for p in prompts) == 1
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].position == Position(x=7, y=5 if followup == 'walk' else 4)
    assert e.state.actors[ME].movement_remaining_ft == remaining
    events = e.events[start:]
    step = next(i for i, row in enumerate(events) if row.event_type == 'MOVEMENT_COMMITTED' and row.source_definition_id == LEGS)
    assert any(row.event_type == 'DAMAGE_COMMITTED' and row.actor_id == ME for row in events[:step])
    packets = [row for row in events if row.event_type == 'DAMAGE_COMMITTED' and row.actor_id == ME]
    assert len(packets) == 2
    # Exact PB, not a loose damage floor: the qualifying first hit and the later Extra Attack in the same
    # action share every modifier except the once-per-turn Proficiency Bonus.
    rolled = [row for row in events if row.event_type == 'DAMAGE_ROLLED' and row.actor_id == ME
              and row.source_definition_id.endswith('.natural.iron_fist')]
    assert len(rolled) == 2
    assert rolled[0].payload['modifier'] - rolled[1].payload['modifier'] == e.state.actors[ME].proficiency_bonus
    # The first hit has resolved before moving; the second Extra Attack remains
    # after the movement and cannot trigger a second PB contribution or step.
    assert len([row for row in events[:step] if row in packets]) == 1
    assert not any(row.event_type == 'ATTACK_ROLLED' and row.actor_id == FOE
                   and 'opportunity' in row.source_definition_id for row in events)
    assert e.state.actors[ME].turn_flags['_round_thousand_mile']


@pytest.mark.parametrize('axis', ['vertical', 'horizontal'])
def test_tripling_precedes_a_separate_fixed_jump_distance_feature(tmp_path, axis):
    """Strength 14 + Polearm Vaulter: the printed rule triples the calculated distance *before* a
    feature that supplies a separate fixed jump distance, so the Vaulter feet are not tripled.
    Without the fix this quotes 30-foot high jumps / 72-foot long jumps instead of 20 / 52."""
    import combat.ext.athletics as athletics
    combat, table, mid = game(tmp_path, cl=5, talents=(VAULTER,),
                              kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.qiang',
                                                               'name': 'Qiang (Spear)', 'quantity': 1}]}})
    e = combat._load_session(mid).engine
    a = e.state.actors[ME]
    a.resources[athletics.FOCUS] = 1
    feet = 5 if axis == 'vertical' else 10
    name = f"Polearm Vaulter: jump {feet} feet " + ('higher' if axis == 'vertical' else 'farther')
    e = combat._load_session(mid).engine
    candidate = next(c for c in e.legal_candidates() if c.display_name == name)
    act(table, mid, candidate.candidate_id, table.state(mid)['menu'],
        lambda p: options(p)[:1] if p.get('choice') else None)
    e = combat._load_session(mid).engine
    a = e.state.actors[ME]
    assert any(c.condition_id == athletics.VAULTER_JUMP for c in a.conditions.values()), name
    if axis == 'vertical':
        # 5ft calculated x3 = 15, then the fixed +5 the Vaulter bought.
        assert flight.jump_steps(e, a, (a.position,)) == 4  # 20 feet
    else:
        # STR 14 = 14ft x3 = 42, then the fixed +10 the Vaulter bought.
        assert flight.horizontal_jump_feet(e, a) == 52


def test_unmodified_owner_jumps_are_unchanged_by_the_fixed_distance_ordering(tmp_path):
    """A creature with no fixed-distance feature keeps the exact prior numbers."""
    combat, table, mid = game(tmp_path)
    e = combat._load_session(mid).engine
    a = e.state.actors[ME]
    assert flight.horizontal_jump_feet(e, a) == 42  # 14ft x3
    assert flight.jump_steps(e, a, (a.position,)) == 3  # (3 + STR 2) x3 = 15 feet


def test_ally_exclusion_at_hook_boundary_after_qualifying_movement(monkeypatch):
    """The after-hit gate must reject a same-team target even on a qualified turn."""
    from types import SimpleNamespace
    from combat.ext.sky_treading import tendon_hits
    import combat.ext.sky_treading as sky_treading
    import combat.typed_executor as typed_executor

    actor = SimpleNamespace(
        entity_id='owner', active=True, team_id='same', proficiency_bonus=2,
        resources={}, turn_flags={},
    )
    target = SimpleNamespace(entity_id='ally', active=True, team_id='same')
    row = {'role': 'legs', 'block': 'path_rider', 'kind': 'sky_treading',
           'feature_id': sky_treading.PREFIX + 'thousand_mile_legs'}
    engine = SimpleNamespace(
        typed_passive_rows={'owner': [row]},
        state=SimpleNamespace(round_number=1, current_actor_id='owner'),
    )
    calls = []
    monkeypatch.setattr(sky_treading, 'moved_this_turn', lambda *_: 20)
    monkeypatch.setattr(typed_executor, 'run_effects', lambda *args, **kwargs: calls.append(args))
    ctx = SimpleNamespace(
        engine=engine, actor=actor, typed={}, numbers={}, source='attack',
        action=SimpleNamespace(display_name='Unarmed Strike'),
        on_hit_context=lambda *args, **kwargs: object(),
    )
    tendon_hits(ctx, target, 'unarmed')
    assert calls == []
    assert '_round_thousand_mile' not in actor.turn_flags


def test_unarmed_hit_on_a_flipped_team_ally_gets_no_legs_rider_or_step(tmp_path):
    # This route moves only 15 feet before the hit, and the in-memory team flip is discarded when the
    # table commit re-reads the fight from disk, so it proves the ordinary (non-qualifying) path: one
    # strike packet, no rider and no step. The 20-foot ally gate itself has a direct damage-hook
    # regression below; a real 20+ foot ally strike is not offered by the engine's own targeting.
    combat, table, mid = game(tmp_path, cl=5, foe_x=7)
    move(combat, table, mid, (6, 4, 0))
    e = combat._load_session(mid).engine
    c = next(c for c in e.legal_candidates()
             if c.source_definition_id.endswith('.natural.iron_fist') and FOE in c.target_ids)
    menu = table.state(mid)['menu']
    ally = e.state.actors[FOE]
    ally.team_id = e.state.actors[ME].team_id
    start_position = e.state.actors[ME].position
    start_hp = ally.current_hp
    prompts = act(table, mid, c.candidate_id, menu,
                  lambda p: options(p)[:1] if p.get('choice') else None)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step'
                   for p in prompts)
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].position == start_position
    assert '_round_thousand_mile' not in e.state.actors[ME].turn_flags
    assert e.state.actors[FOE].current_hp < start_hp  # the ordinary unarmed hit still resolves
    packets = [row for row in e.events if row.event_type == 'DAMAGE_COMMITTED' and row.actor_id == ME]
    assert len(packets) == 1  # only the ordinary strike packet; no separate Proficiency Bonus rider


SPEAR_KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.qiang', 'name': 'Qiang (Spear)', 'quantity': 1}]}}


def weapon_strike(combat, table, mid):
    """The plain weapon attack on FOE (never the natural unarmed strike); takes the spear in hand first if needed."""
    e = combat._load_session(mid).engine
    for c in e.legal_candidates():
        if str(getattr(e.action_catalog.get(c.source_definition_id), 'display_name', '')).startswith('Draw '):
            act(table, mid, c.candidate_id, table.state(mid)['menu'], lambda p: None)
            e = combat._load_session(mid).engine
            break
    for c in e.legal_candidates():
        if tuple(c.target_ids) != (FOE,) or c.kind.value in ('MOVE', 'END_TURN') or c.source_definition_id.endswith('.natural.iron_fist'):
            continue
        name = str(getattr(e.action_catalog.get(c.source_definition_id), 'display_name', '')).lower()
        if 'attack' in name and '+' not in name and ':' not in name:
            return c
    raise AssertionError('no plain weapon attack on FOE')


def test_damage_hook_ignores_an_ally_target_on_a_qualified_turn(monkeypatch):
    """Direct damage-hook gate: removing the ally check from thousand_mile_damage must fail this test."""
    from types import SimpleNamespace
    import combat.ext.sky_treading as sky_treading
    actor = SimpleNamespace(entity_id='owner', active=True, team_id='same', proficiency_bonus=3,
                            resources={}, turn_flags={})
    ally = SimpleNamespace(entity_id='ally', active=True, team_id='same')
    row = {'role': 'legs', 'block': 'path_rider', 'kind': 'sky_treading',
           'feature_id': sky_treading.PREFIX + 'thousand_mile_legs'}
    engine = SimpleNamespace(typed_passive_rows={'owner': [row]},
                             state=SimpleNamespace(round_number=1, current_actor_id='owner'))
    monkeypatch.setattr(sky_treading, 'moved_this_turn', lambda *_: 20)
    ctx = SimpleNamespace(engine=engine, actor=actor, source='attack')
    assert sky_treading.thousand_mile_damage(ctx, ally, {'attack_kind': 'unarmed'}) is None
    assert '_round_thousand_mile' not in actor.turn_flags
    assert '_round_thousand_mile_pending' not in actor.turn_flags


def test_weapon_hit_after_twenty_feet_neither_gets_nor_reserves_the_unarmed_bonus(tmp_path):
    """Review blocker: a spear hit after 20 feet of voluntary movement must not take PB or stamp the turn flag.
    The next unarmed strike still gets exactly PB in its own packet and its 5-foot step; a later turn with no
    movement gets none."""
    combat, table, mid = game(tmp_path, difficult=True, cl=5, kit=SPEAR_KIT)
    stomp(table, combat, mid, 'dash')
    move(combat, table, mid, (7, 4, 0))
    reload_and_replay(tmp_path, combat, mid)
    c = weapon_strike(combat, table, mid)
    start = len(combat._load_session(mid).engine.events)
    prompts = act(table, mid, c.candidate_id, table.state(mid)['menu'],
                  lambda p: options(p)[:1] if p.get('choice') else None)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step' for p in prompts)
    e = reload_and_replay(tmp_path, combat, mid)
    flags = e.state.actors[ME].turn_flags
    assert '_round_thousand_mile' not in flags and '_round_thousand_mile_pending' not in flags
    weapon_rolls = [row for row in e.events[start:] if row.event_type == 'DAMAGE_ROLLED' and row.actor_id == ME]
    assert weapon_rolls and not any(row.source_definition_id.endswith('.natural.iron_fist') for row in weapon_rolls)

    start = len(e.events)
    prompts = strike(combat, table, mid, step='cell:7,5')
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step' for p in prompts) == 1
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].position == Position(x=7, y=5)
    assert e.state.actors[ME].turn_flags['_round_thousand_mile']
    qualifying = next(row for row in e.events[start:] if row.event_type == 'DAMAGE_ROLLED' and row.actor_id == ME
                      and row.source_definition_id.endswith('.natural.iron_fist'))

    # Control: the same unarmed strike on a later own turn with no voluntary movement carries no PB.
    next_own_turn(combat, table, mid)
    e = combat._load_session(mid).engine
    start = len(e.events)
    prompts = strike(combat, table, mid)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step' for p in prompts)
    e = reload_and_replay(tmp_path, combat, mid)
    control = next(row for row in e.events[start:] if row.event_type == 'DAMAGE_ROLLED' and row.actor_id == ME
                   and row.source_definition_id.endswith('.natural.iron_fist'))
    assert qualifying.payload['modifier'] - control.payload['modifier'] == e.state.actors[ME].proficiency_bonus


def next_own_turn(combat, table, mid):
    act(table, mid, table.state(mid)['menu']['end_turn'], table.state(mid)['menu'], lambda p: None)
    for _ in range(8):
        if combat._load_session(mid).engine.state.current_actor_id == ME:
            return
        act(table, mid, table.state(mid)['menu']['end_turn'], table.state(mid)['menu'], lambda p: None)
    raise AssertionError('The owner did not receive another turn')


def strike(combat, table, mid, *, step=None):
    e = combat._load_session(mid).engine
    c = next(c for c in e.legal_candidates() if c.source_definition_id.endswith('.natural.iron_fist') and FOE in c.target_ids)
    def answer(p):
        if p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step':
            return [step] if step else None
        return options(p)[:1] if p.get('choice') else None
    return act(table, mid, c.candidate_id, table.state(mid)['menu'], answer)


def test_threshold_and_new_turn_reset_and_free_step_after_all_movement_is_spent(tmp_path):
    combat, table, mid = game(tmp_path, cl=5, foe_x=7)
    move(combat, table, mid, (6, 4, 0))  # only15 actual feet before the hit
    prompts = strike(combat, table, mid)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step' for p in prompts)
    e = reload_and_replay(tmp_path, combat, mid)
    assert '_round_thousand_mile' not in e.state.actors[ME].turn_flags
    next_own_turn(combat, table, mid)
    move(combat, table, mid, (6, 8, 0))
    move(combat, table, mid, (6, 4, 0))
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].movement_remaining_ft == 0
    start = len(e.events)
    prompts = strike(combat, table, mid, step='cell:5,4')
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step' for p in prompts) == 1
    e = reload_and_replay(tmp_path, combat, mid)
    assert e.state.actors[ME].position == Position(x=5, y=4)
    assert e.state.actors[ME].movement_remaining_ft == 0
    assert not any(row.event_type == 'ATTACK_ROLLED' and row.actor_id == FOE
                   and 'opportunity' in row.source_definition_id for row in e.events[start:])
    next_own_turn(combat, table, mid)
    move(combat, table, mid, (6, 4, 0))  # prior turn's40feet cannot qualify this hit
    prompts = strike(combat, table, mid)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.thousand_mile_step' for p in prompts)
    reload_and_replay(tmp_path, combat, mid)
