"""Native compatibility checks and default-inert contract guards."""
import pytest
from tests import test_riders_c7 as c
from combat.ext import body_modes_scene_resources as common


def finish_setup(engine):
    for _ in range(5):
        candidates=engine.legal_candidates()
        setup=next((x for x in candidates if x.source_definition_id=='system:combat.fight_setup'),None)
        if setup is None:return
        engine.execute_intent(c.ActionIntent(intent_id='body-setup-'+str(len(engine.events)),decision_id=setup.decision_id,
            candidate_id=setup.candidate_id,state_version=setup.state_version,actor_id=setup.actor_id))
    raise AssertionError('Setup did not finish')


def test_furnace_initiative_selection_and_native_paid_guard():
    engine=c.fight(c.bundle([c.VISCERA+'five_viscera_circuit',c.STAMINA_GUARD]),foe=c._typed_foe())
    c.answers(engine,{'organ_furnaces':['liver']})
    finish_setup(engine)
    owner=engine.state.actors[c.ME]
    assert common.scene_record(engine,owner,c.VISCERA.removesuffix('.feature.'))
    assert any(x.data.get('active')==['liver'] for x in owner.conditions.values())
    owner.current_hp-=20
    c.hostile_packet(engine,c.ME,10,'SLASHING')
    assert any(e.event_type=='HEALING_APPLIED' and e.source_definition_id==c.VISCERA+'five_viscera_circuit' for e in engine.events)


def test_unrelated_native_character_has_no_modes_or_scene_edits():
    engine=c.fight(c.bundle([]),foe=c._typed_foe())
    assert not any(x.condition_id==common.SCENE for a in engine.state.actors.values() for x in a.conditions.values())
    assert not any(a.parameters.get('body_mode_source') for a in engine.action_catalog.values())


@pytest.mark.parametrize('seed',('GATE4-TEST','GATE4-AN-1','GATE4-LEE','LOCK5-A','LOCK5-B','LOCK5-C'))
def test_exact_base_six_stock_replays(tmp_path,monkeypatch,seed):
    from tests import test_a2_glass_stock as stock
    from tests.replay_base import replay_base
    monkeypatch.setenv('CF_REPLAY_BASE','8bd818c78df011c2b67145d8e33975468c3e6a75')
    monkeypatch.setattr(stock,'EVIDENCE',__import__('pathlib').Path('/var/tmp/auto-audit/fix/MGR-T14-sol-reserve-nine-star-meridian-body-star-lit-acupoints-1-evidence/stock'))
    stock.test_six_stock_captures_equal_main(tmp_path,seed)


def test_native_incarnation_payment_receipt_diagnostics():
    engine,actor,foe=c._nine(['nine_star_incarnation'],marks=5)
    c.use(engine,'Nine-Star Incarnation')
    from combat.ext.ability_source import mechanic_at
    events=[(e.sequence,e.event_type,e.source_definition_id,mechanic_at(engine,e.source_definition_id),e.actor_id,e.payload) for e in engine.events if e.event_type in ('INTENT_ACCEPTED','RESOURCE_SPENT','RESOURCE_GAINED')]
    receipt=common.paid_receipt(engine,actor,c.NINE+'nine_star_incarnation','INTENT_ACCEPTED')
    assert actor.resources[c.MARKS]==1,(receipt,events)


def test_native_light_setting_reaches_ordinary_space_perception():
    engine,actor,foe=c._nine(['star_lit_acupoints'])
    before=actor.resources[c.MARKS]
    c.use(engine,'Star-Lit Acupoints: Emit Dim Light')
    assert actor.resources[c.MARKS]==before
    from combat import senses
    assert senses.pinpoints(engine,foe,actor)
    assert not any(x.display_name.startswith('Star-Lit Acupoints:') for x in engine.legal_candidates())


def test_native_journey_lung_clock_and_suppression_guard(tmp_path):
    from tests.test_body_modes_native import journey_game,journey_do,declare_source,OWNER
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    doc=c.sheet([c.VISCERA+'five_viscera_circuit'],cl=3)
    service,jid=journey_game(tmp_path,doc)
    journey_do(service,jid,'furnace_select',{'furnace':'lung'})
    journey_do(service,jid,'furnace_breath',{'operation':'hold'})
    declare_source(service,jid,'breathing_exposure','airless',{'source_rule':'An airless sealed chamber.', 'source_cl':3,'no_air':1})
    journey_do(service,jid,'wait',{'seconds':3599})
    assert service.journey_state(jid)['actors'][OWNER]['incapacitated']==0
    journey_do(service,jid,'wait',{'seconds':61})
    cold=CombatService(ROOT,tmp_path)
    assert cold.journey_state(jid)['actors'][OWNER]['encounter_snapshot']['current_hp']==0
