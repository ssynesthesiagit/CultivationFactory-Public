"""Saving-throw proficiency read by Lightning Grounding, for current and pre-change saved bundles.

Synthetic engine and actor only: no fixtures, owner data or saved fights are needed.
"""
from types import SimpleNamespace

from combat.save_proficiencies import is_proficient


def _engine(bundle, passive_rows=None):
    return SimpleNamespace(typed_bundle_documents=[bundle],
                           typed_passive_rows={"actor": passive_rows or []})


ACTOR = SimpleNamespace(entity_id="actor", conditions={})


def test_current_bundle_sealed_list_is_read():
    engine = _engine({"actor_id": "actor", "save_proficiencies": ["WIS"]})
    assert is_proficient(engine, ACTOR, "wis")
    assert not is_proficient(engine, ACTOR, "DEX")


def test_current_bundle_without_proficiency_is_not_proficient():
    engine = _engine({"actor_id": "actor"})
    assert not is_proficient(engine, ACTOR, "WIS")


def test_pre_change_saved_bundle_keeps_grounding_row_proficiency():
    # A fight saved before the bundle sealed save_proficiencies kept it only on the Grounding Breath row.
    engine = _engine({"actor_id": "actor"},
                     [{"block": "grounding_breath", "proficient_saves": ["WIS"]}])
    assert is_proficient(engine, ACTOR, "WIS")
    assert not is_proficient(engine, ACTOR, "DEX")
