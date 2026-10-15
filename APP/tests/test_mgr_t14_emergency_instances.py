"""Real learned Common formula -> native Stroke -> same temporary item -> replay."""
import pytest
import json

def inventory_of(actor):
    row=next((c for c in actor.conditions.values() if c.condition_id=="condition:typed.acquisition_inventory"),None)
    return json.loads(row.data["inventory"]) if row else {}
from combat.ext.talismans import EMERGENCY, STROKES
from tests.test_mgr_t14_items_weapon_delivery import acquire, native
from tests.worker2_support import OWNER, FOE, candidate, reload, turn, settle
from tests.test_auto2_talismans import take

TALISMANS='tianxia.sphere.talismans'
EMBER='tianxia.talent.talismans.ember_talisman'
HEALING='tianxia.talent.talismans.healing_talisman'


def learned(tmp_path, **kwargs):
    return acquire(tmp_path,TALISMANS,talents=[EMBER,HEALING],background='tianxia.background.talisman_apprentice',**kwargs)


@pytest.mark.parametrize('formula',['ember_talisman','healing_talisman'])
def test_stroke_creates_one_selected_common_formula_on_native_surface(tmp_path,formula):
    doc=learned(tmp_path)
    combat,table,mid=native(tmp_path,doc)
    before=reload(tmp_path/'fight',mid).state.actors[OWNER]
    cp=before.resources['resource:core.qi']; uses=before.resources[STROKES]
    prompts=take(combat,table,mid,'Emergency Stroke',choices={'choice:needle.emergency_formula':formula})
    engine=reload(tmp_path/'fight',mid);owner=engine.state.actors[OWNER]
    items=list(inventory_of(owner).values())
    assert len(items)==1
    item=items[0];facts=item['profile']['facts']
    assert facts['formula']==formula and facts['rank']=='common'
    assert all(facts[k]==0 for k in ['reusable','permanent','stable_goods','project_component'])
    assert facts['visibly_crude']==1
    assert item['acquisition']['route']=='emergency_stroke'
    assert owner.resources['resource:core.qi']==cp-1 and owner.resources[STROKES]==uses-1
    assert owner.resources[EMERGENCY]==0
    assert {'choice:needle.emergency_formula','choice:needle.emergency_method','choice:needle.emergency_surface'} <= {p['context']['reaction_source_id'] for p in prompts}


def test_activation_consumes_exact_instance_and_not_another_formula(tmp_path):
    doc=learned(tmp_path)
    combat,table,mid=native(tmp_path,doc,foe_position={'x':8,'y':6})
    take(combat,table,mid,'Emergency Stroke',choices={'choice:needle.emergency_formula':'ember_talisman'})
    item=next(iter(inventory_of(reload(tmp_path/'fight',mid).state.actors[OWNER]).values()))
    settle(table,mid,next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name=='End turn').candidate_id)
    turn(table,mid,OWNER)
    take(combat,table,mid,'Ember Talisman',FOE)
    owner=reload(tmp_path/'fight',mid).state.actors[OWNER]
    stored=inventory_of(owner)[item['id']]
    assert stored['quantity']==0 and stored['profile']['flags']['consumed']==1


def test_no_known_formula_or_writing_method_cannot_create_counter(tmp_path):
    doc=acquire(tmp_path,TALISMANS)
    combat,table,mid=native(tmp_path,doc)
    engine=reload(tmp_path/'fight',mid)
    assert not any(c.display_name.startswith('Emergency Stroke') for c in engine.legal_candidates())
    assert not inventory_of(engine.state.actors[OWNER])
