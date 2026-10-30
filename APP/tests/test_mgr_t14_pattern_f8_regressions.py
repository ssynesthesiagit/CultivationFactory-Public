"""Map-edge placement and post-compilation learning through native seat APIs."""
import pytest

from combat.ext import formations, placed
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, settle, turn
from tests.test_mgr_t14_pattern_f6_regressions import finish


@pytest.mark.parametrize('start,owner,added', [
    ((0, 2), (1, 3), (0, 3)),  # west edge from the first choice
    ((2, 0), (3, 1), (3, 0)),  # north edge from the first choice
    ((1, 2), (1, 3), (0, 2)),  # expand from the interior onto the west edge
    ((2, 1), (3, 1), (2, 0)),  # expand from the interior onto the north edge
])
def test_trap_footprint_edges_commit_all_legal_choices_and_cold_replay(tmp_path, start, owner, added):
    arena = {'display_name': 'Trap edge yard', 'stable_id': 'trap:edge-yard',
             'width_squares': 10, 'height_squares': 10, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': []}
    combat, table, mid = fixture(tmp_path, ['TRAP_BASE_TRIPWIRE'], cl=10, battlefield=arena,
        positions={OWNER: {'x': owner[0], 'y': owner[1]}, ALLY: {'x': 8, 'y': 8}, FOE: {'x': 9, 'y': 8}})
    settle(table, mid, candidate(combat, mid, 'Trap form: Tripwire').candidate_id)
    prompts = settle(table, mid, candidate(combat, mid, 'Set Trap: choose footprint', at=start).candidate_id,
        {'choice:needle.trap_footprint': (f'cell:{added[0]},{added[1]},0', 'finish')})
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    trap, = placed.of(engine, 'trap')
    assert {(p.x, p.y) for p in trap.affected_cells} == {start, added}
    footprint_prompts = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.trap_footprint']
    assert len(footprint_prompts) == 2, 'The edge must also be safe on the next expansion'
    cells = [start]
    for prompt in footprint_prompts:
        expected = {f'cell:{x},{y},0' for x in range(10) for y in range(10)
                    if (x, y) not in cells and (x, y) != owner
                    and max(abs(x-owner[0]), abs(y-owner[1])) <= 1
                    and any(max(abs(x-a), abs(y-b)) == 1 for a, b in cells)}
        assert {o['id'] for o in prompt['choice']['options']} == {'finish', *expected}
        cells.append(added)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'


def assert_ai_pulse(service, mid):
    engine = CombatService(ROOT, service.userdata_root)._load_session(mid).engine
    policy, _ = service.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    def pulses(rows):
        return [c for c in rows if c.target_ids == (FOE,) and
                (a := engine.action_catalog.get(c.source_definition_id)) is not None and
                a.parameters.get(formations.TAG) == 'pulse' and a.parameters.get('pattern') == 'locking_gate']
    assert pulses(engine.legal_candidates())
    assert pulses(context.legal_candidates)


def array_choices(service, mid):
    engine = CombatService(ROOT, service.userdata_root)._load_session(mid).engine
    policy, _ = service.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    def sets(rows):
        return [c for c in rows if (a := engine.action_catalog.get(c.source_definition_id)) is not None
                and a.parameters.get(formations.TAG) == 'set']
    legal = sets(engine.legal_candidates())
    ai = sets(context.legal_candidates)
    patterns = {engine.action_catalog[c.source_definition_id].parameters['pattern'] for c in legal}
    # An owner with no array to place has no rows on either side (the callers
    # assert the learned/unlearned sets themselves).
    # AI seats receive one lazy placement root per ability instead of an eager row
    # per square (combat/placement_menu.py). Reachability is the root with its own
    # evaluated placement, for every array the owner may actually set.
    assert {engine.action_catalog[c.source_definition_id].parameters['pattern'] for c in ai} == patterns
    assert all(c.metadata.get('placement_picker') and c.metadata.get('placement_evaluation') for c in ai)
    return patterns


@pytest.mark.parametrize('source', ['combat', 'journey'])
def test_learned_combat_array_reaches_ai_context_and_journey_continuation(tmp_path, source):
    doc = sheet(['FORMATIONS_BASE_SET_ARRAY'], cl=5, kit={'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.gear.chalk', 'quantity': 1, 'name': 'Chalk'}]}})
    bundles = [compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True}),
               compile_character(sheet([], cl=5), actor_id=FOE)]
    service = CombatService(ROOT, tmp_path)
    arena = {'display_name': 'Learning yard', 'stable_id': 'formation:learning-yard',
             'width_squares': 12, 'height_squares': 12, 'square_size_ft': 5,
             'starting_positions': {}, 'terrain_regions': []}
    state = service.journeys.create(bundles, arena, {OWNER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}},
                                    {OWNER: 30, FOE: 30})
    jid = state['journey_id']
    if source == 'journey':
        options = service.journeys.load(jid).menu(OWNER)['options']
        learn, = [r for r in options if r['id'] == 'learn_pattern:locking_gate']
        state = service.journey_act(jid, state['revision'], OWNER, learn['kind'], learn['payload'])
        assert CombatService(ROOT, tmp_path).journeys.replay(jid)['status'] == 'PASS'
    mid = service.journey_start_scene(jid, state['revision'], {OWNER: 'party', FOE: 'party'},
                                       maximum_rounds=1)['match_id']
    table = TabletopService(service, tmp_path)
    turn(table, mid, OWNER)
    if source == 'combat':
        assert array_choices(service, mid) == set(), 'Unlearned patterns remain unavailable to AI'
        settle(table, mid, candidate(service, mid, 'Formation Training: learn Locking Gate').candidate_id,
               {'choice:needle.formation_first_pattern': 'locking_gate'})
    assert array_choices(service, mid) == {'locking_gate'}
    # Real seat action must still spend the Action/CP and persist the array.
    settle(table, mid, candidate(service, mid, 'Combat Array: Locking Gate', at=(4, 6)).candidate_id)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert len(formations.arrays(session.engine, OWNER)) == 1
    assert_ai_pulse(service, mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    # Combat Array Concentration lingers past the fight; the GM must confirm it ended before travel resumes.
    state = finish(service, table, mid, jid, effect_resolutions={OWNER: 'GM confirms the Combat Array has ended.'})
    # Recompilation/continuation must retain the learned pattern for AI too.
    mid = service.journey_start_scene(jid, state['revision'], {OWNER: 'party', FOE: 'party'},
                                       maximum_rounds=1)['match_id']
    turn(table, mid, OWNER)
    assert array_choices(service, mid) == {'locking_gate'}
    settle(table, mid, candidate(service, mid, 'Combat Array: Locking Gate', at=(4, 6)).candidate_id)
    assert_ai_pulse(service, mid)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
