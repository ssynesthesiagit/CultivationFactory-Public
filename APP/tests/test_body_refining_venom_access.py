"""Venom Body's prerequisite is checked by the common Path access rule."""
from combat import table_advance
from factory_authoring.path_access import blocked, can_learn
from tests.test_mgr_venom_appraise import (
    ME, appraise, cold, offline_ranking, readings, setup,
)

BODY = "tianxia.path.body_refining"
QI = "tianxia.path.qi_cultivation"
POISON = "tianxia.sphere.poison"
METHOD = "tianxia.talent.poison.venom_body_method"
SCRIPTURE = "tianxia.scripture.poison.venom_body_scripture"


def test_venom_route_requires_an_owned_record():
    assert not can_learn(POISON, [BODY])
    assert blocked(POISON, [BODY])
    assert can_learn(POISON, [BODY], [METHOD])
    assert can_learn(POISON, [BODY], [SCRIPTURE])
    assert can_learn(POISON, [QI])
    have = {"cl": 3, "spheres": set(), "paths": [BODY], "talents": set()}
    assert not table_advance.sphere_status(POISON, have)["legal"]
    have["talents"].add(METHOD)
    assert table_advance.sphere_status(POISON, have)["legal"]


def test_owned_method_enables_venom_variant_at_table_and_reload(tmp_path):
    combat, table, mid = setup(tmp_path, owner_path="Body Refining", extra=(METHOD,))
    _, engine = cold(tmp_path, mid)
    assert any(row.get("kind") == POISON for row in engine.typed_passive_rows[ME]
               if row.get("block") == "br_variant")
    appraise(combat, table, mid)
    assert "poison is present" in str(readings(table, mid)).lower()
    cold(tmp_path, mid)
