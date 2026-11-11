"""Current-tree Spirit sheet for Guard's native Soul Drain service tests.

Keep this fixture independent of historical rider tests: public CI exports the
current source tree, without the private Git revisions those tests can select.
The values match the Spirit Awakening fixture used by the original regression.
"""


def spirit_sheet(ids, *, dc=17):
    modifiers = {"STR": 1, "DEX": 2, "CON": 2, "INT": 1, "WIS": 4, "CHA": 1}
    return {
        "identity": {"proficiency_bonus": 6, "cultivation_level": 18,
                     "path": "Spirit Awakening", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": ability, "score": 10 + 2 * modifier,
                           "modifier": modifier} for ability, modifier in modifiers.items()],
            "primary_resource": {"name": "Resonance", "maximum": 60},
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 90},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc,
            "technique_attack_bonus": 9,
        },
        "path_and_subpath": {"path_record_ids": [], "path_feature_record_ids": list(ids)},
    }
