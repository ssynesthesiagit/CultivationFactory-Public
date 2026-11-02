"""Hash-matched owner typing and the joint attack-ability branch regression."""
import hashlib
import json

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet

IRON_FIST = "tianxia.path.body_refining.feature.iron_fist"


def test_iron_fist_review_matches_current_text_and_preserves_the_full_typing():
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[IRON_FIST]
    final = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/owner_iron_fist_2026-09-30.json").read_text())["mechanics"][IRON_FIST]
    record = authority["mechanics"][IRON_FIST]
    # The builder hashes the source section including its trailing newline;
    # hover text is a stripped display copy and is not the authority hash input.
    from tools.typed_mechanics_helpers import sources
    source = next(row for row in sources() if row["id"] == IRON_FIST)
    assert source["text"].strip() == text
    assert final["text_sha256"] == record["source"]["text_sha256"] == hashlib.sha256(source["text"].encode()).hexdigest()
    assert record["typing_status"] == "reviewed_final"
    assert "owner_edit" not in record
    assert next(row for row in authority["owner_text_edits"] if row["mechanic_id"] == IRON_FIST) == {
        "mechanic_id": IRON_FIST, "status": "typed_from_edited_text", "problems": []}
    for field in ("effects", "modifier", "activation", "riders", "cost", "duration"):
        assert record[field] == final[field]
    damage_rows = [record["effects"][0], record["effects"][1]["on_hit"][0], record["modifier"]["effects"][0]]
    for row in damage_rows:
        assert row["evidence"] == "1d8 + Strength, Dexterity or Constitution modifier"
        assert row["evidence"] in text
        assert row["dice"]["count"] == 1 and row["dice"]["sides"] == 8
        assert row["damage_types"] == ["bludgeoning", "piercing", "slashing"]
    assert all(rider in text for rider in record["riders"])


@pytest.mark.parametrize("scores, expected", [((10, 18, 12), 4), ((18, 10, 12), 4), ((10, 12, 18), 4)])
def test_iron_fist_uses_highest_allowed_modifier_after_attack_ability_branch_merge(scores, expected):
    blocks = json.loads((ROOT / "combat/rules/feature_blocks.json").read_text())
    if "DEX" not in blocks["features"][IRON_FIST]["abilities"]:
        pytest.skip("Requires lead to merge fix/attack-ability (1127fc3f): Iron Fist feature block still lacks DEX")
    owner = sheet([IRON_FIST], score=10)
    for row in owner["ability_scores_and_statistics"]["abilities"]:
        if row["ability"] in ("STR", "DEX", "CON"):
            score = dict(zip(("STR", "DEX", "CON"), scores))[row["ability"]]
            row.update(score=score, modifier=(score - 10) // 2)
    bundle = compile_character(owner, actor_id="actor:factory.qa5f")
    action = next(row for row in bundle["action_catalog"] if row["source_definition_id"].endswith(".natural.iron_fist"))
    typed = action["parameters"]["typed"]
    assert typed["numbers"]["attack_bonus"] == 4 + expected
    assert typed["weapon"]["damage"] == {"count": 1, "sides": 8, "modifier": expected}
