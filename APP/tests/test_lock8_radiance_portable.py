"""Real portable saves retain Radiance timers, area filters and hit receipts."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.r10_fixup_support import cast_sender, commit
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install


@pytest.mark.parametrize('feature,name,point',[
 ('searing_halo','Searing Halo',None),
 ('solar_radiance_form','Solar Radiance Form',None),
 ('crown_of_the_unblinking_sun','Crown of the Unblinking Sun',None),
 ('halo_of_the_merciful_sovereign','Halo of the Merciful Sovereign',None),
 ('consecrated_boundary','Consecrated Boundary',(6,4)),
 ('court_of_unshadowed_dawn','Court of Unshadowed Dawn',None),
 ('world_of_revealed_morning','World of Revealed Morning',(6,4)),
])
def test_portable_activation_following_turn_and_reload(monkeypatch,tmp_path,feature,name,point):
    owner,foe='actor:factory.aaaaaaaa','actor:factory.ffffffff'
    for pid in ('aaaaaaaa','ffffffff'):
        doc=sheet(['tianxia.talent.radiance.'+feature,'RADIANCE_BASE_STRIKE'] if pid=='aaaaaaaa' else ['SAND_BASE_SCOURING_HAND'],cl=20)
        doc['identity']['display_name']='Lightkeeper' if pid=='aaaaaaaa' else 'Recorded undead opponent'
        if pid=='ffffffff':doc['identity']['creature_type']='Undead'
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    combat=CombatService(ROOT,tmp_path)
    combat.tabletop_maps.save({'display_name':'Radiance yard','width_squares':12,'height_squares':8,
        'walls':[],'starts':{'team1':[[3,4]],'team2':[[6,4]]}})
    mid=combat.create_factory_match(project_ids=['aaaaaaaa'],opponent_actor_ids=[foe],
        control_modes={owner:'MANUAL',foe:'MANUAL'},arena_id='battlefield:map.radiance-yard',match_seed='L8-RADIANCE-PORT')['match_id']
    table=TabletopService(combat,tmp_path);turn(table,mid,owner)
    commit(cast_sender(combat,table,mid,name,at=point))
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
    assert act(table,mid,'end')['status']=='COMMITTED'
    turn(table,mid,owner)
    commit(cast_sender(combat,table,mid,'Radiance Strike',target=foe))
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
