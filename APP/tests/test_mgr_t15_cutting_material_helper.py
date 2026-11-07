"""Regression: the cutting material check lives in water_second_pass (no shared water_materials module).

Fails before the fix because combat/ext/water_materials.py existed and was imported by water_second_pass.
"""
from types import SimpleNamespace

import importlib.util

from combat.ext import water_second_pass as wsp


def _obj(material, unattended=True, **component):
    return SimpleNamespace(unattended=unattended, component={'material': material, **component})


def test_water_materials_module_is_gone():
    assert importlib.util.find_spec('combat.ext.water_materials') is None


def test_unattended_mundane_listed_material_is_eligible():
    assert wsp.unattended_mundane_material(_obj('Soft_Stone'), wsp.CUTTING_MATERIALS)
    assert wsp.unattended_mundane_material(_obj('rope'), wsp.CUTTING_MATERIALS)


def test_attended_artifact_magical_or_unlisted_material_is_ineligible():
    assert not wsp.unattended_mundane_material(_obj('rope', unattended=False), wsp.CUTTING_MATERIALS)
    assert not wsp.unattended_mundane_material(_obj('rope', artifact=True), wsp.CUTTING_MATERIALS)
    assert not wsp.unattended_mundane_material(_obj('rope', magical=True), wsp.CUTTING_MATERIALS)
    assert not wsp.unattended_mundane_material(_obj('iron'), wsp.CUTTING_MATERIALS)
    assert not wsp.unattended_mundane_material(SimpleNamespace(unattended=True, component=None), wsp.CUTTING_MATERIALS)
