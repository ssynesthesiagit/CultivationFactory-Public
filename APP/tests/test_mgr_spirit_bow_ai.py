"""Native AI choice/payment regression using the existing fake transport."""
from tests.test_mgr_spirit_bow_native import setup, fight, manifest, option, cold, held, O, F, QI


def test_automatic_owner_keeps_native_choice_and_payment_pipeline(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    cid=option(t,mid,'Heaven-Sundering Arrow: Projected Spirit Bow',F)
    from tests.r1i_service_support import force_ai_candidate
    force_ai_candidate(c,mid,O,cid)
    answers=[]
    for _ in range(16):
        result=t.auto_step(mid,0,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];answer={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):answer.update(selection='USE',option_ids=[p['choice']['options'][0]['id']])
        answers.append(answer)
    else:raise AssertionError('automatic native turn did not settle')
    e=cold(c,mid)
    assert held(e,O,'condition:typed.spirit_bow_scene_use')
    assert e.state.actors[O].resources[QI] in (88,91)

