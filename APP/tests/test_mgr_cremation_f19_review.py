"""F19 coverage: printed Ash Sentence / Burn the Scripture acceptance.

These tests read the printed rules text beside the native provider. The first
pins the one clause that was only incidentally covered: "It cannot gain
Temporary Hit Points". The second plays every reviewed Cremation row through
the real table so the five-row terminal acceptance cannot be satisfied by
authority data alone.
"""
from tests.test_mgr_cremation_native import game,fight,verify,A,B
from tests.worker2_support import settle,turn
from combat.typed_executor import condition_rules
from combat.ext import mgr_reserve_cremation_cinder_heart_ash_sentence as cremation

ASH='resource:named.ash_charge'
PREFIX='condition:typed.cremation.'


def test_sentence_temp_hp_denial_reaches_the_actual_grant_site(tmp_path,monkeypatch):
    """Ash Sentence: "It cannot gain Temporary Hit Points."

    A denial is not a zero-sized offer. The old checks accepted a
    TEMP_HP_GRANTED with offered == 0; that event was produced by Borrowed
    Breath's missing-HP cap whenever the target had just been healed, so it
    passed while the Sentence's rule never reached _grant_temp_hp. Target HP is
    deliberately left below maximum here.
    """
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=6,target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path)
    cast=next(c for c in s._load_session(mid).engine.legal_candidates()
        if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART')
        and c.destination and (c.destination.x,c.destination.y)==(8,3))
    settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid);target=engine.state.actors[B]
    assert target.current_hp<target.maximum_hp
    assert any(c.condition_id==PREFIX+'sentence' and c.source_actor_id==A
        for c in target.conditions.values())
    rows=condition_rules(target)
    assert any(row.get('deny_temp_hp') and row.get('temp_hp_denied') for row in rows), rows
    start=engine.state.event_sequence
    engine._grant_temp_hp(target,20,cremation.FEATURES[0],A)
    assert target.temporary_hp==0
    assert not any(e.sequence>start and e.event_type=='TEMP_HP_GRANTED' and B in e.target_ids
        for e in engine.events)
    assert any(e.sequence>start and e.event_type=='PASSIVE_TRIGGERED' and B in e.target_ids
        and 'cannot gain Temporary Hit Points' in str(e.payload.get('log','')) for e in engine.events)


def test_burn_the_scripture_is_not_offered_without_an_active_effect(tmp_path,monkeypatch):
    """CL10: "Choose one active, perceived effect on the target."

    With no effect to choose, the 5-Qi action must not be a legal activation;
    otherwise the table charges 5 Qi and resolves nothing.
    """
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=10,target_hp=500)
    s,t,mid=fight(cold,jid,tmp_path)
    engine=verify(cold,mid)
    assert not any(c.display_name.startswith('Burn the Scripture') and c.target_ids==(B,)
        for c in engine.legal_candidates())


def test_all_five_reviewed_rows_play_through_the_native_table(tmp_path,monkeypatch):
    """CL3, 6, 10, 14 and 18 each reach an actual native consumer.

    Core + Sentence share the Fireball activation; Burn the Scripture consumes a
    real source-owned buff; Prison creates its zone and Anchor; Heaven creates
    the field, then Final Cremation resolves against the Sealed target inside it.
    """
    cold,jid,world,act=game(tmp_path,monkeypatch,cl=18,target_hp=500,owner_score=40,
        target_features=['FIRE_TAL_BURNING_WEAPON'],target_scores={'CON':-100})
    s,t,mid=fight(cold,jid,tmp_path)
    engine=verify(cold,mid)
    rows=[r for r in engine.typed_passive_rows[A] if r.get('block')=='cremation_cinder_heart']
    assert {r['feature_id'] for r in rows}==set(cremation.FEATURES)
    assert {'kind':'resistance','damage_types':['fire']} in cremation.defenses(
        engine,engine.state.actors[A],'fire',{},None)
    # Put a real native buff on the target first so Burn the Scripture has a
    # source-owned effect to choose (Burning Weapon precedes the Sentence).
    turn(t,mid,B)
    ward=next(c for c in cold()._load_session(mid).engine.legal_candidates()
        if c.display_name=='Burning Weapon')
    settle(t,mid,ward.candidate_id)
    turn(t,mid,A)
    # CL10 Burn the Scripture first: end/suppress a real native effect and store
    # its ash. Burning Weapon is a concentration effect, so burn it before the
    # Fireball's damage forces the target's concentration save and ends it.
    burn=next(c for c in cold()._load_session(mid).engine.legal_candidates()
        if c.display_name.startswith('Burn the Scripture — 5 Qi') and c.target_ids==(B,))
    settle(t,mid,burn.candidate_id)
    engine=verify(cold,mid)
    assert engine.state.actors[A].resources[ASH]==1
    assert any(c.condition_id==PREFIX+'scripture' for c in engine.state.actors[A].conditions.values())
    # CL3 Cremation Touch + CL6 Ash Sentence: one Fireball activation.
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    engine=verify(cold,mid)
    cast=next(c for c in engine.legal_candidates()
        if c.source_definition_id.endswith('.FIRE_TAL_FIREBALL_ART')
        and c.destination and (c.destination.x,c.destination.y)==(8,3))
    prompts=settle(t,mid,cast.candidate_id)
    engine=verify(cold,mid)
    assert any('Cremation Touch' in str(p) for p in prompts)
    assert any('Ash Sentence' in str(p) for p in prompts)
    assert any(c.condition_id==PREFIX+'sentence' and c.source_actor_id==A
        for c in engine.state.actors[B].conditions.values())
    assert any(e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids for e in engine.events)
    # CL14 Cremation Prison: a placed concentration zone with its Furnace Anchor.
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    prison=next(c for c in cold()._load_session(mid).engine.legal_candidates()
        if c.display_name.startswith('Cremation Prison') and c.destination
        and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,prison.candidate_id)
    engine=verify(cold,mid)
    assert any((o.component or {}).get('cremation_zone') for o in engine.state.objects.values())
    # CL18 Cremate Heaven and Earth, then its Final Cremation.
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    heaven=next(c for c in cold()._load_session(mid).engine.legal_candidates()
        if c.display_name.startswith('Cremate Heaven and Earth') and c.destination
        and (c.destination.x,c.destination.y)==(7,4))
    settle(t,mid,heaven.candidate_id)
    engine=verify(cold,mid)
    assert any(c.condition_id==PREFIX+'field' and c.source_actor_id==A
        for c in engine.state.actors[A].conditions.values())
    final=next(c for c in engine.legal_candidates()
        if c.display_name.startswith('Final Cremation') and c.target_ids==(B,))
    settle(t,mid,final.candidate_id)
    engine=verify(cold,mid)
    assert any(e.event_type=='SAVE_ROLLED' and e.actor_id==B
        and e.source_definition_id==final.source_definition_id for e in engine.events)
    assert any(e.event_type=='DAMAGE_COMMITTED' and B in e.target_ids
        and e.source_definition_id==final.source_definition_id for e in engine.events)
