"""Final outcomes and transaction-bound intent transport for integrated riders."""
import pytest

from combat.ext.alchemy_riders import DEVOURING_COST, pay_devouring_cost
from tests import test_riders_lane3 as L


@pytest.mark.parametrize('dc,outcome,earned', [(L.FAIL,'success',True),(L.PASS,'failure',False)])
def test_rivalry_earns_only_for_the_final_save_outcome(dc,outcome,earned):
    engine = L._beauty_arena(['tianxia.talent.beauty.radiant_rivalry'], dc=dc)
    L._act(engine,L.ME,'Catch the Eye',L.H.FOE)
    L._act(engine,L.ME,'Radiant Rivalry')
    engine._typed_roll_outcome = {L.H.FOE:outcome}
    L._act(engine,L.ME,'Catch the Eye',L.H.FOE)
    assert ('typed.rivalry_mark' in L._conds(engine.state.actors[L.ME])) == earned


def test_devouring_does_not_reuse_a_stale_unrelated_boundary_intent():
    engine = L._alchemy_arena([L.DEVOURING],cl=15)
    L._act(engine,L.ME,'Pill Devouring')
    actor = engine.state.actors[L.ME]
    held = next(c for c in actor.conditions.values() if c.condition_id == DEVOURING_COST)
    engine.state.round_number = int(held.data['due'].split(':')[1]) + 1
    # Simulate an older plug-in's retained reference during an unrelated system
    # boundary. The round17 public transport rejects its transaction identity.
    from combat.gate2_runtime_models import ActionIntent
    engine._alchemy_boundary_intent = ActionIntent(intent_id='stale',actor_id=L.ME,
        decision_id='stale',candidate_id='stale',state_version=engine.state.state_version)
    engine._active_intent = None
    engine._active_intent_id = 'unrelated-system-transition'
    before = actor.model_dump(mode='json')
    pay_devouring_cost(engine,actor)
    assert actor.model_dump(mode='json') == before


def test_spending_bite_is_inert_without_a_second_attack_rider():
    engine = L.H._engine(L._axes(['TAL_AXES_RENDING_HEW'],dc=L.FAIL))
    L.H._bite(engine)
    L.H._use(engine,L.STRIKE+'Bite + Rending Hew')
    assert not any(key.startswith('_spent_marks:') for key in L.H._me(engine).turn_flags)


def test_cleaving_arc_second_attack_delivers_defenders_declaration_reaction():
    from combat.factory_compiler import compile_character
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.gate2_runtime_models import ReactionDecision, Position

    defender = 'actor:factory.r3i-defender'
    bundles = [L._axes(['TAL_AXES_CLEAVING_ARC'],dc=L.FAIL),
        compile_character(L.H._sheet(None,[],L.H.AXE_KIT),actor_id=L.H.FOE),
        compile_character(L.H._sheet('tianxia.sphere.beauty',
            ['tianxia.talent.beauty.unapproachable_poise'],L.H.AXE_KIT,dc=L.FAIL),actor_id=defender)]
    engine = Gate4ControllerEngine(L.H.ROOT,match_seed='a',typed_bundles=bundles,
        roster_setup={'primary_actor_ids':[L.ME,L.H.FOE,defender],
            'team_by_actor':{L.ME:'team:a',L.H.FOE:'team:b',defender:'team:b'},
            'starting_positions':{L.ME:{'x':3,'y':6},L.H.FOE:{'x':4,'y':6},defender:{'x':3,'y':5}}})
    L._begin_turn(engine,defender)
    L._act(engine,defender,'Catch the Eye',L.ME)
    L._begin_turn(engine,L.ME)
    engine.state.actors[L.H.FOE].armor_class = -50
    calls = []
    def answer(request):
        if request['reaction_source_id'] != 'choice:needle.rider_step':
            return None,None
        calls.append(request)
        return ReactionDecision(checkpoint=request['checkpoint'],reactor_id=defender,
            reaction_source_id=request['reaction_source_id'],selection='USE',option_ids=('cell:3,3',)),None
    engine.set_reaction_provider(answer)
    before = engine.state.actors[defender].current_hp
    L._use_on(engine,L.STRIKE+'Bite + Cleaving Arc',L.H.FOE)
    assert calls and engine.state.actors[defender].position == Position(x=3,y=3)
    assert engine.state.actors[defender].current_hp == before
