"""Narrow general-interface guards and exact-base stock replays."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import pytest
from combat.ext.piercing_areas import object_multiplier
from tests import test_a2_glass_stock as stock


def test_ordered_area_default_and_explicit_object_categories():
    obj=SimpleNamespace(unattended=False,component={},object_kind='weapon')
    assert object_multiplier({'object_multiplier':2},obj)==2
    assert object_multiplier({'double_object_kinds':['unattended','structure']},obj)==1
    obj.unattended=True
    assert object_multiplier({'double_object_kinds':['unattended','structure']},obj)==2
    with pytest.raises(ValueError):object_multiplier({'double_object_kinds':['name']},obj)


def test_observer_panel_owner_privacy_and_distance():
    app=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--test','static/tabletop/observer-information.test.mjs'],cwd=app,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('seed',stock.STOCK_SEEDS)
def test_exact_base_stock_unchanged(tmp_path,monkeypatch,seed):
    # Pin the main revision merged before this fix round, excluding unrelated
    # main changes from the lane's byte-for-byte replay comparison.
    monkeypatch.setenv('CF_REPLAY_BASE','df24524e8e0fcb5af7c88b63482b24471ee92958')
    monkeypatch.setattr(stock,'EVIDENCE',tmp_path/'captures')
    stock.test_six_stock_captures_equal_main(tmp_path,seed)


def test_vertical_placement_is_explicit_and_default_inert():
    from combat.cell_placement import altitudes
    from combat.gate2_runtime_models import Position
    levels=[0,4];actor=SimpleNamespace(entity_id='a',position=Position(x=1,y=1,z=1));engine=SimpleNamespace()
    action=SimpleNamespace(parameters={})
    assert altitudes(engine,actor,action,levels) is levels
    action.parameters={'cell_placement':{'vertical_range_ft':10}}
    assert list(altitudes(engine,actor,action,levels))==[0,1,2,3]
    action.parameters['cell_placement']['vertical_range_ft']=3
    with pytest.raises(ValueError):altitudes(engine,actor,action,levels)
