"""AUTO20 (round 24, Imbuement Sphere automation): the printed lines this lane runs instead of leaving to the GM.

Every test drives a real compiled character through the engine (``compile_character`` + a Gate 4 controller + one accepted
intent), so it fails on the authority and plug-ins this lane changed and passes without them:

  * Clarify and Cloud -- "When the target makes one such ability check, it may treat a roll lower than 10 as a 10. Once
    this replacement is used, the Mandate ends unless you spend 1 CP to keep it active."
  * Sharpen and Dull -- Sharpen's "a critical hit on a roll of 19 or 20" (one printed choice of three) and Dull's
    "attacks made with it cannot score critical hits".
  * Fortify and Expose -- the printed "Augment 2 CP. Expose lasts for the full duration, but each time the target fails a
    saving throw because of this Disadvantage, it may repeat the Wisdom saving throw against this Mandate, ending it on a
    success."
  * Court of Ten Thousand Mandates -- "once on each of your turns, you may use Place Mandate or Fray Mandate from the chosen
    family without spending an Action, targeting a legal Vessel inside the Court".
  * Layered Mandate -- "When you apply Place Mandate to a willing target, you may spend 1 CP to apply two different Imbue
    options you know with the same action".
  * the Fray Mandate anchor and the Slow Augment's "cannot take the Disengage action" no longer print
    "Condition not in the rules file" at the table.

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c5.json and review_sw-imbuement.json (the five talents above),
combat/rules/feature_blocks.d/riders_c5.json (the Layered Mandate button).
Plug-ins: combat/ext/imbuement_mandates.py (critical range, critical cancel, the Expose recheck, the Court's free Mandate,
the Layered Mandate pair), combat/ext/d20_floor.py (a floor used once, a printed cost keeps it), combat/rules/typed_conditions.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from combat import ext
from combat.ext import cp_pools
from combat.gate2_runtime_models import ReactionDecision, ActionIntent
from tests import test_auto_lane1 as L1
from tests import test_riders_c5 as C5
from tests.test_sysv2_objects import force_d20

APP = Path(__file__).resolve().parents[1]
IMB = "tianxia.talent.imbuement."
DAO = {"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "quantity": 1}
FLOOR = "condition:typed.d20_floor"
VESSEL = "condition:typed.mandate_vessel"


def _imbuer(talents, cl=12, dc=50, ally_items=(DAO,)):
    return C5._imbuer(list(talents), cl=cl, dc=dc, ally_items=list(ally_items))


def _riders(events):
    return [str(event.payload.get("rider")) for event in events if event.event_type == "GM_RIDER"]


def _conditions(actor, condition_id):
    return [condition for condition in actor.conditions.values() if condition.condition_id == condition_id]


def _cast(engine, actor_id, name, target):
    """One accepted intent for any caster (C5._cast_as, with the actor named instead of the lane's own)."""
    engine.state.current_actor_id = actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    found = [candidate for candidate in engine.legal_candidates() if candidate.display_name == name
             and candidate.actor_id == actor_id and (target is None or tuple(candidate.target_ids or ()) == (target,))]
    assert found, f"{name!r} on {target} is not legal; legal: {sorted({c.display_name for c in engine.legal_candidates() if c.actor_id == actor_id and not c.display_name.startswith('Move')})}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids, destination=candidate.destination,
                                       option_ids=candidate.option_ids))
    return engine.events[before:]


def _authority():
    return json.loads(Path(L1.factory_compiler.TYPED_AUTHORITY).read_text(encoding="utf-8"))["mechanics"]


def _check_like_the_table(engine, actor, natural=3, modifier=4, reason="CHECK:test:Insight", ability="WIS", dc=15):
    """``ext.floored`` the way the engine calls it: inside an open intent, so a plug-in's choice question can be answered.

    Clarify's replacement is the bearer's choice, and a choice reaches the table through the gate-4 transport, which is only
    live while an intent is open. A bare ``engine.roller.d20`` outside one has nobody to ask, which is a different thing and is
    what the un-asked fallback covers.
    """
    force_d20(engine, natural, natural)
    roll = engine.roller.d20(modifier=modifier, actor_id=actor.entity_id, reason=reason)
    intent = ActionIntent(intent_id=f"check-{engine.state.event_sequence}", decision_id="d", candidate_id="c",
                          state_version=engine.state.state_version, actor_id=actor.entity_id,
                          target_ids=(actor.entity_id,))
    with engine.d20_scope({"kind": "check", "actor_id": actor.entity_id,
                           "source_id": reason.removeprefix("CHECK:"), "ability": ability, "dc": dc}):
        previous, engine._active_intent = engine._active_intent, intent
        try:
            return ext.floored(engine, actor, roll, dc)
        finally:
            engine._active_intent = previous


# ------------------------------------------------------------------------------------------------ Clarify's low roll becomes a 10
def test_clarify_counts_one_low_check_as_ten_and_the_casters_cp_keeps_the_mandate():
    """"The target has Advantage on ability checks using that ability. When the target makes one such ability check, it may
    treat a roll lower than 10 as a 10. Once this replacement is used, the Mandate ends unless you spend 1 CP to keep it
    active."

    The check itself is the table's own d20 through ``combat.ext.floored``, the seam every skill check the engine rolls goes
    through (stealth, escape checks, Perception, Scoundrel Checks: combat/ext/d20_floor.py asks the check_floor hook there).
    "You" in "unless **you** spend 1 CP" is the Imbuement caster, not the target, so the caster's own Path pool pays and the
    caster is the one asked (AUTO20f1: this test used to charge the target).
    """
    L1b, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "layered_mandate"])
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"],
                          "d20_floor_use": lambda options: ["use"], "d20_floor_keep": lambda options: ["keep"]})
    C5._cast_as(L1b, engine, "Place Mandate: Clarify", L1b.ALLY)
    floor = _conditions(ally, FLOOR)
    assert floor, "Clarify's floor is not on the target"
    rule = (floor[0].data or {}).get("rule", {}).get("d20_floor", {})
    assert rule.get("floor") == 10 and rule.get("once") is True and rule.get("keep") == [["cp", 1]]
    assert rule.get("abilities") == ["WIS"], "the printed \"one such ability check\" is the chosen ability"
    assert rule.get("optional") is True, "\"it may treat\" is the bearer's choice"
    assert rule.get("keep_payer") == "caster"

    target_pool = cp_pools.of(ally, at_least=1)
    assert target_pool, "the target has a Path pool the printed cost must NOT come from"
    caster_pool = cp_pools.of(me, at_least=1)
    qi, ally_qi = int(me.resources[caster_pool]), int(ally.resources[target_pool])
    check = _check_like_the_table(engine, ally)
    assert check.natural_result == 3 and check.total == 10 + 4, (check.natural_result, check.total)
    assert me.resources[caster_pool] == qi - 1, "the CASTER spends the printed 1 CP to keep the Mandate active"
    assert ally.resources[target_pool] == ally_qi, "the target pays nothing"
    assert _conditions(ally, FLOOR), "paying the printed cost keeps the Mandate alive"

    for empty in cp_pools.all_of(me):  # the caster cannot pay the printed cost the next time it is used
        me.resources[empty] = 0
    C5._answers(engine, {"d20_floor_use": lambda options: ["use"]})
    _check_like_the_table(engine, ally, reason="CHECK:test:Medicine", ability="WIS")
    assert not _conditions(ally, FLOOR), "the Mandate must end when the caster will not pay to keep it"
    assert not any(m.source_definition_id.endswith("mandate.imbue.clarify") for m in ally.modifiers.values())
    assert me.concentration is None or not me.concentration.source_definition_id.endswith("mandate.imbue.clarify")


def test_clarify_raises_only_a_check_with_the_chosen_ability_and_only_when_the_target_wants_it():
    """"The target has Advantage on ability checks using **that ability**. When the target makes **one such** ability
    check, it may treat a roll lower than 10 as a 10."

    Two printed words, both load-bearing. "Such" narrows the replacement to the chosen ability (AUTO20f1: the floor used to
    raise every check the table rolled, so a Wisdom Clarify rescued a Strength Athletics check), and "may" makes it the
    target's choice (AUTO20f1: the floor used to apply with no question at all).
    """
    L1b, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "layered_mandate"])
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    C5._cast_as(L1b, engine, "Place Mandate: Clarify", L1b.ALLY)

    def check(reason, ability, dc=15):
        return _check_like_the_table(engine, ally, reason=reason, ability=ability, dc=dc)

    asked = C5._answers(engine, {"d20_floor_use": lambda options: ["use"]})
    assert check("CHECK:test:Wisdom", "WIS").total == 14, "a Wisdom check is raised to a 10"
    assert check("CHECK:test:Insight", "WIS").total == 14, "a Wisdom (Insight) check is raised to a 10"
    assert check("CHECK:test:Athletics", "STR").total == 7, "a Strength (Athletics) check is not \"such a check\""
    assert check("CHECK:test:Sleight of Hand", "DEX").total == 7, "a Dexterity (Sleight of Hand) check is not either"
    assert [str(r["reaction_source_id"]).split(".")[-1] for r in asked if r["reaction_source_id"].endswith("use")] == ["d20_floor_use", "d20_floor_use"], \
        "the target decides each time it may use the replacement"

    # A target that says no keeps the roll as rolled, and the Mandate is untouched.
    L1b, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "layered_mandate"])
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    C5._cast_as(L1b, engine, "Place Mandate: Clarify", L1b.ALLY)
    asked = C5._answers(engine, {"d20_floor_use": lambda options: None})  # None declines; [] is a malformed USE
    declined = _check_like_the_table(engine, ally)
    assert declined.total == 7, "declining leaves the roll as rolled"
    assert [str(r["reaction_source_id"]).split(".")[-1] for r in asked if r["reaction_source_id"].endswith("use")] == ["d20_floor_use"]
    assert _conditions(ally, FLOOR), "declining to use the replacement does not spend it, so the Mandate stays"


def _decline(request):
    from combat.gate2_runtime_models import ReactionDecision

    return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                            reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None


# ------------------------------------------------------------------------------------------------ Sharpen and Dull on a critical hit
def _weapon_action(engine, owner_id, word="Dao"):
    return next(action for action in engine.action_catalog.values()
                if action.owner_id == owner_id and action.display_name.startswith(word) and "attack" in action.display_name)


def _sharpened(L1b, engine, bearer, foe, label, choice):
    """Place or Fray the named Mandate on ``bearer``'s own named weapon (the printed Vessel)."""
    weapon = _weapon_action(engine, bearer.entity_id)
    C5._answers(engine, {"mandate_choice": lambda options: [o for o in options if o.endswith(choice)],
                         "mandate_vessel": lambda options: [weapon.source_definition_id]})
    _cast(engine, L1b.ME, label, bearer.entity_id)
    assert _conditions(bearer, VESSEL), f"{label} left no Mandate on the weapon"
    return weapon


def _attack_as(engine, actor_id, action, target_id):
    """One accepted intent: this fighter's own weapon attack (the engine's normal attack path)."""
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    for pool in cp_pools.all_of(actor):
        actor.resources[pool] = 30
    found = [candidate for candidate in engine.legal_candidates()
             if candidate.actor_id == actor_id and candidate.source_definition_id == action.source_definition_id
             and target_id in (candidate.target_ids or ())]
    assert found, f"{action.display_name} is not legal for {actor.display_name}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"a-{candidate.candidate_id}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids, destination=candidate.destination,
                                       option_ids=candidate.option_ids))
    return engine.events[before:]


def test_sharpens_printed_choice_makes_a_19_a_critical_hit():
    """"attacks with the Vessel score a critical hit on a roll of 19 or 20" -- the confirmed hit's critical range widens."""
    L1b, engine, me, ally, foe = _imbuer(["sharpen_and_dull", "layered_mandate"])
    weapon = _sharpened(L1b, engine, ally, foe, "Place Mandate: Sharpen", "critical")
    force_d20(engine, 19, 19)
    events = _attack_as(engine, L1b.ALLY, weapon, L1b.AN)
    critical = [event for event in events if event.event_type == "ATTACK_CRITICAL_RESOLVED"]
    assert critical and critical[0].payload["critical"] is True
    assert int(critical[0].payload["critical_threshold"]) == 19

    # The other printed choice is the extra damage instead, and is not both at once.
    L1b, engine, me, ally, foe = _imbuer(["sharpen_and_dull", "layered_mandate"])
    weapon = _sharpened(L1b, engine, ally, foe, "Place Mandate: Sharpen", "damage")
    rule = ((_conditions(ally, VESSEL)[0].data or {}).get("rule") or {}).get("mandate_vessel") or {}
    assert rule.get("critical_lowest") is None and rule.get("once_damage_bonus") == "pb"


def test_dull_stops_the_chosen_weapon_scoring_a_critical_hit():
    """"Attacks made with it cannot score critical hits": a confirmed natural 20 becomes a normal hit."""
    from tests import test_auto_lane4 as L4

    engine = L4._duel([IMB + "sharpen_and_dull", IMB + "layered_mandate"], subject_sphere="tianxia.sphere.imbuement",
                      attacker_sphere="tianxia.sphere.brute", attacker_kit={"starting_kit": {"items": [DAO]}}, cl=12)
    victim, caster = engine.state.actors[L4.ME], engine.state.actors[L4.SUBJ]
    weapon = _weapon_action(engine, victim.entity_id)
    C5._answers(engine, {"mandate_vessel": lambda options: [weapon.source_definition_id]})
    _cast(engine, L4.SUBJ, "Fray Mandate: Dull", L4.ME)
    assert _conditions(victim, VESSEL), "Dull left no Mandate on the weapon"
    force_d20(engine, 20, 20)
    events = _attack_as(engine, L4.ME, weapon, L4.SUBJ)
    critical = [event for event in events if event.event_type == "ATTACK_CRITICAL_RESOLVED"]
    assert critical and critical[0].payload["critical"] is False, [event.payload for event in critical]

    # Default-inert: a fighter with no such Mandate is untouched by both hooks.
    assert ext.run("critical_cancel", engine, caster, victim, {}, None, None) == [False]
    assert ext.run("attack_critical_range", engine, caster, victim, {}) == []


# ------------------------------------------------------------------------------------------------ Expose's Augment
def test_exposes_augment_lets_the_target_repeat_the_wisdom_save_and_ends_the_mandate():
    """"Augment 2 CP. Expose lasts for the full duration, but each time the target fails a saving throw because of this
    Disadvantage, it may repeat the Wisdom saving throw against this Mandate, ending it on a success."

    Expose (2 CP, the printed Augment) puts its Disadvantage on the target's next Wisdom saving throw; the next one the
    target actually makes is the Slow Mandate's, it fails because of that Disadvantage, and the repeat ends Expose.
    """
    L1b, engine, me, ally, foe = _imbuer(["fortify_and_expose", "quicken_and_slow", "layered_mandate"], dc=16)
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    force_d20(engine, 1, 3)  # the target fails the Mandate's own Wisdom save
    events = C5._cast_as(L1b, engine, "Fray Mandate: Expose + Augment 2 CP", L1b.AN)
    assert not [text for text in _riders(events) if "GM applies" in text], _riders(events)
    pending = _conditions(foe, "condition:typed.save_against")
    assert pending, "Expose did not put its Disadvantage on the target"
    assert pending[0].data["rule"]["save_against"]["abilities"] == ["WIS"]

    saves_then_natural(engine, 3, 20)  # the Mandate's own save fails on a 3; the repeated one succeeds on a 20
    C5._answers(engine, {"expose_recheck": lambda options: ["repeat"]})
    C5._cast_as(L1b, engine, "Fray Mandate: Slow", L1b.AN)
    assert [event for event in engine.events if event.event_type == "SAVE_ROLLED"], "no save was rolled at all"
    assert not _exposed(foe), "the repeated Wisdom save did not end Expose"

    # A target that declines keeps the Expose (it is the target's choice).
    L1b, engine, me, ally, foe = _imbuer(["fortify_and_expose", "quicken_and_slow", "layered_mandate"], dc=16)
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    force_d20(engine, 1, 3)
    C5._cast_as(L1b, engine, "Fray Mandate: Expose + Augment 2 CP", L1b.AN)
    saves_then_natural(engine, 3, 20)
    C5._answers(engine, {"expose_recheck": lambda options: []})
    C5._cast_as(L1b, engine, "Fray Mandate: Slow", L1b.AN)
    assert _exposed(foe), "declining the repeat must leave Expose in place"


def _exposed(foe):
    """What is still on the target from the (augmented) Expose Mandate itself."""
    return [row for row in (*foe.conditions.values(), *foe.modifiers.values())
            if str(getattr(row, "source_definition_id", "")).endswith(".expose.augmented")]


def test_an_augmented_expose_stays_soft_for_the_whole_mandate_and_can_be_repeated_each_time():
    """"**Augment 2 CP. Expose lasts for the full duration**, but **each time** the target fails a saving throw because of
    this Disadvantage, it may repeat the Wisdom saving throw against this Mandate, ending it on a success."

    The base Expose is genuinely one-shot ("Disadvantage on the **next** saving throw of that type it makes before the start
    of your next turn"), and that is what the augmented button used to do as well (AUTO20f1: the Augment had no rows of its
    own, so it reused the base one -- the Disadvantage was spent by the first save and no second failure could ever open the
    way out). Here the Disadvantage survives three separate Wisdom saves and each failure offers the repeat again.
    """
    L1b, engine, me, ally, foe = _imbuer(["fortify_and_expose", "quicken_and_slow", "layered_mandate",
                                          "court_of_ten_thousand_mandates"], cl=12, dc=16)
    me.resources["resource:core.qi"] = 30
    # A standing Court adds the caster's Proficiency Bonus to Mandate Load, so placing a Slow for each save below is not
    # what ends the Expose (the printed Mandate Load rule, not the printed Augment, is being kept out of the way).
    C5._answers(engine, {"court_family": lambda options: options[:1]})
    C5._cast_as(L1b, engine, "Court of Ten Thousand Mandates", None)
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    force_d20(engine, 1, 3)  # the target fails the Mandate's own Wisdom save
    C5._cast_as(L1b, engine, "Fray Mandate: Expose + Augment 2 CP", L1b.AN)
    pending = _conditions(foe, "condition:typed.save_against")
    assert pending, "Expose did not put its Disadvantage on the target"
    rule = pending[0].data["rule"]["save_against"]
    assert rule["abilities"] == ["WIS"] and rule["mode"] == "DISADVANTAGE"
    assert not rule.get("next"), "\"Expose lasts for the full duration\": the Disadvantage is not used up by one save"
    assert pending[0].expires_on != "START_OF_SOURCE_NEXT_TURN", pending[0].expires_on

    for attempt in (1, 2, 3):
        saves_then_natural(engine, 3, 2)  # the Mandate's own save fails; the repeated one fails too
        asked = C5._answers(engine, {"expose_recheck": lambda options: ["repeat"]})
        C5._cast_as(L1b, engine, "Fray Mandate: Slow", L1b.AN)
        assert "expose_recheck" in [str(r["reaction_source_id"]).split(".")[-1] for r in asked], \
            f"save {attempt}: the repeated Wisdom saving throw was not offered again"
        assert _conditions(foe, "condition:typed.save_against"), f"save {attempt}: the Disadvantage ran out early"
        assert _exposed(foe), f"save {attempt}: a failed repeat must leave Expose in place"

    saves_then_natural(engine, 3, 20)  # this time the repeated save succeeds
    C5._answers(engine, {"expose_recheck": lambda options: ["repeat"]})
    C5._cast_as(L1b, engine, "Fray Mandate: Slow", L1b.AN)
    assert not _exposed(foe), "a successful repeat ends the Mandate"


def test_the_base_expose_is_still_only_the_next_saving_throw():
    """The un-augmented Expose keeps its printed one-shot: \"Disadvantage on the **next** saving throw of that type it
    makes before the start of your next turn.\" Only the printed Augment says it lasts for the full duration."""
    L1b, engine, me, ally, foe = _imbuer(["fortify_and_expose", "quicken_and_slow", "layered_mandate"], dc=16)
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    force_d20(engine, 1, 3)
    C5._cast_as(L1b, engine, "Fray Mandate: Expose", L1b.AN)
    pending = _conditions(foe, "condition:typed.save_against")
    assert pending and pending[0].data["rule"]["save_against"].get("next") is True, pending


def saves_then_natural(engine, failing, passing):
    """The first saving throw lands on ``failing``; every later one lands on ``passing``.

    Both numbers are fixed values, not ranges: the Mandate's own Wisdom save must fail for Expose to have marked it, and the
    repeated save must succeed to end the Mandate, so neither may depend on the seed (AUTO20 2026-10-04: this was a range
    2..20, whose first roll could pass the save at DC 16 and make the test pass or fail depending on how many rolls ran earlier
    in the session).
    """
    original = getattr(engine.roller, "_real_d20", None) or engine.roller.d20
    engine.roller._real_d20 = original
    state = {"save": 0}

    def d20(**kwargs):
        first = "SAVE" in str(kwargs.get("reason") or "") and state["save"] == 0
        if "SAVE" in str(kwargs.get("reason") or ""):
            state["save"] += 1
        want = failing if first else passing
        while True:
            roll = original(**kwargs)
            if int(roll.natural_result) == want:
                return roll

    engine.roller.d20 = d20


# ------------------------------------------------------------------------------------------------ the Court's free Mandate
def _court(family_suffix="quicken_and_slow", talents=None, cl=12):
    """A caster with a standing Court of Ten Thousand Mandates, its family already chosen."""
    L1b, engine, me, ally, foe = _imbuer(list(talents or ["court_of_ten_thousand_mandates", "quicken_and_slow",
                                                           "clarify_and_cloud", "layered_mandate"]), cl=cl)
    me.resources["resource:core.qi"] = 30
    C5._answers(engine, {"court_family": lambda options: [o for o in options if o.endswith(family_suffix)]})
    C5._cast_as(L1b, engine, "Court of Ten Thousand Mandates", None)
    return L1b, engine, me, ally, foe


def _family_of(actor):
    return next((condition for condition in actor.conditions.values()
                 if condition.condition_id == "condition:typed.imbuement_court_family"), None)


def test_the_court_offers_one_free_mandate_each_turn_from_the_chosen_family():
    """"When you create the Court, choose one Mandate family you know ... once on each of your turns, you may use Place
    Mandate or Fray Mandate from the chosen family without spending an Action, targeting a legal Vessel inside the Court" """
    L1b, engine, me, ally, foe = _court()
    family = _family_of(me)
    assert family is not None, "choosing a family is what creating the Court does"
    assert (family.data or {}).get("family") == IMB + "quicken_and_slow", (family.data or {})

    L1._ready(engine)
    names = {c.display_name for c in engine.legal_candidates() if c.actor_id == L1b.ME}
    assert "Court of Ten Thousand Mandates: Free Mandate" in names, sorted(names)
    before = ally.movement_remaining_ft
    C5._answers(engine, {"court_free_mandate": lambda options: [o for o in options if o.endswith(".quicken")]})
    C5._cast_as(L1b, engine, "Court of Ten Thousand Mandates: Free Mandate", L1b.ALLY)
    assert any(m.source_definition_id.endswith("mandate.court.free") for m in ally.modifiers.values()), \
        "the free Mandate placed no Quicken"
    assert ally.movement_remaining_ft >= before
    L1._ready(engine)
    assert "Court of Ten Thousand Mandates: Free Mandate" not in {c.display_name for c in engine.legal_candidates()
                                                                  if c.actor_id == L1b.ME}, "the free Mandate must be once a turn"


def test_a_mandate_from_the_court_belongs_to_the_free_button_and_ends_with_it():
    """The Court's free Mandate is a real Mandate the table charges for with no Action, so it is the caster's Concentration
    on the free button, and the Mandate it places belongs to that button too.

    AUTO20f1: the chosen option's rows used to run in a context of their own, so the Mandate was owned by its own button
    while the Concentration sat on the free one -- and ending the Concentration left the Mandate running with nothing able
    to stop it.
    """
    from combat import zones

    L1b, engine, me, ally, foe = _court()
    L1._ready(engine)
    C5._answers(engine, {"court_free_mandate": lambda options: [o for o in options if o.endswith(".quicken")]})
    C5._cast_as(L1b, engine, "Court of Ten Thousand Mandates: Free Mandate", L1b.ALLY)
    placed = [m for m in ally.modifiers.values() if m.source_definition_id.endswith("mandate.court.free")]
    assert placed, "the free Mandate left nothing the free button owns"
    assert me.concentration is not None and me.concentration.source_definition_id.endswith("mandate.court.free"), \
        "the Concentration is on the free button"
    engine._end_concentration(me, "TEST")
    assert not [m for m in ally.modifiers.values() if m.source_definition_id.endswith("mandate.court.free")], \
        "dropping Concentration must end the Mandate the Court placed"

    # The same held Mandate is one the caster can still Counter-Mandate (foreign_mandates reads the source).
    from combat.ext import imbuement_mandates as IM

    L1b, engine, me, ally, foe = _court()
    L1._ready(engine)
    C5._answers(engine, {"court_free_mandate": lambda options: [o for o in options if o.endswith(".quicken")]})
    C5._cast_as(L1b, engine, "Court of Ten Thousand Mandates: Free Mandate", L1b.ALLY)
    free_id = next(k for k in engine.action_catalog if k.endswith("mandate.court.free"))
    assert free_id in IM.foreign_mandates(engine, foe, ally), "a rival must be able to Counter-Mandate what the Court placed"
    assert zones.typed_zones(engine), "the Court is still standing"


def test_the_court_only_offers_a_mandate_the_chosen_option_may_target():
    """"once on each of your turns, you may use Place Mandate or Fray Mandate from the chosen family ... targeting a legal
    Vessel inside the Court".

    The Court allows either kind, but it does not override the Mandate's own target rule: Place Mandate "can target one
    willing creature" and Fray Mandate "can target one creature". AUTO20f1: the free button was ``ANY_CREATURE`` and ran
    whichever option was chosen, so a Place Mandate landed on a hostile with no saving throw and a Fray Mandate landed on an
    ally with its save and its repeat-save group.
    """
    L1b, engine, me, ally, foe = _court("clarify_and_cloud")

    def options_for(target_id):
        """One fresh fight per target: the free Mandate is once each turn, so the second use needs a new round or a new
        caster."""
        L1b, engine, me, ally, foe = _court("clarify_and_cloud")
        L1._ready(engine)
        seen: dict[str, list] = {}

        def pick(options):
            seen["options"] = list(options)
            return list(options)[:1]

        C5._answers(engine, {"court_free_mandate": pick, "mandate_choice": lambda options: ["WIS"]})
        C5._cast_as(L1b, engine, "Court of Ten Thousand Mandates: Free Mandate", target_id)
        return [str(key).rsplit(".", 1)[-1] for key in seen["options"]], ally, foe

    on_foe, ally, foe = options_for(L1b.AN)
    assert on_foe == ["cloud"], "only the Fray option is a legal target on a hostile"
    on_ally, ally, _ = options_for(L1b.ALLY)
    assert on_ally == ["clarify"], "only the Place option is a legal target on a willing ally"

    # And neither illegal pairing leaves anything behind: a Place option is not on the menu for a hostile at all.
    L1b, engine, me, ally, foe = _court("clarify_and_cloud")
    C5._answers(engine, {"court_free_mandate": lambda options: [o for o in options if o.endswith(".clarify")],
                          "mandate_choice": lambda options: ["WIS"], "use": lambda options: ["use"]})
    L1._ready(engine)
    assert not [c for c in engine.legal_candidates()
                if c.display_name == "Place Mandate: Clarify" and L1b.AN in (c.target_ids or ())], \
        "sanity: the Place Mandate's own button never offers a hostile either"


def test_the_courts_family_is_chosen_when_it_is_created_and_ends_with_it():
    """"**When you create the Court**, choose one Mandate family you know." AUTO20f1: the question was asked on every
    technique the caster used and the stored family changed mid-fight; and the answer outlived its Court, so the sheet kept
    offering a free Mandate the caster could not use and a new Court silently reused the old answer."""
    from combat import zones

    L1b, engine, me, ally, foe = _court("quicken_and_slow")
    asked = C5._answers(engine, {"court_family": lambda options: [o for o in options if o.endswith("clarify_and_cloud")],
                                 "mandate_choice": lambda options: ["WIS"]})
    L1._ready(engine)
    C5._cast_as(L1b, engine, "Place Mandate: Clarify", L1b.ALLY)
    assert "court_family" not in [str(r["reaction_source_id"]).split(".")[-1] for r in asked], \
        "the family is chosen once, as the Court is created"
    assert (_family_of(me).data or {}).get("family") == IMB + "quicken_and_slow"

    zones.remove(engine, next(iter(engine.state.zones.values())), "DURATION_ENDED")
    assert _family_of(me) is None, "the chosen family ends with the Court that was created for it"
    L1._ready(engine)
    assert "Court of Ten Thousand Mandates: Free Mandate" not in {c.display_name for c in engine.legal_candidates()
                                                                  if c.actor_id == L1b.ME}


# ------------------------------------------------------------------------------------------------ Layered Mandate
def test_layered_mandate_applies_two_imbue_options_with_one_action():
    """"When you apply Place Mandate to a willing target, you may spend 1 CP to apply two different Imbue options you know with
    the same action." One Action, one 1 CP payment, and both chosen options land on the one willing target."""
    L1b, engine, me, ally, foe = _imbuer(["layered_mandate", "quicken_and_slow", "tempered_equipment"], cl=12)
    weapon = _weapon_action(engine, ally.entity_id)
    C5._answers(engine, {"layered_mandate": lambda options: [o for o in options if o.endswith(".quicken")]
                                                                   + [o for o in options if o.endswith(".temper_weapon")],
                         "mandate_vessel": lambda options: [weapon.source_definition_id]})
    before = int(me.resources.get("resource:core.qi", 0))
    events = C5._cast_as(L1b, engine, "Place Mandate: Layered Mandate (1 CP)", L1b.ALLY)
    assert not [text for text in _riders(events) if "the second" in text or "GM applies" in text], _riders(events)
    assert not [event for event in events if event.event_type == "SAVE_ROLLED"], \
        "a willing target makes no saving throw against a Layered Mandate"

    # Both options landed: Quicken's Speed and Temper's bonus on the named weapon.
    speeds = [row for row in ally.modifiers.values() if row.target_field == "speed_ft"]
    assert speeds, "the first chosen option (Quicken) placed no Speed bonus"
    assert int(speeds[0].value) == 20, speeds[0].value  # Quicken is +20 feet at CL 12
    vessel = (condition for condition in ally.conditions.values() if condition.condition_id == VESSEL)
    rule = ((next(vessel).data or {}).get("rule") or {}).get("mandate_vessel") or {}
    assert rule.get("attack_bonus") and rule.get("damage_bonus"), "the second chosen option (Temper) placed no bonus"
    assert int(me.resources.get("resource:core.qi", 0)) == before - 1, "the printed cost is 1 CP"


def test_layered_mandate_is_absent_without_the_talent_or_a_second_option():
    """Default-inert: the composite button exists only for a character with Layered Mandate and two Imbue options to choose."""
    L1b, engine, me, ally, foe = _imbuer(["quicken_and_slow"])
    assert "Place Mandate: Layered Mandate (1 CP)" not in {c.display_name for c in engine.legal_candidates()}
    L1b, engine, me, ally, foe = _imbuer(["layered_mandate", "quicken_and_slow"])
    assert "Place Mandate: Layered Mandate (1 CP)" not in {c.display_name for c in engine.legal_candidates()}, \
        "one Imbue option cannot make a pair"


# ------------------------------------------------------------------------------------------------ the table's own rules file
def test_no_imbuement_mandate_condition_reports_itself_missing_from_the_rules_file():
    """"Condition not in the rules file: fray_mandate" reached the player's log on every Fray Mandate (13 lines in one
    Imbuement fight), and the Slow Augment's "no Disengage" did the same."""
    L1b, engine, me, ally, foe = _imbuer(["quicken_and_slow", "layered_mandate", "reflex_edict"])
    events = C5._cast_as(L1b, engine, "Fray Mandate: Slow + no Disengage (1 CP)", L1b.AN)
    events += C5._cast_as(L1b, engine, "Fray Mandate: Lagging Reflex", L1b.AN)
    assert not [text for text in _riders(events) if "not in the rules file" in text], _riders(events)
    rules = json.loads((APP / "combat/rules/typed_conditions.json").read_text(encoding="utf-8"))["conditions"]
    assert {"fray_mandate", "no_disengage"} <= set(rules)


# ------------------------------------------------------------------------------------------------ the typing itself
def test_the_five_automated_lines_are_no_longer_gm_riders():
    """The retired lines are gone from the authority and the honest remaining ones are still there."""
    mechanics = _authority()
    assert not any("lower than 10 as a 10" in rider for rider in mechanics[IMB + "clarify_and_cloud"]["riders"])
    assert not any("critical hits on a 19 or 20" in rider for rider in mechanics[IMB + "sharpen_and_dull"]["riders"])
    assert not any("cannot score critical hits" in rider and "GM" in rider
                   for rider in mechanics[IMB + "sharpen_and_dull"]["riders"])
    expose = [row for row in _walk(mechanics[IMB + "fortify_and_expose"]["effects"])
              if row.get("label") == "Expose" and row.get("type") == "mandate_option"][0]
    assert expose["augment"] == "Augment 2 CP" and expose["cost"] == [["cp", 2]]
    # The printed Augment carries its own rows: a Disadvantage with no "next" and no turn limit, so it lasts the whole
    # Mandate (AUTO20f1: the Augment reused the base one-shot, so only the first save could ever be repeated).
    augmented = {choice["id"]: choice["effects"][0] for choice in expose["augment_choose"]["choices"]}
    base = {choice["id"]: choice["effects"][0] for choice in expose["choose"]["choices"]}
    assert set(augmented) == set(base) == {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
    for code, row in augmented.items():
        assert "next" not in row["on"], (code, row["on"])
        assert not row.get("duration"), (code, row)
    assert "next" in base["WIS"]["on"] and base["WIS"]["duration"] == "until_start_of_your_next_turn", base["WIS"]
    # Clarify's replacement names the chosen ability, says who pays, and is the bearer's to use.
    clarify = next(row for row in mechanics[IMB + "clarify_and_cloud"]["effects"]
                   if row.get("type") == "mandate_option" and row.get("label") == "Clarify")
    for choice in clarify["choose"]["choices"]:
        floor = next(row for row in choice["effects"] if row.get("type") == "d20_floor")
        assert floor["abilities"] == [choice["id"]] and floor["keep_payer"] == "caster" and floor["optional"] is True, floor
    assert not any("lower than 10 as a 10" in rider for rider in mechanics[IMB + "clarify_and_cloud"]["riders"])
    assert not any("repeat the Wisdom saving throw" in rider for rider in mechanics[IMB + "fortify_and_expose"]["riders"])
    assert not any("free Mandate" in rider for rider in mechanics[IMB + "court_of_ten_thousand_mandates"]["riders"])
    assert mechanics[IMB + "layered_mandate"]["riders"] == []
    assert mechanics[IMB + "layered_mandate"]["coverage"] == "FULL", mechanics[IMB + "layered_mandate"]["coverage"]
    # Honest lines that the table cannot run stay.
    assert any("proficient" in rider for rider in mechanics[IMB + "fortify_and_expose"]["riders"])
    assert any("material" in rider for rider in mechanics[IMB + "sharpen_and_dull"]["riders"])


def _walk(rows):
    for row in rows or []:
        if isinstance(row, dict):
            yield row
            yield from _walk(row.get("effects"))
            for choice in (row.get("choose") or {}).get("choices") or []:
                yield from _walk(choice.get("effects"))

# ------------------------------------------------------------------------------------------------ the table service, and a reload
def _service(tmp_path, talents, *, allies=()):
    """A real saved match through CombatService + TabletopService (tests/r1i_service_support.fixture): the level the
    bug showed, because every one of these is state the table writes, pauses on and reloads."""
    from tests.r1i_service_support import fixture

    return fixture(tmp_path, talents, second_talents=[IMB + "clarify_and_cloud"], allies=allies,
                   owner_kit={"starting_kit": {"items": [DAO]}})


def test_clarifys_replacement_survives_a_table_commit_and_reload(tmp_path):
    """"When the target makes one such ability check, it may treat a roll lower than 10 as a 10. Once this replacement is
    used, the Mandate ends unless you spend 1 CP to keep it active."

    Everything that decides that sentence is written into fight state, so it has to come back out of a save: the chosen
    ability, that the use is the target's choice, that the 1 CP is the caster's to spend, and the name of the ability a
    later question reads. Integers and strings only.

    AUTO20r2: the name is presentation and belongs beside the printed rule, not inside it -- every granted floor's rule
    dictionary is read by its own regression, and Complete Mandala Auspice's must stay exactly its two printed numbers
    (tests/test_sys_resources_states.py::test_complete_mandala_auspice_is_an_action_that_puts_a_d20_floor_on_the_target).
    """
    from combat.ext import d20_floor

    from tests.r1i_service_support import SECOND, candidate
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit = _service(tmp_path, [IMB + "clarify_and_cloud"], allies=(SECOND,))
    before, prompts = resolve(combat, mid, send, candidate(table, mid, "Place Mandate: Clarify", SECOND),
                              {"choice:needle.mandate_choice": "WIS"})
    assert [p["context"]["reaction_source_id"] for p in prompts] == ["choice:needle.mandate_choice"]

    engine = reload(tmp_path, mid)
    held = [condition for condition in engine.state.actors[SECOND].conditions.values()
            if condition.condition_id == FLOOR]
    assert len(held) == 1, held
    rule = (held[0].data or {}).get("rule", {}).get("d20_floor")
    assert rule["floor"] == 10 and rule["once"] is True and rule["keep"] == [["cp", 1]]
    assert rule["abilities"] == ["WIS"] and rule["optional"] is True and rule["keep_payer"] == "caster", rule
    assert set(rule) == {"floor", "release_range_ft", "once", "keep", "abilities", "optional", "keep_payer"}, \
        "a floor's rule is the printed rule and nothing else"
    assert (held[0].data or {}).get("source_name") == "Place Mandate: Clarify", held[0].data
    assert d20_floor._source_name(engine, held[0], rule) == "Place Mandate: Clarify", \
        "the stored name is what a later question reads, off a reload"
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_a_saved_row_that_still_keeps_the_name_inside_its_rule_is_read_too():
    """The shape a row saved while the name lived inside the rule (AUTO20r1f1) has to keep working: an old save is never
    rewritten, so the reader takes the name from wherever that row put it -- and never from an internal id."""
    from combat.ext import d20_floor

    L1b, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "layered_mandate"])
    legacy = _plain_floor(engine, ally, me.entity_id, 10, source="test:imbuement.saved_before_the_move")
    legacy.data = {"rule": {"d20_floor": {**d20_floor._rule(legacy), "source_name": "Place Mandate: Clarify"}},
                   "label": "A roll of 9 or lower counts as a 10", "reading": "A row saved before the name moved."}
    assert d20_floor._source_name(engine, legacy, d20_floor._rule(legacy)) == "Place Mandate: Clarify"

    unknown = _plain_floor(engine, ally, me.entity_id, 10, source="test:imbuement.nothing_knows_this")
    unknown.data = {"rule": {"d20_floor": d20_floor._rule(unknown)}, "label": "x", "reading": "y"}
    assert d20_floor._source_name(engine, unknown, d20_floor._rule(unknown)) == "", \
        "a feature id nothing in the catalog knows must never be shown to a player"


def test_the_courts_family_survives_a_table_commit_and_reload(tmp_path):
    """"When you create the Court, choose one Mandate family you know." The answer is one string on the caster, and it has to
    still be there -- and still be the only one asked -- after the table has written the fight to disk and read it back."""
    from tests.r1i_service_support import FOE, OWNER, SECOND, candidate
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit = _service(
        tmp_path, [IMB + "court_of_ten_thousand_mandates", IMB + "quicken_and_slow", IMB + "layered_mandate"],
        allies=(SECOND,))
    family = IMB + "quicken_and_slow"
    before, prompts = resolve(combat, mid, send, candidate(table, mid, "Court of Ten Thousand Mandates"),
                              {"choice:needle.court_family": family})
    assert "choice:needle.court_family" in [p["context"]["reaction_source_id"] for p in prompts], prompts

    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    chosen = next((condition for condition in owner.conditions.values()
                   if condition.condition_id == "condition:typed.imbuement_court_family"), None)
    assert chosen and (chosen.data or {}).get("family") == family, chosen
    assert [zone.active for zone in engine.state.zones.values() if zone.owner_id == OWNER] == [True]
    # It is a read the free Mandate uses, so the menu still offers the button after the reload.
    assert any("Court of Ten Thousand Mandates: Free Mandate" in group["label"]
               for group in table.state(mid)["menu"]["actions"]), \
        [g["label"] for g in table.state(mid)["menu"]["actions"]]
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"

# ------------------------------------------------------------------------------------------------ two floors on one bearer
def _plain_floor(engine, bearer, caster_id, floor, source="test:fate.complete_mandala_auspice"):
    """An unconditional Auspice-style floor on the same bearer: no ``once``, no cost, no question -- the Fate reading
    the shared plug-in was written for first, and the only thing that separates it from Clarify is that it is not a
    choice. Applied through the engine's own evented condition call, exactly as the plug-in applies it."""
    engine._apply_condition(bearer, FLOOR, source, caster_id, expires_on="UNTIL_REMOVED",
                            data={"rule": {"d20_floor": {"floor": int(floor), "release_range_ft": 0}},
                                  "label": f"A roll of {int(floor) - 1} or lower counts as a {int(floor)}",
                                  "reading": "An unconditional floor."})
    return next(c for c in bearer.conditions.values() if c.source_definition_id == source)


def test_declining_clarify_still_leaves_an_equal_floor_to_raise_the_roll(tmp_path):
    """"it may treat a roll lower than 10 as a 10", and an Auspice that "treats a d20 roll of 9 or lower as a 10".

    Two floor-10 effects on one bearer. The unconditional one already raises this roll to a 10, so the bearer must not
    be asked to spend a replacement to reach a number it has for free -- and the answer it would give is irrelevant.

    AUTO20r1: the shared plug-in picked one winning floor and gave up when that one was declined, so declining this
    Mandate switched off an unrelated Auspice on the same bearer and the roll came up as a 7.
    """
    L1b, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "layered_mandate"])
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    C5._cast_as(L1b, engine, "Place Mandate: Clarify", L1b.ALLY)
    _plain_floor(engine, ally, me.entity_id, 10)
    caster_pool = cp_pools.of(me, at_least=1)
    qi = int(me.resources[caster_pool])
    asked = C5._answers(engine, {"d20_floor_use": lambda options: ["use"]})
    check = _check_like_the_table(engine, ally)
    assert (check.natural_result, check.total) == (3, 14), (check.natural_result, check.total)
    assert not [r for r in asked if r["reaction_source_id"].endswith("d20_floor_use")], \
        "no replacement is spent for a roll the other floor already raises to a 10"
    assert int(me.resources[caster_pool]) == qi, "and no printed cost is asked for"
    assert len(_conditions(ally, FLOOR)) == 2, "both Mandates are still on the bearer"


def test_declining_clarify_falls_through_to_a_lower_floor_instead_of_the_raw_roll(tmp_path):
    """The same pair with different floors: the bearer's printed "may" is about the 10, and declining it must not
    leave the roll bare. AUTO20r1: this returned the roll exactly as it came up (a 7), not the other floor's 8."""
    L1b, engine, me, ally, foe = _imbuer(["clarify_and_cloud", "layered_mandate"])
    C5._answers(engine, {"mandate_choice": lambda options: ["WIS"]})
    C5._cast_as(L1b, engine, "Place Mandate: Clarify", L1b.ALLY)
    _plain_floor(engine, ally, me.entity_id, 8)
    C5._answers(engine, {"d20_floor_use": lambda options: None})  # None declines; [] is a malformed USE
    check = _check_like_the_table(engine, ally)
    assert (check.natural_result, check.total) == (3, 12), (check.natural_result, check.total)
    assert _conditions(ally, FLOOR), "declining Clarify spends neither the replacement nor the Mandate"


# ------------------------------------------------------------------------------------------------ the floor's decisions, as the table runs them
# AUTO20r1: these drive the repair through real service transactions (pause -> answer -> COMMITTED -> reload) with
# the match's own control modes. "An AI recipient always declines" and "an AI payer never pays" were both invisible to
# a test that installed its own provider and fabricated an active intent.
from tests.r1i_service_support import FOE, OWNER, SECOND  # noqa: E402  (the table's three real participants)

HUNGER = "HUNGER_BASE_TASTE_THE_QI"
USE, KEEP = "choice:needle.d20_floor_use", "choice:needle.d20_floor_keep"
FREE_MANDATE = "Court of Ten Thousand Mandates: Free Mandate"
QUICKEN = "quicken_and_slow"


def _floors(actor):
    return [condition for condition in actor.conditions.values() if condition.condition_id == FLOOR]


def _low_rolls(monkeypatch, natural=3):
    """Every d20 lands on ``natural``, so the printed floor is the thing under test. Test-only, on the roll authority;
    production dice, typed authority and the engine are untouched."""
    from combat.gate2_rolls import DeterministicRollAuthority

    for name in ("d20", "raw_d20"):
        real = getattr(DeterministicRollAuthority, name)

        def dice(roller, _real=real, **kwargs):
            while True:
                roll = _real(roller, **kwargs)
                if roll.natural_result == natural:
                    return roll

        monkeypatch.setattr(DeterministicRollAuthority, name, dice)


def _insight_contest(bundles):
    """OWNER's real HUNGER button becomes a plain Insight contest, so the bearer's *own* Wisdom check is a real
    creature-versus-creature check the engine floors (combat/typed_executor.resolve_opposed_check -> combat.ext.floored,
    the one place a creature's own check runs through the seam the d20 floor hangs on).

    Test bundles only, the pattern tests/test_a11_contests.py already uses: production authority, generated files and
    the engine stay exactly as they are.
    """
    from combat.canonical import canonical_sha256

    owner = next(b for b in bundles if b["actor_id"] == OWNER)
    second = next(b for b in bundles if b["actor_id"] == SECOND)
    for resource in second["actor_template"]["resources"]:
        if resource["resource_id"] == "resource:core.qi":
            resource["initial"] = 30  # the printed 1 CP has to be affordable for the payer test
    action = next(a for a in owner["action_catalog"] if "oppose Charisma" in a["display_name"])
    action["display_name"] = "Table Contest"
    action["parameters"]["typed"]["riders"] = []
    action["parameters"]["typed"]["effects"] = [{"type": "contest_against", "harmful": True,
        "actor_check": {"kind": "check", "ability": "DEX", "skill": "Sleight of Hand"},
        "target_check": {"kind": "check", "ability": "WIS", "skill": "Insight"},
        "on_success": [], "on_fail": []}]
    owner["action_catalog"] = [action]
    owner["actor_template"]["action_ids"] = [action["source_definition_id"]]
    for bundle in (owner, second):
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def _bearers(tmp_path, monkeypatch):
    """SECOND (team b) is the Imbuement caster whose printed "you" is the payer, FOE (team b, its ally) is the bearer
    whose Wisdom check the floor covers, and OWNER (team a) is the rival making that check. Two different creatures,
    so "a separate AI payer" is a real second participant rather than the bearer paying its own cost."""
    from tests.r1i_service_support import fixture

    _low_rolls(monkeypatch)
    return fixture(tmp_path, [HUNGER], allies=(), second_talents=[IMB + "clarify_and_cloud"],
                   bundle_transform=_insight_contest, owner_dc=50)


def _turn_to(table, mid, commit, actor, label):
    """Advance the table with real End Turns until ``actor`` holds an action called ``label``.

    A computer-run participant's turn has no End Turn at the table, so it is played with the service's own auto step;
    nothing here reaches past the service to move a turn on.
    """
    for _ in range(24):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == actor and any(label in group["label"] for group in menu.get("actions") or []):
            return
        if "end_turn" in menu:
            commit(menu["end_turn"])
        else:
            table.auto_step(mid, 0, [])
    raise AssertionError(f"{actor} was never offered {label!r}")


def _place_clarify(table, mid, send, caster, bearer):
    from tests.r1i_service_support import candidate

    cid = candidate(table, mid, "Place Mandate: Clarify", bearer)
    answers = []
    for _ in range(8):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            return
        prompt = result["reaction"]
        assert prompt["context"]["reactor_id"] == caster, prompt["context"]
        source = prompt["context"]["reaction_source_id"]
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": ["WIS" if source.endswith("mandate_choice")
                                       else prompt["choice"]["options"][0]["id"]]})
    raise AssertionError("too many prompts placing Clarify")


def _qi(actor):
    return int(actor.resources[cp_pools.of(actor, at_least=1)])


def _contest(combat, table, mid, send, commit):
    """OWNER's contest, forced onto the computer so the whole transaction runs with nobody at the table driving it."""
    from tests.r1i_service_support import candidate, force_ai_candidate

    _turn_to(table, mid, commit, OWNER, "Table Contest")
    cid = candidate(table, mid, "Table Contest", FOE)
    force_ai_candidate(combat, mid, OWNER, cid)
    return cid


def test_an_ai_bearer_uses_clarifys_replacement_and_a_separate_payer_is_asked_on_an_ai_turn(tmp_path, monkeypatch):
    """"When the target makes one such ability check, it may treat a roll lower than 10 as a 10. Once this replacement
    is used, the Mandate ends unless you spend 1 CP to keep it active."

    The bearer is a computer-run creature and the payer is a different, person-run one, so the whole repair is one real
    transaction: a LOCAL_AUTO recipient takes the printed "it may" for itself, and the caster that owes the 1 CP is
    asked even though nobody at the table is driving the turn.

    AUTO20r1: the preference compared teams, so this AI bearer was read as a player and always declined its own
    replacement, and an AI caster declined to pay. The bearer is an ally of its caster, which is the legal Place Mandate
    recipient, so both old comparisons were false.
    """
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = _bearers(tmp_path, monkeypatch)
    _turn_to(table, mid, commit, SECOND, "Place Mandate: Clarify")
    _place_clarify(table, mid, send, SECOND, FOE)
    cid = _contest(combat, table, mid, send, commit)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    before = _qi(combat._load_session(mid).engine.state.actors[SECOND])

    first = send(cid, auto=True)
    assert first["status"] == "REACTION_REQUIRED", first
    prompt = first["reaction"]
    assert prompt["context"]["reaction_source_id"] == KEEP, prompt["context"]
    assert prompt["context"]["reactor_id"] == SECOND, prompt["context"]
    assert send(cid, auto=True)["reaction"] == prompt, "a pending question is re-asked unchanged"
    asked = str(prompt)
    assert "Clarify" in asked and "Wisdom" in asked and "Foe" in asked and "Second" in asked, asked
    # The raised roll is named as the table rolled it, and the benefit being bought is named as the scope the row
    # really keeps. AUTO20r2: the sentence promised "the next low Insight (Wisdom) roll", which is narrower than what
    # paying buys -- Clarify stores the chosen ability, so a Wisdom floor also covers the next Perception check.
    assert "Insight (Wisdom)" in asked, "the roll that was just raised is named as the table rolled it: " + asked
    assert "next low Wisdom ability check" in asked, \
        "the retained benefit is the chosen ability's next check, not another of the same skill: " + asked
    assert "next low Insight" not in asked, \
        "the retained benefit must not be narrowed to the skill that triggered the question: " + asked
    assert send(cid, [{**prompt["context"], "selection": "USE", "option_ids": ["keep"]}], auto=True)["status"] == "COMMITTED"

    engine = reload(tmp_path, mid)
    assert _qi(engine.state.actors[SECOND]) == before - 1, "the caster paid the printed 1 CP"
    assert _floors(engine.state.actors[FOE]), "paying the printed cost keeps the Mandate alive"


def test_an_ai_bearer_and_a_separate_ai_caster_settle_the_replacement_and_its_cost_between_them(tmp_path, monkeypatch):
    """"it may treat a roll lower than 10 as a 10. Once this replacement is used, the Mandate ends unless you spend 1 CP
    to keep it active."

    Both halves decided by the computer, on two different creatures: the recipient takes the printed "it may" for
    itself, and the caster whose printed "you" owes the 1 CP pays it. Nobody is at the table, so the whole sentence
    settles inside one committed transaction with no prompt at all.

    AUTO20r1: both preferences compared teams instead of asking who is running the creature. The bearer is an ally of
    its caster (the only legal Place Mandate recipient), so both comparisons were false, this AI recipient declined its
    own replacement and this AI caster refused to pay -- the printed floor silently did nothing and the 1 CP was
    never spent.
    """
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = _bearers(tmp_path, monkeypatch)
    _turn_to(table, mid, commit, SECOND, "Place Mandate: Clarify")
    _place_clarify(table, mid, send, SECOND, FOE)
    cid = _contest(combat, table, mid, send, commit)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    combat.set_controller_mode(mid, actor_id=SECOND, controller_mode="LOCAL_AUTO")
    started = combat._load_session(mid).engine.state.actors
    before, bearer_pool = _qi(started[SECOND]), dict(started[FOE].resources)

    assert send(cid, auto=True)["status"] == "COMMITTED", "nobody is at the table, so nothing pauses"
    engine = reload(tmp_path, mid)
    raised = [roll for roll in engine.rolls if roll.actor_id == FOE and str(roll.reason).startswith("CHECK:")]
    assert raised, "the bearer never made the check the floor covers"
    roll = raised[-1]
    assert roll.natural_result < 10 and roll.total == 10 + int(roll.modifier), \
        f"the AI bearer counted its d20 as a 10: natural {roll.natural_result}, total {roll.total}"
    assert _qi(engine.state.actors[SECOND]) == before - 1, "the separate AI caster paid the printed 1 CP"
    assert dict(engine.state.actors[FOE].resources) == bearer_pool, "the bearer is on the roll; the cost is the caster's"
    assert _floors(engine.state.actors[FOE]), "paying keeps the Mandate alive"


def _striker(bundles):
    """FOE gains one plain damaging strike, so the Concentration the owner's Court is holding is ended by the table's
    own printed rule ("A damaging hit calls for one Concentration save; a failure ends only the most recently started
    technique": APP/combat/rules/concentration.json) instead of by a call into the engine.

    Test bundles only, the pattern ``_insight_contest`` below already uses: production authority, the roll authority
    and the engine are untouched. The strike has no attack roll and no prompt, so the only d20 the transaction spends
    is the Concentration save the test then forces low."""
    from combat.canonical import canonical_sha256

    foe = next(b for b in bundles if b["actor_id"] == FOE)
    action = {"source_definition_id": "action:typed.test.table_strike", "display_name": "Table Strike",
              "owner_id": FOE, "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY",
              "range_ft": 30, "attack_bonus": None, "attack_count": 1, "damage": None, "damage_type": None,
              "save": None, "costs": [], "concentration": False, "radius_ft": None,
              "parameters": {"typed": {"effects": [{"type": "damage", "flat": 20, "damage_types": ["BLUDGEONING"],
                                                   "evidence": "test: one plain hit, no attack roll"}],
                                       "numbers": {}, "duration": {"kind": "instant"}, "riders": [],
                                       "source": "test:table_strike", "range_ft": 30},
                             "expected_damage": 20, "player_only": False}}
    foe["action_catalog"] = [action]
    foe["actor_template"]["action_ids"] = [action["source_definition_id"]]
    foe.pop("bundle_sha256", None)
    foe["bundle_sha256"] = canonical_sha256(foe)


def test_the_courts_free_mandate_ends_with_its_concentration_across_a_reload(tmp_path, monkeypatch):
    """"once on each of your turns, you may use Place Mandate or Fray Mandate from the chosen family without spending an
    Action": the Mandate the free button places is a real Mandate, so it is the caster's Concentration, and losing that
    Concentration ends it.

    AUTO20r1: the existing cleanup test called combat.gate2_engine._end_concentration directly, and the service tests
    only read the family back off disk, so nothing showed the cleanup survives a save.

    AUTO20r2: this test then reloaded, called _end_concentration on the cached engine and looked at that engine only --
    it never committed anything and never reloaded again, so it could not see a Concentration or a Mandate that survived
    the save. Here the whole thing is fought through the service: the Court is created, the free Mandate is placed, the
    fight is reloaded and the Mandate and its Concentration are read back off disk; then a *legal table action* -- the
    rival's strike, and the Concentration save the printed rules answer with -- is committed, and a second reload shows
    both the Concentration and the modifier the free button placed gone from the file, with the reducer still replaying.
    """
    from tests.r1i_service_support import candidate, fixture
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = fixture(tmp_path, [IMB + "court_of_ten_thousand_mandates", IMB + QUICKEN,
                                                           IMB + "layered_mandate"], allies=(SECOND,), owner_dc=50,
                                              bundle_transform=_striker)
    answers = []
    for _ in range(8):
        result = send(candidate(table, mid, "Court of Ten Thousand Mandates"), answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": [o["id"] for o in prompt["choice"]["options"] if o["id"].endswith(QUICKEN)][:1]})
    assert result["status"] == "COMMITTED", result

    _turn_to(table, mid, commit, OWNER, FREE_MANDATE)
    cid = candidate(table, mid, FREE_MANDATE, SECOND)
    answers = []
    for _ in range(8):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": [o["id"] for o in prompt["choice"]["options"] if o["id"].endswith(".quicken")][:1]})
    assert result["status"] == "COMMITTED", result

    placed = reload(tmp_path, mid)
    free = [m for m in placed.state.actors[SECOND].modifiers.values()
            if m.source_definition_id.endswith("mandate.court.free")]
    assert free, "the free Mandate placed nothing the free button owns"
    assert placed.state.actors[OWNER].concentration is not None \
        and placed.state.actors[OWNER].concentration.source_definition_id.endswith("mandate.court.free"), \
        "the Concentration is on the free button, and it survived the reload"

    # The Mandate and its Concentration came back off disk, so the cleanup is settled on the fight the table writes.
    # The rival hits the caster; every d20 lands on 1 (_low_rolls, test-only, on the roll authority), so the printed
    # Concentration save fails and the printed rule ends the most recently started technique.
    _low_rolls(monkeypatch, natural=1)
    _turn_to(table, mid, commit, FOE, "Table Strike")
    assert commit(candidate(table, mid, "Table Strike", OWNER))["status"] == "COMMITTED"

    after = reload(tmp_path, mid)
    ended = [event for event in after.events if event.event_type == "CONCENTRATION_ENDED"
             and event.payload.get("reason") == "FAILED_DAMAGE_CHECK"]
    assert ended, "a hit that fails the printed Concentration save ends the technique it was holding"
    assert after.state.actors[OWNER].concentration is None, after.state.actors[OWNER].concentration
    assert not [m for m in after.state.actors[SECOND].modifiers.values()
                if m.source_definition_id.endswith("mandate.court.free")], \
        "the Mandate the Court placed must be gone from the save, not only from a live engine"
    assert not [m for m in after.state.actors[SECOND].modifiers.values()
                if m.source_definition_id.endswith("mandate.imbue.quicken")], \
        "no Quicken may be left whichever button placed it -- the free Mandate was the only one used, and the whole " \
        "point of owning it with the free button is that losing the Concentration takes it away (AUTO20f1)"

    # And it is gone from the file itself, not only from what a reload builds out of it: the last transaction the
    # table committed reduces to exactly the cleaned state, read straight out of the journal on disk.
    from combat.gate3_reducer import canonical_state_sha256

    store = combat._load_session(mid).store
    records = [json.loads(line) for line in store.journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert records, "the table wrote no journal, so nothing was committed to read back"
    assert records[-1].get("post_state_sha256") == canonical_state_sha256(after.state), \
        "the last committed journal record must be the cleanup, not a transaction that left the Mandate running"
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS", \
        "the committed history of the cleanup has to reduce"
