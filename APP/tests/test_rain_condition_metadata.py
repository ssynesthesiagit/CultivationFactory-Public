"""General additive source metadata guards; native acceptance lives in table tests."""
from copy import deepcopy
import pytest
from combat.condition_metadata import merge,primitive


def test_additive_provenance_retains_native_state_and_recovery_rules():
    original={'escape_dc':19,'repeat_save':{'ability':'STR','dc':19,'when':'end'},
        'information_profile':{'tags':['dust'],'save_ability':None}}
    result=merge(deepcopy(original),{'information_profile':{'source_cl':18,'save_dc':19}})
    assert result['escape_dc']==19 and result['repeat_save']==original['repeat_save']
    assert result['information_profile']=={'tags':['dust'],'save_ability':None,'source_cl':18,'save_dc':19}
    assert original['information_profile']=={'tags':['dust'],'save_ability':None}


def test_conflicting_committed_source_number_cannot_be_overridden():
    with pytest.raises(ValueError,match='Conflicting native condition metadata'):
        merge({'information_profile':{'source_cl':12}},{'information_profile':{'source_cl':18}})


@pytest.mark.parametrize('value',[1.0,True,object(),{'facts':[None]}, {'facts':[{'dc':1.5}]}])
def test_new_source_metadata_rejects_unpersistable_values(value):
    assert primitive(value) is False


def test_new_source_metadata_accepts_typed_integer_documents():
    assert primitive({'information_profile':{'source_cl':18,'mundane':0,'tags':['dust']}})


def test_unknown_source_slot_can_be_filled_but_known_zero_is_retained():
    assert merge({'source_cl':None},{'source_cl':18})=={'source_cl':18}
    with pytest.raises(ValueError):merge({'mundane':0},{'mundane':1})
