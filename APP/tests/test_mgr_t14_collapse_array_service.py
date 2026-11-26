"""Collapse Array through compiled ownership, native arrays and table commits."""
import pytest

from combat.ext import formations as F
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import CandidateKind
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture
from tests.formation_support import reload, settle, turn
from tests.test_a2_formations_r9_service import execute, equivalent


def collapse_rows(engine):
    return [c for c in engine.legal_candidates()
            if engine.action_catalog.get(c.source_definition_id)
            and engine.action_catalog[c.source_definition_id].parameters.get(F.TAG) == 'collapse']


def test_sphere_membership_without_the_base_record_does_not_grant_collapse(tmp_path):
    document = sheet([F.BASE_COLLAPSE], cl=15)
    owned = document['spheres_and_talents']
    owned['automatic_sphere_component_record_ids'].remove(F.BASE_COLLAPSE)
    owned['learned_talent_record_ids'].remove(F.BASE_COLLAPSE)
    bundle = compile_character(document, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, seed='MGR-T14-COLLAPSE-UNOWNED')
    cold = reload(tmp_path, mid)
    assert not any(a.owner_id == OWNER and a.display_name == 'Collapse Array' for a in cold.action_catalog.values())


def test_native_harmful_array_collapse_is_free_harmless_and_available_to_ai(tmp_path):
    combat, table, mid = fixture(tmp_path, [F.BASE_COLLAPSE], seed='MGR-T14-COLLAPSE-HARM')
    settle(table, mid, candidate(combat, mid, 'Combat Array: Killing Line (Fire)', at=(5, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    zone, = F.arrays(engine, OWNER)
    eye = F.record(zone)['eye']
    assert zone.trigger_profile['triggers'], 'the real Set action must create harmful ongoing behavior'
    assert not engine.state.actors[OWNER].action_available
    before = {aid: (a.current_hp, a.temporary_hp, dict(a.resources), a.action_available,
                    a.bonus_action_available, a.reaction_available) for aid, a in engine.state.actors.items()}
    ai = build_decision_context(engine, PolicyLibrary(ROOT).for_actor(OWNER)[0], for_ai=True)
    assert any(c.source_definition_id.endswith('.formation.collapse') for c in ai.legal_candidates)
    settle(table, mid, candidate(combat, mid, 'Collapse Array', at=(5, 6)).candidate_id)
    cold = reload(tmp_path, mid)
    assert not F.arrays(cold, OWNER)
    assert cold.state.objects[eye].destroyed
    assert cold.state.actors[OWNER].concentration is None
    assert before == {aid: (a.current_hp, a.temporary_hp, dict(a.resources), a.action_available,
                           a.bonus_action_available, a.reaction_available) for aid, a in cold.state.actors.items()}
    assert not collapse_rows(cold)


@pytest.mark.parametrize('automatic', [False, True])
def test_overlapping_arrays_select_exactly_one_and_persist(tmp_path, automatic):
    combat, table, mid = fixture(tmp_path, [F.BASE_COLLAPSE], seed='MGR-T14-COLLAPSE-CHOICE', named=True)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Locking Gate', at=(5, 6)).candidate_id)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(5, 6)).candidate_id)
    before = F.arrays(reload(tmp_path, mid), OWNER)
    assert len(before) == 2
    if automatic:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
        session = combat._load_session(mid)
        row = next(c for c in collapse_rows(session.engine) if c.destination.x == 5 and c.destination.y == 6)
        prompts = execute(combat, table, mid, session, row)
        assert not prompts, 'the AI resolves its own array choice'
        cold = equivalent(tmp_path, mid, session)
        ended = before[0]
    else:
        prompts = settle(table, mid, candidate(combat, mid, 'Collapse Array', at=(5, 6)).candidate_id,
                         {'choice:needle.formation_collapse': before[1].zone_id})
        choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.formation_collapse')
        assert {o['id'] for o in choice['choice']['options']} == {z.zone_id for z in before}
        assert 'Collapse Array' in choice['moment'] and 'Wren' in choice['moment']
        cold = reload(tmp_path, mid)
        ended = before[1]
    remaining, = F.arrays(cold, OWNER)
    assert remaining.zone_id != ended.zone_id
    assert cold.state.objects[F.record(ended)['eye']].destroyed
    assert not cold.state.objects[F.record(remaining)['eye']].destroyed


def test_native_movement_checks_120_foot_boundary_and_wrong_owner(tmp_path):
    def arena(row):
        row.update(width_squares=35, height_squares=6, terrain_regions=[])
    combat, table, mid = fixture(tmp_path, [F.BASE_COLLAPSE], owner_speed=150,
        seed='MGR-T14-COLLAPSE-RANGE', battlefield_transform=arena,
        positions={OWNER: {'x': 3, 'y': 1}, ALLY: {'x': 1, 'y': 2}, FOE: {'x': 2, 'y': 2}})
    settle(table, mid, candidate(combat, mid, 'Combat Array: Locking Gate', at=(5, 1)).candidate_id)
    for x, expected in [(29, True), (30, False)]:
        engine = combat._load_session(mid).engine
        move = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE
                    and c.destination.x == x and c.destination.y == 1)
        settle(table, mid, move.candidate_id)
        cold = reload(tmp_path, mid)
        assert bool(collapse_rows(cold)) is expected
    turn(table, mid, ALLY)
    cold = reload(tmp_path, mid)
    assert not collapse_rows(cold)
    assert not any(a.owner_id == ALLY and a.display_name == 'Collapse Array' for a in cold.action_catalog.values())
    assert F.arrays(cold, OWNER), 'wrong-owner/off-turn control leaves the array intact'


@pytest.mark.parametrize('pattern,pulse_target', [
    ('Killing Line (Fire)', FOE), ('Locking Gate', FOE), ('Nourishing Cycle', OWNER),
])
def test_automatic_turn_preserves_useful_array_after_other_actions_are_spent(tmp_path, pattern, pulse_target):
    combat, table, mid = fixture(tmp_path, [F.BASE_COLLAPSE], owner_speed=5,
                                 seed='MGR-T14-COLLAPSE-RETAIN-' + pattern)
    settle(table, mid, candidate(combat, mid, 'Combat Array: ' + pattern, at=(5, 6)).candidate_id)
    pulse = pattern.split(' (')[0]
    settle(table, mid, candidate(combat, mid, 'Pulse: ' + pulse, target=pulse_target).candidate_id)
    engine = combat._load_session(mid).engine
    move = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE
                and c.destination.x == 3 and c.destination.y == 5)
    settle(table, mid, move.candidate_id)
    before = reload(tmp_path, mid)
    actor = before.state.actors[OWNER]
    assert not actor.action_available and not actor.bonus_action_available and actor.movement_remaining_ft == 0
    zone, = F.arrays(before, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    context = build_decision_context(combat._load_session(mid).engine,
                                     PolicyLibrary(ROOT).for_actor(OWNER)[0], for_ai=True)
    assert any(c.source_definition_id.endswith('.formation.collapse') for c in context.legal_candidates)
    assert all(c.source_definition_id.endswith('.formation.collapse') for c in context.legal_candidates
               if c.kind in {CandidateKind.ACTION, CandidateKind.BONUS_ACTION, CandidateKind.OPTIONAL_RIDER})
    from combat import ext
    row = next(c for c in context.legal_candidates if c.source_definition_id.endswith('.formation.collapse'))
    components = [component for result in ext.run_strict('ai_score_components', context, row, ())
                  for component in result]
    assert any(component.component == 'formation_retention' and component.value < -1030
               for component in components), 'Collapse retention must reach the native scoring hook'
    assert table.auto_step(mid, 0, [])['status'] == 'COMMITTED'
    cold = reload(tmp_path, mid)
    assert cold.state.current_actor_id != OWNER, 'the controller should finish its turn'
    assert [z.zone_id for z in F.arrays(cold, OWNER)] == [zone.zone_id]
    assert not cold.state.objects[F.record(zone)['eye']].destroyed


def test_explicit_automatic_collapse_priority_can_outweigh_retention(tmp_path, monkeypatch):
    """A deliberate policy objective can end an array; retention is no veto."""
    combat, table, mid = fixture(tmp_path, [F.BASE_COLLAPSE], seed='MGR-T14-COLLAPSE-INTENT')
    settle(table, mid, candidate(combat, mid, 'Combat Array: Locking Gate', at=(5, 6)).candidate_id)
    source = next(a.source_definition_id for a in reload(tmp_path, mid).action_catalog.values()
                  if a.owner_id == OWNER and a.parameters.get(F.TAG) == 'collapse')
    original = PolicyLibrary.for_actor
    def priority(library, actor_id):
        policy, fallback = original(library, actor_id)
        if actor_id == OWNER:
            policy = policy.model_copy(update={'action_priorities': {**policy.action_priorities, source: 2000}})
        return policy, fallback
    monkeypatch.setattr(PolicyLibrary, 'for_actor', priority)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, 0, [])['status'] == 'COMMITTED'
    assert not F.arrays(reload(tmp_path, mid), OWNER)
