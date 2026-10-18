"""Overlapping compiled Lightning Chains survive table reload and snap separately.

riders/c13 (14cd285f, approved C13r3.review.md) requires a real hostile
Charge hit instead of Gather Charge. Its extra roll changes this fixture seed;
the two independent links and both reciprocal snap assertions stay intact.
"""
import pytest

from combat.gate5_service import CombatService
from combat.canonical import canonical_sha256
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, charge_setup, commit_charge, OWNER, FOE, SECOND, THIRD

LINK = "condition:typed.link.lightning"


def links(engine, actor):
    return [c for c in engine.state.actors[actor].conditions.values() if c.condition_id == LINK]


@pytest.mark.parametrize("first", [SECOND, FOE])
@pytest.mark.parametrize("same_source", [False, True])
def test_overlapping_chains_commit_reload_and_independent_snap(tmp_path, first, same_source):
    def repeatable(bundles):
        charge_setup(bundles)
        # Exercise repeated delivery of the exact same compiled source through
        # the service, without mutating runtime state or a locked dispatcher.
        # The fixture changes only its action economy; all effects stay compiled.
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        for action in owner["action_catalog"]:
            if same_source and action["display_name"] == "Lightning Lash: Charge + Lightning Chains":
                action["economy"] = "NONE"
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_LIGHTNING_LIGHTNING_CHAINS",
        "TAL_LIGHTNING_LIGHTNING_SOVEREIGN_INCARNATION"], foe_ac=0, extra_foe=True, bundle_transform=repeatable, seed="R23-CHAINS-HITS",
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}, THIRD: {"x": 2, "y": 6}})
    # Printed eligibility: the victim must already be Charged before the Lash hits.
    # Establish it before Sovereign replaces Lash menu entries with range aliases.
    commit_charge(table, mid, send, FOE)
    commit(candidate(table, mid, "Lightning Sovereign Incarnation"))

    def lash(partner, free):
        menu = table.state(mid)["menu"]
        labels = [g["label"] for g in menu["actions"]]
        assert any("Lightning Chains" in label and ("(free)" in label) == free for label in labels), labels
        cid = next(o["candidate_id"] for g in menu["actions"]
                   if "Lightning Lash: Charge" in g["label"] and "Lightning Chains" in g["label"]
                   and ("(free)" in g["label"]) == free
                   for o in g["options"] if FOE in o.get("target_ids", []))
        answers = []
        for _ in range(16):
            result = send(cid, answers)
            if result["status"] == "COMMITTED":
                return
            assert result["status"] == "REACTION_REQUIRED", result
            p = result["reaction"]
            answer = {**p["context"], "selection": "USE"}
            if p.get("choice"):
                answer["option_ids"] = [partner] if p["context"]["reaction_source_id"].endswith("arc") else [p["choice"]["options"][0]["id"]]
            answers.append(answer)
        raise AssertionError("too many prompts")

    lash(SECOND, False)
    lash(THIRD, not same_source)

    def reload():
        return CombatService(ROOT, tmp_path)._load_session(mid)

    engine = reload().engine
    assert len(links(engine, FOE)) == 2
    pairs = {c.data["with"]: c.data["pair_id"] for c in links(engine, FOE)}
    assert pairs.keys() == {SECOND, THIRD} and len(set(pairs.values())) == 2
    for endpoint in (SECOND, THIRD):
        link, = links(engine, endpoint)
        assert link.data["with"] == FOE and link.data["pair_id"] == pairs[endpoint]

    def move(who):
        while table.state(mid)["menu"]["actor_id"] != who:
            commit(table.state(mid)["menu"]["end_turn"])
        destination = {"x": 8, "y": 6} if who == SECOND else {"x": 1, "y": 6} if who == FOE else {"x": 4 if first == FOE else 1, "y": 6}
        cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"] if o["destination"] == destination)
        # Decline unrelated opportunity attacks; movement still commits.
        answers = []
        for _ in range(16):
            result = send(cid, answers)
            if result["status"] == "COMMITTED":
                return
            assert result["status"] == "REACTION_REQUIRED", result
            answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
        raise AssertionError("too many prompts")

    damage_start = engine.state.event_sequence
    snap_sources = {c.source_definition_id for c in links(engine, FOE)}
    expected_damage = [(first, links(engine, first)[0].data["damage"]),
                       (THIRD, links(engine, THIRD)[0].data["damage"])]
    assert all(amount > 0 for _, amount in expected_damage)
    move(first)
    engine = reload().engine
    other = THIRD
    assert not links(engine, SECOND)
    remaining, = links(engine, FOE)
    assert remaining.data["with"] == other and remaining.data["pair_id"] == pairs[other]
    reciprocal, = links(engine, other)
    assert reciprocal.data["pair_id"] == pairs[other]
    move(other)
    loaded = reload()
    assert all(not links(loaded.engine, who) for who in (SECOND, FOE, THIRD))
    damage = [e for e in loaded.engine.events if e.sequence > damage_start
              and e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id in snap_sources]
    assert [(e.target_ids[0], e.payload["reduced_to"]) for e in damage] == expected_damage
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_legacy_links_without_pair_ids_snap_only_reciprocal_endpoints():
    from tests.test_riders_lane1 import _engine, _bundle, _move, ME, AN, F1, F2

    engine = _engine(_bundle("TAL_LIGHTNING_LIGHTNING_CHAINS", cl=10, dc=50),
                     {F1: (5, 6), F2: (5, 7)})
    source = "test:legacy_chains"
    for left, right in ((AN, F1), (AN, F2)):
        for holder, partner in ((left, right), (right, left)):
            engine._apply_condition(engine.state.actors[holder], LINK, source, ME,
                expires_on="START_OF_SOURCE_NEXT_TURN", data={"with": partner, "damage": 4})
    _move(engine, F1, (8, 6))
    assert not links(engine, F1)
    remaining, = links(engine, AN)
    assert remaining.data["with"] == F2
    reciprocal, = links(engine, F2)
    assert reciprocal.data["with"] == AN
