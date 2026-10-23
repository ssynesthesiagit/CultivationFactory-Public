"""Hunt 71 (MMX6) regressions for weapon damage ability, the shared hand model, and Ask-me prompt text.

Scope is labelled per test. ``test_compile_*`` are compilation/unit-level checks. The
``test_table_*`` tests are the regressions that matter: they drive real TabletopService actions,
commit them, and reload the saved fight from a fresh service.

1. A weapon technique whose printed damage is "the ability modifier used for the attack"
   (Close Haft Strike) must add the ATTACK's ability modifier, not the character's key ability.
2. A Versatile weapon uses the die its grip allows, in both directions: dropping the shield that
   took the second hand restores the two-handed die, and picking it up again returns to the
   ordinary one. The grip question is combat/ext/hand_occupancy.py's, the one shared model.
3. A shared-transport choice prompt shows a plain-language rule that keeps the timing and the
   number of picks, and the free follow-up to an already-paid reaction is shown as already paid.
4. A grip rewrites only the weapon's own damage: a technique that printed a fixed die keeps it
   whichever Versatile weapon delivers it.
5. One physical weapon is one grip, however many attack modes it is offered in.
6. A flat-only hit row uses weapon dice and preserves its bonus through either grip transition.
"""
import copy

import pytest

from combat.decision_text import build_decision_text, _choice_summary
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.hunt51_grapple_support import IDS, fight, on_turn, send, verify_reloaded
from tests.test_hunt51_grapple_persisted import reload
from tests.test_shared_hand_occupancy import SHIELD, options, weapon_option

W = "tianxia.mortal.weapon."
HAFT = "TAL_AXES_CLOSE_HAFT_STRIKE"
# A Versatile weapon: printed 1d8, or 1d10 when it has the second hand to itself.
JIAN = W + "jian"
HERON = "tianxia.subpath.body.white_heron_crescent_body.feature."
JI = W + "ji"

def _stronger_than_key(monkeypatch, *, armor_class=None):
    """Give every fighter of ``fight()`` STR +2 against a CON +4 key ability.

    Close Haft Strike is only a real test when the attack's ability and the character's key
    ability resolve to different numbers, so the sheet is built with them deliberately apart.
    ``armor_class`` of 1 makes the table's attack roll land every time, so the damage the test
    reads is the damage of the row, not of the dice.
    """
    import tests.hunt51_grapple_support as support

    original = support.sheet

    def build(mids, **kw):
        doc = original(mids, **kw)
        doc["ability_scores_and_statistics"]["abilities"] = [
            {"ability": a, "score": s, "modifier": (s - 10) // 2}
            for a, s in (("STR", 14), ("DEX", 12), ("CON", 18), ("INT", 10), ("WIS", 12), ("CHA", 10))]
        if armor_class is not None:
            doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = armor_class
        return doc

    monkeypatch.setattr(support, "sheet", build)


def _fixed_rolls(monkeypatch):
    """Make every roll in this fight deterministic: a natural 10 on a d20, the minimum otherwise.

    A fixed 10 means no criticals and, against the sheet's low AC here, a hit every time, so the
    damage these table tests read is the damage row's own. The counter still advances per die, so
    the mechanical replay stays a real replay of the recorded rolls.
    """
    from combat.gate2_rolls import DeterministicRollAuthority

    def die(self, sides):
        if sides < 2:
            raise ValueError("die requires at least two sides")
        current = self.counter
        self.counter += 1
        return (10 if sides == 20 else 1), current

    monkeypatch.setattr(DeterministicRollAuthority, "_die", die)


# ------------------------------------------------------------------ finding 1, compilation
def test_compile_close_haft_strike_names_the_attack_ability_not_the_key_ability():
    from factory_authoring.starting_kits import item_definition

    doc = sheet(HAFT, cl=10, key="CON")
    doc["ability_scores_and_statistics"]["abilities"] = [
        {"ability": a, "score": s, "modifier": (s - 10) // 2}
        for a, s in (("STR", 14), ("DEX", 12), ("CON", 18), ("INT", 10), ("WIS", 12), ("CHA", 10))]
    doc["equipment"] = [{"starting_kit": {"items": [
        {"item_id": W + "fu", "name": item_definition(W + "fu")["name"], "quantity": 1}]}}]
    bundle = compile_character(doc, actor_id="actor:factory.mmx6.haft")
    action = next(a for a in bundle["action_catalog"] if "CLOSE_HAFT" in a["source_definition_id"])
    typed = action["parameters"]["typed"]
    row = typed["effects"][0]["on_hit"][0]
    # The roll uses Strength, so the damage must add Strength.
    assert typed["weapon"]["ability"] == "STR"
    assert typed["weapon"]["ability_modifier"] == 2
    assert row["formula"] == "attack_ability_modifier"
    # The key ability is still Constitution, and is deliberately not what this row adds.
    assert typed["numbers"]["key_mod"] == 4


# ------------------------------------------------------------------ finding 2, compilation
def test_compile_versatile_die_follows_the_shared_hand_model():
    """Compilation answers the shield question the approved shared model answers.

    A carried shield occupies a hand, so the compiler picks the ordinary die; without one the
    weapon is two-handed and needs the second hand. The play-time correction in both directions
    is covered at the table below.
    """
    from factory_authoring.starting_kits import item_definition

    def jian(*, shield):
        doc = sheet([], cl=10, key="STR")
        items = [JIAN] + ([SHIELD] if shield else [])
        doc["equipment"] = [{"starting_kit": {"items": [
            {"item_id": item, "name": item_definition(item)["name"], "quantity": 1} for item in items]}}]
        bundle = compile_character(doc, actor_id="actor:factory.mmx6.versatile")
        action = next(a for a in bundle["action_catalog"]
                      if a["source_definition_id"].endswith("weapon.jian"))
        return action["parameters"], (action["parameters"].get("typed") or {}).get("weapon") or {}

    with_shield, shield_weapon = jian(shield=True)
    without_shield, bare_weapon = jian(shield=False)
    assert shield_weapon["damage"]["sides"] == 8
    assert bare_weapon["damage"]["sides"] == 10
    assert without_shield.get("requires_hands") == 2


# ------------------------------------------------------------------ finding 3, prompt text
def _needle_prompt():
    """The exact shape hunt71 H71-02 saw: a shared-transport sub-decision whose printed feature
    name ("Reed Quench" / "Tempering Forms") is not a printed heading, so no rules_text entry matches."""
    return {
        "reaction": "Tempering Forms",
        "reactor": "Lunar Void-Strand Monk",
        "moment": "Tempering Forms: choose one Form until your next turn.",
        "by": "",
        "trigger_actor": "Xiahou Zhen",
        "action": "",
        "affected": "",
        "choice": {
            "options": [
                {"id": "edge", "label": "Edge: once per turn + 4 on an unarmed or melee hit", "description": ""},
                {"id": "spine", "label": "Spine: the first Bludgeoning, Piercing or Slashing damage each round - 4", "description": ""},
            ],
            "minimum": 1,
            "maximum": 1,
            "allow_decline": False,
            "preferred": ["edge"],
        },
    }


def test_choice_prompt_fallback_keeps_the_timing_and_the_number_of_picks():
    prompt = _needle_prompt()
    context = {"reactor_id": "actor:factory.mmx6.monk", "reaction_source_id": "choice:needle.tempering_forms"}
    summary = build_decision_text(None, context, prompt, {}, {}, {})["summary"]
    assert "No printed rule summary" not in summary
    assert "Tempering Forms" in summary  # names the ability
    assert "Edge" in summary and "Spine" in summary  # says what each option does
    # The name is not repeated, but the rest of the moment must survive: it is the only place
    # the summary says how many are picked and how long they last.
    assert "one Form" in summary
    assert "until your next turn" in summary
    assert "Cost" in summary


def test_choice_prompt_prefers_the_printed_rule_when_one_resolves():
    """The fallback is inert whenever a printed rule does resolve: the printed text wins."""
    prompt = _needle_prompt()
    context = {"reactor_id": "actor:factory.mmx6.monk", "reaction_source_id": "choice:needle.tempering_forms"}
    rules = {"some.record": "#### Tempering Forms\n\nGain the Tempering Forms and pick one Form each turn."}
    result = build_decision_text(None, context, prompt, {}, {}, rules)
    assert result["summary"] == "Gain the Tempering Forms and pick one Form each turn."


def test_no_options_choice_prompt_is_inert():
    assert _choice_summary({"reaction": "X", "choice": {}}, "none") == ""


def test_ask_transport_exposes_the_documented_prompt_context_seam():
    """A transport-contract check only: ``ask`` accepts prompt_context (this lane's Quench seam).

    It inspects the signature and nothing else; the paid Quench movement it stands for is
    exercised for real by the table regression at the bottom of this file.
    """
    from combat.ext.needle import ask
    import inspect
    assert "prompt_context" in inspect.signature(ask).parameters


# ------------------------------------------------------------------ finding 1, at the table
def test_table_close_haft_strike_damage_adds_the_attack_ability(monkeypatch, tmp_path):
    _stronger_than_key(monkeypatch, armor_class=1)
    _fixed_rolls(monkeypatch)
    user, service, table, match, ids = fight(tmp_path, "haft-table", equipment=(W + "fu",), talents=(HAFT,))
    on_turn(table, match, ids[0])
    # The printed Haft Strike needs the Bite mark, so the Hewing Strike places it first.
    send(table, match, lambda option: "Hewing Strike: Bite" in option["label"]
         and option.get("target_ids") == [ids[2]])
    send(table, match, lambda option: "CLOSE_HAFT" in option.get("source_definition_id", "")
         and option.get("target_ids") == [ids[2]])
    verify_reloaded(user, service, match)
    engine = reload(user, service, match)
    rolled = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and "CLOSE_HAFT" in e.source_definition_id]
    assert rolled, "the Haft Strike rolled no damage at the table"
    payload = rolled[0].payload
    # The delivered attack's die rolled 1, and the modifier added to it is the attack's Strength
    # +2 -- never the key ability's Constitution +4.
    assert payload["expression"].endswith("+2")
    assert payload["modifier"] == 2
    assert payload["total"] == 3


# ------------------------------------------------------------------ finding 2, at the table
def test_table_versatile_grip_follows_the_hands_both_ways_across_reload(tmp_path):
    """The shared hand model, at the table, in both directions, across real commits and reloads.

    Compiled with the shield carried, the Jian uses its ordinary 1d8. Dropping that shield frees
    the second hand and the same weapon rolls 1d10; picking the shield up again returns it to 1d8.
    """
    user, service, table, match, ids = fight(tmp_path, "versatile-grip", equipment=(JIAN, SHIELD))
    on_turn(table, match, ids[0])

    def last_die():
        """The die of the most recent Jian roll, so a stale earlier roll cannot pass for a later one."""
        engine = reload(user, service, match)
        rows = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
                and e.source_definition_id.endswith("weapon.jian")]
        assert rows, "the Jian rolled no damage"
        return rows[-1].payload["expression"].split("d", 1)[1].split("+")[0].split("-")[0]

    send(table, match, weapon_option("weapon.jian", ids[2]))
    verify_reloaded(user, service, match)
    assert last_die() == "8", "a carried shield takes the second hand"

    # Drop the shield, then start a fresh turn: an attack is once per turn.
    send(table, match, lambda option: "Drop Shield" in option["label"])
    verify_reloaded(user, service, match)
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, weapon_option("weapon.jian", ids[2]))
    verify_reloaded(user, service, match)
    assert last_die() == "10", "dropping the shield must restore the two-handed die"

    send(table, match, lambda option: "Pick up Shield" in option["label"])
    verify_reloaded(user, service, match)
    send(table, match)
    on_turn(table, match, ids[0])
    send(table, match, weapon_option("weapon.jian", ids[2]))
    verify_reloaded(user, service, match)
    assert last_die() == "8", "taking the hand back must return the ordinary die"


# ------------------------------------------------- SOL82 (weapon dice plus flat bonus), at the table
@pytest.mark.parametrize("shield", [True, False], ids=["compiled-one-handed", "compiled-two-handed"])
def test_table_flat_bonus_weapon_dice_follow_both_grips_across_reload(monkeypatch, tmp_path, shield):
    """A supported flat-only hit row adds to weapon dice, including after grip changes.

    Start with either compiled grip and exercise its opposite and return. A shield frees the
    second hand when dropped; a Grapple occupies it when the weapon started two-handed.
    The fixture changes only the hit row's representation, not the printed weapon or hand rules.
    """
    import tests.hunt51_grapple_support as support
    from tests.hunt51_grapple_support import grapple

    _stronger_than_key(monkeypatch, armor_class=1)
    _fixed_rolls(monkeypatch)
    original = support.compile_character

    def flat_bonus_bundle(doc, **kwargs):
        bundle = original(doc, **kwargs)
        if kwargs["actor_id"] == IDS[0]:
            action = next(a for a in bundle["action_catalog"]
                          if a["source_definition_id"].endswith("weapon.jian"))
            typed = action["parameters"]["typed"]
            assert typed["weapon"]["damage"]["sides"] == (8 if shield else 10)
            attack = next(row for row in typed["effects"] if row["type"] == "attack")
            attack["on_hit"] = [{"type": "damage", "flat": 2, "damage_types": ["slashing"]}]
        return bundle

    monkeypatch.setattr(support, "compile_character", flat_bonus_bundle)
    equipment = (JIAN, SHIELD) if shield else (JIAN,)
    user, service, table, match, ids = fight(tmp_path, "flat-bonus-grip", equipment=equipment)
    on_turn(table, match, ids[0])
    rolls = 0

    def strike(sides):
        nonlocal rolls
        send(table, match, weapon_option("weapon.jian", ids[2]))
        verify_reloaded(user, service, match)
        engine = reload(user, service, match)
        rows = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
                and e.source_definition_id.endswith("weapon.jian")]
        rolls += 1
        assert len(rows) == rolls, "each transition must produce a new weapon damage roll"
        payload = rows[-1].payload
        # Strength +2 from the weapon, plus the row's fixed +2, must both survive resizing.
        assert payload["expression"] == f"1d{sides}+4"
        assert payload["modifier"] == 4
        assert payload["total"] == 5

    def next_turn():
        send(table, match)
        on_turn(table, match, ids[0])

    strike(8 if shield else 10)
    if shield:
        send(table, match, lambda option: "Drop Shield" in option["label"])
    else:
        next_turn()
        send(table, match, grapple(ids[2]))
    verify_reloaded(user, service, match)
    next_turn()
    strike(10 if shield else 8)
    if shield:
        send(table, match, lambda option: "Pick up Shield" in option["label"])
    else:
        send(table, match, lambda option: "Release grapple" in option["label"])
    verify_reloaded(user, service, match)
    next_turn()
    strike(8 if shield else 10)


# ------------------------------------------------- finding 1 (fixed dice), at the table
def test_table_versatile_weapon_keeps_a_fixed_technique_die_in_both_grips(monkeypatch, tmp_path):
    """Close Haft Strike prints its own die, so no grip rewrites it.

    Delivered by a Versatile Jian (1d8, or 1d10 with the second hand to itself), the technique
    keeps the die its own row prints in both grips. A carried shield takes the second hand, and
    dropping it hands that die back to the weapon, not to this attack. The weapon's own strikes
    in the same fight do follow the grip -- that is the Jian test above, 8 -> 10 -> 8.

    At CL 18 the technique's level table prints 1d8, the same size as the Jian's ordinary die.
    That coincidence is the point: only the executor's own answer about where the dice came from
    can tell the two apart, so this is a real regression rather than a lucky mismatch.

    The Bite mark the technique requires is placed through a fixture action rather than by the
    Fu-only Hewing Strike: the mark is a precondition here, the die under test is not.
    """
    _stronger_than_key(monkeypatch, armor_class=1)
    _fixed_rolls(monkeypatch)
    user, service, table, match, ids = fight(tmp_path, "versatile-fixed-die", equipment=(JIAN, SHIELD),
                                             talents=(HAFT,),
                                             fixture_conditions=("mark.bite." + IDS[0],))
    on_turn(table, match, ids[0])

    def last_haft_die():
        engine = reload(user, service, match)
        rows = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
                and "CLOSE_HAFT" in e.source_definition_id]
        assert rows, "the Haft Strike rolled no damage"
        return rows[-1].payload["expression"].split("d", 1)[1].split("+")[0].split("-")[0]

    def haft_strike(target):
        # The Haft Strike also pushes its target 5 feet away, so the second turn uses the other foe.
        send(table, match, lambda option: "Fixture" in str(option.get("label", ""))
             and option.get("target_ids") == [target])
        send(table, match, lambda option: "CLOSE_HAFT" in option.get("source_definition_id", "")
             and option.get("target_ids") == [target])
        verify_reloaded(user, service, match)

    haft_strike(ids[2])
    printed = last_haft_die()
    assert printed == "8", "the technique must roll the die its own level table prints"

    # Drop the shield: the weapon now has both hands and its own die grows to d10, this row does not.
    send(table, match, lambda option: "Drop Shield" in option["label"])
    verify_reloaded(user, service, match)
    send(table, match)
    on_turn(table, match, ids[0])
    haft_strike(ids[3])
    assert last_haft_die() == printed, "dropping the shield must not resize a fixed technique die"


# ------------------------------------------------- finding 2 (one weapon, one grip), at the table
def test_table_alternative_modes_of_one_weapon_share_one_grip(tmp_path):
    """A Two-Handed Ji's extended-reach variant is the same weapon, not a second one.

    Crescent Body Integration compiles an extended-reach mode of the ordinary Ji attack. Both
    modes are one object in one character's hands, so together they must not fill both hands
    and refuse the ordinary Two-Handed strike.
    """
    user, service, table, match, ids = fight(tmp_path, "ji-shared-grip", equipment=(JI,),
                                             talents=(HERON + "crescent_body_integration",))
    on_turn(table, match, ids[0])
    engine = reload(user, service, match)
    from combat.ext.hand_occupancy import weapon_grips
    grips = [identity for identity in weapon_grips(engine, engine.state.actors[ids[0]])
             if identity.endswith("weapon.ji")]
    assert len(grips) == 1, f"one Ji must occupy one grip, not {grips}"
    # The ordinary Two-Handed strike is offered, so it was not refused for want of a second hand.
    assert any(weapon_option("weapon.ji", ids[2])(option) for option in options(table, match)), \
        "the ordinary Ji attack was refused while its own reach variant held the other hand"


# ------------------------------------------------------------------ finding 3, at the table
def test_table_paid_reed_quench_shows_its_move_as_already_paid(monkeypatch, tmp_path):
    """The paid Quench the Impact reaction, then the free move it includes.

    The move spends nothing: the prompt must say so, and the saved fight must show the Stamina
    paid once for the reaction and not again for the movement.
    """
    from tests.test_c7_review_fixup import STEEL, load, settle, table_fight, to_turn
    from tests.test_riders_c7 import FOE, ME, STAMINA
    from tests.test_tabletop_hunt6 import on_hold

    combat, table, mid = table_fight(tmp_path, [STEEL + "body_forged_in_three_forms", STEEL + "quench_the_impact"])
    to_turn(table, mid, FOE)

    def damage(engine):
        engine._commit_damage(engine.state.actors[ME], 8, "FORCE", "test:hostile",
                              FOE, engine._active_intent, reaction_depth=0)

    on_hold(monkeypatch, lambda engine: damage(engine))
    _result, prompts = settle(table, mid, picks={"quench_the_impact": "reed"})

    move = [p for p in prompts if "reed_quench_move" in str(p["context"].get("reaction_source_id"))]
    assert move, "choosing Reed Quench did not ask where to move"
    cost = str(move[0].get("cost") or "")
    assert cost.lower().startswith("no extra cost"), f"the move must read as already paid, got {cost!r}"
    assert "already spent" in cost.lower()
    assert "15" in str(move[0].get("moment") or move[0].get("trigger") or ""), "the distance must survive"

    saved = load(tmp_path, mid)
    # The reaction cost 1 Stamina; the movement that came with it cost nothing more.
    assert saved.engine.state.actors[ME].resources[STAMINA] == 59
    assert saved.mechanical.replay()["status"] == "PASS"
