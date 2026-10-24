import json
import pytest
from combat.ext import imbuement_mandates as mandates
from tests.worker2_support import OWNER, fixture, reload, settle

QI = "resource:core.qi"

@pytest.mark.parametrize("mode", ["single", "mass", "army"])
def test_diag(tmp_path, mode):
    prefix = "tianxia.talent.imbuement."
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}}
    combat, table, mid = fixture(tmp_path, ["IMBUEMENT_BASE_PLACE_MANDATE", prefix + "tempered_equipment",
        prefix + "mass_mandate", prefix + "name_the_army_s_gear", prefix + "layered_mandate", prefix + "qi_written_mandate"], owner_kit=kit)
    engine = reload(tmp_path, mid)
    actions = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.variant and a.variant.base_label == "Place Mandate: Temper (armor)"]
    action = next(a for a in actions if (next((p.key for p in a.variant.choices if p.axis == "targets"), "single") == mode))
    out = {"action": action.source_definition_id, "costs": str(action.costs), "params_mass": bool((action.parameters or {}).get("mass_mandate"))}
    out["roster"] = [t.entity_id for t in mandates._mass_targets(engine, engine.state.actors[OWNER], action)]
    out["all_actors"] = list(engine.state.actors)
    out["owner_weapons_armor"] = str(mandates._weapons(engine, engine.state.actors[OWNER], "armor"))
    cands = [c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id]
    out["cands"] = [(c.candidate_id, c.target_ids) for c in cands][:10]
    selected = next(c for c in cands if c.target_ids == (OWNER,))
    prompts = settle(table, mid, selected.candidate_id, picks={"choice:needle.mass_mandate": [OWNER]})
    out["prompts"] = [p["context"]["reaction_source_id"] for p in prompts]
    after = reload(tmp_path, mid)
    o = after.state.actors[OWNER]
    out["owner_conds"] = [(c.condition_id, c.source_definition_id, str(c.data)[:150]) for c in o.conditions.values()]
    out["armor"] = mandates.vessel_armor(after, o)
    out["events"] = [(e.event_type, e.actor_id, str(e.payload)[:120]) for e in after.events][-25:]
    raise AssertionError(json.dumps(out, default=str, indent=1))
