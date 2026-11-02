"""Visibility and success controls for the saved Beguiling Perfume contract."""
from combat.target_knowledge import can_see
from tests.hunt12_support import ME, FOE, candidate, reload
from tests.test_auto86_flowers import shape, at
from tests.test_a2_flowers import scene, commit, end, advance, seed_condition, ALLY, FRAGRANCE, BEGUILE


def test_beguiling_ally_penalty_requires_attacker_to_see_charmer(tmp_path,monkeypatch):
    seed_condition(monkeypatch,ME,'invisible')
    combat,table,mid=scene(tmp_path,[FRAGRANCE,BEGUILE])
    shape(combat,table,mid,'Shape Fragrance: Beguiling Perfume')
    commit(combat,table,mid,at(combat,mid,'Fragrance',4,6))
    end(combat,table,mid); advance(combat,table,mid,FOE)
    engine=reload(tmp_path,mid)
    assert not can_see(engine,engine.state.actors[FOE],engine.state.actors[ME])
    assert any(c.condition_id=='condition:typed.charmed' for c in engine.state.actors[FOE].conditions.values())
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.display_name.startswith('Unarmed Strike') and ALLY in c.target_ids))
    engine=reload(tmp_path,mid)
    assert [e.payload['mode'] for e in engine.events if e.event_type=='ATTACK_ROLLED']==['NORMAL']


def test_beguiling_success_penalizes_exactly_next_attack_without_charming(tmp_path):
    combat,table,mid=scene(tmp_path,[FRAGRANCE,BEGUILE],dc=-100)
    shape(combat,table,mid,'Shape Fragrance: Beguiling Perfume')
    commit(combat,table,mid,at(combat,mid,'Fragrance',4,6))
    end(combat,table,mid); advance(combat,table,mid,FOE)
    engine=reload(tmp_path,mid); foe=engine.state.actors[FOE]
    assert not any(c.condition_id=='condition:typed.charmed' for c in foe.conditions.values())
    assert any(m.target_field=='attack_mode' and m.applies_to=='NEXT_ATTACK' for m in foe.modifiers.values())
    commit(combat,table,mid,candidate(combat,mid,lambda c:c.display_name.startswith('Unarmed Strike') and ME in c.target_ids))
    engine=reload(tmp_path,mid)
    assert [e.payload['mode'] for e in engine.events if e.event_type=='ATTACK_ROLLED']==['DISADVANTAGE']
    assert not any(m.target_field=='attack_mode' and m.applies_to=='NEXT_ATTACK' for m in engine.state.actors[FOE].modifiers.values())
