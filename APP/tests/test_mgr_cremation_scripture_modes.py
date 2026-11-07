"""All stored Scripture choices use actual acquired source effects and intents."""
from tests.test_mgr_cremation_native import game,fight,verify,A,B,ASH
from tests.worker2_support import settle,turn


def test_native_scripture_discount_uses_authenticated_printed_source_tags(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_cl=9,target_hp=500,target_features=['FIRE_TAL_BURNING_WEAPON'],owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id);turn(t,mid,A)
    burn=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id)
    prep=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Scripture Ash:'))
    settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.scripture_benefit':'discount'})
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    engine=verify(cold,mid);before=engine.state.actors[A].resources['resource:core.qi']
    cast=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id,picks={'choice:needle.cremation.spend_ash':None,'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources['resource:core.qi']==before-3
    assert not any(c.condition_id=='condition:typed.cremation.scripture' for c in engine.state.actors[A].conditions.values())
    assert engine.state.actors[A].resources[ASH]==1


def test_native_scripture_save_bonus_matches_only_the_same_named_effect_off_turn(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_cl=9,target_hp=500,target_features=['FIRE_TAL_FIREBALL_ART'],owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    conflag=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_BASE_CONFLAGRATION') and c.destination and (c.destination.x,c.destination.y)==(5,3))
    settle(t,mid,conflag.candidate_id);turn(t,mid,A)
    burn=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id)
    prep=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Scripture Ash:'))
    settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.scripture_benefit':'save'})
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    cast=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    prompts=settle(t,mid,cast.candidate_id,picks={'choice:needle.cremation.spend_ash':None,'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    assert not any(p['context']['reaction_source_id']=='choice:needle.cremation.scripture_save' for p in prompts)
    assert any(c.condition_id=='condition:typed.cremation.scripture_ready' for c in verify(cold,mid).state.actors[A].conditions.values())
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,B)
    engine=verify(cold,mid);start=len(engine.rolls)
    conflag=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_BASE_CONFLAGRATION') and c.destination and (c.destination.x,c.destination.y)==(5,3))
    prompts=settle(t,mid,conflag.candidate_id,picks={'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    engine=verify(cold,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.cremation.scripture_save' and p['context']['reactor_id']==A for p in prompts)
    saves=[r for r in engine.rolls[start:] if r.actor_id==A and 'SAVE:' in r.reason and 'CONFLAGRATION' in r.reason]
    assert saves and saves[0].modifier==15
    event=next(e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.payload.get('roll_id')==saves[0].roll_id)
    # Native save bonuses lower the effective threshold; the raw d20 modifier remains recorded.
    assert event.payload['dc']==16-4
    assert not any(c.condition_id=='condition:typed.cremation.scripture_ready' for c in engine.state.actors[A].conditions.values())


def test_native_scripture_discount_does_not_infer_a_tag_from_fire_damage(tmp_path,monkeypatch):
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_cl=9,target_hp=500,target_features=['FIRE_TAL_BURNING_WEAPON'],owner_score=40)
    s,t,mid=fight(cold,jid,tmp_path);turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id);turn(t,mid,A)
    burn=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id)
    prep=next(c for c in cold()._load_session(mid).engine.legal_candidates() if c.display_name.startswith('Scripture Ash:'))
    settle(t,mid,prep.candidate_id,picks={'choice:needle.cremation.scripture_benefit':'discount'})
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    engine=verify(cold,mid);before=engine.state.actors[A].resources['resource:core.qi']
    cast=next(c for c in engine.legal_candidates() if c.source_definition_id.endswith('.FIRE_BASE_CONFLAGRATION') and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id,picks={'choice:needle.cremation.spend_ash':None,'choice:needle.cremation.touch':None,'choice:needle.cremation.sentence':None})
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources['resource:core.qi']==before-2
    assert any(c.condition_id=='condition:typed.cremation.scripture' for c in engine.state.actors[A].conditions.values())
    assert engine.state.actors[A].resources[ASH]==1


def test_source_tag_reader_has_no_name_damage_or_pool_fallback():
    from combat.ext.source_eligibility import printed_source_tags
    from combat.gate2_runtime_models import ActionDefinition
    action=ActionDefinition(source_definition_id='unknown:fire',display_name='Fire - Unique Fire Talent',owner_id=A,
        economy='ACTION',resolution_kind='TYPED',target_kind='SELF',costs=(('resource:core.qi',2),),
        parameters={'typed':{'source':'unknown:fire','effects':[{'type':'damage','damage_types':['fire']}]}})
    assert printed_source_tags(action)==[]
    malformed=action.model_copy(update={'parameters':{'typed':{'tags':'Fire'}}})
    assert printed_source_tags(malformed)==[]
