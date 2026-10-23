"""F12R finding 1: Claimed Province grants allies Half Cover against ranged attack rolls.

Drives the plug-in's directional_cover hook directly with the in-memory engine
used by the other Dragon-Vein regression files. Only ownership, Province and
Claimed Ground queries are monkeypatched.
"""
from types import SimpleNamespace

from combat.ext import dragon_vein_geomancer as dv
from combat.gate2_runtime_models import Position


class Engine:
    def __init__(self, owner, ally, foe):
        self.state = SimpleNamespace(actors={'owner': owner, 'ally': ally, 'foe': foe})


def actor(eid, x=0, y=0):
    return SimpleNamespace(entity_id=eid, position=Position(x=x, y=y, z=0))


def setup(monkeypatch, *, province_ally=True):
    owner, ally, foe = actor('owner'), actor('ally', 3, 3), actor('foe', 8, 8)
    eng = Engine(owner, ally, foe)
    monkeypatch.setattr(dv, 'kit', lambda e, a: {'owned': [dv.IMPERIAL]} if a.entity_id == 'owner' else None)
    monkeypatch.setattr(dv, 'state', lambda a: {'allies': ['ally']} if a.entity_id == 'owner' else {})
    monkeypatch.setattr(dv, 'in_province', lambda e, o, p: province_ally and p.x == 3)
    monkeypatch.setattr(dv, 'claimed', lambda e, o, p: True)
    return eng, ally, foe


def test_ranged_attack_on_ally_in_province_gets_half_cover(monkeypatch):
    eng, ally, foe = setup(monkeypatch)
    assert dv.province_cover(eng, foe, ally, {'ranged': True}) == 2


def test_melee_attack_on_ally_in_province_gets_no_province_cover(monkeypatch):
    eng, ally, foe = setup(monkeypatch)
    assert dv.province_cover(eng, foe, ally, {'ranged': False}) is None


def test_non_ally_in_province_gets_no_province_cover(monkeypatch):
    eng, ally, foe = setup(monkeypatch)
    assert dv.province_cover(eng, foe, foe, {'ranged': True}) is None


def test_ally_outside_the_province_gets_no_province_cover(monkeypatch):
    eng, ally, foe = setup(monkeypatch, province_ally=False)
    assert dv.province_cover(eng, foe, ally, {'ranged': True}) is None
