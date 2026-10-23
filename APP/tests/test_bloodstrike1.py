"""Bloodline Strike and Blood HP prices, using public synthetic table transactions."""
import json
import re

import pytest

from combat.ext import ancestral_bloodline as lineage
from combat.ext.blood_riders import effect_marker
from combat.factory_compiler import compile_character
from tests.cw2_service_support import add_action, seal
from tests.h1_support import ROOT, sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

FEATURE = lineage.BLOODLINE
CHOICE = lineage.STRIKE_CHOICE
POOL = lineage.RESONANCE
ARMAMENT = "tianxia.talent.blood.blood_armament"
ARMOR = "tianxia.talent.blood.blood_armor"
COURT = "tianxia.talent.blood.crimson_court"


def setup(tmp_path, talents=(), *, cl=3, resonance=3, owns=True, modes=None,
          affinity="Fire", insights=(), primary="Qi", bloodline_lineage="azure_dragon"):
    def prepare(bundles):
        bundle = bundles[0]
        add_action(bundle, "Lineage affinity damage", [
            {"type": "damage", "applies_to": "target", "flat": 1,
             "damage_types": [affinity.lower()]}], typed={"source": "synthetic.mundane"})
        for name, amount, source, extra in (
            ("Qi strike", 2, "tianxia.subpath.qi.synthetic.strike", {}),
            ("Qi volley", 2, "tianxia.subpath.qi.synthetic.volley", {}),
            ("Empty Qi", 0, "tianxia.subpath.qi.synthetic.empty", {}),
            ("Mundane strike", 2, "synthetic.mundane", {}),
            ("Weapon technique", 2, "tianxia.talent.sword.synthetic", {"delivered_by": "action:synthetic.weapon"}),
        ):
            effects = [{"type": "damage", "applies_to": "target", "flat": amount, "damage_types": ["force"]}]
            if name == "Qi volley":
                effects *= 2
            add_action(bundle, name, effects, typed={"source": source, **extra})
        add_action(bundle, "Qi crossfire", [
            {"type": "damage", "applies_to": "target", "flat": 2, "damage_types": ["force"]},
            {"type": "damage", "applies_to": "self", "flat": 2, "damage_types": ["force"]},
        ], typed={"qi_powered": True, "numbers": {"cl": cl, "key_mod": 8, "potency": 4}})
        add_action(bundle, "Wound creature", [{"type": "damage", "applies_to": "target", "flat": 35,
                                             "damage_types": ["force"]}])
        add_action(bundle, "Wound self", [{"type": "damage", "applies_to": "self", "flat": 59,
                                         "damage_types": ["force"]}], target="SELF")
        seal(bundle)
    document = sheet(list(talents), cl=cl, primary=primary, name="Wren")
    document["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
    document.setdefault("path_and_subpath", {}).update(
        path_feature_record_ids=[FEATURE] if owns else [],
        bloodline_lineage=bloodline_lineage)
    if insights:
        document.setdefault("spheres_and_talents", {})["cultivation_insight_record_ids"] = list(insights)
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={"ask": True})
    combat, table, mid = fixture(tmp_path, list(talents), cl=cl, named=True,
                                 owner_bundle=bundle,
                                 bundle_transform=prepare, modes=modes, primary=primary)
    if owns:
        settle(table, mid, candidate(combat, mid, f"Bloodline affinity: {affinity}").candidate_id)
        owner = reload(tmp_path, mid).state.actors[OWNER]
        assert owner.resources[POOL] == 0
        assert owner.resource_maximums[POOL] == owner.proficiency_bonus
        # Earn the test balance through the printed Azure Dragon trigger, never
        # by adding a resource or changing a compiled/runtime balance.
        for index in range(resonance):
            if index:
                turn(table, mid, ALLY)
                turn(table, mid, OWNER)
            use(combat, table, mid, "Lineage affinity damage", target=FOE)
        assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == resonance
    return combat, table, mid


def use(combat, table, mid, title, **kwargs):
    return settle(table, mid, candidate(combat, mid, title, target=kwargs.pop("target", None)).candidate_id, **kwargs)


def strike_rolls(engine):
    return [event for event in engine.events if event.event_type == "DAMAGE_ROLLED"
            and event.payload.get("damage_label") == "Bloodline Strike"]


@pytest.mark.parametrize("talent,title,hp", [(ARMAMENT, "Blood Armament", 1), (COURT, "Crimson Court", 0)])
def test_nondamaging_blood_activation_never_strikes(tmp_path, talent, title, hp):
    combat, table, mid = setup(tmp_path, [talent], cl=15)
    before_engine = reload(tmp_path, mid)
    before = before_engine.state.actors[OWNER]
    before_events = before_engine.events
    prompts = use(combat, table, mid, title)
    engine = reload(tmp_path, mid)
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert not strike_rolls(engine)
    # Also catch the old unconditional, differently labelled roll.
    assert not any(e.event_type == "DAMAGE_ROLLED" for e in engine.events[len(before_events):])
    assert engine.state.actors[OWNER].resources[POOL] == before.resources[POOL]
    assert engine.state.actors[OWNER].current_hp == before.current_hp - hp


@pytest.mark.parametrize("cl,count", [(3, 1), (11, 2), (17, 3)])
def test_damaging_qi_offers_paid_affinity_strike_once_per_turn(tmp_path, cl, count):
    combat, table, mid = setup(tmp_path, cl=cl)
    prompts = use(combat, table, mid, "Qi volley", target=FOE)
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert "Bloodline Strike" in str(prompt) and "Qi volley" in str(prompt) and "Mara" in str(prompt)
    assert "1 Ancestral Resonance" in str(prompt)
    engine = reload(tmp_path, mid)
    roll, = strike_rolls(engine)
    assert roll.target_ids == (FOE,)
    assert len(roll.payload["dice"]) == count
    assert roll.payload["modifier"] == 0
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
               and e.payload.get("display_source_id") == FEATURE]
    packet, = packets
    assert packet.target_ids == (FOE,) and packet.payload["damage_type"] == "FIRE"
    assert engine.state.actors[OWNER].resources[POOL] == 2
    use(combat, table, mid, "Qi strike", target=FOE)
    assert len(strike_rolls(reload(tmp_path, mid))) == 1
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    use(combat, table, mid, "Qi strike", target=FOE)
    engine = reload(tmp_path, mid)
    assert len(strike_rolls(engine)) == 2
    # On this new turn the Strike itself deals affinity damage and earns 1 back.
    assert engine.state.actors[OWNER].resources[POOL] == 2


def test_normally_compiled_resonance_can_be_earned_and_spent(tmp_path):
    combat, table, mid = setup(tmp_path)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 3
    use(combat, table, mid, "Qi strike", target=FOE)
    engine = reload(tmp_path, mid)
    assert len(strike_rolls(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOL] == 2


def test_subpath_affinity_survives_independent_insight_choice_and_table_reload(tmp_path):
    combat, table, mid = setup(tmp_path, affinity="Cold", insights=[lineage.INSIGHT])
    use(combat, table, mid, "Ancestral Bloodline: Azure Dragon -- Fire")
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert lineage.recorded_affinity(owner) == "cold"
    assert lineage.chosen_damage(owner) == "FIRE"

    prompts = use(combat, table, mid, "Qi strike", target=FOE)
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert "Cold" in str(prompt)
    engine = reload(tmp_path, mid)
    packet, = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
               and e.payload.get("display_source_id") == FEATURE]
    assert packet.target_ids == (FOE,)
    assert packet.payload["damage_type"] == "COLD"
    assert engine.state.actors[OWNER].resources[POOL] == 2
    assert lineage.recorded_affinity(engine.state.actors[OWNER]) == "cold"
    assert lineage.chosen_damage(engine.state.actors[OWNER]) == "FIRE"


def test_declining_does_not_spend_or_consume_turn_allowance(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, "Qi strike", target=FOE, picks={CHOICE: None})
    engine = reload(tmp_path, mid)
    assert not strike_rolls(engine)
    assert engine.state.actors[OWNER].resources[POOL] == 3
    prompts = use(combat, table, mid, "Qi strike", target=FOE)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert reload(tmp_path, mid).state.actors[OWNER].resources[POOL] == 2


@pytest.mark.parametrize("owns,resonance,title", [
    (False, 3, "Qi strike"), (True, 0, "Qi strike"),
    (True, 3, "Empty Qi"), (True, 3, "Mundane strike"),
])
def test_inert_without_ownership_payment_actual_damage_or_qualifying_delivery(tmp_path, owns, resonance, title):
    combat, table, mid = setup(tmp_path, owns=owns, resonance=resonance)
    prompts = use(combat, table, mid, title, target=FOE)
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert not strike_rolls(reload(tmp_path, mid))


def test_ai_owner_uses_the_paid_rider_without_a_human_prompt(tmp_path):
    # The selected in-process controller uses the real AI table transaction;
    # it never calls any live model or embedding service.
    from tests.test_a2r_bone_general import ai_send
    combat, table, mid = setup(tmp_path)
    ai_send(combat, table, mid, candidate(combat, mid, "Qi strike", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert len(strike_rolls(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOL] == 2


def test_authorized_weapon_delivery_qualifies(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid, "Weapon technique", target=FOE)
    assert len(strike_rolls(reload(tmp_path, mid))) == 1


@pytest.mark.parametrize("talent,title,amount,cp", [(ARMAMENT, "Blood Armament", 1, 1), (ARMOR, "Blood Armor", 5, 3)])
def test_fixed_hp_cost_commits_real_hp_with_correct_source_and_no_reaction(tmp_path, talent, title, amount, cp):
    combat, table, mid = setup(tmp_path, [talent], cl=15)
    before = reload(tmp_path, mid).state.actors[OWNER]
    use(combat, table, mid, title)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.current_hp == before.current_hp - amount
    assert owner.resources["resource:core.qi"] == before.resources["resource:core.qi"] - cp
    paid, = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
             and e.source_definition_id.endswith(".hp_cost")]
    assert paid.target_ids == (OWNER,) and paid.payload["hp_damage"] == amount
    assert paid.payload["temporary_hp_absorbed"] == 0


def test_cannot_offer_armament_when_hp_cannot_pay(tmp_path):
    combat, table, mid = setup(tmp_path, [ARMAMENT])
    use(combat, table, mid, "Wound self")
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == 1
    assert not any(engine.action_catalog.get(c.source_definition_id)
                   and engine.action_catalog[c.source_definition_id].display_name == "Blood Armament"
                   for c in engine.legal_candidates())


def test_only_damaged_recipients_are_offered_including_self_when_actually_harmed(tmp_path):
    combat, table, mid = setup(tmp_path)
    prompts = use(combat, table, mid, "Qi crossfire", target=FOE, picks={CHOICE: [OWNER]})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert {option["id"] for option in prompt["choice"]["options"]} == {OWNER, FOE}
    engine = reload(tmp_path, mid)
    roll, = strike_rolls(engine)
    assert roll.target_ids == (OWNER,)
    # Neither the triggering feature's +8 key modifier nor its already-used +4
    # once-per-activation Potency may be charged again on the extra dice.
    assert roll.payload["modifier"] == 0
    packet, = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
               and e.payload.get("display_source_id") == FEATURE]
    assert packet.target_ids == (OWNER,)
    assert engine.state.actors[OWNER].resources[POOL] == 2


@pytest.mark.parametrize("primary,qualifies", [("Qi", True), ("Stamina", False)])
def test_court_later_damage_qualifies_by_its_paid_pool_on_an_ai_creatures_turn(tmp_path, primary, qualifies):
    # Printed CP is paid from this owner's Path pool. Only the Qi-funded
    # activation qualifies; a generic CP price alone is not proof of Qi power.
    combat, table, mid = setup(tmp_path, [COURT], cl=15, primary=primary)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    use(combat, table, mid, "Wound creature", target=FOE)
    before = reload(tmp_path, mid)
    pool = f"resource:core.{primary.lower()}"
    balance = before.state.actors[OWNER].resources[pool]
    court = candidate(combat, mid, "Crimson Court")
    assert before.action_catalog[court.source_definition_id].costs == ((pool, 7),)
    use(combat, table, mid, "Crimson Court")
    cast = reload(tmp_path, mid)
    assert cast.state.actors[OWNER].resources[pool] == balance - 7
    assert not strike_rolls(cast)
    damage_start = len(cast.events)
    prompts = []
    for _ in range(3):
        if table.state(mid)["menu"]["actor_id"] == FOE:
            break
        prompts.extend(settle(table, mid, table.state(mid)["menu"]["end_turn"]))
    assert table.state(mid)["menu"]["actor_id"] == FOE
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts) == qualifies
    engine = reload(tmp_path, mid)
    # The negative case must still deal Court damage: absence of its trigger
    # must not accidentally make the Stamina-funded assertion pass.
    court_damage = [event for event in engine.events[damage_start:]
                    if event.event_type == "DAMAGE_COMMITTED"
                    and event.source_definition_id == court.source_definition_id
                    and event.actor_id == OWNER and event.target_ids == (FOE,)]
    assert court_damage
    assert sum(event.payload["hp_damage"] for event in court_damage) > 0
    assert len(strike_rolls(engine)) == int(qualifies)
    spent = [event for event in engine.events[damage_start:]
             if event.event_type == "RESOURCE_SPENT" and event.actor_id == OWNER
             and event.payload.get("resource_id") == POOL]
    assert sum(event.payload["amount"] for event in spent) == int(qualifies)
    # On the enemy turn the first affinity Strike earns its spent point back.
    assert engine.state.actors[OWNER].resources[POOL] == 3


def test_every_printed_blood_fixed_hp_price_is_compiled_once():
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    records = {key: text for key, text in rules.items() if key.startswith("tianxia.talent.blood.")}
    assert len(records) >= 20
    checked = {}
    for key, text in records.items():
        price = re.search(r"^Cost:.*?\b(\d+) HP\b", text, re.M)
        amount = int(price[1]) if price else 0
        bundle = compile_character(sheet([key], cl=20), actor_id=OWNER)
        actions = [a for a in bundle["action_catalog"]
                   if (a.get("parameters", {}).get("typed") or {}).get("source") == key]
        for action in actions:
            marker = effect_marker(action["parameters"]["typed"], "hp_cost") or {}
            assert int(marker.get("amount", 0)) == amount, (key, action["display_name"])
        if amount:
            assert actions, key
            checked[key] = amount
    assert checked == {ARMAMENT: 1, ARMOR: 5}
