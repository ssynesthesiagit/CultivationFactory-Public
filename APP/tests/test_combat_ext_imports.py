"""Every combat/ext plug-in imports cleanly, so a removed name cannot crash a release at runtime."""
import importlib
import pkgutil

import pytest

import combat.ext as ext

MODULES = sorted(m.name for m in pkgutil.iter_modules(ext.__path__))


@pytest.mark.parametrize("name", MODULES)
def test_combat_ext_module_imports(name):
    importlib.import_module(f"combat.ext.{name}")


def test_thrown_equipment_has_no_removed_grip_name():
    from combat.ext import hand_occupancy, thrown_equipment

    assert not hasattr(hand_occupancy, "GRIP")
    source = open(thrown_equipment.__file__, encoding="utf-8").read()
    assert "import GRIP" not in source
