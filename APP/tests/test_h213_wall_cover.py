"""Printed wall heights and attack-qualified cover across table commit/reload.

Wind Wall: '10 feet high' and 'Three-Quarters Cover against ordinary ranged
weapon attacks that pass through it.' Dune Wall instead protects against
'attacks and effects that pass through it.'
"""
import json
from pathlib import Path

import pytest

from combat import zones
from combat.attack_provenance import describe
from combat.directional_cover import tactical_cover
from combat.effect_cover import query
from combat.factory_compiler import _wall_fields, compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from tests.cw2_service_support import seal
from tests.h1_support import sheet
from tests.test_hidden_targeting import turn

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = 'actor:factory.wall-owner', 'actor:factory.wall-foe'
WIND = 'TAL_AIR_WIND_WALL'


def act(table, mid, predicate):
    state = table.state(mid)
    engine = table.combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if predicate(c))
    result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                       candidate.state_version, state['last_sequence'], [])
    assert result['status'] == 'COMMITTED', result


def fight(tmp_path, talent, *, altitude=0, foe_altitude=None, match_seed='H213-WALL'):
    kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.gong_jian', 'quantity': 1}]}}
    bundles = [compile_character(sheet([talent], kit=kit), actor_id=ME),
               compile_character(sheet(['AIR_BASE_WIND_LASH'], kit=kit), actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    document = {'display_name': 'Wall yard', 'width_squares': 12, 'height_squares': 12, 'walls': []}
    # Both fliers use legal native flight (fly speed + hover): the caster
    # hovers to aim the ground wall, and the elevated attacker stays at
    # altitude. An unsupported starting altitude settles back to the ground,
    # and this open yard has no walls, so no authored roof can exist here.
    if altitude:
        for bundle in bundles:
            bundle['actor_template'].update(fly_speed_ft=60, hover=True)
            seal(bundle)
    arena = to_battlefield(normalize_map(document))
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME: 'a', FOE: 'b'},
        {ME: {'x': 3, 'y': 6, 'z': altitude}, FOE: {'x': 7, 'y': 6, 'z': foe_altitude if foe_altitude is not None else altitude}},
        arena, [ME], [FOE], control_modes={ME: 'MANUAL', FOE: 'MANUAL'},
        match_seed=match_seed, display_name='Wall yard', maximum_rounds=5)['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, ME)
    act(table, mid, lambda c: talent in c.source_definition_id
        and c.destination == Position(x=5, y=6))
    session = combat._load_session(mid)
    created = [e for e in session.engine.events if e.event_type == 'ZONE_CREATED']
    assert created and created[-1].payload['zone']['trigger_profile']['wall']['height_ft'] == 10
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == session.engine.state
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return CombatService(ROOT, tmp_path), mid


@pytest.mark.parametrize('attack,altitude,expected', [
    ('bow', 0, 5), ('cultivation', 0, 0), ('bow', 3, 0),
])
def test_wind_wall_actual_attack_commit_and_cold_reload(tmp_path, attack, altitude, expected):
    combat, mid = fight(tmp_path, WIND, altitude=altitude)
    table = TabletopService(combat, tmp_path)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    source = next(a.source_definition_id for a in engine.action_catalog.values()
        if a.owner_id == FOE and (a.source_definition_id.endswith('.weapon.gong_jian')
            if attack == 'bow' else 'AIR_BASE_WIND_LASH' in a.source_definition_id))
    before = engine.state.model_dump(mode='json')
    action = engine.action_catalog[source]
    effects = action.parameters['typed']['effects']
    packet = next(e for e in effects if e['type'] == 'attack')
    descriptor = describe(engine, engine.state.actors[FOE], {'range_ft': action.range_ft,
        'parameters': action.parameters, 'checkpoint_context': {'effect': packet}}, source)
    assert tactical_cover(engine, engine.state.actors[FOE], engine.state.actors[ME],
        engine.state.actors[ME].position, [descriptor]) == expected
    assert query(engine, engine._actor_volume(engine.state.actors[FOE]), FOE,
                 engine.state.actors[ME], purpose='effect')['bonus'] == 0
    assert engine.state.model_dump(mode='json') == before
    act(table, mid, lambda c: c.source_definition_id == source and ME in c.target_ids)
    session = combat._load_session(mid)
    rolls = [e for e in session.engine.events if e.event_type == 'ATTACK_ROLLED'
             and e.actor_id == FOE and e.source_definition_id == source]
    assert rolls and all(e.payload['cover_bonus'] == expected for e in rolls)
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.state == session.engine.state
    assert cold.verify()['status'] == cold.mechanical.replay()['status'] == 'PASS'
    # A successful damaging attack may end Concentration; its recorded wall
    # profile must still survive the commit and cold reload in either case.
    [wall] = [z for z in cold.engine.state.zones.values() if z.trigger_profile.get('wall')]
    assert wall.trigger_profile['wall']['height_ft'] == 10
    assert wall.trigger_profile['wall']['cover_attack_kinds'] == ['weapon', 'weapon_ranged']


@pytest.mark.parametrize('altitude,expected', [(0, 5), (3, 0)])
def test_dune_wall_keeps_general_cover_below_its_printed_top(tmp_path, altitude, expected):
    combat, mid = fight(tmp_path, 'TAL_SAND_DUNE_WALL', altitude=altitude)
    engine = combat._load_session(mid).engine
    a, t = engine.state.actors[FOE], engine.state.actors[ME]
    assert engine._attack_defense(a, t, {'range_ft': 60,
        'parameters': {'attack_kind': 'cultivation_ranged'}})[0] == expected
    assert query(engine, engine._actor_volume(a), FOE, t)['bonus'] == expected


def test_dune_wall_grants_cover_to_the_sloped_shot_through_its_printed_height(tmp_path):
    """Dune Wall, printed: '30 feet long, 5 feet thick, and 10 feet high' and
    'The wall grants Three-Quarters Cover against attacks and effects that
    pass through it.' A ground archer's shot at a hovering target crosses the
    wall's interior between 5.625 and 9.375 feet -- inside its printed height
    -- so the shot keeps +5. The rounded 5-foot voxel sample used to place
    that column's only voxel above the span and report no cover at all."""
    combat, mid = fight(tmp_path, 'TAL_SAND_DUNE_WALL', altitude=3, foe_altitude=0)
    table = TabletopService(combat, tmp_path)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    source = next(k for k, a in engine.action_catalog.items() if a.owner_id == FOE
                  and a.source_definition_id.endswith('.weapon.gong_jian'))
    before = engine.state.model_dump(mode='json')
    action = engine.action_catalog[source]
    effect = next(e for e in action.parameters['typed']['effects'] if e['type'] == 'attack')
    descriptor = describe(engine, engine.state.actors[FOE],
        {'range_ft': action.range_ft, 'parameters': action.parameters,
         'checkpoint_context': {'effect': effect}}, source)
    a, t = engine.state.actors[FOE], engine.state.actors[ME]
    assert tactical_cover(engine, a, t, t.position, [descriptor]) == 5
    assert query(engine, engine._actor_volume(a), FOE, t, purpose='effect')['bonus'] == 5
    assert engine.state.model_dump(mode='json') == before
    act(table, mid, lambda c: c.source_definition_id == source and ME in c.target_ids)
    session = combat._load_session(mid)
    rolls = [e for e in session.engine.events if e.event_type == 'ATTACK_ROLLED'
             and e.actor_id == FOE and e.source_definition_id == source]
    assert rolls and all(e.payload['cover_bonus'] == 5 for e in rolls)
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.engine.state == session.engine.state
    assert cold.verify()['status'] == cold.mechanical.replay()['status'] == 'PASS'
    [wall] = [z for z in cold.engine.state.zones.values() if z.trigger_profile.get('wall')]
    assert wall.trigger_profile['wall']['height_ft'] == 10


@pytest.mark.parametrize('name,height', [
    ('lava wall', 10), ('dune wall', 10), ('blackglass rampart', 10),
    ('force wall', 10), ('wind wall', 10), ('humble wall', 3),
    ('raise the load-bearing wall', 10), ('scripture wall', 10),
    ('talisman wall', 10), ('puzzle wall', 15),
])
def test_every_printed_numeric_wall_height_survives_compilation(name, height):
    rules = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    # An authority entry may carry empty text (TAL_DARK_RAPID_MELD today);
    # an untitled entry cannot match a wall's first printed line.
    text = next(v for v in rules.values() if v.splitlines() and name in v.splitlines()[0].lower())
    assert f'{height} feet high' in text
    assert _wall_fields(zones.terrain_rules()['walls'][name])['height_ft'] == height


def test_cultivation_weapon_damage_is_not_an_ordinary_weapon_attack(tmp_path):
    combat, mid = fight(tmp_path, WIND)
    engine = combat._load_session(mid).engine
    a, t = engine.state.actors[FOE], engine.state.actors[ME]
    spec = {'range_ft': 60, 'typed': {'weapon': {'name': 'Bow'}},
        'parameters': {'attack_kind': 'weapon'}, 'checkpoint_context': {'effect': {
            'attack_kind': 'cultivation_ranged', 'on_hit': [{'weapon_damage': True}]}}}
    assert describe(engine, a, spec)['delivery'] == 'weapon'
    assert engine._attack_defense(a, t, spec)[0] == 0


def test_created_solid_wall_has_finite_sight_movement_and_zone_height_after_reload(tmp_path):
    combat, mid = fight(tmp_path, 'TAL_MAGMA_LAVA_WALL')
    engine = combat._load_session(mid).engine
    [wall] = zones.typed_zones(engine)
    assert not engine.grid.line_of_sight(Position(x=3, y=6), Position(x=7, y=6))
    assert engine.grid.line_of_sight(Position(x=3, y=6, z=3), Position(x=7, y=6, z=3))
    assert engine.grid.terrain_at((5, 6, 0), 'BLOCKED')
    assert not engine.grid.terrain_at((5, 6, 3), 'BLOCKED')
    actor = engine.state.actors[ME]
    assert zones.actor_inside_zone(engine, actor, wall, Position(x=5, y=6))
    assert not zones.actor_inside_zone(engine, actor, wall, Position(x=5, y=6, z=3))
