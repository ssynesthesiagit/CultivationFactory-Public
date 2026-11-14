"""Alchemy Training's source/catalog boundary, not proof of learning execution.

The acquisition proficiency and conditional bonus-talent producer remain open.
Keep this narrow check separate from combat tests that seed already-owned rows.
"""

import hashlib
import json
from pathlib import Path

from character_builder import CharacterBuilderService


ROOT = Path(__file__).resolve().parents[1]
TRAINING = "ALCHEMY_BASE_ALCHEMY_TRAINING"


def test_alchemy_training_native_catalog_preserves_source_and_automatic_package(catalog_environment):
    catalog = CharacterBuilderService(catalog_environment["db"]).canonical_catalog
    sphere = catalog.get_sphere("tianxia.sphere.alchemy")
    components = {row["source_component_name"]: row for row in sphere["automatic_base_abilities"]}
    assert set(components) == {
        "Alchemy Training", "Alchemy Check", "Pill Forging", "Field Formula", "Reagent Stock",
    }
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    text = rules[TRAINING]
    assert hashlib.sha256(text.encode()).hexdigest() == (
        "a7db5f2cd10be26e31bd7d6a111a948608244a33cb443e7dbac027133b84b87d"
    )
    assert text in sphere["full_exact_source_text"]
    training = components["Alchemy Training"]
    assert training["player_rules_text"] == text
    for row in components.values():
        assert row["automatic_grant"] is True
        assert row["owner_removable"] is False
        assert row["counts_as_talent_choice"] is False
        assert row["counts_as_advancement_talent"] is False
        assert row["counts_as_training_talent"] is False
    # Other spheres must not advertise this owner's training package.
    air = catalog.get_sphere("tianxia.sphere.air")
    assert "Alchemy Training" not in {row["source_component_name"] for row in air["automatic_base_abilities"]}
