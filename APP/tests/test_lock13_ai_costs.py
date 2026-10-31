"""Factory prices reach deterministic scoring without changing native contexts."""
import pytest
from combat.gate2_runtime_content import ACTIONS
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_models import DecisionContext
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_combat_gate4_controller import engine as legacy_engine
from tests.r10_fixup_support import commit

WORLD = 'tianxia.talent.disease.world_of_pestilence'


def resource_score(context,candidate):
    score = LocalDeterministicController()._score_candidate(context,candidate,())
    return next(row.value for row in score.components if row.component == 'resource_use')


@pytest.mark.parametrize('reserve_penalty', [False, True])
def test_world_of_pestilence_counts_qi_use_and_reserve_and_commits(monkeypatch,tmp_path,reserve_penalty):
    combat, table, mid = H.table_fight(tmp_path,[WORLD],cl=20,ally_talents=[])
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[H.LEFT]
    raw = engine.legal_candidates()
    action = next(a for a in engine.action_catalog.values() if a.owner_id == H.LEFT and a.display_name == 'World of Pestilence')
    assert ('resource:core.qi',12) in action.costs and len(action.costs) == 2
    reserves = {rid:actor.resources[rid] for rid,_ in action.costs} if reserve_penalty else {}
    policy = PolicyLibrary(ROOT).fallback().model_copy(update={'resource_reserves':reserves,'weights':{'resource_use':2}})
    before = engine.state.model_dump(mode='json')
    context = build_decision_context(engine,policy,for_ai=True)
    candidate = next(c for c in context.legal_candidates if c.source_definition_id == action.source_definition_id)
    assert candidate.metadata['compiled_costs'] == [[rid,cost] for rid,cost in action.costs]
    assert candidate.candidate_id in {c.candidate_id for c in raw}
    assert all('compiled_costs' not in c.metadata for c in raw)
    assert engine.state.model_dump(mode='json') == before
    expected = 2 * (-4 * sum(cost for _,cost in action.costs) - (18 * len(action.costs) if reserve_penalty else 0))
    assert resource_score(context,candidate) == expected < 0
    decoded = DecisionContext.model_validate_json(context.model_dump_json(by_alias=True))
    choice_context = decoded.model_copy(update={'legal_candidates':(candidate,)})
    controller = LocalDeterministicController()
    choice = controller.choose_primary_action(choice_context)
    assert choice == controller.choose_primary_action(choice_context)
    sequence = table.state(mid)['last_sequence']
    commit(lambda answers=(): table.act(mid,candidate.candidate_id,candidate.decision_id,candidate.state_version,sequence,list(answers)))
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    payments = [ev.payload['amount'] for ev in loaded.engine.events if ev.event_type == 'RESOURCE_SPENT' and ev.source_definition_id == action.source_definition_id]
    assert sorted(payments) == [1,12]
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_native_static_costs_and_old_contexts_remain_unchanged():
    engine = legacy_engine('LOCK13-COSTS')
    policy,_ = PolicyLibrary(ROOT).for_actor(engine.state.current_actor_id)
    context = build_decision_context(engine,policy)
    assert all('compiled_costs' not in c.metadata for c in context.legal_candidates)
    actor = next(a for a in context.actors if a.entity_id == context.active_actor_id)
    for candidate in context.legal_candidates:
        action = ACTIONS.get(candidate.source_definition_id)
        expected = sum(-4 * cost - (18 if actor.resources.get(rid,0) - cost < policy.resource_reserves.get(rid,0) else 0)
                       for rid,cost in action.costs) if action else 0
        assert resource_score(context,candidate) == expected * policy.weights.get('resource_use',1)
    # Historical Factory contexts without the new metadata remain deterministic
    # and readable; generating a fresh context supplies the compiled prices.
    old = context.legal_candidates[0].model_copy(update={'source_definition_id':'action:typed.old','metadata':{}})
    assert resource_score(context,old) == 0
