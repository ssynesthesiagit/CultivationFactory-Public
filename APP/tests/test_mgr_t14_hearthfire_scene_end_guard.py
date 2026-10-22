"""Regression: a world-fact request cannot forge a scene end (review fix, Hearthfire 1F16).

Scene ends must go through end_scene, which checks the phase, advances the scene
id and number and emits SCENE_ENDED. The generic world-fact path must refuse them.
"""
import pytest
from tests.test_mgr_t14_hearthfire_native import journey


def test_world_fact_cannot_record_a_scene_end_receipt(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    before=cold().journey_state(jid)
    forged={'source':'system:journey.scene','subject':a,'kind':'scene_end','scope':jid+':forged',
            'value':'The tea-house meeting ends and the guests leave.','expires_at':before['seconds']+1,'readers':[]}
    with pytest.raises(ValueError,match='Only the native end-scene action'):
        cold().journey_world_fact(jid,before['revision'],forged)
    after=cold().journey_state(jid)
    assert after==before
    assert after.get('scene_number',0)==0
    assert not [e for e in after['events'] if e.get('kind')=='SCENE_ENDED']


def test_world_fact_rejects_scene_end_kind_under_any_source(tmp_path,monkeypatch):
    cold,jid,act,a,b=journey(tmp_path,monkeypatch)
    before=cold().journey_state(jid)
    forged={'source':'system:journey.other','subject':a,'kind':'scene_end','scope':jid+':forged',
            'value':'x','expires_at':before['seconds']+1,'readers':[]}
    with pytest.raises(ValueError,match='Only the native end-scene action'):
        cold().journey_world_fact(jid,before['revision'],forged)
    assert cold().journey_state(jid)==before
