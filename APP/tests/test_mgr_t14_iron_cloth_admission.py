"""Authoritative admission must be answerable through the native table caller."""
import pytest
from tests.test_mgr_t14_iron_cloth import SILKEN,QI,play,whip_of
from tests.worker2_support import OWNER,FOE,candidate,act,reload


def test_native_declaration_prompt_survives_menu_discovery_and_refusal_is_inert(tmp_path):
    from combat.gate5_service import CombatServiceError
    from combat.fact_consent_admission import combat_records
    combat,table,mid=play(tmp_path,[SILKEN])
    c=candidate(combat,mid,'Silken Whip')
    before=reload(tmp_path,mid).state.model_dump_json()
    result=act(table,mid,c.candidate_id,[])
    assert result['status']=='REACTION_REQUIRED'
    fabric=result['reaction']
    assert fabric['context']['reaction_source_id']=='choice:needle.iron_cloth.fabric'
    pick={**fabric['context'],'selection':'USE','option_ids':[fabric['choice']['options'][0]['id']]}
    result=act(table,mid,c.candidate_id,[pick])
    assert result['status']=='REACTION_REQUIRED'
    fact=result['reaction']
    assert fact['context']['reaction_source_id']=='choice:needle.fact_admission.iron_cloth_fabric'
    assert fact['choice']['options'][0]['id']=='flexible_fabric'
    assert reload(tmp_path,mid).state.model_dump_json()==before
    with pytest.raises(CombatServiceError) as error:
        act(table,mid,c.candidate_id,[pick,{**fact['context'],'selection':'DECLINE'}])
    assert error.value.diagnostic.details['reason']=='Identify the selected flexible fabric before activating this feature.'
    assert reload(tmp_path,mid).state.model_dump_json()==before
    accepted=act(table,mid,c.candidate_id,[pick,{**fact['context'],'selection':'USE','option_ids':['flexible_fabric']}])
    assert accepted['status']=='COMMITTED'
    e=reload(tmp_path,mid);w=whip_of(e)
    assert w and e.state.actors[OWNER].resources[QI]==99
    assert w.data['fabric_receipt']==combat_records(e,e.state.actors[OWNER],source=SILKEN,kind='iron_cloth_fabric')[0]['receipt_id']
    assert not combat_records(e,e.state.actors[FOE],source=SILKEN,kind='iron_cloth_fabric')
