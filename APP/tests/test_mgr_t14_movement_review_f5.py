"""Review regressions at native acquisition, table, and cold-replay boundaries."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import (
    OWNER, ALLY, FOE, fixture, turn, settle, candidate, reload, sealed_native_attack,
)

SLAM = 'WRESTLING_BASE_APPLYING_A_SLAM'
EARTH = 'EARTH_BASE_SPENDING_A_BURDEN_MARK'
STEP = 'tianxia.subpath.qi.divination_cultivator.feature.predictive_step'


def test_ordinary_grapple_follows_a_step_directly_away_and_replays(tmp_path):
    # No Wrestling ownership: ordinary Unarmed Strike uses the same physical hold.
    owner = compile_character(sheet([], cl=18, key='STR', score=30), actor_id=OWNER,
                              reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner,
        foe_sheet=sheet([], cl=18, score=1), foe_position={'x': 3, 'y': 5},
        ally_position={'x': 1, 'y': 6}, seed='REVIEW-DRAG')
    settle(table, mid, candidate(combat, mid, 'Grapple', target=FOE).candidate_id,
           picks={'choice:needle.save_choice': 'STR', 'choice:needle.grapple_part': 'hand:left'})
    before = reload(tmp_path, mid)
    hold = next(c for c in before.state.actors[FOE].conditions.values()
                if c.condition_id == 'condition:typed.grappled')
    assert hold.data['native_grapple_steps'] == 1
    budget = before.state.actors[OWNER].movement_remaining_ft
    for y in (7, 8):
        engine = reload(tmp_path, mid)
        move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                    and (c.destination.x, c.destination.y, c.destination.z) == (3, y, 0))
        settle(table, mid, move.candidate_id)
        engine = reload(tmp_path, mid)
        assert hold.instance_id in engine.state.actors[FOE].conditions
        assert engine._distance_actor_to_actor(engine.state.actors[OWNER], engine.state.actors[FOE]) <= 5
    assert engine.state.actors[FOE].position != before.state.actors[FOE].position
    assert engine.state.actors[OWNER].movement_remaining_ft == budget - 20
    assert len([e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                and e.actor_id == FOE and e.payload.get('dragged_by') == OWNER]) == 2


def test_learned_slam_is_available_in_a_cold_ordinary_match(tmp_path):
    docs = {OWNER: sheet([SLAM], cl=18, primary='Stamina', key='STR', score=30),
            FOE: sheet([], cl=18, score=1)}
    for aid, doc in docs.items():
        path = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        path.mkdir(parents=True)
        with zipfile.ZipFile(path / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    def cold():
        return CombatService(ROOT, tmp_path)
    state = cold().create_journey(project_ids=[a.removeprefix('actor:factory.') for a in docs],
        arena_id=next(iter(cold().factory_arenas())),
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 3, 'y': 5}},
        base_paces={a: 3000 for a in docs})
    jid = state['journey_id']
    options = cold().journey_source_choices(jid, OWNER, SLAM)
    choice = next(o for o in options['options'] if o['payload']['talent_id'] == 'TAL_WRESTLING_HAMMERLOCK')
    cold().journey_acquire_source(jid, options['revision'], OWNER, SLAM, choice['payload'])
    # Ordinary match API, not journey_start_combat and not an injected bundle.
    result = cold().create_factory_match(project_ids=[OWNER.removeprefix('actor:factory.')],
        opponent_actor_ids=[FOE], control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'},
        match_seed='REVIEW-LEARNED-SLAM')
    mid = result['match_id']
    table = TabletopService(cold(), tmp_path)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert any(a.owner_id == OWNER and a.display_name == 'Apply a Slam: Hammerlock'
               for a in engine.action_catalog.values())
    assert not any(a.owner_id == FOE and a.display_name == 'Apply a Slam: Hammerlock'
                   for a in engine.action_catalog.values())
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert any(a.owner_id == OWNER and a.display_name == 'Apply a Slam: Hammerlock'
               for a in reload(tmp_path, mid).action_catalog.values())
    assert 'TAL_WRESTLING_HAMMERLOCK' not in docs[OWNER]['spheres_and_talents']['learned_talent_record_ids']
    assert cold().journey_source_choices(jid, OWNER, SLAM)['options'] == []


def test_independently_pushed_victim_still_ends_the_native_grapple(tmp_path):
    from tests.cw2_service_support import add_action
    owner = compile_character(sheet([], cl=18, key='STR', score=30), actor_id=OWNER,
                              reaction_plan={'ask': True})
    def actions(bundles):
        add_action(bundles[1], 'Review push', [{'type': 'push', 'distance_ft': 10}])
    combat, table, mid = fixture(tmp_path, [], owner_bundle=owner,
        foe_sheet=sheet([], cl=18, score=1), foe_position={'x': 3, 'y': 5},
        bundle_transform=actions, seed='REVIEW-INDEPENDENT-PUSH')
    settle(table, mid, candidate(combat, mid, 'Grapple', target=FOE).candidate_id,
           picks={'choice:needle.save_choice': 'STR', 'choice:needle.grapple_part': 'hand:left'})
    assert any(c.condition_id == 'condition:typed.grappled'
               for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Review push', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.grappled'
                   for c in engine.state.actors[FOE].conditions.values())
    assert any(e.event_type == 'CONDITION_REMOVED' and e.payload.get('reason') == 'OUT_OF_REACH'
               for e in engine.events)


@pytest.mark.parametrize('size,placement,area', [
    ('Large', 'cell:7,6', None),       # far edge of the actual 2x2 body
    ('Medium', 'cell:4,7', None),      # beside, rather than on, the attack ray
    ('Medium', 'cell:2,8', {'shape': 'sphere', 'size_ft': 10}),
    ('Medium', 'cell:2,8', {'shape': 'line', 'size_ft': 30, 'width_ft': 10}),
    ('Medium', 'cell:3,4', {'shape': 'wall', 'size_ft': 20}),
])
def test_ridge_complete_geometry_is_reachable_and_survives_commit(tmp_path, size, placement, area):
    from tests.cw2_service_support import add_action
    from tests.test_mgr_t14_committed_movement import native_burden
    foe = sheet([], cl=6, score=1)
    foe['identity']['size'] = size
    def actions(bundles):
        if area:
            add_action(bundles[2], 'Review area', [], target='CELL',
                       typed={'sphere': 'tianxia.sphere.earth', 'area': area})
        else:
            sealed_native_attack(bundles[2], 'Review ranged attack')
    combat, table, mid = fixture(tmp_path, [EARTH, 'EARTH_BASE_WEIGHT_SEEKING_CLOD'], cl=6,
        foe_sheet=foe, bundle_transform=actions,
        positions={OWNER: {'x': 2, 'y': 6}, ALLY: {'x': 1, 'y': 9}, FOE: {'x': 5, 'y': 6}})
    native_burden(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    action = candidate(combat, mid, 'Review area', at=(2, 6)) if area else candidate(
        combat, mid, 'Review ranged attack', target=OWNER)
    prompts = settle(table, mid, action.candidate_id,
        picks={'choice:needle.earth_ridge_space': placement, 'choice:needle.earth_response': 'ridge'})
    choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.earth_ridge_space')
    assert placement in {o['id'] for o in choice['choice']['options']}
    engine = reload(tmp_path, mid)
    ridge = next(c for c in engine.state.actors[OWNER].conditions.values()
                 if c.condition_id == 'condition:typed.earth_raised_ridge')
    assert (ridge.data['x'], ridge.data['y']) == tuple(map(int, placement.split(':')[1].split(',')))
    assert ridge.expires_on == 'START_OF_SOURCE_NEXT_TURN'


@pytest.mark.parametrize('signature', [
    'release_grips_fallback(ctx, available)', 'escape_grips_fallback(ctx, available)',
    'journey_initialize(session, actor_id)', 'journey_initialized(session)',
    'journey_rest_completed(session, actor_id, kind)',
])
def test_shared_hook_contracts_are_published(signature):
    contract = (ROOT / 'combat/ext/__init__.py').read_text()
    assert signature in contract
    assert 'primary empty list suppresses' in contract


def test_ridge_never_prompts_for_an_unperceived_marked_source(tmp_path, monkeypatch):
    from combat import senses
    from tests.test_mgr_t14_committed_movement import native_burden
    combat, table, mid = fixture(tmp_path, [EARTH, 'EARTH_BASE_WEIGHT_SEEKING_CLOD'], cl=6,
        bundle_transform=lambda bs: sealed_native_attack(bs[2], 'Review ranged attack'))
    native_burden(combat, table, mid, tmp_path)
    turn(table, mid, FOE)
    original = senses.perceives
    monkeypatch.setattr(senses, 'perceives', lambda engine, viewer, subject, *args, **kwargs:
        False if (viewer.entity_id, subject.entity_id) == (OWNER, FOE)
        else original(engine, viewer, subject, *args, **kwargs))
    prompts = settle(table, mid, candidate(combat, mid, 'Review ranged attack', target=OWNER).candidate_id)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.earth_ridge_space' for p in prompts)
    reload(tmp_path, mid)


def test_objective_admission_pill_names_ability_creatures_cost_and_duration(tmp_path):
    from combat.fact_consent_admission import CONDITION
    combat, table, mid = fixture(tmp_path,
        ['WARLEADER_BASE_MOMENTUM_MARKS', 'WARLEADER_BASE_SET_THE_STANDARD'], named=True)
    settle(table, mid, candidate(combat, mid, 'Identify an objective', target=FOE).candidate_id,
           picks={'choice:needle.fact_admission.objective': 'visible'})
    engine = reload(tmp_path, mid)
    label = next(c.data['label'] for c in engine.state.actors[OWNER].conditions.values()
                 if c.condition_id == CONDITION)
    for text in ('Warleader', 'Wren', 'Mara', 'No Action or resource cost', 'until removed'):
        assert text in label
    assert 'Source-scoped' not in label


def test_willingness_admission_pill_explains_the_specific_offer_and_expiry(tmp_path):
    from combat.fact_consent_admission import CONDITION
    combat, table, mid = fixture(tmp_path, [STEP], cl=11, named=True,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=ALLY).candidate_id,
        picks={'choice:needle.predictive_step': 'protect', 'choice:needle.fact_admission.willing': 'accept',
               'choice:needle.predictive_step_landing': 'cell:4,8'})
    engine = reload(tmp_path, mid)
    label = next(c.data['label'] for c in engine.state.actors[ALLY].conditions.values()
                 if c.condition_id == CONDITION)
    for text in ('Predictive Step', 'Wren', 'Tobin', 'No cost to you', 'end of this turn'):
        assert text in label
    assert 'Source-scoped' not in label
