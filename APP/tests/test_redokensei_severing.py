"""Printed Kensei rules at the table, with cold mechanical replay.

Only the small trigger action is synthetic; ownership, prompts, payment,
Concentration and unstable-array maintenance use shipped combat code.
"""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import formations
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_body_subpaths_3 import seal
from tests.hunt12_support import hit_dice

KENSEI = "tianxia.subpath.body.kensei.feature."
PALM = KENSEI + "severing_palm"
SAINT = KENSEI + "sword_saint_incarnation"
IRON = "tianxia.path.body_refining.feature.iron_fist"
STAMINA = "resource:core.stamina"
CHOICE = "choice:needle.severing_palm"


def test_sword_saint_is_offered_at_match_start_and_after_cold_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_features=[SAINT],
        owner_path="Body Refining", primary="Stamina", cl=18)
    first = candidate(combat, mid, "Sword Saint Incarnation")
    reload(tmp_path, mid)
    cold = CombatService(ROOT, tmp_path)
    cold_table = TabletopService(cold, tmp_path)
    again = candidate(cold, mid, "Sword Saint Incarnation")
    assert again.source_definition_id == first.source_definition_id
    before = cold._load_session(mid).engine.state.actors[OWNER].resources[STAMINA]
    settle(cold_table, mid, again.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[STAMINA] == before - 7
    assert any(c.condition_id == "condition:typed.state.sword_saint_incarnation"
               for c in engine.state.actors[OWNER].conditions.values())


def delivery(bundles):
    seal(bundles[0], "Measured hit", [
        {"type": "attack", "attack_kind": "unarmed",
         "on_hit": [{"type": "damage", "flat": 1, "damage_types": ["bludgeoning"],
                     "applies_to": "target"}]}],
         target="HOSTILE_ENTITY", numbers={"cl": 18, "pb": 6,
         "save_dc": 50, "attack_bonus": 100, "key_mod": 4})
    bundles[0]["action_catalog"][-1]["parameters"]["free_primary"] = True
    seal(bundles[2], "Maintained technique", [], economy="NONE")
    bundles[2]["action_catalog"][-1]["parameters"]["free_primary"] = True
    bundles[2]["action_catalog"][-1]["parameters"]["typed"]["duration"] = {
        "kind": "minutes", "amount": 1, "concentration": True}
    from combat.canonical import canonical_sha256
    for bundle in (bundles[0], bundles[2]):
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def start(tmp_path, talents=(), foe_talents=(), features=(PALM,)):
    return fixture(tmp_path, list(talents), owner_features=[IRON, *features], cl=18,
        primary="Stamina", owner_path="Body Refining", bundle_transform=delivery,
        foe_sheet=sheet(list(foe_talents), cl=18, primary="Stamina"),
        positions={OWNER: {"x": 3, "y": 6},
                   "actor:factory.worker2-ally": {"x": 3, "y": 7},
                   FOE: {"x": 4, "y": 6}}, seed="GUARD-PARENT")


def palm(combat, table, mid, choice="flow"):
    return settle(table, mid, candidate(combat, mid, "Measured hit", target=FOE).candidate_id,
                  choices={CHOICE: choice})


def test_flow_affects_real_maintained_array_check_after_reload(tmp_path, monkeypatch):
    hit_dice(monkeypatch)
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20

    def saves(self, **kw):
        reason = str(kw.get("reason", ""))
        # Keep the actual maintained array through the triggering hit. Only
        # Severing Palm fails; the independent Concentration save succeeds.
        desired = (20 if reason.startswith("SAVE:system:combat.concentration")
                   else 1 if reason.startswith("SAVE:") else None)
        while True:
            roll = original(self, **kw)
            if desired is None or roll.natural_result == desired:
                return roll
    monkeypatch.setattr(DeterministicRollAuthority, "d20", saves)
    combat, table, mid = start(tmp_path,
        talents=["tianxia.talent.formations.disrupt_node"],
        foe_talents=["FORMATIONS_BASE_SET_ARRAY", "FORMATIONS_BASE_FORMATION_TRAINING"])
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Combat Array: Nourishing Cycle", at=(5, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    zone = formations.arrays(engine, FOE)[0]
    eye = formations.record(zone)["eye"]
    turn(table, mid, OWNER)
    palm(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert any(c.source_definition_id == PALM + "#flow"
               for c in engine.state.actors[FOE].conditions.values())
    settle(table, mid, candidate(combat, mid, "Disrupt Node", target=eye).candidate_id)
    engine = reload(tmp_path, mid)
    assert formations.record(engine.state.zones[zone.zone_id])["unstable"]
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    check = next(e for e in reversed(engine.events) if e.event_type == "CHECK_ROLLED"
                 and e.source_definition_id == "formation:disrupt_node")
    assert check.payload["actor"]["mode"] == "DISADVANTAGE"


def test_severing_can_be_used_again_on_another_creatures_turn(tmp_path, monkeypatch):
    hit_dice(monkeypatch, save_roll=1)
    combat, table, mid = start(tmp_path, features=(PALM, KENSEI + "flowing_blade_stance"))
    settle(table, mid, candidate(combat, mid, "Flowing Blade Stance").candidate_id)
    palm(combat, table, mid, "leg")
    before = reload(tmp_path, mid).state.actors[OWNER].resources[STAMINA]
    # A real missed melee attack triggers Flowing Blade's granted reaction.
    # The foe's low attack bonus guarantees the miss (except a natural 20).
    turn(table, mid, FOE)
    c = candidate(combat, mid, "Unarmed Strike", target=OWNER)
    # Script a natural 1 for the incoming attack, then a hit for the response.
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20

    def rolls(self, **kw):
        desired = 1 if kw.get("actor_id") == FOE and str(kw.get("reason", "")).startswith("ATTACK") else None
        while True:
            roll = original(self, **kw)
            if desired is None or roll.natural_result == desired:
                return roll
    monkeypatch.setattr(DeterministicRollAuthority, "d20", rolls)
    prompts = settle(table, mid, c.candidate_id, choices={CHOICE: "breath",
        "choice:needle.flowing_blade_answer": "first",
        "choice:needle.flowing_blade_step": None})
    engine = reload(tmp_path, mid)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert engine.state.actors[OWNER].resources[STAMINA] == before - 4
