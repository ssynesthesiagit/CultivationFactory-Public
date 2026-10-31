"""Public, synthetic table regressions for native reaction-route checkpoints."""
import copy
import json
from pathlib import Path
import zipfile

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
OWNER, FOE, OTHER = ['actor:factory.route-' + key for key in ('owner', 'foe', 'other')]
EMPTY = 'tianxia.subpath.body.drunken_fist.feature.empty_cup'
FLOWING = 'tianxia.subpath.qi.abyssal_depths_cultivator.feature.flowing_evasion'
WING = 'tianxia.subpath.body.white_heron_crescent_body.feature.white_wing_crosses_the_reed_field'
CROWN = 'tianxia.subpath.body.black_thorn_demon_body.feature.crown_of_black_thorns'
SLIP = 'foundation.weak_reed_tendons_v0_2B.reed_slip'
SPINE, REED = 'resource:named.demon_spine', 'resource:foundation.reed_flex'


def fixture(tmp_path, feature, *, positions=None, ignore_difficult=False):
    ids = [OWNER, FOE, OTHER]
    bundles = []
    for aid in ids:
        item = 'ji' if aid == OWNER and feature == WING else 'dao'
        document = sheet([feature] if aid == OWNER else [], cl=20, dc=50,
                         primary='Qi' if feature == FLOWING else 'Stamina',
                         kit={'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.' + item}]}})
        document['identity']['name'] = aid.rsplit('-', 1)[-1].title()
        stats = document['ability_scores_and_statistics']
        stats['hit_points']['maximum'] = 500
        stats['armor_class']['base_value'] = 1
        stats['technique_attack_bonus'] = 100
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
        bundle = compile_character(document, actor_id=aid, reaction_plan={'ask': True})
        if aid == OWNER:
            if ignore_difficult:
                bundle['typed_passives'].append({'feature_id': 'test:unimpeded',
                    'block': 'motion', 'kind': 'ignore_difficult'})
            for pool in bundle['actor_template']['resources']:
                if pool['resource_id'] in (SPINE, REED):
                    pool['initial'] = 1
            # Isolate the movement-time Reed spend from its separate Guard/Recovery.
            if feature == SLIP:
                bundle['typed_reactions'] = [r for r in bundle['typed_reactions'] if r['feature_id'] == SLIP]
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Route checkpoint yard', 'width_squares': 16,
        'height_squares': 12, 'walls': [], 'starts': {'team1': [[3, 6]], 'team2': [[4, 6]]}})
    arena = combat.factory_arenas(include_retired=True)['battlefield:map.route-checkpoint-yard']
    positions = positions or {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, OTHER: {'x': 12, 'y': 9}}
    mid = combat._finish_factory_match(bundles, ids, {OWNER: 'a', FOE: 'b', OTHER: 'b'},
        positions, arena, [OWNER], [FOE, OTHER], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='ROUTE-CHECKPOINT', display_name='Route checkpoint', maximum_rounds=15)['match_id']
    return combat, TabletopService(combat, tmp_path), mid


def engine(combat, mid):
    return combat._load_session(mid).engine


def send(table, mid, candidate, answers=()):
    state = table.state(mid)
    menu = state['menu']
    return table.act(mid, candidate, menu['decision_id'], menu['state_version'],
                     state['last_sequence'], list(answers))


def commit(table, mid, candidate, picks=None):
    answers, prompts = [], []
    for _ in range(30):
        result = send(table, mid, candidate, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        context = prompt['context']
        source = context.get('reaction_source_id', '')
        selected = picks(prompt) if picks else None
        answer = {**context, 'selection': 'DECLINE'}
        if selected is not None:
            answer.update(selection='USE', option_ids=selected)
        elif prompt.get('choice') and not prompt['choice'].get('allow_decline'):
            options = prompt['choice']
            answer.update(selection='USE', option_ids=options.get('preferred') or [options['options'][0]['id']])
        answers.append(answer)
    raise AssertionError('choice loop')


def turn(table, mid, actor):
    for _ in range(12):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == actor:
            return
        commit(table, mid, menu['end_turn'])
    raise AssertionError('turn not reached')


def attack(combat, mid, target):
    e = engine(combat, mid)
    return next(c.candidate_id for c in e.legal_candidates()
                if c.target_ids == (target,) and e.action_catalog.get(c.source_definition_id)
                and e.action_catalog[c.source_definition_id].display_name.startswith(('Dao', 'Ji')))


def move(combat, mid, x, y):
    return next(c for c in engine(combat, mid).legal_candidates()
                if c.kind.value == 'MOVE' and c.destination == Position(x=x, y=y))


def reload(combat, mid, tmp_path):
    session = combat._load_session(mid)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.engine.state.model_dump(mode='json') == fresh.engine.state.model_dump(mode='json')
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    assert not getattr(fresh.engine, '_rider_crossing', None)
    return fresh.engine


@pytest.mark.parametrize('feature', [EMPTY, FLOWING])
def test_reaction_crossing_is_offered_committed_and_reloaded(tmp_path, monkeypatch, feature):
    # With ordinary terrain prices the same crossing costs 15 feet; an
    # independent ignore-difficult grant makes it fit the printed 10-foot move.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [*ext._HOOKS.get('d20_result', ()),
        lambda *args: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20}])
    combat, table, mid = fixture(tmp_path, feature, ignore_difficult=True)
    turn(table, mid, FOE)
    before = copy.deepcopy(engine(combat, mid).state.actors[OWNER])
    def picks(prompt):
        source = prompt['context']['reaction_source_id']
        if 'empty_cup_move' in source or 'flowing_evasion_move' in source:
            assert 'cell:5,6' in [o['id'] for o in prompt['choice']['options']]
            return ['cell:5,6']
        if 'flowing_evasion_distance' in source:
            return ['10']
        if 'flowing_evasion' in source:
            return ['halve']
        if feature == EMPTY and EMPTY in source:
            return []
        return None
    prompts = commit(table, mid, attack(combat, mid, OWNER), picks)
    assert any('move' in p['context']['reaction_source_id'] for p in prompts)
    e = reload(combat, mid, tmp_path)
    actor = e.state.actors[OWNER]
    assert actor.position == Position(x=5, y=6)
    pool = 'resource:core.qi' if feature == FLOWING else 'resource:core.stamina'
    assert before.resources[pool] - actor.resources[pool] == 2
    assert not actor.reaction_available
    assert actor.movement_remaining_ft == before.movement_remaining_ft
    receipts = [ev for ev in e.events if ev.event_type == 'MOVEMENT_COMMITTED'
                and ev.actor_id == OWNER and ev.source_definition_id == feature]
    assert len(receipts) == 1 and receipts[0].payload['granted_cost_ft'] == 10
    assert {'x': 4, 'y': 6} in receipts[0].payload['path']
    assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.actor_id == OTHER for ev in e.events)


def test_white_wing_crosses_at_native_cost_and_only_exempts_its_target(tmp_path, monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [*ext._HOOKS.get('d20_result', ()),
        lambda *args: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20}])
    positions = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6}, OTHER: {'x': 3, 'y': 7}}
    combat, table, mid = fixture(tmp_path, WING, positions=positions)
    turn(table, mid, OWNER)
    before = engine(combat, mid).state.actors[OWNER].movement_remaining_ft
    def picks(prompt):
        source = prompt['context']['reaction_source_id']
        if 'white_wing_move' in source:
            return ['cell:5,6']
        if 'white_wing_result' in source:
            return ['ac']
        return None
    prompts = commit(table, mid, attack(combat, mid, FOE), picks)
    assert any(p['context'].get('reactor_id') == OTHER for p in prompts), prompts
    e = reload(combat, mid, tmp_path)
    assert e.state.actors[OWNER].position == Position(x=5, y=6)
    assert e.state.actors[OWNER].movement_remaining_ft == before
    receipt = next(ev for ev in e.events if ev.event_type == 'MOVEMENT_COMMITTED' and ev.source_definition_id == WING)
    assert receipt.payload['granted_cost_ft'] == 15
    assert any(m.value == 2 and m.source_definition_id == WING for m in e.state.actors[OWNER].modifiers.values())
    assert not any(p['context'].get('reactor_id') == FOE and 'opportunity' in str(p).lower() for p in prompts)


@pytest.mark.parametrize('split', [False, True])
def test_crown_stops_at_first_paid_step_and_accumulates_across_reload(tmp_path, split):
    positions = {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4 if split else 9, 'y': 6}, OTHER: {'x': 12, 'y': 9}}
    combat, table, mid = fixture(tmp_path, CROWN, positions=positions)
    turn(table, mid, FOE)
    if split:
        # One willing 5-foot move inside reach, then a cold reload.
        commit(table, mid, move(combat, mid, 4, 5).candidate_id)
        e = reload(combat, mid, tmp_path)
        assert e.state.actors[OWNER].resources[SPINE] == 1
        target = move(combat, mid, 2, 5)
        expected = target.canonical_path[1]
    else:
        target = move(combat, mid, 2, 6)
        e = engine(combat, mid)
        owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
        expected = next(cell for cell in target.canonical_path[1:]
                        if e._distance_actor_to_actor(owner, foe, target_position=cell) <= 5)
    def picks(prompt):
        return [] if CROWN in prompt['context']['reaction_source_id'] else None
    prompts = commit(table, mid, target.candidate_id, picks)
    assert any(CROWN in p['context']['reaction_source_id'] for p in prompts)
    e = reload(combat, mid, tmp_path)
    assert e.state.actors[FOE].position == expected
    assert e.state.actors[OWNER].resources[SPINE] == 0
    assert e.state.actors[OWNER].reaction_available
    assert any(c.condition_id == 'condition:typed.bleeding' for c in e.state.actors[FOE].conditions.values())
    resolved = [ev for ev in e.events if ev.event_type == 'REACTION_RESOLVED' and ev.source_definition_id == CROWN]
    assert len(resolved) == 1


@pytest.mark.parametrize('accept', [False, True])
def test_reed_slip_spends_only_preexisting_flex_and_not_a_reaction(tmp_path, accept):
    combat, table, mid = fixture(tmp_path, SLIP)
    turn(table, mid, OWNER)
    before = copy.deepcopy(engine(combat, mid).state.actors[OWNER])
    def picks(prompt):
        source = prompt['context']['reaction_source_id']
        if SLIP in source:
            return [] if accept else None
        if 'reed_slip_move' in source:
            return ['cell:2,6']
        if 'reed_slip_exempt' in source:
            return [FOE]
        return None
    commit(table, mid, move(combat, mid, 3, 5).candidate_id, picks)
    e = reload(combat, mid, tmp_path)
    actor = e.state.actors[OWNER]
    assert actor.position == Position(x=2 if accept else 3, y=6 if accept else 5)
    assert actor.resources[REED] == int(not accept)
    assert actor.reaction_available
    assert before.movement_remaining_ft - actor.movement_remaining_ft == (0 if accept else 5)
    assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.actor_id == FOE for ev in e.events)


def test_route_queries_keep_costs_blockers_endpoints_and_one_crossing(tmp_path):
    from combat.ext.rider_movement import routes, crossed, crossing, route_permission, consume_crossing, PassageRoute, step
    combat, _, mid = fixture(tmp_path, EMPTY)
    e = engine(combat, mid)
    actor, occupant = e.state.actors[OWNER], e.state.actors[FOE]
    before = copy.deepcopy(e.state.model_dump(mode='json')), list(e.events)
    # Required transit remains available even though going around is cheaper.
    offered = routes(e, actor, 15, through=[FOE], require_through=True)
    assert 'cell:5,6' in offered and crossed(e, actor, offered['cell:5,6'], FOE) == 1
    assert 'cell:4,6' not in offered
    assert 'cell:5,6' not in routes(e, actor, 10, through=[FOE], require_through=True)
    assert (e.state.model_dump(mode='json'), e.events) == before
    with crossing(e, actor, FOE):
        assert route_permission(e, actor, occupant) == 'difficult'
        actor.position = occupant.position
        consume_crossing(e, actor, occupant, None)
        consume_crossing(e, actor, occupant, None)
        assert route_permission(e, actor, occupant) == 'difficult'
        actor.position = Position(x=5, y=6)
        assert route_permission(e, actor, occupant) is None
    actor.position = Position(x=3, y=6)
    repeated = PassageRoute(tuple(Position(x=x, y=6) for x in (3, 4, 5, 4, 3)), 'walk', FOE)
    with pytest.raises(ValueError, match='one crossing'):
        step(e, actor, repeated, EMPTY)
    assert not getattr(e, '_rider_crossing', None)
