"""Focused defense allocation regressions for the opt-in hit component seam."""
from types import SimpleNamespace
import pytest
from combat.attack_components import collect, defenses, apply
from combat import typed_reactions


def found(*, resist=False, immune=False, rows=()):
    return dict(immune=immune, resist=resist, vulnerable=False,
        resistance_suppressed=False, resistance_ordinary=resist, once=[],
        resistance_next=[], reduction=0, pre_reduction=0, ext_reduction=0,
        per_round=[], reduction_rows=list(rows))


def test_components_resist_only_base_and_share_one_flat_reduction(monkeypatch):
    row={'kind':'reduction','amount':3,'feature_id':'fixture.flat',
         'damage_types':['BLUDGEONING']}
    base=found(resist=True, rows=[row])
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:found(resist=True,rows=[row]))
    parts=collect(8,'BLUDGEONING',[{'amount':20,'damage_type':'BLUDGEONING','ignore_resistance':True}])
    combined,prepared=defenses(None,None,parts,'strike','owner',base)
    assert combined['reduction']==3
    assert apply(28,prepared)==21  # 8/2 + 20 - 3, not two flat reductions


@pytest.mark.parametrize('immune,expected',[(False,24),(True,4)])
def test_component_bypass_never_bypasses_immunity(monkeypatch,immune,expected):
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:found(resist=True,immune=immune))
    parts=collect(8,'BLUDGEONING',[{'amount':20,'damage_type':'FORCE','ignore_resistance':True}])
    _,prepared=defenses(None,None,parts,'strike','owner',found(resist=True))
    assert apply(28,prepared)==expected


def test_typed_reduction_cannot_spill_into_ineligible_component(monkeypatch):
    base=found(rows=[{'kind':'reduction','amount':50,'feature_id':'physical armor',
                     'damage_types':['BLUDGEONING']}])
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:found())
    parts=collect(8,'BLUDGEONING',[{'amount':20,'damage_type':'FORCE'}])
    _,prepared=defenses(None,None,parts,'strike','owner',base)
    assert apply(28,prepared)==20


def test_same_type_components_share_resistance_rounding(monkeypatch):
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:found(resist=True))
    parts=collect(7,'BLUDGEONING',[{'amount':7,'damage_type':'BLUDGEONING'}])
    _,prepared=defenses(None,None,parts,'strike','owner',found(resist=True))
    assert apply(14,prepared)==7


def test_same_defense_projected_per_type_still_reduces_one_hit_once(monkeypatch):
    base={'kind':'reduction','amount':3,'feature_id':'fixture.same',
          'damage_types':['BLUDGEONING']}
    extra={**base,'damage_types':['FORCE']}
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:found(rows=[extra]))
    parts=collect(8,'BLUDGEONING',[{'amount':20,'damage_type':'FORCE'}])
    combined,prepared=defenses(None,None,parts,'strike','owner',found(rows=[base]))
    assert combined['reduction']==3 and apply(28,prepared)==25


def test_zero_primary_does_not_consume_its_next_type_defense(monkeypatch):
    primary=found(resist=True);primary['resistance_next']=['next_bludgeoning']
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:found())
    parts=collect(0,'BLUDGEONING',[{'amount':20,'damage_type':'FORCE'}])
    combined,_=defenses(None,None,parts,'strike','owner',primary)
    assert combined['resistance_next']==[]


def test_no_components_preserves_original_defense_flow(monkeypatch):
    # No real engine or model transport is needed to exercise the default path.
    from combat import ext
    engine=SimpleNamespace(state=SimpleNamespace(round_number=1),typed_passive_rows={},
                           runtime_actor_ids=set(),typed_actor_ids=set())
    target=SimpleNamespace(entity_id='target',modifiers={},turn_flags={})
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:found(resist=True))
    monkeypatch.setattr(ext,'run',lambda *a,**k:[])
    monkeypatch.setattr(ext,'run_strict',lambda *a,**k:[])
    monkeypatch.setattr(ext,'iter_strict_all',lambda *a,**k:iter(()))
    monkeypatch.setattr(ext,'has',lambda *a,**k:False)
    assert typed_reactions.defend(engine,target,9,'FORCE','strike',None)==4


def test_once_per_round_reduction_is_consumed_even_when_it_absorbs_whole_hit(monkeypatch):
    from combat import ext
    row={'kind':'reduction','amount':5,'once_per_round':True,
         'feature_id':'fixture.once','damage_types':['BLUDGEONING','FORCE']}
    engine=SimpleNamespace(state=SimpleNamespace(round_number=1),typed_passive_rows={})
    target=SimpleNamespace(entity_id='target',modifiers={},turn_flags={})
    defense=found(rows=[row]);defense.update(reduction=5,per_round=['fixture.once'])
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:copy_defense(defense))
    monkeypatch.setattr(ext,'run',lambda *a,**k:[])
    monkeypatch.setattr(ext,'run_strict',lambda *a,**k:[])
    monkeypatch.setattr(ext,'iter_strict_all',lambda *a,**k:iter(()))
    monkeypatch.setattr(ext,'has',lambda *a,**k:False)
    parts=collect(2,'BLUDGEONING',[{'amount':2,'damage_type':'FORCE'}])
    assert typed_reactions.defend(engine,target,4,'BLUDGEONING','strike',None,components=parts)==0
    assert target.turn_flags['defense_round_used:fixture.once']==1


def copy_defense(value):
    return {key:list(item) if isinstance(item,list) else item for key,item in value.items()}


@pytest.mark.parametrize('shared,expected',[(False,20),(True,24)])
def test_numeric_reducers_add_per_provider_and_consume_once_for_eligible_type(monkeypatch,shared,expected):
    from combat import ext
    applied=[]
    def physical(e,t,kind,typed,actor,applied_flag=False):
        amount=4 if shared else 3 if kind=='BLUDGEONING' else 0
        if applied_flag:applied.append(('physical',kind))
        return amount
    def force(e,t,kind,typed,actor,applied_flag=False):
        if applied_flag:applied.append(('force',kind))
        return 5 if kind=='FORCE' else 0
    handlers=[physical] if shared else [physical,force]
    def query(point,*args,**kwargs):
        if point=='damage_reduction' and kwargs.get('_with_handlers'):
            return [(h,h(*args)) for h in handlers]
        return []
    engine=SimpleNamespace(state=SimpleNamespace(round_number=1),typed_passive_rows={})
    target=SimpleNamespace(entity_id='target',modifiers={},turn_flags={})
    monkeypatch.setattr(typed_reactions,'_defenses',lambda *a,**k:found())
    monkeypatch.setattr(ext,'run',query)
    monkeypatch.setattr(ext,'run_strict',lambda *a,**k:[])
    monkeypatch.setattr(ext,'iter_strict_all',lambda *a,**k:iter(()))
    monkeypatch.setattr(ext,'has',lambda *a,**k:False)
    parts=collect(8,'BLUDGEONING',[{'amount':20,'damage_type':'FORCE'}])
    assert typed_reactions.defend(engine,target,28,'BLUDGEONING','strike',None,components=parts)==expected
    assert applied==([('physical','BLUDGEONING')] if shared else [('physical','BLUDGEONING'),('force','FORCE')])
