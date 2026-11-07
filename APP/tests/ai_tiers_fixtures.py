"""Synthetic character sheets for AI tier tests, independent of combat runtime.

Callers supply mechanical records from the shipped corpus (native fights) or
small synthetic records (public fixture tests). No owner character, repository
history, model client, compiler, or filesystem data is read here.
"""


def sheet(mids, *, mechanics, cl=10, name, kit=None):
    """Build the equal-stat sheet used by the native AI duels."""
    mids = list(mids)
    spheres = list(dict.fromkeys(mechanics[mid]["sphere_id"] for mid in mids
                                 if mechanics[mid].get("sphere_id")))
    out = {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl,
                     "path": "Qi Cultivation", "key_ability": "CON", "name": name},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2}
                          for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30},
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": 16,
            "technique_attack_bonus": 8,
        },
    }
    if spheres:
        out["spheres_and_talents"] = {
            "sphere_record_ids": spheres,
            "learned_talent_record_ids": [mid for mid in mids if mechanics[mid].get("sphere_id")],
            "automatic_sphere_component_record_ids": [
                mid for mid, row in mechanics.items()
                if row.get("sphere_id") in spheres and row.get("kind") == "base_ability"],
        }
    if kit:
        out["equipment"] = [kit]
    return out
