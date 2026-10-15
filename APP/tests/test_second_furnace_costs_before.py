import pytest
from tests.test_second_furnace_native import game,fight,turn,play,engine,choose_seed,verify,OWNER,f

@pytest.mark.parametrize('printed_cost',[1,3])
@pytest.mark.parametrize('erase_flag',[False,True])
def test_real_compiled_immortal_art_retains_its_printed_minimum_qi(tmp_path,monkeypatch,erase_flag,printed_cost):
    art={'art_id':'tianxia.constructed.immortal_art.second_furnace_mantle','display_name':'Imperial Mantle Immortal Art',
         'source_record_id':'TAL_FORCE_FORCE_MANTLE','path_id':'tianxia.path.qi_cultivation','activation_cp':printed_cost,
         'action_surface':{'action_type':'action','dc_basis':'none'}}
    cold,jid,declare,state=game(tmp_path,monkeypatch,cl=10,arts=(art,),seed='immortal-floor-'+str(erase_flag))
    action=next(a for a in state['actors'][OWNER]['bundle']['action_catalog'] if a['display_name']==art['display_name'])
    assert action['parameters']['typed']['immortal_from']=='TAL_FORCE_FORCE_MANTLE'
    if erase_flag:
        declare('cost_profile',{'source_rule':action['source_definition_id'],'quotation':'This declaration does not alter the actual Immortal Art provenance.',
            'classification':{'immortal_art':0}},'attempt-to-erase')
        state=cold().journey_state(jid)
        cold().journey_act(jid,state['revision'],OWNER,'furnace_cost_profile',{'scope':'attempt-to-erase'})
    mid=fight(cold,jid);turn(cold,tmp_path,mid,OWNER)
    prompts=play(cold,tmp_path,mid,art['display_name'],select=choose_seed)
    a=engine(cold,mid).state.actors[OWNER]
    assert a.resources[f.QI]==29 and a.resources[f.CORRUPTION]==1 and a.resources[f.DEVIL]==2
    assert not any('Second Furnace Core:' in str(p) for p in prompts)
    verify(cold,mid)
