"""White Heron native learning -> table commit -> cold mechanical replay."""
import json
import zipfile
import pytest
from functools import lru_cache
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, settle, reload, candidate, turn, OWNER, FOE
SCHOOL='tianxia.subpath.body.white_heron_crescent_body'
PREFIX=SCHOOL+'.feature.'
FEATURES=['crescent_body_integration','one_legged_guard','crescent_reaping_circle','white_wing_crosses_the_reed_field','moon_over_the_reed_sea']
PID='0badc0de-0000-4000-8000-000000000059'
STAFF='tianxia.mortal.weapon.ji'
KIT={'starting_kit':{'items':[{'item_id':STAFF}]}}


@lru_cache(maxsize=1)
def catalog():
    return CanonicalCatalogAuthorityService(ROOT)


def native_table(combat,tmp_path):
    table=TabletopService(combat,tmp_path)
    table.canonical_catalog=catalog()
    return table


def acquired(tmp_path,cl=18,path='Body Refining'):
    doc=sheet([],cl=cl,primary='Stamina',kit=KIT,dc=50)
    doc['identity']['path']=path
    doc['identity']['name']='White Heron practitioner'
    doc['identity']['path_ids']=['tianxia.path.body_refining'] if path=='Body Refining' else ['tianxia.path.qi_cultivation']
    doc['path_and_subpath']={'path_record_ids':doc['identity']['path_ids']}
    folder=tmp_path/'portable_characters'/PID;folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:
        z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    table=native_table(CombatService(ROOT,tmp_path),tmp_path)
    table.add_advancement(PID,'subpath',SCHOOL)
    return CombatService(ROOT,tmp_path)._factory_owner_sheet(PID)


def game(tmp_path,cl=18,**kwargs):
    doc=acquired(tmp_path/'learning',cl)
    bundle=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    return fixture(tmp_path/'fight',[],owner_bundle=bundle,owner_path='Body Refining',primary='Stamina',
        owner_kit=KIT,cl=cl,seed='HERON58',foe_position=kwargs.pop('foe_position',{'x':4,'y':6}),
        ally_position={'x':3,'y':7},named=True,**kwargs)


@pytest.mark.parametrize('cl,count',[(2,0),(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_acquisition_progression_cold(tmp_path,cl,count):
    doc=acquired(tmp_path,cl)
    ids=doc.get('path_and_subpath',{}).get('path_feature_record_ids',[])
    assert [mid for mid in ids if mid.startswith(PREFIX)]==[PREFIX+f for f in FEATURES[:count]]
    assert not doc.get('spheres_and_talents',{}).get('sphere_record_ids')


def test_native_acquisition_rejects_wrong_path(tmp_path):
    from combat.tabletop_service import TabletopError
    with pytest.raises((ValueError,TabletopError)):
        acquired(tmp_path,path='Qi Cultivation')
