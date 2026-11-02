"""Review regressions use sealed setups, table intents and cold mechanical replay."""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, prompt_turn
from tests.test_a2_verdant_growth import SOW, OVER


@pytest.mark.parametrize('mode,altitude', [('fly', 0), ('fly', 1), ('walk', 1)])
@pytest.mark.parametrize('pick', [FOE, ALLY, None], ids=['selected', 'other-enemy-selected', 'choose-none'])
def test_overgrowth_committed_volume_movement_recipient_policy(tmp_path, monkeypatch, mode, altitude, pick):
    # A second hostile makes choosing another enemy distinct from choosing none.
    finish = CombatService._finish_factory_match
    def hostile_ally(self, bundles, ids, teams, positions, arena, allies, foes, **kwargs):
        teams = {**teams, ALLY: teams[FOE]}
        arena = deepcopy(arena)
        if mode == 'walk':
            # Native finite solid columns support a five-foot-high walking ledge.
            arena['terrain_regions'].append({'terrain_type': 'BLOCKED', 'height_ft': 5,
                'movement_cost': 1, 'cells': [{'x': x, 'y': y} for x, y in ((3, 6), (4, 6), (6, 6), (6, 5))]})
        return finish(self, bundles, ids, teams, positions, arena,
                      [a for a in allies if a != ALLY], [*foes, ALLY], **kwargs)
    monkeypatch.setattr(CombatService, '_finish_factory_match', hostile_ally)

    def mobility(bundles):
        for b in bundles:
            b['actor_template']['speed_ft'] = 10
            if b['actor_id'] == FOE and mode == 'fly':
                b['actor_template'].update(fly_speed_ft=10, hover=True)
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [SOW, OVER], bundle_transform=mobility, positions={
        OWNER: {'x': 3, 'y': 6, 'z': altitude if mode == 'walk' else 0},
        ALLY: {'x': 4, 'y': 6, 'z': altitude if mode == 'walk' else 0},
        FOE: {'x': 6, 'y': 6, 'z': altitude}})
    # Cast on the ledge's plane: a ground-level raster correctly excludes solid columns.
    engine = combat._load_session(mid).engine
    growth = next(c for c in engine.legal_candidates()
                  if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Cultivated Overgrowth'
                  and c.destination and (c.destination.x, c.destination.y, c.destination.z) ==
                      (5, 6, altitude if mode == 'walk' else 0))
    prompts = settle(table, mid, growth.candidate_id, {'choice:needle.growth_terrain': pick})
    terrain = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.growth_terrain')
    assert {o['id'] for o in terrain['choice']['options']} == {FOE, ALLY}
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    prompt_turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    actor = before.state.actors[FOE]
    destination = actor.position.model_copy(update={'y': 5})
    from combat.spatial_areas import zone_contains
    zone, = [z for z in before.state.zones.values() if z.active]
    assert zone_contains(before, actor, zone, at=destination)
    from combat.movement_routes import explicit_candidate
    move = explicit_candidate(before, FOE, (actor.position, destination), mode)
    remaining = actor.movement_remaining_ft
    answers = []
    for _ in range(10):
        menu = table.state(mid)['menu']
        result = table.act(mid, move.candidate_id, menu['decision_id'], menu['state_version'], 0, answers,
            movement_path=[p.model_dump(mode='json') for p in move.canonical_path],
            movement_mode=mode, actor_id=FOE)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
    else:
        raise AssertionError('Too many movement prompts')
    after = reload(tmp_path, mid)
    expected = 10 if pick == FOE else 5
    assert after.state.actors[FOE].position == destination
    assert remaining - after.state.actors[FOE].movement_remaining_ft == expected
    assert move.movement_cost_ft == expected
    event = next(e for e in reversed(after.events) if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE)
    assert event.payload['cost_ft'] == expected
