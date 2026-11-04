"""C4 review: real table choices, damage delivery, AI turns and persisted Aegises."""
import json
import pytest

from combat.canonical import canonical_sha256
from combat import typed_reactions
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE
from tests.test_r1i_round3 import resolve, reload

PR = "tianxia.talent.protection."
BASE = ["PROTECTION_BASE_AEGIS", "PROTECTION_BASE_ARMORED_AEGIS"]


@pytest.fixture(autouse=True)
def inherited_prompt_loader():
    """Keep the imported fixture contract while exercising round20's real loader."""
    from combat import tabletop_service
    from tests.h1_support import ROOT
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    assert tabletop_service._rules_texts() == rules


def packets(amount, kind, defense, *, attack=False):
    """Bounded test packets in compiled actions; no engine patching or live data."""
    def prepare(bundles):
        owner, foe = bundles[:2]
        for action in owner["action_catalog"]:
            if action["display_name"].startswith("Aegis:") and defense == "existing":
                action["parameters"]["typed"]["effects"].append({
                    "type": "resistance", "applies_to": "self", "damage_types": [kind]})
        for action in foe["action_catalog"]:
            if action["display_name"].startswith("Scouring Hand"):
                damage = {"type": "damage", "applies_to": "target", "flat": amount,
                          "damage_types": [kind]}
                effects = [damage]
                if attack:
                    # Inspect the real attack's rolled packet, including a
                    # possible critical hit, rather than assuming a dice total.
                    damage.update(dice={"count": 1, "sides": 4}, flat=amount - 1)
                    effects = [{"type": "attack", "attack_kind": "cultivation", "on_hit": [damage]}]
                if defense == "suppressed":
                    effects.insert(0, {"type": "suppress_resistance", "applies_to": "target",
                                       "damage_types": [kind], "expires_on": "UNTIL_REMOVED"})
                if defense == "effect_ignores":
                    effects.insert(0, {"type": "ignore_resistance", "damage_types": [kind]})
                action["parameters"]["typed"]["effects"] = effects
                action["parameters"]["typed"]["riders"] = []
        if defense == "attacker_ignores":
            foe["typed_passives"].append({"feature_id": "test:penetration", "block": "defense",
                "kind": "ignore_resistance", "damage_types": [kind], "attack_kinds": ["cultivation"]})
        for bundle in bundles:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    return prepare


@pytest.mark.parametrize("talent,kind", [("energy_resistance", "FIRE"), ("protected_health", "POISON")])
@pytest.mark.parametrize("amount", [1, 2, 3])
@pytest.mark.parametrize("defense", ["normal", "existing", "suppressed"])
@pytest.mark.parametrize("ai_turn", [False, True])
def test_aegis_delivered_packet_rounding_suppression_and_nonstacking_table(tmp_path, talent, kind, amount, defense, ai_turn):
    check_delivery(tmp_path, talent, kind, amount, defense, ai_turn)


@pytest.mark.parametrize("talent,kind", [("energy_resistance", "FIRE"), ("protected_health", "POISON")])
@pytest.mark.parametrize("defense", ["effect_ignores", "attacker_ignores"])
@pytest.mark.parametrize("ai_turn", [False, True])
def test_aegis_penetrating_attack_table(tmp_path, talent, kind, defense, ai_turn):
    check_delivery(tmp_path, talent, kind, 3, defense, ai_turn, attack=True)


def check_delivery(tmp_path, talent, kind, amount, defense, ai_turn, *, attack=False):
    label = "Aegis: " + {"energy_resistance": "Energy Resistance", "protected_health": "Protected Health"}[talent]
    combat, table, mid, send, commit = fixture(tmp_path, [*BASE, PR + talent],
        foe_talents=["SAND_BASE_SCOURING_HAND"], seed="C4-REVIEW-RESISTANCE",
        bundle_transform=packets(amount, kind, defense, attack=attack))
    cid = candidate(table, mid, label + " (Persistent)", OWNER)
    before, prompts = resolve(combat, mid, send, cid, {"choice:needle.protection_energy": "fire"})
    if talent == "energy_resistance":
        assert len(prompts) == 1
        assert prompts[0]["context"]["reaction_source_id"] == "choice:needle.protection_energy"
        assert "Energy Resistance" in str(prompts[0])
    else:
        assert not prompts
    bearer = reload(tmp_path, mid).state.actors[OWNER]
    assert bearer.current_hp == before["actors"][OWNER]["current_hp"]
    # Reload before the opposing turn, then deliver through a table transaction.
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Scouring Hand", OWNER)
    if ai_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    before, _ = resolve(combat, mid, send, cid, {}, auto=ai_turn)
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == FOE
              and OWNER in e.target_ids and e.payload["damage_type"].upper() == kind]
    assert len(events) == 1
    packet = events[0].payload
    raw = packet["rolled_or_pending_damage"]
    if not attack:
        assert raw == amount
    expected = raw if defense in ("suppressed", "effect_ignores", "attacker_ignores") else raw // 2
    assert packet["reduced_to"] == expected
    assert before["actors"][OWNER]["current_hp"] - engine.state.actors[OWNER].current_hp == expected
    assert typed_reactions.damage_factor(engine, engine.state.actors[OWNER], kind,
        events[0].source_definition_id, FOE) == (1 if expected == raw else 0.5)


def test_concentration_aegis_defense_ends_with_its_mark():
    from tests.test_riders_c4 import protect, use, ME, ALLY
    engine = protect("energy_resistance")
    bearer = engine.state.actors[ALLY]
    use(engine, "Aegis: Energy Resistance", target=ALLY)
    assert typed_reactions.damage_factor(engine, bearer, "FIRE", "test:hit", None) == 0.5
    engine._end_concentration(engine.state.actors[ME], "TEST")
    assert typed_reactions.damage_factor(engine, bearer, "FIRE", "test:hit", None) == 1
