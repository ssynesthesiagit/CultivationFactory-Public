"""TEMP DIAGNOSTIC - delete before commit."""
import pytest
from tests.worker2_support import OWNER, fixture, reload, settle
from tests.test_action_variants import QI

PREFIX = "tianxia.talent.imbuement."
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}}


def _run(tmp_path, mode):
    from combat.ext import imbuement_mandates as mandates
    combat, table, mid = fixture(tmp_path, ["IMBUEMENT_BASE_PLACE_MANDATE", PREFIX + "tempered_equipment",
        PREFIX + "mass_mandate", PREFIX + "name_the_army_s_gear", PREFIX + "layered_mandate", PREFIX + "qi_written_mandate"], owner_kit=KIT)
    engine = reload(tmp_path, mid)
    actions = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.variant and a.variant.base_label == "Place Mandate: Temper (armor)"]
    action = next(a for a in actions if (next((p.key for p in a.variant.choices if p.axis == "targets"), "single") == mode))
    selected = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id and c.target_ids == (OWNER,))
    targets = [t.entity_id for t in mandates._mass_targets(engine, engine.state.actors[OWNER], action)]
    settle(table, mid, selected.candidate_id, picks={"choice:needle.mass_mandate": [OWNER]})
    after = reload(tmp_path, mid)
    return engine, action, targets, after


@pytest.mark.parametrize("mode", ["mass", "army"])
def test_a_targets(tmp_path, mode):
    engine, action, targets, after = _run(tmp_path, mode)
    assert targets == [OWNER], "TARGETS " + repr(targets)


@pytest.mark.parametrize("mode", ["mass", "army"])
def test_b_conditions(tmp_path, mode):
    engine, action, targets, after = _run(tmp_path, mode)
    assert False, "CONDS " + repr(sorted(after.state.actors[OWNER].conditions))


@pytest.mark.parametrize("mode", ["mass", "army"])
def test_c_armor(tmp_path, mode):
    from combat.ext import imbuement_mandates as mandates
    engine, action, targets, after = _run(tmp_path, mode)
    a = after.state.actors[OWNER]
    assert False, "ARMOR " + repr(mandates.vessel_armor(after, a)) + " QI " + repr(a.resources.get(QI)) + " MODS " + repr(sorted(a.modifiers))
