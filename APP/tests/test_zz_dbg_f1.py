"""TEMP DIAGNOSTIC - delete before commit."""
from combat.action_variants import cost_delta
from tests.worker2_support import OWNER, fixture, reload, settle
from tests.test_action_variants import QI
import pytest


@pytest.mark.parametrize("mode", ["mass", "army"])
def test_dbg(tmp_path, mode):
    from combat.ext import imbuement_mandates as mandates
    prefix = "tianxia.talent.imbuement."
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}}
    combat, table, mid = fixture(tmp_path, ["IMBUEMENT_BASE_PLACE_MANDATE", prefix + "tempered_equipment",
        prefix + "mass_mandate", prefix + "name_the_army_s_gear", prefix + "layered_mandate", prefix + "qi_written_mandate"], owner_kit=kit)
    engine = reload(tmp_path, mid)
    actions = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.variant and a.variant.base_label == "Place Mandate: Temper (armor)"]
    action = next(a for a in actions if (next((p.key for p in a.variant.choices if p.axis == "targets"), "single") == mode))
    log = [f"ACTION {action.source_definition_id} params_mass={(action.parameters or {}).get('mass_mandate')}"]
    rows = ((action.parameters or {}).get("typed") or {}).get("effects")
    log.append(f"ROWS {rows}")
    selected = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id and c.target_ids == (OWNER,))
    log.append(f"CAND {selected.candidate_id} targets={selected.target_ids}")
    log.append(f"CARRY {mandates._army_equipment_on(engine, engine.state.actors[OWNER], {'armor'})} weapons_armor={mandates._weapons(engine, engine.state.actors[OWNER], 'armor')}")
    log.append(f"MASS_TARGETS {[t.entity_id for t in mandates._mass_targets(engine, engine.state.actors[OWNER], action)]}")
    prompts = settle(table, mid, selected.candidate_id, picks={"choice:needle.mass_mandate": [OWNER]})
    after = reload(tmp_path, mid)
    actor = after.state.actors[OWNER]
    log.append(f"CONDS {sorted(actor.conditions)}")
    log.append(f"MODS {sorted(actor.modifiers)}")
    log.append(f"QI before={engine.state.actors[OWNER].resources[QI]} after={actor.resources[QI]}")
    log.append(f"ARMOR {mandates.vessel_armor(after, actor)}")
    log.append(f"LOG {getattr(after, 'log', None) and str(after.log)[-1500:]}")
    assert False, "\n".join(log)
