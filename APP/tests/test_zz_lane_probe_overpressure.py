"""Lane-local probe (not committed): dumps the prompts and candidates a Radiant Overpressure fight raises."""
import json
from combat.typed_executor import bears_mark
from tests.test_carry import KIT
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn, act


def test_probe(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_FURNACE_BACKLASH", "TAL_YANG_RADIANT_OVERPRESSURE"],
                                 seed="LIGHT-S3-OVERPRESSURE", owner_dc=100, owner_ac=1,
                                 foe_kit={"starting_kit": {"items": [KIT["items"][-1]]}}, foe_position={"x": 3, "y": 5})
    settle(table, mid, candidate(combat, mid, "Rising Thread", target=FOE).candidate_id)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    names = sorted({(engine.action_catalog.get(c.source_definition_id).display_name if engine.action_catalog.get(c.source_definition_id) else "?") for c in engine.legal_candidates() if c.actor_id == FOE})
    out = {"foe_candidates": names}
    cand = [c for c in engine.legal_candidates() if c.actor_id == FOE and "Bi Shou" in str(engine.action_catalog.get(c.source_definition_id).display_name)]
    out["bi_shou_count"] = len(cand)
    prompts = []
    for step in range(6):
        cid = cand[0].candidate_id
        res = act(table, mid, cid, [])
        out.setdefault("steps", []).append({"status": res["status"], "reaction": (res.get("context") or {}).get("reaction_source_id")})
        break
    with open("/var/tmp/lane/LIGHTS3F19/probe.json", "w") as fh:
        json.dump(out, fh, indent=1, default=str)
