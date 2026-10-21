"""Per-effect area warnings and AI costs agree with actual Table recipients."""
import pytest
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from tests import test_tabletop_hunt6 as H
from tests.test_lock_choices import install
from tests.test_lock11_friendly_fire import context
from tests.test_lock2_persistence import act

SOURCE = 'test:scope_practice'


@pytest.mark.parametrize('scope', ['self', 'enemies_in_area', 'nested_enemy', 'legacy_enemy', 'creatures_in_area'])
def test_effect_scopes_match_table_warning_controller_and_committed_damage(monkeypatch,tmp_path,scope):
    save = {'type':'save','ability':'CON','on_fail':[{'type':'damage','flat':4,
        'damage_types':['force'],'applies_to':'enemies_in_area' if scope=='nested_enemy' else 'target'}],
        'on_success':[]}
    if scope=='legacy_enemy':
        save['recipient_text']='Hostile creatures in the area make Constitution saving throws.'
    else:
        save['applies_to']='creatures_in_area' if scope=='nested_enemy' else scope
    def compile_action(info):
        if info['actor_id']!=H.LEFT:
            return []
        return [ActionDefinition(source_definition_id=SOURCE,display_name='Practice field',owner_id=H.LEFT,
            economy=EconomyKind.ACTION,resolution_kind='TYPED',target_kind='SELF',radius_ft=15,
            costs=(('resource:core.qi',1),),parameters={'expected_damage':4,'typed':{
                'numbers':{**info['numbers'],'save_dc':99},
                # Only the creature-wide fixture deliberately includes its
                # user. The self cost must inherit its own explicit scope.
                'area':{'shape':'sphere','size_ft':15,'centered_on_self':True,
                        **({'include_self':True} if scope=='creatures_in_area' else {})},
                'effects':[save,{'type':'healing','flat':3,'applies_to':'ally'}]}})]
    install(monkeypatch,'compile_actions',compile_action)
    combat,table,mid=H.table_fight(tmp_path,[],ally_talents=[])
    H.on_hold(monkeypatch,lambda e:e._commit_damage(e.state.actors[H.ALLY],10,'FORCE',
        'test:prior_wound',H.RIGHT,None,reaction_depth=0))
    assert act(table,mid,H.HOLD)['status']=='COMMITTED'
    e=combat._load_session(mid).engine
    before=e.state.model_dump(mode='json');seq=e.state.event_sequence
    c=next(c for c in e.legal_candidates() if c.source_definition_id==SOURCE)
    assert e.state.model_dump(mode='json')==before
    all_harmed=scope=='creatures_in_area'
    assert c.metadata.get('allies_in_area',0)==(2 if all_harmed else 0)
    assert c.metadata.get('ally_expected_damage',0)==(8 if all_harmed else 0)
    assert c.metadata.get('self_expected_damage',0)==(4 if scope=='self' else 0)
    state=table.state(mid)
    option=next(o for g in state['menu']['actions'] for o in g['options'] if o['candidate_id']==c.candidate_id)
    assert ('Hits allies too:' in option['label']) is all_harmed
    decision=LocalDeterministicController().choose_primary_action(context(e,[c]))
    components={row.component:row.value for row in decision.record.scored_alternatives[0].components}
    assert ('friendly_fire' in components) is all_harmed
    assert ('self_harm' in components) is (scope=='self')
    assert act(table,mid,SOURCE)['status']=='COMMITTED'
    loaded=CombatService(H.ROOT,tmp_path)._load_session(mid)
    events=[ev for ev in loaded.engine.events if ev.sequence>seq and ev.source_definition_id==SOURCE]
    hurt={who for ev in events if ev.event_type=='DAMAGE_COMMITTED' for who in ev.target_ids}
    expected={H.LEFT} if scope=='self' else {H.LEFT,H.ALLY,H.RIGHT} if all_harmed else {H.RIGHT}
    assert hurt==expected
    ally=loaded.engine.state.actors[H.ALLY]
    assert ally.current_hp==before['actors'][H.ALLY]['current_hp']+3-(4 if all_harmed else 0)
    assert loaded.engine.state.actors[H.LEFT].resources['resource:core.qi']==before['actors'][H.LEFT]['resources']['resource:core.qi']-1
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_real_crown_false_grace_does_not_warn_of_harming_allies(tmp_path):
    source='tianxia.tradition.spirit.halo_eater.feature.crown_of_borrowed_light'
    combat,table,mid=H.table_fight(tmp_path,[source],primary='Resonance',ally_talents=[])
    e=combat._load_session(mid).engine
    # The reviewed Crown chooses Facets after activation. Crown Collapse's
    # conditional damage is not an activation cost or friendly-fire packet.
    c=next(c for c in e.legal_candidates() if c.display_name == 'Crown of Borrowed Light')
    assert not c.metadata.get('allies_in_area') and not c.metadata.get('ally_expected_damage')
    assert c.metadata.get('self_expected_damage', 0)==0
    state=table.state(mid)
    option=next(o for g in state['menu']['actions'] for o in g['options'] if o['candidate_id']==c.candidate_id)
    assert 'Hits allies too:' not in option['label']
    choice=LocalDeterministicController().choose_primary_action(context(e,[c]))
    assert not any(row.component=='friendly_fire' for row in choice.record.scored_alternatives[0].components)
