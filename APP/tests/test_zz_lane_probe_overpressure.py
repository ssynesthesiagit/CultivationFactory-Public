"""Lane-local probe (not committed): dumps the prompts and candidates a Radiant Overpressure fight raises."""
import json
from tests.test_carry import KIT
from tests.worker2_support import FOE, OWNER, candidate, fixture, settle, turn, act


def _name(engine, c):
    row = engine.action_catalog.get(c.source_definition_id)
    return getattr(row, "display_name", None) or c.source_definition_id


def test_probe(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_FURNACE_BACKLASH", "TAL_YANG_RADIANT_OVERPRESSURE"],
                                 seed="LIGHT-S3-OVERPRESSURE", owner_dc=100, owner_ac=1,
                                 foe_kit={"starting_kit": {"items": [KIT["items"][-1]]}}, foe_position={"x": 3, "y": 5})
    settle(table, mid, candidate(combat, mid, "Rising Thread", target=FOE).candidate_id)
    turn(table, mid, FOE)
    engine = combat._load_session(mid).engine
    out = {"foe_candidates": sorted({_name(engine, c) for c in engine.legal_candidates() if c.actor_id == FOE})}
    bi = [c for c in engine.legal_candidates() if c.actor_id == FOE and "Bi Shou" in _name(engine, c)]
    out["bi_shou"] = len(bi)
    if bi:
        res = act(table, mid, bi[0].candidate_id, [])
        out["first_act"] = json.loads(json.dumps(res, default=str))
    with open("/var/tmp/lane/LIGHTS3F19/probe.json", "w") as fh:
        json.dump(out, fh, indent=1, default=str)
