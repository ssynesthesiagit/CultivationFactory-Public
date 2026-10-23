"""Printed Explosive Pill collateral through committed table actions.

These tests certify recipient scope, not the five whole-record lifecycle. The
legacy service fixture explicitly grants Explosive Pill; it is not acquisition
evidence and must not be counted as native whole-record acceptance.
"""
import pytest

from tests.test_a2_qi_subpaths_2_service import (
    ALLY, FOE, ME, PILL, QI, cold, fight, use,
)
from tests import auto11_service_support as S


def test_smoke_utility_opt_in_is_source_owned_and_does_not_change_other_formulas():
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    bundle = compile_character(sheet([PILL]), actor_id=ME)
    actions = [a for a in bundle['action_catalog']
               if (a['parameters'].get('typed') or {}).get('source') == PILL]
    assert len(actions) == 5
    for action in actions:
        smoke = action['parameters']['typed']['option_label'] == 'Smoke Pill'
        assert bool(action['parameters'].get('ai_allow_empty_area')) == smoke
    unowned = compile_character(sheet([]), actor_id=ALLY)
    assert not any((a['parameters'].get('typed') or {}).get('source') == PILL
                   for a in unowned['action_catalog'])


def test_native_ai_context_retains_smoke_square_before_committed_cold_replay(tmp_path):
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary
    from tests.h1_support import ROOT
    svc, table, mid = fight(tmp_path)
    engine = cold(svc, mid)
    policy = PolicyLibrary(ROOT).for_actor(ME)[0]
    context = build_decision_context(engine, policy, for_ai=True)
    assert any(c.display_name.startswith('Explosive Pill: Smoke Pill at ')
               and c.destination is not None and (c.destination.x, c.destination.y) == (4, 6)
               for c in context.legal_candidates)
    use(svc, table, mid, 'Smoke')
    assert cold(svc, mid).state.actors[ME].resources[QI] == 27


@pytest.mark.parametrize('formula', ['Flame', 'Frost', 'Venom', 'Impact'])
@pytest.mark.parametrize('dc', [1, 30])
def test_each_creature_includes_thrower_and_ally_after_commit_and_cold_replay(
        tmp_path, formula, dc):
    svc, table, mid = fight(tmp_path, dc=dc)
    before = cold(svc, mid)

    def answer(prompt):
        # Keep Impact's optional failed-save displacement at zero so neither
        # sequential displacement nor collisions change this recipient check.
        if prompt['context']['reaction_source_id'] == 'choice:needle.displacement_distance':
            return '0'
        return None

    use(svc, table, mid, formula, answer)
    after = cold(svc, mid)
    saves = [e for e in after.events
             if e.event_type == 'SAVE_ROLLED' and PILL in e.source_definition_id]
    assert {e.actor_id for e in saves} == {ME, ALLY, FOE}
    assert len(saves) == 3
    for aid in (ME, ALLY, FOE):
        assert after.state.actors[aid].current_hp < before.state.actors[aid].current_hp
    assert after.state.actors[ME].resources[QI] == before.state.actors[ME].resources[QI] - 3


def test_outside_area_creature_is_unaffected_and_nonowner_has_no_pill_action(tmp_path):
    # The same source/aim excludes a creature beyond the actual ten-foot
    # sphere. A source-wide all-creatures flag must not become global damage.
    svc, table, mid = fight(tmp_path, foe_position=(18, 6))
    before = cold(svc, mid)
    use(svc, table, mid, 'Flame')
    after = cold(svc, mid)
    saves = {e.actor_id for e in after.events
             if e.event_type == 'SAVE_ROLLED' and PILL in e.source_definition_id}
    assert saves == {ME, ALLY}
    assert after.state.actors[FOE].current_hp == before.state.actors[FOE].current_hp
    assert not any(a.owner_id == ALLY and PILL in a.source_definition_id
                   for a in S.engine(svc, mid).action_catalog.values())
