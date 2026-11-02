"""Which Paths may learn which Spheres, and Body Refining's external projection (owner 2026-09-27: "body refining isnt
modifying access to spheres ... The ai chose lava spit and other ranged qi techniques")."""

import json
from pathlib import Path

from character_creation.creative_controller.linear_menus import _Candidate, _path_legal
from factory_authoring.path_access import blocked, can_learn

BODY, QI = "tianxia.path.body_refining", "tianxia.path.qi_cultivation"
MECHANICS = json.loads((Path(__file__).resolve().parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
LAVA_SPIT = next(key for key, row in MECHANICS.items() if row["name"] == "Lava Spit")


def test_a_sphere_its_path_is_not_listed_for_is_closed():
    assert not can_learn("tianxia.sphere.ash", [BODY])  # Ash: Qi Cultivation, Spirit Awakening
    assert can_learn("tianxia.sphere.ash", [QI]) and can_learn("tianxia.sphere.axes", [BODY])
    assert can_learn("tianxia.sphere.magma", [BODY])  # "through Volcanic Body scripture": allowed until the owner rules


def test_body_refining_does_not_project_qi_without_an_exception():
    assert "projects Qi" in blocked(LAVA_SPIT, [BODY])
    assert blocked(LAVA_SPIT, [QI]) is None and blocked(LAVA_SPIT, [BODY, QI]) is None
    assert blocked("TAL_AXES_HEWING_STRIKE", [BODY]) is None  # a weapon attack


def test_the_builder_drops_what_the_path_cannot_take_but_never_strands_a_menu():
    committed = {"by_slot": {"path_choice": [BODY]}}
    options = [_Candidate((LAVA_SPIT,), "Lava Spit"), _Candidate(("TAL_AXES_HEWING_STRIKE",), "Hewing Strike")]
    assert [c.cue for c in _path_legal({}, {}, committed, "ordinary_talent", options, 1)] == ["Hewing Strike"]
    only = [_Candidate((LAVA_SPIT,), "Lava Spit")]
    assert _path_legal({}, {}, committed, "ordinary_talent", only, 1) == only  # nothing else to take: left as it was
    assert _path_legal({}, {}, {"by_slot": {}}, "ordinary_talent", options, 1) == options  # no Path chosen yet
