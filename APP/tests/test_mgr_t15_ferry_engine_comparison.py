"""Public, real-table replacements for the four broken review behaviour probes.

These scenarios run unchanged on main and the Ferry branch. Ownership, Qi and
weapons come from compiled synthetic sheets, not nonexistent "Attack" actions or
resources inserted into live actors. Every observation follows a commit/reload.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import (
    ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn,
)

RIVER = "tianxia.subpath.qi.riverway_cultivator.feature."
FERRY = RIVER + "ferry_the_wounded"
PASSAGE = RIVER + "flowing_passage"
REFLECTION = "tianxia.talent.talismans.talisman_reflection"
SWEEP = "tianxia.subpath.body.bojutsu.feature.sweeping_strike"
QI = "resource:core.qi"
AXE = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu"}]}}
STAFF = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gun"}]}}


def seal(bundle):
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def reliable_weapons(bundles):
    """Keep the setup deterministic without replacing combat resolution."""
    for bundle in bundles:
        for action in bundle["action_catalog"]:
            if action["source_definition_id"].endswith((".weapon.fu", ".weapon.gun")):
                action["attack_bonus"] = 100
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        seal(bundle)


def damage(combat, table, mid, tmp_path, *, target=ALLY, name="Fu (Short Axe) attack",
           choices=None):
    start = len(reload(tmp_path, mid).events)
    prompts = settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
                     choices=choices or {})
    engine = reload(tmp_path, mid)
    events = engine.events[start:]
    assert any(e.event_type == "DAMAGE_COMMITTED" and target in e.target_ids
               and int(e.payload.get("hp_damage") or 0)
               + int(e.payload.get("temporary_hp_absorbed") or 0) > 0 for e in events)
    return engine, events, prompts


@pytest.mark.parametrize("owned,qi,passage", [
    (True, 10, False), (True, 0, False), (False, 10, False), (True, 10, True),
], ids=["ferry-accept", "ferry-no-qi", "ferry-nonowner", "flowing-passage-arrival"])
def test_ferry_after_real_weapon_damage(tmp_path, owned, qi, passage):
    doc = sheet(([FERRY] if owned else []) + ([PASSAGE] if passage else []),
                cl=6, primary="Qi", name="Wren")
    doc["identity"]["proficiency_bonus"] = 3
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    # Qi exists because the sheet owns a Qi pool, even when its balance is zero.
    pool = next(r for r in bundle["actor_template"]["resources"] if r["resource_id"] == QI)
    pool["initial"] = qi
    seal(bundle)
    combat, table, mid = fixture(
        tmp_path, [], cl=6, named=True, owner_bundle=bundle, foe_kit=AXE,
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6},
                   FOE: {"x": 5, "y": 6}},
        bundle_transform=reliable_weapons, seed="MGR-T14-FERRY-SETTLEMENT")
    if passage:
        settle(table, mid, candidate(combat, mid, "Flowing Passage", at=(4, 7)).candidate_id,
               choices={"choice:needle.flowing_passage_cell.1": ["end"],
                        "choice:needle.flowing_passage_allies": [OWNER, ALLY]})
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources[QI] == qi - int(passage)
    engine, events, prompts = damage(
        combat, table, mid, tmp_path, choices={"reaction:typed." + FERRY: ["cell:4,7"]})
    accepted = owned and qi >= 2
    assert any(p["context"]["reaction_source_id"] == "reaction:typed." + FERRY
               for p in prompts) == accepted
    assert engine.state.actors[OWNER].reaction_available is not accepted
    ally = engine.state.actors[ALLY]
    assert (ally.position.x, ally.position.y) == ((4, 7) if accepted else (4, 6))
    assert ally.temporary_hp == (3 if passage else 0)
    assert engine.state.actors[OWNER].resources[QI] == qi - int(passage) - 2 * accepted
    spent = [e for e in events if e.source_definition_id == FERRY
             and e.event_type == "RESOURCE_SPENT"]
    assert len(spent) == int(accepted)
    if accepted:
        damage_index = next(i for i, e in enumerate(events) if e.event_type == "DAMAGE_COMMITTED")
        move_index = next(i for i, e in enumerate(events)
                          if e.source_definition_id == FERRY and e.event_type == "MOVEMENT_COMMITTED")
        assert damage_index < move_index
        if passage:
            assert move_index < next(i for i, e in enumerate(events)
                                     if e.source_definition_id == FERRY and e.event_type == "TEMP_HP_GRANTED")


def test_sweeping_strike_real_staff_hit_has_one_paid_provider(tmp_path):
    bundle = compile_character(sheet([SWEEP], cl=15, dc=50, primary="Stamina", kit=STAFF),
                               actor_id=OWNER, reaction_plan={"ask": True})
    assert not any(r["feature_id"] == SWEEP and r["block"] == "generic"
                   for r in bundle["typed_reactions"])
    combat, table, mid = fixture(
        tmp_path, [], cl=15, owner_bundle=bundle, bundle_transform=reliable_weapons,
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7},
                   FOE: {"x": 4, "y": 6}}, seed="R13")
    before = reload(tmp_path, mid).state.actors[OWNER].resources["resource:core.stamina"]
    engine = combat._load_session(mid).engine
    staff = next(a.display_name for a in engine.action_catalog.values()
                 if a.owner_id == OWNER and a.source_definition_id.endswith(".weapon.gun"))
    engine, events, prompts = damage(
        combat, table, mid, tmp_path, target=FOE, name=staff,
        choices={"choice:needle.bojutsu_sweep": ["Use Sweeping Strike"],
                 "choice:needle.bojutsu_result": ["Prone"]})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.bojutsu_sweep"
               for p in prompts)
    assert engine.state.actors[OWNER].resources["resource:core.stamina"] == before - 1
    assert any(c.condition_id == "condition:typed.prone"
               for c in engine.state.actors[FOE].conditions.values())
    assert len([e for e in events if e.event_type == "RESOURCE_SPENT"
                and e.source_definition_id == SWEEP]) == 1


def test_talisman_reflection_real_hostile_technique_keeps_generic_provider(tmp_path):
    # A hostile technique with a plain "one creature" target. Lightning Prison
    # Bars only targets a Charged creature or one standing in a Conductive
    # Field, so against an ordinary creature it is never a legal option and
    # opens no reaction window at all.
    nail = "TAL_METAL_MERIDIAN_NAIL"
    combat, table, mid = fixture(
        tmp_path, [REFLECTION], cl=15, ask=False,
        foe_sheet=sheet([nail], cl=15, name="Mara"),
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7},
                   FOE: {"x": 4, "y": 6}}, seed="H74-HOSTILE")
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    owner = before.state.actors[OWNER]
    assert owner.resources[QI] >= 5
    assert owner.resources["resource:named.prepared_talismans"] >= 1
    start = len(before.events)
    settle(table, mid, candidate(combat, mid, "Meridian Nail", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    owner_after = engine.state.actors[OWNER]
    assert not owner_after.reaction_available
    assert owner_after.resources[QI] == owner.resources[QI] - 5
    assert owner_after.resources["resource:named.prepared_talismans"] == (
        owner.resources["resource:named.prepared_talismans"] - 1)
    assert len([e for e in engine.events[start:] if e.source_definition_id == REFLECTION
                and e.event_type == "REACTION_WINDOW_OPENED"]) == 1
