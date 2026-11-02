"""Native review regressions: real acquired sources, table commits and cold replay."""
import json
from types import SimpleNamespace
import pytest
from tests.test_mgr_cremation_native import game,fight,verify,A,B
from tests.worker2_support import settle,turn

PREFIX='condition:typed.cremation.'
DECLINE={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None,
         'choice:needle.cremation.spend_ash':None,'choice:needle.cremation.scripture_benefit':None}


def test_object_spend_ash_consumes_only_its_bound_activation(monkeypatch):
    from combat.ext import mgr_reserve_cremation_cinder_heart_ash_sentence as provider
    selected=SimpleNamespace(instance_id='current',condition_id=PREFIX+'activation',
        source_definition_id=provider.FEATURES[0],data={'source':'action:one','kind':'damage','intent':'one'})
    retained=SimpleNamespace(instance_id='other',condition_id=PREFIX+'activation',
        source_definition_id=provider.FEATURES[0],data={'source':'action:two','kind':'damage','intent':'two'})
    actor=SimpleNamespace(entity_id='actor',conditions={
        selected.instance_id:selected,retained.instance_id:retained})
    engine=SimpleNamespace(_remove_condition_instance=lambda actor,instance,source,expected=None: removed.append(instance))
    removed=[]; ctx=SimpleNamespace(engine=engine,actor=actor,source='action:one',intent='one')
    monkeypatch.setattr(provider,'context',lambda *args:ctx)
    monkeypatch.setattr(provider,'activation_matches',lambda ctx,row:row.data['intent']==ctx.intent)
    monkeypatch.setattr(provider,'ask',lambda *args,**kwargs:['FIRE'])
    monkeypatch.setattr(provider,'put',lambda *args,**kwargs:None)
    from combat import typed_executor
    monkeypatch.setattr(typed_executor,'_roll',lambda *args,**kwargs:8)
    provider.spend_ash_object_packet(engine,actor,SimpleNamespace(component={},object_id='obj'),[], 'action:one')
    assert removed==['current']
    assert retained.instance_id not in removed


def test_generated_family_rows_remain_reviewed_native_after_main_merge():
    from pathlib import Path
    from tests.h1_support import ROOT
    from combat.ext.mgr_reserve_cremation_cinder_heart_ash_sentence import FEATURES
    mechanics=json.loads((Path(ROOT)/'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    for source in FEATURES:
        assert mechanics[source]['typing_status']=='reviewed_final'
        assert mechanics[source]['effects']==[]
        assert mechanics[source]['riders']==[]


@pytest.mark.parametrize('typed,costs',[
    ({'technique_alignment':{'resource_id':'resource:core.stamina'},'qi_powered':True},()),
    ({'qi_powered':True},(('resource:core.stamina',5),)),
    ({'qi_powered':False},(('resource:core.qi',5),)),
])
def test_explicit_non_qi_powering_overrides_qi_defaults(typed,costs):
    from types import SimpleNamespace
    from combat.ext.mgr_reserve_cremation_cinder_heart_ash_sentence import qi_powered
    ctx=SimpleNamespace(typed={**typed,'source':'tianxia.subpath.qi.example'},
        damage_source_flags=(),action=SimpleNamespace(costs=costs))
    assert qi_powered(ctx) is False


def candidate(cold,mid,name,*,at=None,target=None):
    return next(c for c in cold()._load_session(mid).engine.legal_candidates()
        if name in c.display_name and (target is None or c.target_ids==(target,))
        and (at is None or c.destination and (c.destination.x,c.destination.y)==at))


@pytest.mark.parametrize('benefit',['healing','temp_hp'])
def test_successful_prison_save_allows_healing_but_denies_temporary_hp(tmp_path,monkeypatch,benefit):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=14,target_hp=500,target_scores={'CON':200},
        target_features=['LIFE_BASE_MEND_THE_PULSE','tianxia.talent.life.greater_invigorate'])
    s,t,mid=fight(cold,jid,tmp_path)
    settle(t,mid,candidate(cold,mid,'Cremation Prison',at=(7,4)).candidate_id,picks=DECLINE)
    # Entering B's turn runs the furnace judgment, and its damage also offers the
    # separate 2-Qi Ash Sentence. This regression is about the Prison's successful
    # save, so decline every optional rider while advancing; a bare turn() answers
    # choice prompts with their first option, which would silently apply a Sentence
    # (whose own successful save does reduce healing by PB) and mask the result.
    for _ in range(4):
        if t.state(mid)['menu']['actor_id']==B:break
        settle(t,mid,t.state(mid)['menu']['end_turn'],picks=DECLINE)
    else:
        raise AssertionError('the prison target never received its turn')
    engine=verify(cold,mid);start=engine.state.event_sequence
    seal=next(c for c in engine.state.actors[B].conditions.values() if c.condition_id==PREFIX+'sealed')
    assert seal.data['full']==0
    assert 'healing reduced' not in seal.data['label']
    assert 'start of Mara' in seal.data['label']
    if benefit=='healing':
        mend=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.LIFE_BASE_MEND_THE_PULSE') and c.target_ids==(B,))
        settle(t,mid,mend.candidate_id,picks=DECLINE)
        engine=verify(cold,mid)
        heal=next(e for e in engine.events if e.sequence>start and e.event_type=='HEALING_APPLIED' and B in e.target_ids)
        roll=next(r for r in reversed(engine.rolls) if str(r.reason).startswith('HEALING:'))
        assert heal.payload['offered']==roll.total, [
            (c.condition_id.removeprefix(PREFIX),
             (c.data or {}).get('full'), (c.data or {}).get('reduce_healing'))
            for c in engine.state.actors[B].conditions.values()
            if c.condition_id.startswith(PREFIX)]
    else:
        invigorate=candidate(cold,mid,'Borrowed Breath + Greater Invigorate',target=B)
        settle(t,mid,invigorate.candidate_id,picks=DECLINE)
        engine=verify(cold,mid)
        assert engine.state.actors[B].temporary_hp==0
        # Denial happens before the offer, so no TEMP_HP_GRANTED event exists to
        # carry a zero. Asserting a zero offer let the test pass on Borrowed
        # Breath's missing-HP cap while the printed denial was not enforced.
        assert not any(e.sequence>start and e.event_type=='TEMP_HP_GRANTED' and B in e.target_ids for e in engine.events)
        assert any(e.sequence>start and e.event_type=='PASSIVE_TRIGGERED' and B in e.target_ids
            and 'cannot gain Temporary Hit Points' in str(e.payload.get('log','')) for e in engine.events)


def test_replacing_scripture_ash_invalidates_prepared_tags_through_reload(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_cl=9,target_hp=500,
        target_features=['FIRE_TAL_BURNING_WEAPON'],owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    settle(t,mid,candidate(cold,mid,'Burning Weapon').candidate_id,picks=DECLINE);turn(t,mid,A)
    settle(t,mid,candidate(cold,mid,'Burn the Scripture — 5 Qi',target=B).candidate_id,picks=DECLINE)
    settle(t,mid,candidate(cold,mid,'Scripture Ash:').candidate_id,
        picks={**DECLINE,'choice:needle.cremation.scripture_benefit':'discount'})
    engine=verify(cold,mid)
    old=next(c for c in engine.state.actors[A].conditions.values() if c.condition_id==PREFIX+'scripture')
    assert 'unique fire talent' in [v.lower() for v in json.loads(old.data['profile'])['tags']]
    settle(t,mid,t.state(mid)['menu']['end_turn'],picks=DECLINE);turn(t,mid,B)
    conflag=next(c for c in cold()._load_session(mid).engine.legal_candidates()
        if c.source_definition_id.endswith('.FIRE_BASE_CONFLAGRATION') and c.destination and (c.destination.x,c.destination.y)==(5,3))
    settle(t,mid,conflag.candidate_id,picks=DECLINE);turn(t,mid,A)
    # The stored Fire discount does not match Burn the Scripture, so the old
    # preparation survives its declaration. Its successful result replaces ash.
    settle(t,mid,candidate(cold,mid,'Burn the Scripture — 5 Qi',target=B).candidate_id,picks=DECLINE)
    engine=verify(cold,mid)
    fresh=next(c for c in engine.state.actors[A].conditions.values() if c.condition_id==PREFIX+'scripture')
    assert fresh.instance_id!=old.instance_id
    # The replacement ash belongs to the newly burned effect, not the old one.
    # Conflagration's own printed effect is "Create an area of Fire Terrain" /
    # "Take Fire damage", and its compiled zone carries source_tags ["Fire"], so
    # the new ash records Fire. What must never survive is the prior Burning
    # Weapon preparation and its "unique fire talent" tag.
    tags=json.loads(fresh.data['profile'])['tags']
    assert tags==['Fire']
    assert 'unique fire talent' not in [v.lower() for v in tags]
    assert not any(c.condition_id==PREFIX+'scripture_prepared' for c in engine.state.actors[A].conditions.values())
    settle(t,mid,t.state(mid)['menu']['end_turn'],picks=DECLINE);turn(t,mid,A)
    engine=verify(cold,mid);before=engine.state.actors[A].resources['resource:core.qi']
    fireball=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART')
        and c.destination and (c.destination.x,c.destination.y)==(8,3))
    prompts=settle(t,mid,fireball.candidate_id,picks=DECLINE)
    engine=verify(cold,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.cremation.scripture_benefit' for p in prompts)
    assert engine.state.actors[A].resources['resource:core.qi']==before-5
    assert any(c.condition_id==PREFIX+'scripture' and c.instance_id==fresh.instance_id for c in engine.state.actors[A].conditions.values())
