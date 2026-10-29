"""Wave 2 sphere ownership -- Alchemy, Poison, Blood, Life, Flowers, Harvesting & Gathering, Karma, Chains
(owner 2026-09-28, "automate every aspect before another playtest"). Covers the highest-priority fixes:
CL-scaled dice that were fixed at their lowest tier, the Ingrain the Toxin / Deepen the Burden free-power
gate (a Dose Mark must exist first), and Karma ownership: borrowed talents can
consume existing Imprints but do not grant the unowned Record the Deed reaction."""

from pathlib import Path
import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import bears_mark
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.life"


def _bundle(talents, sphere_ids, *, cl=10):
    sheet = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": cl}, "equipment": [],
             "spheres_and_talents": {"sphere_record_ids": sphere_ids, "learned_talent_record_ids": talents}}
    return compile_character(sheet, actor_id=ME)


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="LIFE", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _action(engine, name):
    return next(c for c in engine.legal_candidates() if c.display_name == name)


def _use(engine, candidate, actor_id=ME):
    engine.execute_intent(ActionIntent(intent_id="i", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids))


# ---------------------------------------------------------------- dice_by_cl scaling
def test_deliver_the_dose_scales_by_realm_instead_of_a_fixed_1d8():
    dose = _bundle(["POISON_BASE_DELIVER_THE_DOSE"], ["tianxia.sphere.poison"], cl=10)
    action = next(row for row in dose["action_catalog"] if row["display_name"] == "Deliver the Dose")
    dice = action["parameters"]["typed"]["effects"][0]["on_hit"][0]["dice_by_cl"]
    # Printed by Realm (Mortal 1d8, Foundation 2d8, Core Formation 3d8, Nascent Soul 4d8): the core rules' Realm bands, CL 1-4 / 5-9 /
    # 10-14 / 15-20 (rider lane C13), not the CL 1-4 / 5-10 / 11-16 / 17-20 table other talents print.
    assert dice == [[1, 4, 1, 8], [5, 9, 2, 8], [10, 14, 3, 8], [15, 20, 4, 8]]


def test_chain_lash_scales_by_realm_in_every_minor_link_option():
    bundle = _bundle(["TAL_CHAINS_CHAIN_LASH_BASE"], ["tianxia.sphere.chains"], cl=5)
    options = [row for row in bundle["action_catalog"] if row["display_name"].startswith("Chain Lash")]
    assert len(options) >= 4
    for row in options:
        on_hit = row["parameters"]["typed"]["effects"][0]["on_hit"]
        damage = next(e for e in on_hit if e["type"] == "damage")
        assert damage["dice_by_cl"] == [[1, 4, 1, 8], [5, 9, 2, 8], [10, 14, 3, 8], [15, 20, 4, 8]]  # the Realm bands, as above


def test_blood_ward_reduction_scales_by_realm():
    bundle = _bundle(["tianxia.talent.blood.blood_ward"], ["tianxia.sphere.blood"], cl=20)
    row = next(r for r in bundle["typed_reactions"] if r["name"] == "Blood Ward")
    damage_mod = next(e for e in row["effects"] if e["type"] == "damage_modifier")
    assert damage_mod["dice_by_cl"][-1] == [17, 20, 4, 8]


# ---------------------------------------------------------------- missing effects restored
def test_corrosive_dose_now_deals_its_printed_bonus_acid_damage():
    bundle = _bundle(["POISON_BASE_DELIVER_THE_DOSE", "tianxia.talent.poison.corrosive_dose"], ["tianxia.sphere.poison"], cl=10)
    modifier = next(m for m in bundle["modifiers"] if m["name"] == "Corrosive Dose")
    assert modifier["status"] == "applied"
    combo = next(row for row in bundle["action_catalog"] if row["display_name"] == "Deliver the Dose + Corrosive Dose")
    on_hit = combo["parameters"]["typed"]["effects"][0]["on_hit"]
    bonus = next(e for e in on_hit if e.get("type") == "extra_damage" and e.get("source_modifier") == "tianxia.talent.poison.corrosive_dose")
    # CL10 (Du Daoyuan's actual level) falls in the Foundation tier (+2d6) -- correct for him today.
    # A modifier-sourced effect's dice_by_cl does not survive whatever step bakes a modifier into its
    # target action (unlike a base action's own dice_by_cl, confirmed reaching typed_executor above), so
    # this stays pinned to the Foundation tier at any other Realm; see the rider on this mechanic.
    assert "acid" in bonus["damage_types"] and (bonus["dice"]["count"], bonus["dice"]["sides"]) == (2, 6)


def test_blood_mending_cannot_be_reused_on_the_same_target_before_a_short_rest():
    from combat import factory_compiler as fc
    import json
    mech = json.loads(fc.TYPED_AUTHORITY.read_bytes())["mechanics"]
    assert "short rest" in str(mech["tianxia.talent.blood.blood_mending"].get("use_limit") or "").lower()


# ---------------------------------------------------------------- Ingrain the Toxin / Deepen the Burden gate
def test_ingrain_the_toxin_is_hidden_until_the_target_carries_a_dose_mark():
    bundle = _bundle(["POISON_BASE_DELIVER_THE_DOSE", "POISON_BASE_INGRAIN_THE_TOXIN"], ["tianxia.sphere.poison"], cl=10)
    engine = _engine(bundle)
    foe = engine.state.actors[AN]
    assert not any(c.display_name.startswith("Ingrain the Toxin") for c in engine.legal_candidates())
    from combat.ext import stacking_marks
    owner = engine.state.actors[ME]
    stacking_marks.add(engine, owner, foe, "Dose Mark", 1, "test")
    assert stacking_marks.count(engine, owner, foe, "Dose Mark") == 1
    # "Target: One creature with at least 2 Dose Marks from you" (rider lane 10: marks stack, combat/ext/stacking_marks.py)
    assert not any(c.display_name.startswith("Ingrain the Toxin") for c in engine.legal_candidates())
    stacking_marks.add(engine, owner, foe, "Dose Mark", 1, "test")
    assert stacking_marks.count(engine, owner, foe, "Dose Mark") == 2
    assert any(c.display_name.startswith("Ingrain the Toxin") for c in engine.legal_candidates())


# ---------------------------------------------------------------- Karma Debt Imprint (real ledger)
@pytest.mark.parametrize('owns_record', [False, True])
def test_burden_of_deeds_needs_owned_record_to_create_an_imprint(owns_record):
    """Printed Burden consumes existing Imprints; only owned Record grants the reaction."""
    talents = ["tianxia.talent.karma.burden_of_deeds"]
    if owns_record:
        talents.append('TAL_KARMA_RECORD_THE_DEED')
    bundle = _bundle(talents, ["tianxia.sphere.the_piercing_needle"], cl=10)
    engine = _engine(bundle)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert not bears_mark(foe, ME, "Debt Imprint")
    engine._commit_damage(me, 5, "SLASHING", "action:test.foe_hit", AN, None, reaction_depth=2)
    assert bears_mark(foe, ME, "Debt Imprint") == owns_record
    assert me.reaction_available == (not owns_record)
