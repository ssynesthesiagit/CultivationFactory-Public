"""C16 audit 9: settled melee delivery and Bark-Back's own Temporary HP at a table."""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from tests.r1i_service_support import FOE, OWNER, candidate, fixture, force_ai_candidate
from tests.test_r1i_round3 import reload
from tests.test_riders_c16 import SEED, SOWN, VG, growth

INCARNATION = "tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree"
BARK = VG + "BARK_BACK_GUARD"


@pytest.mark.parametrize("auto_attacker", [False, True])
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("case", ["melee", "ranged", "reach", "replacement", "prior_grant", "rejected", "depleted", "consumed", "miss", "forced_miss", "no_owner"])
def test_verdant_confirmed_melee_guards_at_table(tmp_path, monkeypatch, auto_attacker, native, case):
    """Real actions persist grants/state, then commit/reload verifies exact damage and marks."""
    from tests.test_lock_choices import install

    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:c16.fixed_attack", "operation": "replace", "natural_result": 10})
    def prepare(bundles):
        foe = next(b for b in bundles if b["actor_id"] == FOE)
        strike = next(a for a in foe["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        # These isolated test attacks remove Seed-Thorn's own mark/damage riders.
        strike.update(display_name="Guard probe", attack_bonus=100,
                      range_ft=30 if case == "ranged" else None, reach_ft=None if case == "ranged" else 10)
        typed = strike["parameters"]["typed"]
        typed["range_ft"] = 30 if case == "ranged" else None
        typed["numbers"]["attack_bonus"] = 100
        typed["weapon"] = {"damage": {"count": 1, "sides": 2, "modifier": 7}, "damage_type": "PIERCING", "fixed_damage": 9}
        typed["effects"] = [{"type": "attack", "applies_to": "target", "attack_kind": "ranged" if case == "ranged" else "melee",
                             "no_damage": case != "consumed", "on_hit": []}]
        if native:
            strike.update(resolution_kind="ATTACK", damage_type="PIERCING",
                          damage={"count": 1, "sides": 2, "modifier": 8} if case == "consumed" else None)
        for label, effects, target_kind in (
            ("Replace guard HP", [{"type": "temp_hp", "flat": 9 if case == "replacement" else 2, "applies_to": "target"}], "HOSTILE_ENTITY"),
            ("Deplete guard HP", [{"type": "damage", "flat": 4, "damage_types": ["PIERCING"], "applies_to": "target"}], "HOSTILE_ENTITY"),
        ):
            action = deepcopy(strike)
            action.update(source_definition_id="test:c16." + label.replace(" ", "_"), display_name=label,
                          resolution_kind="TYPED", target_kind=target_kind, economy="BONUS_ACTION", range_ft=60, reach_ft=None)
            action["parameters"]["typed"].update(range_ft=60, effects=effects)
            foe["action_catalog"].append(action)
            foe["actor_template"]["action_ids"].append(action["source_definition_id"])
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)
        if case == "prior_grant":
            owner = next(b for b in bundles if b["actor_id"] == OWNER)
            grant = deepcopy(next(a for a in owner["action_catalog"] if a["display_name"] == "Sow Living Claim"))
            grant.update(source_definition_id="test:c16.preexisting_hp", display_name="Preexisting HP probe",
                         target_kind="SELF", economy="ACTION")
            grant["parameters"]["typed"]["effects"] = [{"type": "temp_hp", "applies_to": "self", "flat": 9}]
            owner["action_catalog"].append(grant)
            owner["actor_template"]["action_ids"].append(grant["source_definition_id"])
            owner.pop("bundle_sha256", None)
            owner["bundle_sha256"] = canonical_sha256(owner)

    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN] + ([] if case == "no_owner" else [BARK, INCARNATION]), foe_talents=[SEED],
        owner_ac=1000 if case == "miss" else 0, seed="C16-HIT-GUARDS",
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 5 if case == "reach" else 4, "y": 6}},
        bundle_transform=prepare)
    if case != "no_owner":
        if case == "prior_grant":
            commit(candidate(table, mid, "Preexisting HP probe"))
        commit(candidate(table, mid, "Verdant Incarnation"))
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            commit(table.state(mid)["menu"]["end_turn"])
        # Incarnation's turn-start claim granted Bark-Back HP via a recorded event.
    else:
        commit(next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Sow Living Claim"
                    for o in g["options"] if o.get("destination") == {"x": 3, "y": 6}))
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == (0 if case == "no_owner" else 9 if case == "prior_grant" else 4)
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    if case in ("replacement", "rejected"):
        commit(candidate(table, mid, "Replace guard HP", OWNER))
    elif case == "depleted":
        commit(candidate(table, mid, "Deplete guard HP", OWNER))
    engine = reload(tmp_path, mid)
    before, foe_hp = len(engine.events), engine.state.actors[FOE].current_hp
    if case == "forced_miss":
        install(monkeypatch, "before_attack", lambda *args: {
            "force_miss": True, "source_id": "test:guard_miss", "label": "Guard test: attack misses"})
    cid = candidate(table, mid, "Guard probe", OWNER)
    if auto_attacker:
        force_ai_candidate(combat, mid, FOE, cid)
        assert send(cid, auto=True)["status"] == "COMMITTED"
    else:
        commit(cid)
    engine = reload(tmp_path, mid)  # asserts complete mechanical replay, not just selected events
    events = engine.events[before:]
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert len(rolls) == 1
    assert rolls[0].payload["provisional_hit"] == (case != "miss")
    landed = case not in ("miss", "forced_miss", "no_owner", "ranged")
    assert growth(engine, FOE, OWNER) == int(landed)
    bark = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == BARK]
    retaliates = landed and case not in ("replacement", "prior_grant", "depleted")
    assert len(bark) == int(retaliates)
    if bark:
        assert bark[0].target_ids == (FOE,) and bark[0].payload["hp_damage"] == 4
    assert foe_hp - engine.state.actors[FOE].current_hp == (4 if retaliates else 0)
    assert engine.state.actors[OWNER].temporary_hp == (
        9 if case in ("replacement", "prior_grant") else 0 if case in ("consumed", "depleted", "no_owner") else 4)
    if case == "melee":
        # The first hit used this grant. Incarnation's equal offer next turn
        # cannot renew it, and a new round cannot retaliate from it again.
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="MANUAL")
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != FOE:
            commit(table.state(mid)["menu"]["end_turn"])
        engine = reload(tmp_path, mid)
        before, hp = len(engine.events), engine.state.actors[FOE].current_hp
        assert growth(engine, FOE, OWNER) == 0  # previous mark expired at the owner's next turn end
        commit(candidate(table, mid, "Guard probe", OWNER))
        engine = reload(tmp_path, mid)
        assert growth(engine, FOE, OWNER) == 1
        assert engine.state.actors[FOE].current_hp == hp
        assert not any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == BARK for e in engine.events[before:])
