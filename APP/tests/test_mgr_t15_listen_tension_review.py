"""Review regressions: private space fidelity, shared cap eviction and labels.

Runtime inputs: authority/typed_mechanics/rules_text.json,
authority/Tianxia_Typed_Mechanics_Authority_R1.json,
authority/Tianxia_Forged_Technique_Authority_R1.json,
authority/Tianxia_Immortal_Art_Authority_R1.json,
catalog_authority/cat3/generated/catalog_authority.v1.json,
authority/typed_mechanics/reviewed_final.d/review_sw-thread.json,
authority/Tianxia_Sphere_Path_Access_R1.json,
catalog_authority/cat1/data/prerequisite_projection.v1.json.
"""
import pytest

from combat import target_knowledge as tk, typed_executor
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from tests.test_mgr_t15_listen_tension import (
    ROOT, P, F, S, HUNDRED, fight, draw, choose, cold, advance,
    private, grants, candidate, send, reach, checks, receipts,
)


@pytest.mark.parametrize('analytic', [False, True])
def test_native_invisible_space_is_current_but_never_full_actor_knowledge(tmp_path, monkeypatch, analytic):
    monkeypatch.setenv('CF_COMBAT_AI_SLICES_1_2', '1' if analytic else '0')
    combat, table, mid = fight(tmp_path, foe_mids=['tianxia.talent.illusion.greater_invisibility'])
    draw(table, mid)
    reach(table, mid, F)
    choose(table, mid, candidate(table, mid, 'Greater Invisibility', F))
    e = cold(tmp_path, mid)
    step = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y, c.destination.z) == (6, 6, 0))
    choose(table, mid, step.candidate_id)
    reach(table, mid, P)
    # Space is added by the Invisible connection; the printed reading chosen here is motion.
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), ('motion',))
    e = cold(tmp_path, mid)
    viewer, target = e.state.actors[P], e.state.actors[F]
    known = tk.knowledge(e, viewer, target)
    assert known.position_only and known.position == target.position
    assert known.mode == 'DIRECT'  # Current aim keeps the complete legal attack menu.
    assert not tk.located(e, viewer, target)  # No unrelated perception-trigger benefit.
    assert tk.located(e, viewer, target, personal=True)
    assert not tk.can_see(e, viewer, target)
    assert not tk.knowledge(e, e.state.actors[S], target).position_only
    assert e.state.observations[viewer.team_id][F] != target.position
    projected = next(a for a in tk.actors_for(e, viewer) if a.entity_id == F)
    assert projected is not target and projected.position == target.position
    assert target.resources and target.conditions and target.maximum_hp == 2000
    assert (projected.current_hp, projected.maximum_hp, projected.armor_class) == (100, 100, 0)
    assert not projected.conditions and not projected.resources and projected.concentration is None
    assert next(row for row in private(table, mid) if 'position' in row)['position'] == target.position.model_dump(mode='json')
    assert private(table, mid, S) == []

    policy, _ = PolicyLibrary(ROOT).for_actor(P)
    for context in (build_decision_context(e, policy), build_decision_context(e, policy, for_ai=True)):
        other = next(a for a in context.actors if a.entity_id == F)
        assert other.position == target.position
        assert (other.current_hp, other.maximum_hp, other.armor_class) == (100, 100, 0)
        assert not other.resources and not other.conditions and other.concentration_source_id is None
        assert next(row for row in context.private_information if 'position' in row)['position'] == target.position.model_dump(mode='json')
        assert any(c.target_ids == (F,) and tk.is_attack(e.action_catalog[c.source_definition_id])
                   for c in context.legal_candidates)
        if context.own_knowledge is not None:
            personal = next(a for a in context.own_knowledge.creatures if a.entity_id == F)
            assert personal.position == (6, 6, 0)

    # Commit an actually offered attack at the current square, not the stale
    # team observation. Some Draw variants require sight; knowing a space does
    # not waive that restriction or imply a particular attack label is offered.
    sequence = e.state.event_sequence
    attack = next(c for c in e.legal_candidates() if c.target_ids == (F,)
                  and tk.is_attack(e.action_catalog[c.source_definition_id]))
    choose(table, mid, attack.candidate_id)
    e = cold(tmp_path, mid)
    new_events = [ev for ev in e.events if ev.sequence > sequence]
    assert any(ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == P and F in ev.target_ids
               for ev in new_events)
    assert not any(ev.event_type == 'ATTACK_LOCATION_MISSED' for ev in new_events)
    choose(table, mid, table.state(mid)['menu']['end_turn'])
    e = cold(tmp_path, mid)
    assert not grants(e)
    assert not tk.located(e, e.state.actors[P], e.state.actors[F], personal=True)
    assert not tk.knowledge(e, e.state.actors[P], e.state.actors[F]).position_only


def test_capacity_eviction_preserves_newer_same_bearer_and_foreign_marks(monkeypatch):
    """Generic engine regression: evict one slot, not every instance of its id.

    Isolated existing mark fixtures exercise the engine-level capacity bug;
    these seeded marks are not claimed as native Thread acquisition proof.
    """
    from tests.test_marks import _engine_with
    typed = {'effects': [], 'numbers': {'pb': 2}, 'duration': {'kind': 'instant'}}
    engine, owner_id = _engine_with(typed, 'LISTEN-REVIEW-CAPACITY')
    owner = engine.state.actors[owner_id]
    bearer, recipient = [a for a in engine.state.actors.values() if a is not owner][:2]
    cid = typed_executor.mark_condition_id('Thread Line', owner_id)
    foreign = typed_executor.mark_condition_id('Thread Line', recipient.entity_id)
    for oid in ('object:older', 'object:newer'):
        engine._apply_condition(bearer, cid, 'test:object_line', owner_id,
            expires_on='UNTIL_REMOVED', data={'connected_object_id': oid})
    engine._apply_condition(bearer, foreign, 'test:foreign', recipient.entity_id, expires_on='UNTIL_REMOVED')
    older, newer = [c for c in bearer.conditions.values() if c.condition_id == cid]
    monkeypatch.setattr(typed_executor, 'mark_capacity', lambda ctx, name: 2)
    action = engine.action_catalog['action:typed.test']
    ctx = typed_executor.Context(engine, owner, action, None, typed, [recipient], recipient, {})
    typed_executor.block_mark(ctx, {'type': 'mark', 'mark': 'Thread Line', 'applies_to': 'target'})
    assert older.instance_id not in bearer.conditions
    assert newer.instance_id in bearer.conditions
    assert any(c.condition_id == foreign for c in bearer.conditions.values())
    assert typed_executor.bears_mark(recipient, owner_id, 'Thread Line')
    assert sum(c.condition_id == cid for a in engine.state.actors.values() for c in a.conditions.values()) == 2


def test_native_object_check_subject_names_the_bell_and_consumes_its_grant(tmp_path):
    _, table, mid = fight(tmp_path, owner_talents=[HUNDRED], objects=[
        {'id': 1, 'kind': 'custom', 'name': 'Bell', 'x': 7, 'y': 5, 'blocks': False, 'ac': 10, 'hp': 30}])
    draw(table, mid)
    advance(table, mid, F)
    advance(table, mid, P, keep=True)
    choose(table, mid, candidate(table, mid, 'Draw the Line: Guide (Qi Thread) (at an object)', 'object:map.1'))
    from combat.ext.thread_common import maintained_lines
    e = cold(tmp_path, mid)
    rows = maintained_lines(e, e.state.actors[P])
    creature_line = next(i for i, target, _, _ in rows if getattr(target, 'entity_id', None) == F)
    object_line = next(i for i, target, _, _ in rows if getattr(target, 'object_id', None) == 'object:map.1')
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), (object_line, 'check'))
    advance(table, mid, F)
    advance(table, mid, P, keep=True)
    check_id = candidate(table, mid, 'Check involving your Thread Line')
    pending = send(table, mid, check_id)
    assert pending['status'] == 'REACTION_REQUIRED'
    labels = {o['id']: o['label'] for o in pending['reaction']['choice']['options']}
    assert labels[object_line] == 'Line to Bell'
    assert labels[creature_line].startswith('Line to ') and labels[creature_line] != labels[object_line]
    cold(tmp_path, mid)  # Reopen the real pending check through a fresh service.
    choose(table, mid, check_id, (object_line, 'Perception'))
    e = cold(tmp_path, mid)
    check = [ev for ev in e.events if ev.event_type == 'CHECK_ROLLED' and ev.actor_id == P][-1]
    assert check.payload['check_context']['subject'] == object_line
    assert check.payload['actor']['mode'] == 'ADVANTAGE'
    # Spent check: no Advantage left; the receipt stays bound to the object line.
    assert not checks(e)
    assert [c.data['line_id'] for c in receipts(e)] == [object_line]


@pytest.mark.parametrize('analyzed', [True, False])
def test_line_check_keeps_the_connected_creatures_own_resolver_mode(tmp_path, monkeypatch, analyzed):
    """A line check against the connected creature is a real check against it.

    F15 review P2: the scoped line check rolled with no opposing creature, so a
    source/target-qualified resolver benefit never ran -- Discern Tells gives
    Advantage on Wisdom (Insight) against a creature you have Analyzed, and this
    path stayed NORMAL. The mode below is the committed CHECK_ROLLED receipt.
    """
    from tests.r10_fixup_support import fixed_dice
    from combat.ext.mind_hidden_eye import analyzed_by
    from combat.ext.thread_common import maintained_lines

    fixed_dice(monkeypatch, [20] * 120)
    _, table, mid = fight(tmp_path, owner_spheres=('tianxia.sphere.thread', 'tianxia.sphere.the_hidden_eye'),
                          owner_talents=['tianxia.talent.the_hidden_eye.discern_tells'])
    if analyzed:
        choose(table, mid, candidate(table, mid, 'Analyze', F))
        assert analyzed_by(cold(tmp_path, mid).state.actors[F], P)
        advance(table, mid, F)
        advance(table, mid, P, keep=True)
    draw(table, mid)
    advance(table, mid, F)
    advance(table, mid, P, keep=True)
    e = cold(tmp_path, mid)
    line = next(iid for iid, target, _, _ in maintained_lines(e, e.state.actors[P])
                if getattr(target, 'entity_id', None) == F)
    # The handling reading, not Listen's own check benefit: any Advantage here
    # must come from the check being against this creature.
    choose(table, mid, candidate(table, mid, 'Listen Through Tension'), (line, 'handling'))
    choose(table, mid, candidate(table, mid, 'Check involving your Thread Line'), (line, 'Insight'))
    e = cold(tmp_path, mid)
    check = [ev for ev in e.events if ev.event_type == 'CHECK_ROLLED' and ev.actor_id == P][-1]
    assert check.payload['check_context']['subject'] == line
    assert check.payload['check_context']['against'] == F
    assert (check.payload['skill'], check.payload['ability']) == ('Insight', 'WIS')
    assert check.payload['actor']['mode'] == ('ADVANTAGE' if analyzed else 'NORMAL')
    # The reading is untouched: the line check consumed nothing it did not earn.
    assert [c.data['benefit'] for c in grants(e)] == ['handling']
