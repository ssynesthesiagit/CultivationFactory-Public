"""Ascetic Body immunities (RW189 fix round, review findings 1 and 2).

Rules text (authority/typed_mechanics/rules_text.json, Ascetic Body): "Immunity to mundane disease." and "Immunity to environmental
cold." (the old rider's "not Cold damage" scope). Both are automated in combat/ext/yamabushi.py (``ascetic_immunities``, on
automatic_save_success): an Ascetic's save against one of them succeeds without a die. Each positive test runs a real typed save
through typed_executor.block_save and checks the roll count, so it fails on the code before this fix; the control creature lacks
the feature and rolls as before.
"""

from __future__ import annotations

import json
from pathlib import Path

from combat import typed_executor
from combat.ext import spirit_traditions as st
from combat.ext.disease import DISEASE_SPHERE
from combat.gate2_runtime_models import ActionIntent

from tests.test_riders_c7 import FOE, ME, YAMA, _yama

ROOT = Path(__file__).resolve().parents[1]
ASCETIC = YAMA + "ascetic_body"
SICKENED = "condition:typed.sickened"
COLD_SAVE_ROWS = {"on_fail": [{"type": "condition", "applies_to": "target", "condition": "prone"}], "on_success": []}


def _save(engine, effect_rows, *, categories=None, sphere=None):
    """A hostile typed save from FOE against ME, shaped like a compiled ability's save row."""
    foe, me = engine.state.actors[FOE], engine.state.actors[ME]
    engine._active_intent = ActionIntent(intent_id=f"rw189-save-{len(engine.events)}", decision_id="rw189-save", candidate_id="rw189-save",
                                         state_version=engine.state.state_version, actor_id=FOE, target_ids=(ME,))
    ctx = st.context(engine, foe, st.feature_action(engine, foe, "test:rw189_ascetic_save"), [me], {"save_dc": 15, "pb": 3, "cl": 5})
    if sphere is not None:
        ctx.typed["sphere"] = sphere
    effect = {"type": "save", "applies_to": "target", "ability": "con", **effect_rows}
    if categories is not None:
        effect["save_categories"] = list(categories)
    try:
        typed_executor.block_save(ctx, effect)
    finally:
        engine._active_intent = None


def _disease_rows():
    return {"on_fail": [{"type": "condition", "applies_to": "target", "condition": "sickened",
                         "duration": "until_start_of_next_turn"}], "on_success": []}


def _sickened(engine):
    return any(c.condition_id == SICKENED for c in engine.state.actors[ME].conditions.values())


def test_ascetic_is_immune_to_a_mundane_disease_save_without_a_roll():
    engine, _me, _foe = _yama(["ascetic_body"])
    before = len(engine.rolls)
    _save(engine, _disease_rows(), categories=["disease"])
    assert len(engine.rolls) == before and not _sickened(engine)


def test_a_creature_without_ascetic_body_still_rolls_a_disease_save():
    engine, _me, _foe = _yama([])
    before = len(engine.rolls)
    _save(engine, _disease_rows(), categories=["disease"])
    assert len(engine.rolls) == before + 1


def test_ascetic_is_not_immune_to_disease_from_a_disease_sphere_source():
    """A Disease-sphere ability is supernatural, so the mundane-disease immunity does not apply to it."""
    engine, _me, _foe = _yama(["ascetic_body"])
    before = len(engine.rolls)
    _save(engine, _disease_rows(), categories=["disease"], sphere=DISEASE_SPHERE)
    assert len(engine.rolls) == before + 1


def test_ascetic_is_immune_to_an_environmental_cold_save_without_cold_damage():
    engine, _me, _foe = _yama(["ascetic_body"])
    before = len(engine.rolls)
    _save(engine, COLD_SAVE_ROWS, categories=["environmental_cold"])
    assert len(engine.rolls) == before


def test_ascetic_is_not_immune_to_cold_damage_from_an_environmental_cold_save():
    """"Not Cold damage": a save whose rows deal Cold damage still rolls."""
    engine, _me, _foe = _yama(["ascetic_body"])
    before = len(engine.rolls)
    rows = {"on_fail": [{"type": "damage", "applies_to": "target", "damage_types": ["cold"], "dice": "2d6"}], "on_success": []}
    _save(engine, rows, categories=["environmental_cold"])
    assert len(engine.rolls) == before + 1


def test_disease_immunity_rider_is_no_longer_a_gm_rider_in_the_authority():
    """The record carries the automated immunities; the "non-combat" rider the review rejected is gone from the source table."""
    table = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/paths.json").read_text(encoding="utf8"))
    record = table["mechanics"][ASCETIC]
    assert record["riders"] == []
    assert "non-combat" not in json.dumps(record)
