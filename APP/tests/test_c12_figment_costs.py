"""Combined figment payments through real table menus, commits and reloads."""
import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.ext import placed
from combat.ext.illusion_riders import SUBSTANTIAL
from tests.r1i_service_support import fixture, candidate, OWNER
from tests.test_r1i_round3 import resolve, reload

POOL = "resource:core.qi"


@pytest.mark.parametrize("hold,base_cost", [("grappled", 3), ("restrained", 5), (None, 0)])
@pytest.mark.parametrize("enough", [False, True])
@pytest.mark.parametrize("floor", [0, 2])
def test_combined_figment_affordability_table(tmp_path, monkeypatch, hold, base_cost, enough, floor):
    # A test-only cost provider exercises the public native-cost quote, without
    # changing production payment or patching an engine method.
    if floor:
        monkeypatch.setitem(ext._HOOKS, "technique_cost_floor", [
            *ext._HOOKS.get("technique_cost_floor", []),
            lambda engine, actor, source, listed, reduced:
                {POOL: base_cost + floor} if ".substantial." in source else None,
        ])
    upfront = base_cost + (floor if hold else 0)
    funds = upfront + int(enough)  # larger cube costs one additional CP

    def set_funds(bundles):
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        next(r for r in owner["actor_template"]["resources"] if r["resource_id"] == POOL)["initial"] = funds
        owner.pop("bundle_sha256")
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = fixture(tmp_path, [SUBSTANTIAL], bundle_transform=set_funds)
    commit(candidate(table, mid, "Figment: larger cube"))
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[POOL] == funds
    label = f"Create Figment + Substantial Phantasm ({base_cost} CP; {hold.title()})" if hold else "Create Figment"
    options = [o for g in table.state(mid)["menu"]["actions"] if g["label"] == label for o in g["options"]]
    assert bool(options) == enough
    assert any(g["label"] == "Create Figment" and g["options"] for g in table.state(mid)["menu"]["actions"]) == (funds >= 1)
    if not enough:
        assert reload(tmp_path, mid).state.model_dump(mode="json") == before.state.model_dump(mode="json")
        assert not placed.of(before, "figment")
        return
    cid = next(o["candidate_id"] for o in options if o.get("destination") == {"x": 4, "y": 6})
    resolve(combat, mid, send, cid, {})  # decline optional Phantasm recipients
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert not engine.state.actors[OWNER].action_available
    (zone,) = placed.of(engine, "figment")
    assert placed.data(zone)["size_ft"] == 50
    spent = [e.payload["amount"] for e in engine.events[len(before.events):]
             if e.event_type == "RESOURCE_SPENT" and e.actor_id == OWNER and e.payload["resource_id"] == POOL]
    assert sum(spent) == funds
