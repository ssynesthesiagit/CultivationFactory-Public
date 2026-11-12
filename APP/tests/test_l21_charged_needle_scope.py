"""Charged Needle's compiler scope matches its printed attack categories."""

from combat.factory_compiler import _resolve_targets


def test_charged_needle_scope_selects_only_needle_and_pressure_point_attacks():
    modifier = {"scope": "attack_or_sphere_technique", "scope_filter": {
        "attack_flags": ["needle"], "weapon_families": ["Projectile / Throwing Dart Proficiency"],
        "sphere_ids": ["tianxia.sphere.pressure_points"]}}
    owner = {"sphere_id": "tianxia.sphere.lightning"}
    built = {
        "needle weapon": {"mechanic": {"name": "Spear attack", "sphere_id": "tianxia.sphere.spears"},
                          "typed": {"weapon": {"implement_id": "needle.01", "weapon_family": "Projectile / Throwing Dart Proficiency"},
                                    "effects": [{"type": "attack", "attack_kind": "weapon"}]}},
        "pressure point": {"mechanic": {"name": "Intercepting Tap", "sphere_id": "tianxia.sphere.pressure_points"},
                           "typed": {"effects": [{"type": "save", "on_fail": [{"type": "condition"}]}]}},
        "needle flag": {"mechanic": {"name": "Needle attack", "sphere_id": "tianxia.sphere.other"},
                        "typed": {"effects": [{"type": "attack", "attack_kind": "needle"}]}},
        "substring control": {"mechanic": {"name": "Heart-Stopping Reversal", "sphere_id": "tianxia.sphere.iron_fist"},
                              "typed": {"effects": [{"type": "attack", "attack_kind": "weapon"}]}},
        "lightning lash": {"mechanic": {"name": "Lightning Lash", "sphere_id": "tianxia.sphere.lightning"},
                           "typed": {"effects": [{"type": "attack", "attack_kind": "cultivation_ranged"}]}},
    }
    assert _resolve_targets(modifier, owner, built, {}, {}, {}) == (["needle weapon", "pressure point", "needle flag"], [])
