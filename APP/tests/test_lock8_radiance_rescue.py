import pytest
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.ext.radiance_rescue import FEATURE, PENDING
from tests import lock8_support as S
from tests.test_lock8_radiance import kind_bundle


def engine(kind='Undead', ally=False):
    return S.fight(S.bundle(FEATURE,cl=20),
        foe=kind_bundle(['SAND_BASE_SCOURING_HAND'],S.FOE,kind,cl=20),
        ally=S.bundle('SAND_BASE_SCOURING_HAND',actor_id=S.ALLY) if ally else None)


def response(e, option='damage'):
    def provider(request):
        return ReactionDecision(checkpoint=request['checkpoint'], reactor_id=request['reactor_id'],
            reaction_source_id=request['reaction_source_id'], selection='USE', option_ids=(option,)),None
    e.set_reaction_provider(provider)
    c=next(c for c in e.legal_candidates() if c.kind=='END_TURN')
    return ActionIntent(intent_id='test:rescue',decision_id=c.decision_id,candidate_id=c.candidate_id,
                        state_version=c.state_version,actor_id=c.actor_id)


@pytest.mark.parametrize('kind,dtype,allowed',[('Undead','FIRE',True),(None,'NECROTIC',True),(None,'FIRE',False)])
@pytest.mark.parametrize('ally',[False,True])
def test_morning_breath_final_floor_cost_and_actual_attacker_followup(kind,dtype,allowed,ally):
    e=engine(kind,ally);intent=response(e)
    a=e.state.actors[S.ME];target=e.state.actors[S.ALLY if ally else S.ME];b=e.state.actors[S.FOE]
    target.current_hp=3;target.temporary_hp=2
    before=a.resources['resource:core.qi'];enemy_hp=b.current_hp
    e._commit_damage(target,100,dtype,'test:lethal',S.FOE,intent,reaction_depth=0)
    assert target.current_hp==(1 if allowed else 0)
    assert a.resources['resource:core.qi']==before-(8 if allowed else 0)
    assert (b.current_hp<enemy_hp)==allowed
    assert not any(c.condition_id==PENDING for c in target.conditions.values())
    if allowed:
        assert not a.reaction_available
        a.reaction_available=True
        assert not any(rid for rid,n in a.resources.items() if 'resurrection_of_the_morning_breath' in rid and n>0)


def test_morning_breath_decline_and_unowned_are_inert():
    e=engine();a=e.state.actors[S.ME];a.current_hp=3
    before=a.resources['resource:core.qi']
    e._commit_damage(a,10,'FIRE','test:no_intent',S.FOE,None,reaction_depth=0)
    assert a.current_hp==0 and a.resources['resource:core.qi']==before


def test_morning_breath_fear_choice_only_cleanses_saved_subject():
    e=engine(ally=True);a=e.state.actors[S.ALLY]
    e._apply_condition(a,'condition:typed.frightened','test:fear',S.FOE,expires_on='UNTIL_REMOVED')
    a.current_hp=3
    e._commit_damage(a,10,'FIRE','test:lethal',S.FOE,response(e,'frightened'),reaction_depth=0)
    assert a.current_hp==1 and not S.held(a,'frightened')
