"""Permanent score changes also shift legacy published combat totals."""

from combat.table_advance import recompute_from_abilities


def test_permanent_score_projection_reads_legacy_totals():
    before = {
        "identity": {"cultivation_level": 4},
        "ability_scores_and_statistics": {
            "armor_class": "12",
            "initiative": {"bonus": "5"},
            "skills": [{"skill": "Acrobatics", "bonus": "7"},
                       {"skill": "Athletics", "ability": "DEX", "bonus": "9"}],
            "saving_throws": {"DEX": "4"},
            "technique_attack_bonus": "9",
            "technique_save_dc": "17",
        },
    }
    old = {"STR": 10, "DEX": 14, "INT": 14}
    new = {"STR": 10, "DEX": 16, "INT": 16}
    totals = recompute_from_abilities(before, old, new)["ability_scores_and_statistics"]

    assert (totals["armor_class"], totals["initiative"]["bonus"]) == (13, 6)
    assert [row["bonus"] for row in totals["skills"]] == [8, 10]
    assert totals["saving_throws"]["DEX"] == 5
    assert (totals["technique_attack_bonus"], totals["technique_save_dc"]) == (10, 18)
    assert before["ability_scores_and_statistics"]["initiative"]["bonus"] == "5"
