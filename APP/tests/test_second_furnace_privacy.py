"""Native acquired furnace knowledge must stay with its actual controller."""
from tests.test_second_furnace_native import game,fight,turn,engine,verify,OWNER,FOE,f

def test_native_furnace_pool_and_organ_do_not_reveal_private_anatomy_to_other_ai(tmp_path,monkeypatch):
    cold,jid,_,_=game(tmp_path,monkeypatch,cl=6,seed='private-furnace')
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    service=cold();own=service.ai_decision_context(service._load_session(mid))
    me=next(a for a in own.actors if a.entity_id==OWNER)
    assert f.DEVIL in me.resources and f.CORRUPTION in me.resources and f.ORGAN in me.conditions
    turn(cold,tmp_path,mid,FOE)
    service=cold();other=service.ai_decision_context(service._load_session(mid))
    observed=next(a for a in other.actors if a.entity_id==OWNER)
    assert f.DEVIL not in observed.resources and f.CORRUPTION not in observed.resources
    assert f.ORGAN not in observed.conditions
    assert f.DEVIL in engine(cold,mid).state.actors[OWNER].resources
    assert f.condition(engine(cold,mid).state.actors[OWNER],f.ORGAN)
    verify(cold,mid)
