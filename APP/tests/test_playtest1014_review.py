"""Review regressions: effective canopy volume, and cones that never include their user's own space.

Owner 2026-10-18 removed the "include the cone's starting space" alternative: every cone starts on its user,
so it only meant hitting yourself.
"""
import pytest

from combat.gate4_adapters import ManualControllerAdapter
from tests import test_tabletop_hunt6 as H
from tests.test_playtest1014 import BREATH, cold
from tests.r10_fixup_support import commit


ORIGIN_LABEL = 'include the cone’s starting space'


@pytest.mark.parametrize('automatic', [False, True])
def test_cone_menu_has_no_self_hitting_alternative_and_spares_its_user(tmp_path, automatic):
    combat, table, mid = H.table_fight(tmp_path, [BREATH], cl=10,
                                      primary='Stamina', ally_talents=[])
    state = table.state(mid)
    groups = [g for g in state['menu']['actions'] if 'Hunger-Refining Breath' in g['label']]
    assert groups and not [g for g in groups if ORIGIN_LABEL in g['label']]
    cid = groups[0]['options'][0]['candidate_id']
    _, _, before = cold(tmp_path, mid)
    hp = before.state.actors[H.LEFT].current_hp
    if automatic:
        real = combat.controller
        class OriginController:
            def choose_primary_action(self, context):
                # This is also the engine-issued context offered to model seats.
                names = [c.display_name for c in context.legal_candidates]
                assert not any(ORIGIN_LABEL in n for n in names)
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = OriginController()
        combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='LOCAL_AUTO')
        send = lambda answers=(): table.auto_step(mid, 0, list(answers))
    else:
        send = lambda answers=(): table.act(mid, cid, state['menu']['decision_id'],
            state['menu']['state_version'], state['last_sequence'], list(answers))
    commit(send, lambda p: ('cell:8,4,0', True) if p.get('choice')
           and 'square' in p['context']['reaction_source_id'] else (None, False))
    _, _, engine = cold(tmp_path, mid)
    own_saves = [ev for ev in engine.events if ev.event_type == 'SAVE_ROLLED'
                 and ev.actor_id == H.LEFT and BREATH in ev.source_definition_id]
    assert not own_saves
    assert engine.state.actors[H.LEFT].current_hp == hp


@pytest.mark.parametrize('clip', ['footprint', 'suppressed', 'all'])
def test_canopy_path_respects_effective_volume(clip):
    from combat.gate2_runtime_models import Position, ZoneState
    from combat.spatial_areas import positions_inside_zone
    from combat.zone_attack_geometry import path_distance_ft
    from tests.h1_support import duel, ME, FOE
    engine = duel([])
    attacker, target = engine.state.actors[FOE], engine.state.actors[ME]
    attacker.position, target.position = Position(x=10, y=4, z=1), Position(x=3, y=4, z=1)
    center = Position(x=3, y=4)
    spec = {'shape': 'emanation', 'size_ft': 20}
    cells = engine.grid.cells_in_radius(center, 4)
    if clip == 'footprint':
        cells = (Position(x=3, y=4),)
        spec['footprint_is_authoritative'] = True
    else:
        spec['suppressed'] = [{'all': 1}] if clip == 'all' else [{'cells': [[4, 4], [5, 4], [6, 4]]}]
    zone = ZoneState(zone_id='test:clipped', source_definition_id='test:clipped', owner_id=ME,
        center=center, radius_cells=4, affected_cells=cells, concentration_link=False,
        created_round=1, trigger_profile=spec)
    assert path_distance_ft(engine, zone, attacker, target) == pytest.approx(0 if clip == 'all' else 2.5)
    assert positions_inside_zone(engine, ((3, 4, 1),), zone) == (clip != 'all')
    assert not positions_inside_zone(engine, ((4, 4, 1),), zone)


def test_cone_actions_have_no_origin_included_variants(tmp_path):
    from tests.test_playtest1014 import AUGMENT
    combat, table, mid = H.table_fight(tmp_path, [BREATH, AUGMENT], cl=10,
                                      primary='Stamina', ally_talents=[])
    engine = combat._load_session(mid).engine
    cones = [a for a in engine.action_catalog.values() if a.owner_id == H.LEFT
             and (a.parameters.get('typed') or {}).get('source') == BREATH
             and (a.parameters.get('typed') or {}).get('area')]
    assert len(cones) > 1  # ordinary and augmented casts are still offered
    assert not [a for a in engine.action_catalog.values() if a.source_definition_id.endswith('.origin_included')
                or a.parameters.get('targeting_variant_of')]


def test_cone_origin_loadout_choice_survives_reload(monkeypatch, tmp_path):
    from combat import loadout
    from tests.test_action_availability_persistence import priced_actions, BASE, COMBO
    from tests.test_lock_choices import install
    def cone_actions(info):
        return [action.model_copy(update={'parameters': {**action.parameters,
            'typed': {**action.parameters['typed'], 'area': {'shape': 'cone', 'size_ft': 30}}},
            'target_kind': 'CELL', 'range_ft': 30, 'radius_ft': 30}) for action in priced_actions(info)]
    install(monkeypatch, 'compile_actions', cone_actions)
    combat, table, mid = H.table_fight(tmp_path, [], primary='Stamina', ally_talents=[])
    H.on_hold(monkeypatch, lambda engine: loadout.toggle(engine, engine.state.actors[H.LEFT],
        BASE + H.LEFT, None, 'test:clear-augments'))
    from tests.test_lock2_persistence import act
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    _, _, engine = cold(tmp_path, mid)
    hidden = loadout.hidden(engine, engine.state.actors[H.LEFT])
    family, combo = BASE + H.LEFT, COMBO + H.LEFT
    assert loadout.chosen(engine.state.actors[H.LEFT], family) == []
    assert combo in hidden and family not in hidden


def test_cone_zone_leaves_its_user_outside_after_table_reload(monkeypatch, tmp_path):
    from combat import zones
    from combat.gate2_runtime_models import ActionDefinition
    from tests.test_lock_choices import install
    def cone_actions(info):
        return [ActionDefinition(source_definition_id='test:cone.' + info['actor_id'],
            display_name='Practice cone', owner_id=info['actor_id'], economy='ACTION',
            resolution_kind='TYPED', target_kind='CELL', range_ft=30, radius_ft=30,
            parameters={'typed': {'numbers': info['numbers'], 'effects': [],
                'area': {'shape': 'cone', 'size_ft': 30},
                'zone_spec': {'name': 'Practice cone', 'shape': 'cone', 'size_ft': 30,
                              'duration': {'kind': 'rounds', 'amount': 1}}}})]
    install(monkeypatch, 'compile_actions', cone_actions)
    combat, table, mid = H.table_fight(tmp_path, [], ally_talents=[])
    state = table.state(mid)
    source = 'test:cone.' + H.LEFT
    assert not [g for g in state['menu']['actions'] if g['source_definition_id'].endswith('.origin_included')]
    group = next(g for g in state['menu']['actions'] if g['source_definition_id'] == source)
    send = lambda answers=(): table.act(mid, group['options'][0]['candidate_id'],
        state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], list(answers))
    commit(send, lambda p: ('cell:8,4,0', True) if p.get('choice') else (None, False))
    _, _, engine = cold(tmp_path, mid)
    zone = next(z for z in zones.typed_zones(engine) if z.source_definition_id == source)
    actor = engine.state.actors[H.LEFT]
    assert not zones.actor_inside_zone(engine, actor, zone)
    assert actor.position not in zone.affected_cells
    assert not zone.trigger_profile.get('include_origin')
