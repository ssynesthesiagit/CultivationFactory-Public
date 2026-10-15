"""Independent Chaos-Step counters, including old bundles and real table persistence.

The table fixture adds a test-only effect to exercise the public reaction spending
contract inside service transactions, independently of Swaying Guard's other riders.
No production ability behavior or engine methods are replaced.
"""
import copy

import pytest

from combat import ext, typed_reactions as reactions
from combat.canonical import canonical_sha256
from combat.ext import reaction_economy as economy
from tests import test_riders_c4 as C4
from tests.r1i_service_support import OWNER, FOE, candidate, fixture, force_ai_candidate
from tests.test_r1i_round3 import reload
from tests.test_riders_c15 import _commit_all

CHAOS = "TAL_DRUNKEN_STYLE_SOVEREIGN_CHAOS_STEP_INCARNATION"
SWAY = "TAL_DRUNKEN_STYLE_SWAYING_GUARD"
OTHER = "TAL_DRUNKEN_STYLE_LAUGHING_AT_CERTAIN_DEATH"


def reaction(kind):
    return {"feature_id": SWAY if kind == "free" else OTHER,
            "name": "Swaying Guard" if kind == "free" else "Laughing at Certain Death"}


def spend(engine, owner, kind):
    row = reaction(kind)
    assert reactions.reaction_waived(engine, owner, row)
    reactions._open(engine, row, owner, (), "TEST_GRANT")
    reactions.spend_reaction(engine, owner, row)


def unused(engine, owner, kind):
    grant = next(r for r in economy._rows(engine, owner) if r["grant"] == kind)
    return economy._unused(engine, owner, grant)


@pytest.mark.parametrize("first", ["free", "extra"])
@pytest.mark.parametrize("legacy_bundle", [False, True])
def test_independent_grants_both_orders_and_next_round(first, legacy_bundle):
    bundle = C4.bundle(CHAOS, cl=17)
    engine = C4.fight(bundle)
    owner = engine.state.actors[C4.ME]
    C4.use(engine, "Sovereign Chaos-Step Incarnation")
    rows = reactions._rows(engine, owner.entity_id, economy.BLOCK)
    if legacy_bundle:
        for row in rows:
            row.pop("reaction_grant_key", None)
    owner.reaction_available = False  # ordinary Reaction was already spent
    second = "extra" if first == "free" else "free"
    spend(engine, owner, first)
    assert not unused(engine, owner, first)
    spend(engine, owner, second)
    assert not reactions.reaction_waived(engine, owner, reaction(second))
    keys = [k for k in owner.turn_flags if k.startswith(economy.FLAG)]
    assert len(keys) == 2 and all(type(owner.turn_flags[k]) is int for k in keys)
    engine.state.round_number += 1
    assert reactions.reaction_waived(engine, owner, reaction("free"))
    assert reactions.reaction_waived(engine, owner, reaction("extra"))


def test_grant_keys_do_not_depend_on_data_order_and_single_grants_keep_their_key():
    spec = copy.deepcopy(reactions.rules()["features"][CHAOS])
    row = {"feature_id": CHAOS}
    original = economy._compile(economy.BLOCK, spec, row, {})
    spec["grants"].reverse()
    reversed_rows = economy._compile(economy.BLOCK, spec, row, {})
    assert {r["grant"]: r["reaction_grant_key"] for r in original} == {
        r["grant"]: r["reaction_grant_key"] for r in reversed_rows}
    (single,) = economy._compile(economy.BLOCK, {"grant": "free"}, row, {})
    assert "reaction_grant_key" not in single


def test_old_shared_usage_is_not_refunded_mid_round():
    engine = C4.fight(C4.bundle(CHAOS, cl=17))
    owner = engine.state.actors[C4.ME]
    C4.use(engine, "Sovereign Chaos-Step Incarnation")
    owner.reaction_available = False
    owner.turn_flags[economy.FLAG + CHAOS] = int(engine.state.round_number)
    assert not reactions.reaction_waived(engine, owner, reaction("free"))
    assert not reactions.reaction_waived(engine, owner, reaction("extra"))
    engine.state.round_number += 1
    assert reactions.reaction_waived(engine, owner, reaction("free"))
    assert reactions.reaction_waived(engine, owner, reaction("extra"))


@pytest.mark.parametrize("first", ["free", "extra"])
@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("legacy_bundle", [False, True])
def test_grants_survive_separate_table_commits_and_reload(tmp_path, monkeypatch, first, auto_turn, legacy_bundle):
    second = "extra" if first == "free" else "free"

    def exercise(ctx, effect):
        owner = ctx.actor
        if effect["first"]:
            # Isolate additional-Reaction availability after an ordinary spend.
            owner.reaction_available = False
        spend(ctx.engine, owner, effect["grant"])

    monkeypatch.setitem(ext._EFFECTS, "test_c15_grant", exercise)

    def prepare(bundles):
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        if legacy_bundle:
            def remove_keys(value):
                if isinstance(value, dict):
                    value.pop("reaction_grant_key", None)
                    for child in value.values():
                        remove_keys(child)
                elif isinstance(value, list):
                    for child in value:
                        remove_keys(child)
            remove_keys(owner)
        for action in owner["action_catalog"]:
            name = action["display_name"]
            if name in ("Sovereign Chaos-Step Incarnation", "Iron Fist attack"):
                is_first = name == "Sovereign Chaos-Step Incarnation"
                action["parameters"]["typed"]["effects"].append({
                    "type": "test_c15_grant", "grant": first if is_first else second, "first": is_first})
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = fixture(tmp_path, [CHAOS, "tianxia.path.body_refining.feature.iron_fist"],
                                             bundle_transform=prepare, foe_ac=1)
    for label in ("Sovereign Chaos-Step Incarnation", "Iron Fist attack"):
        if auto_turn:
            combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
        cid = candidate(table, mid, label, FOE if label == "Iron Fist attack" else None)
        if auto_turn:
            force_ai_candidate(combat, mid, OWNER, cid)
        _commit_all(send, cid, auto_turn)
        engine = reload(tmp_path, mid)  # includes mechanical replay PASS
        owner = engine.state.actors[OWNER]
        keys = [k for k in owner.turn_flags if k.startswith(economy.FLAG)]
        assert len(keys) == (1 if label == "Sovereign Chaos-Step Incarnation" else 2)
        assert all(type(owner.turn_flags[k]) is int for k in keys)
        assert not unused(engine, owner, first)
        assert reactions.reaction_waived(engine, owner, reaction(second)) == (len(keys) == 1)
    original_round = engine.state.round_number
    # Advance through ordinary service commits: the persisted counters reset by round.
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
    while table.state(mid)["menu"]["actor_id"] == OWNER or reload(tmp_path, mid).state.round_number == original_round:
        commit(table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    owner.reaction_available = False  # query both grants, independent of the ordinary Reaction
    assert reactions.reaction_waived(engine, owner, reaction("free"))
    assert reactions.reaction_waived(engine, owner, reaction("extra"))
