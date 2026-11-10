"""Insight prerequisites are typed clause by clause (smoke test 2026-09-23)."""

from __future__ import annotations

from catalog_authority.cat3.compiler import _insight_prerequisite_relations, normalize
from character_creation.creative_controller.linear_menus import _relation_satisfied

SPHERES = {normalize("Harvesting Gathering"): "tianxia.sphere.harvesting_gathering", normalize("Alchemy"): "tianxia.sphere.alchemy"}
TALENTS = {
    normalize("Corpse Servant"): ["TAL_DEATH_CORPSE_SERVANT"],
    normalize("Animate Minor Vessel"): ["tianxia.talent.imbuement.animate_minor_vessel"],
    normalize("Speak to the Vessel"): ["tianxia.talent.imbuement.speak_to_the_vessel"],
    normalize("Simple Beast Dressing"): ["tianxia.talent.harvesting_gathering.simple_beast_dressing"],
}


def _relations(text: str, **raw: object) -> list[dict]:
    relations, _terms = _insight_prerequisite_relations(
        {"prerequisites": text, **raw},
        sphere_ids_by_name=SPHERES,
        unique_insight_ids_by_name={},
        talent_ids_by_name=TALENTS,
    )
    return relations


def test_talent_prerequisites_are_required() -> None:
    assert _relations("Corpse Servant, CL 8+") == [{"kind": "talent", "target_id": "TAL_DEATH_CORPSE_SERVANT", "operator": "requires"}]
    kinds = {(r["kind"], r["target_id"]) for r in _relations("Harvesting and Gathering, Simple Beast Dressing, CL 8+.")}
    assert kinds == {("sphere", "tianxia.sphere.harvesting_gathering"), ("talent", "tianxia.talent.harvesting_gathering.simple_beast_dressing")}


def test_or_is_one_of_and_the_controller_accepts_any_alternative() -> None:
    (relation,) = _relations("Animate Minor Vessel or Speak to the Vessel, CL 8+")
    assert relation["operator"] == "one_of" and len(relation["value"]) == 2
    assert _relation_satisfied(relation, {"tianxia.talent.imbuement.speak_to_the_vessel"}) is True
    assert _relation_satisfied(relation, {"something.else"}) is False


def test_roleplay_conditions_pass_and_mechanical_unknowns_fail_closed() -> None:
    assert _relations("Survive a Sword, Saber, Blade, Weapon, Killing-Intent Tribulation") == []
    (relation,) = _relations("Constitution 15+")
    assert relation["kind"] == "narrative_condition" and relation["operator"] == "requires"
    assert _relation_satisfied(relation, {"TAL_DEATH_CORPSE_SERVANT"}) is False
