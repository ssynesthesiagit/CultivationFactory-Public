"""The character's Dao, combined from the Sphere Dao master list."""

from factory_authoring.sphere_dao import authority, character_dao, mark_label


def test_every_current_sphere_has_a_profile_and_the_hexagram_table_is_complete():
    data = authority()
    assert len(data["spheres"]) == 85
    assert {row["status"] for row in data["spheres"].values()} == {"owner", "draft"}
    assert sorted(row["number"] for row in data["hexagrams"].values()) == list(range(1, 65))
    # Thunder over Mountain is Xiao Guo; Earth over Heaven is Tai.
    assert data["hexagrams"]["zhen/gen"]["number"] == 62
    assert data["hexagrams"]["kun/qian"]["number"] == 11


def test_layers_are_weighted_by_softened_investment():
    dao = character_dao({
        "tianxia.sphere.air": 42, "tianxia.sphere.berserker": 12, "tianxia.sphere.disease": 8,
        "tianxia.sphere.daemonic_cultivation": 4, "tianxia.sphere.sabers": 2,
        "tianxia.sphere.dual_wielding": 1, "tianxia.sphere.scoundrel": 1,
    })
    assert [layer["name"] for layer in dao["layers"]][:3] == ["Air", "Berserker", "Disease"]
    assert round(dao["layers"][0]["weight"], 2) == 6.56  # sqrt(42 + 1)
    assert dao["hexagram"]["number"] == 62
    assert dao["posture"]["shadow"]["line"] == 6 and dao["excess"]["becomes"]["number"] == 56
    assert len(dao["dao_verbs"]) == 6 and "rages" in dao["dao_verbs"]
    assert set(dao["draft_spheres"]) == {"Berserker", "Sabers", "Dual Wielding"}


def test_unknown_spheres_are_reported_not_guessed():
    assert character_dao({}) is None
    dao = character_dao({"tianxia.sphere.life": 0, "tianxia.sphere.not_a_sphere": 3})
    assert dao["unprofiled_sphere_ids"] == ["tianxia.sphere.not_a_sphere"]
    assert [mark_label(n) for n in (1, 2, 3, 5)] == ["hint", "tendency", "trail", "strong resonance"]


def test_the_combat_ai_policy_follows_the_dao():
    from pathlib import Path

    from combat.gate4_models import LocalControllerPolicy
    from combat.gate4_policy import PolicyLibrary
    from factory_authoring.sphere_dao import controller_policy

    thunder = character_dao({"tianxia.sphere.air": 42, "tianxia.sphere.berserker": 12, "tianxia.sphere.sabers": 2})
    earth = character_dao({"tianxia.sphere.life": 5, "tianxia.sphere.guardian": 3})
    striker, keeper = controller_policy(thunder, "actor:a"), controller_policy(earth, "actor:b")
    LocalControllerPolicy.model_validate(striker)
    # Thunder presses and finishes at close range; Earth covers its allies.
    assert striker["weights"]["immediate_effect"] > keeper["weights"]["immediate_effect"]
    assert keeper["weights"]["ally_support"] > striker["weights"]["ally_support"]
    assert striker["preferred_range_bands_ft"][0] == (5, 15)

    library = PolicyLibrary(Path(__file__).resolve().parents[1], actor_policy=lambda actor: striker if actor == "actor:a" else None)
    policy, fallback = library.for_actor("actor:a")
    assert not fallback and policy.policy_id == "policy:dao.actor:a"
    assert library.for_actor("actor:unknown")[1] is True
