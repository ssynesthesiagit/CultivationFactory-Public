"""Reactions fire in combat (owner 2026-09-25).

combat/reaction_triggers.py classifies a reaction's printed trigger text into a
kind the engine can run; combat/factory_compiler.py compiles every owned
reaction with a supported kind into a "generic" typed_reactions row instead of
leaving it in diagnostics.skipped; combat/typed_reactions.py's engine hooks
(on_attack_hit, on_damage, on_save, plus the new on_attacked/on_attack_missed
called from combat/typed_executor.block_attack) run the best eligible one.
"""

from pathlib import Path

from combat import typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.reaction_triggers import RUNNABLE_KINDS, classify_trigger, distribution

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ classifier
def test_classifier_recognizes_the_common_clean_phrasings():
    cases = {
        "A creature hits you with a melee attack": ("hit", {"melee_only": True, "ranged_only": False}),
        "You are hit by a ranged attack roll.": ("hit", {"melee_only": False, "ranged_only": True}),
        "A creature within reach misses you with a melee attack": ("missed", {"melee_only": True, "range_ft": None}),
        "A creature you can see makes an attack roll against you": ("attacked", {"requires_sight": True}),
        "You take Bludgeoning, Force, Lightning, or Thunder damage.": ("damaged", {}),
        "You fail a saving throw.": ("save", {}),
        "A creature you can see within 30 feet hits you or an ally with a metal weapon": ("hit", {"range_ft": 30}),
    }
    for trigger, (kind, filters) in cases.items():
        match = classify_trigger(trigger)
        assert match.kind == kind, f"{trigger!r} -> {match.kind}, expected {kind}"
        for key, value in filters.items():
            assert getattr(match, key) == value, f"{trigger!r}.{key} -> {getattr(match, key)}, expected {value}"


def test_classifier_requires_you_not_a_bystander():
    # No "you" anywhere: a bystander/ally-only trigger must not be mistaken for a self reaction.
    assert classify_trigger("When a creature within 5 feet of the servant is hit by an attack").kind == "unsupported"
    assert classify_trigger("A creature bearing your Beauty Mark damages a creature other than you").kind == "unsupported"


def test_classifier_puts_a_miss_before_an_attack_roll_phrase_in_the_same_order():
    # "misses an attack roll against you": missed must win even though "an attack roll against you" alone matches attacked.
    assert classify_trigger("A creature you can see within 30 feet misses an attack roll against you or an ally").kind == "missed"


def test_classifier_you_or_an_ally_is_a_bystander_kind_not_a_self_kind():
    assert classify_trigger("You or an ally within 60 feet is hit by an attack").kind == "ally_hit"
    assert classify_trigger("An ally you can perceive within 30 feet is targeted by an attack roll").kind == "ally_attacked"


def test_classifier_empty_or_missing_trigger_is_unsupported():
    assert classify_trigger(None).kind == "unsupported"
    assert classify_trigger("None").kind == "unsupported"


def test_distribution_over_the_real_authority():
    """Owner report: how the 460 reactions in the shipped authority split by kind (427 Sphere/Path/Subpath
    reactions plus 33 Foundation features, added 2026-09-25; extended 2026-09-26 with ally_missed/
    ally_damaged, drop_to_zero, bloodied, condition_gained, critical_hit, natural_1, technique_targets/
    technique_used and the non-runnable "moved" -- see combat/rules/reaction_trigger_phrases.json).

    Also 2026-09-26: the trigger-normalization overlay (authority/typed_mechanics/trigger_normalization.jsonl,
    docs/rules/TRIGGER_NORMALIZATION_REVIEW.md) fills in (rule-based rows) or corrects (DeepSeek V4.1 Flash rows) the phrase classifier; "you or an ally" is the ally kind with includes_self;
    the kind follows both the event and its subject (an ally's event is the ally hook).

    Also 2026-09-26 ("make sure the mechanics aren't damaged"): a save ability, damage type, condition
    or held resource named in a trigger is now a checkable limit (combat/reaction_triggers.py,
    combat/typed_reactions.py) rather than a blanket reason to distrust the overlay's kind
    (combat/trigger_overlay.py's enforceable), so one more overlay row is usable: Refuse Heaven-Lock
    ("You would fail a Strength or Constitution saving throw...") moves unsupported -> save.

    Also 2026-09-26 (mark tracking): a "bearing your <Mark>"/"a marked creature" subject is checkable
    now too (combat/typed_executor.py's block_mark, combat/typed_reactions.py's bears_mark), so
    Thread the Weapon ("When a creature with your Tension Mark makes a melee weapon attack" -- no
    literal "you" for the phrase classifier to key off, so only the overlay's own subject reading
    catches it) moves unsupported -> attacked.

    Also 2026-09-26 (tournament bug hunt): a header after an intro sentence is read, so Smoke Responses'
    printed Reaction header makes it a reaction (its trigger is not one combat can run yet: unsupported).

    Also 2026-09-26 (resources generated): the character's own hit/kill/enemy's failed save are trigger kinds now
    (own_hit/own_kill/own_save_failed, typed_reactions.on_own_event); two reactions move unsupported -> own_*.
    And Yin's and Yang's bundled base records split into their own abilities (authority/typed_mechanics/splits.json):
    Receive Overextension and Force the Rising are two new "you or an ally is hit" reactions.

    Owner 2026-09-28 (auto-ironclad, the parallel automation push): three reviewed_final.d/ironclad.json
    corrections shift these numbers again. Smoke Responses' Reaction header was real (Blind the Line) but its
    trigger text is rewritten to escape a stale DeepSeek-normalized overlay row and now classifies as attacked
    instead of unsupported. Iron Forearm Guard ("A creature you can see hits you with a melee attack") had the
    same stale-overlay problem with subject="ally" recorded against it, so it classified ally_hit -- a kind
    _offer_ally_hit only ever offers to a DIFFERENT active fighter, never the one actually struck, meaning it
    could never fire for its owner's own defense; its trigger text is likewise reworded and it now correctly
    classifies as hit. Iron Fist Breaks the Weapon's printed text never states an Action Type (unlike its
    Guard/Meridian siblings); reviewed_final.d infers Reaction economy for it, adding one new "missed" reaction
    that did not exist in the distribution before (activation.economy was "passive").
    """
    import json

    authority = json.loads((ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    dist = distribution(authority["mechanics"])
    # ironroot 2026-09-28 (Lingfeng Ironroot automation, worker typing pass): two more of her own reactions
    # became runnable. Catch Blade was mistyped as a passive, so its printed "the triggering attack misses"
    # trigger never counted as a reaction at all (missed 17 -> 18). Devour Essence had no working trigger
    # (Multi-Mode, never resolved); typed as a reaction on the clearest of its five listed triggers, a hostile
    # creature dropping to 0 HP in range (any_drop_to_zero 12 -> 13).
    # integrator 2026-09-29: with ironclad's reclassifications (Iron Forearm Guard ally_hit -> hit, Smoke Responses'
    # Blind the Line -> attacked, Iron Fist Breaks the Weapon -> missed) on top of ironroot's: 486.
    # sphere review 2026-09-29: Tumbling Recovery ("drop Prone … to avoid an attack") is a Reaction to being attacked,
    # not a Bonus Action (attacked 27 -> 28): 487.
    # sw-weather 2026-09-28: Ground Game is printed "use a Bonus Action to force that creature to make a Strength or Dexterity
    # saving throw", not a Reaction. It was typed as a turn-start Reaction that laid Prone with no save (the own_turn_start kind has no row left): 485.
    # sys/menus-forms 2026-09-29: the four Jester Punchlines that were passives (Excellent Idea, After You Honored Guest, Applaud the
    # Master, The Audience Chooses the Hero) and Absurd Agreement are Reactions keyed to their Foil's mark (combat/ext/jester.py):
    # technique_used +2, enters_range +1, ally_attacked +2: 491.
    # sys-resources-states 2026-09-29: Legion Unending is a Warleader Standard, not a reaction (ally_drop_to_zero 14 -> 13).
    # riders/lane13: Staff of One's unconditional attack was invented. Its
    # wielded-Staff benefits are passive; Deflecting Staff remains a GM rider
    # until its qualified damage interception is implemented (ally_damaged -1).
    # rider lane 9 2026-09-29: Thrown Slipper Rebuke and Reductio ad Absurdum are Punchline Reactions (ally_attacked +1,
    # technique_used +1): 492; Borrowed Gesture and Borrowed Action got their Foil readings (unsupported 77 -> 75, ally_attacked +2).
    # rider lane 9 (Shield): Cover Ally is Active Defense's ally Reaction ("an attack targets one ally within your natural reach"),
    # a reading of ally_attacked within 5 feet (ally_attacked +1): 493.
    # rider lane C4 2026-09-30: Punishment's Succor half is a printed Reaction ("Trigger: A protected ally takes damage from an
    # attack. Sacrifice one Persistent Aegis on that ally.") that was typed as a passive: 490.
    # Rider lane C7 2026-09-30: Hell-Tempered's Eat the Flame answers once the Fire damage has landed ("declared after the
    # complete triggering damage packet resolves"), so combat/ext/jigoku.py plays it and it is no longer a compiled reaction.
    # Jujutsu's Redirect Force likewise runs from combat/ext/jujutsu.py (its Reaction is optional under Empty Body).
    # Rider lane C7: Quench the Impact is asked by combat/ext/steel_forms.py as the damage is about to land (its Reaction menu picks a
    # Form and its Quench; the generic "damaged" row halved every hit), so it is no longer a compiled reaction (damaged 44 -> 43).
    # Rider lane C7: Guardian at the Gate (unsupported: "crosses your Guarded Threshold") is asked by combat/ext/vermilion_gate.py
    # when a move crosses the owner's threshold (unsupported 75 -> 74).
    # Shelter Beneath the Tusks (ally_hit) is asked by combat/ext/elephant_sovereign.py through hit_response (its three answers need the
    # roll and the attacker's reach), so it is no longer a compiled reaction (ally_hit 15 -> 14).
    # P13 adds the reviewed Iron Shirt and Threads of Intent Insight reactions.
    # Reviewed automation after 2ee5b3ac moved four Athletics/Retribution/Hidden Eye/Water reactions to passive (bodyb.json,
    # a2_retribution.json, eye_second_pass.json, zz_a2_water.json: 60366fd3/a6107988, 206d0068, f2ce3dea, d96bdc5a: unsupported 73 -> 70,
    # own_ability 5 -> 4) and added insight.folded-reflexes (attacked +1) and insight.shared-breath-guardian (damaged +1): 488.
    assert sum(dist.values()) == 488
    # Step 8 (owner 2026-09-26): other creatures moving, dropping to 0, saving and healing are hooked; "a creature" triggers
    # that are really about allies moved from the reactor's own kinds to the ally kinds.
    # Readings (owner 2026-09-26, "i want all the reactions usable"): each of the 276 unsupported reactions has a
    # reviewed reading (authority/typed_mechanics/trigger_readings.jsonl); a reaction counts under its first kind combat
    # can run, else its first reading. 77 remain unsupported (owner 2026-09-28: Smoke Responses moved out, see above;
    # previously 78 -- 51 outside what combat models, 26 need the zone system, and Intercepting Strike's attack-off effect);
    # the kinds below with no hook yet (creature_d20, ally_would_drop, ...) are the next batches. R2 (pushes and pulls):
    # forced_moved, ally_forced_moved and ally_condition_gained run. R3-R5: other creatures' actions, reactions and rolls,
    # turn starts and initiative, range and reach, grapples, an ally about to drop, several damaged, own follow-ups run.
    # R6: Intercepting Strike's negation is typed, and the reviews keep each reaction's trigger as it was.
    # sw-blacksmith 2026-09-28: Shift Weight ("A creature fails an attack roll ... against you") had its overlay subject widened
    # to "a creature", so it read as an ally reaction; subject "you" makes it a self "missed" (ally_missed 6 -> 5, missed 22 -> 23).
    # rider lane C4 2026-09-30: Dune Bank's reading ("You or a creature within 5 feet of Sand Terrain you control is targeted by an
    # attack roll") runs as a you-or-an-ally attacked reaction; combat/ext/sand_riders.py checks the 5 feet (unsupported 77 -> 76,
    # ally_attacked 26 -> 27). Punishment Succor runs as an ally_damaged reaction (ally_damaged 43 -> 44).
    # Rider lane C7 2026-09-30: Swallow the Technique reduces the damage of the technique affecting you as it is applied
    # ("Resolve the attack or save normally, then reduce all valid stored damage types"), a damage checkpoint, not a
    # technique_targets response (damaged 43 -> 44, technique_targets 9 -> 8). Circle of Uncounted Arms' reading leads with its
    # printed "A hostile creature within reach makes an attack roll" (attacked 28 -> 29, moved 19 -> 18; it still answers moves). Eat the Flame (above): damaged 44 -> 43;
    # Redirect Force: missed 23 -> 22. Store the Collision's reading is its Store Impact (Bludgeoning, Force or Thunder damage);
    # Store Movement is asked by combat/ext/momentum_body.py (forced_moved 4 -> 3, damaged 43 -> 44). Empty-Scabbard Step
    # ("A creature makes a melee attack against you") read as an ally reaction; its reading makes it a self "attacked"
    # before the roll (ally_attacked 30 -> 29, attacked 29 -> 30). Eye beneath the Skin ("A creature you can see makes an attack
    # roll against you") also read as an ally reaction; it is declared as that attack would hit, a self "hit" (ally_attacked
    # 29 -> 28, hit 31 -> 32).
    # C13: Swaying Guard targets its owner: attacked +1, ally_attacked -1.
    # auto/paths-b 2026-10-04 (Qi Cultivation): combat/rules/reaction_trigger_phrases.json gained the runnable phrases for a
    # plain "At the start of each of your turns" moment (the kind existed in combat/reaction_triggers.py's RUNNABLE_KINDS and
    # in this file's kind_order, but no phrase reached it). Every count here is unchanged: the one printed record that uses it,
    # Immortal of Qi, is a passive ("regain 5 Qi"), not a reaction, so the kind is now reported at 0 rather than missing.
    assert dist == {"hit": 32, "missed": 22, "attacked": 33, "damaged": 44, "save": 11, "ally_hit": 14,
                    "ally_attacked": 28, "ally_missed": 5, "ally_damaged": 44, "drop_to_zero": 10, "bloodied": 0,
                    "condition_gained": 3, "critical_hit": 1, "natural_1": 1, "technique_targets": 8, "technique_used": 26,
                    "own_hit": 1, "own_kill": 0, "own_save_failed": 1, "moved": 18, "forced_moved": 4, "healed": 6,
                    "any_drop_to_zero": 13, "creature_save_failed": 13, "creature_save_succeeded": 4, "unsupported": 70,
                    "own_ability": 4, "ally_grapple_succeeded": 1, "ally_forced_moved": 8, "creature_d20": 21,
                    "own_action": 3, "ally_drop_to_zero": 13, "creature_nat": 3, "reaction_used": 1, "enters_range": 4,
                    "own_save_succeeded": 2, "creature_attack_missed": 1, "initiative": 4,
                    "grapple_failed": 1, "creature_acted": 3, "multi_damage": 1, "ally_turn_start": 1, "own_d20_fail": 1,
                    "leaves_reach": 3, "creature_turn_start": 1, "own_turn_start": 0}
    # reach-fix 2026-09-29: 8 "hits/misses/attacks you" reactions the model overlay read as ally kinds are self kinds again.
    assert sum(dist.get(kind, 0) for kind in RUNNABLE_KINDS) == 418


# ------------------------------------------------------------------ compiler
def _mechanic(key: str, name: str, economy: str, effects: list, *, trigger: str | None = None,
             modifier: dict | None = None, cost: list | None = None) -> dict:
    return {"mechanic_id": key, "name": name, "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": economy, "trigger": trigger}, "effects": effects, "riders": [],
            "range": None, "area": None, "duration": {"kind": "instant"}, "cost": cost or [],
            **({"modifier": modifier} if modifier else {})}


AUTHORITY = {"mechanics": {
    "GUARD_REFLEX": _mechanic("GUARD_REFLEX", "Guard Reflex", "reaction",
        [{"type": "ac_bonus", "amount": 5}], trigger="A creature hits you with a melee attack"),
    "IRON_SKIN": _mechanic("IRON_SKIN", "Iron Skin", "reaction",
        [{"type": "resistance", "damage_types": ["fire"]}], trigger="You take damage",
        cost=[[{"resource": "cp", "amount": 2}]]),
    "RIPOSTE": _mechanic("RIPOSTE", "Riposte", "reaction",
        [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["force"], "applies_to": "attacker"}],
        trigger="A creature misses you with a melee attack"),
    "WARD_STANCE": _mechanic("WARD_STANCE", "Ward Stance", "reaction",
        [{"type": "ac_bonus", "amount": 2}], trigger="A creature makes an attack roll against you"),
    "WARD_MASTERY": _mechanic("WARD_MASTERY", "Ward Mastery", "passive", [], modifier={
        "targets": ["Ward Stance"], "scope": "named", "when": "use", "optional": False, "limit": "none",
        "effects": [{"type": "condition", "condition": "reaction_denied", "applies_to": "attacker"}]}),
}}
REACTOR = "actor:factory.generic_reactor"
REACTOR_SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["GUARD_REFLEX", "IRON_SKIN", "RIPOSTE", "WARD_STANCE", "WARD_MASTERY"]},
}


def test_generic_reaction_is_compiled_and_a_modifier_attaches():
    bundle = compile_character(REACTOR_SHEET, actor_id="actor:factory.generic_compile", typed_authority=AUTHORITY)
    reactions = {row["feature_id"]: row for row in bundle["typed_reactions"] if row.get("block") == "generic"}
    assert reactions["GUARD_REFLEX"]["kind"] == "hit" and reactions["GUARD_REFLEX"]["melee_only"] is True
    assert reactions["IRON_SKIN"]["kind"] == "damaged"
    assert reactions["IRON_SKIN"]["costs"] == [{"resource_id": "resource:core.qi", "amount": 2}]
    assert reactions["RIPOSTE"]["kind"] == "missed"
    assert reactions["WARD_STANCE"]["kind"] == "attacked"
    # Ward Mastery has no attack/save node on Ward Stance to ride on, so its effect is appended directly.
    assert {"type": "condition", "condition": "reaction_denied", "applies_to": "attacker"} in reactions["WARD_STANCE"]["effects"]
    skipped = bundle["diagnostics"]["skipped"]["reaction"]
    assert not ({"Guard Reflex", "Iron Skin", "Riposte", "Ward Stance"} & set(skipped))
    report = {row["name"]: row for row in bundle["modifiers"]}
    assert report["Ward Mastery"]["status"] == "applied" and report["Ward Mastery"]["applied"] == ["Ward Stance"]


# ------------------------------------------------------------------ engine hooks
def _engine() -> Gate2Engine:
    bundle = compile_character(REACTOR_SHEET, actor_id=REACTOR, typed_authority=AUTHORITY)
    return Gate2Engine(ROOT, match_seed="GENERIC-REACTIONS-ENGINE", typed_bundles=(bundle,),
                       roster_setup={"primary_actor_ids": [REACTOR, AN], "team_by_actor": {REACTOR: "team:a", AN: "team:b"}})


def test_a_hit_reaction_with_enough_ac_turns_the_hit_into_a_miss():
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    new_ac, hit = typed_reactions.on_attack_hit(engine, attacker, reactor, {"range_ft": None}, total=15, natural=15, effective_ac=13)
    assert hit is False and new_ac == 18  # Guard Reflex: +5 AC; 15 no longer reaches 13 + 5
    resolved = [e for e in engine.events if e.source_definition_id == "GUARD_REFLEX" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].payload["hit_after_recheck"] is False


def test_a_hit_reaction_that_would_not_flip_the_hit_is_not_spent():
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    # Guard Reflex only adds 5 AC; a total of 30 still hits an AC of 18, so it is not worth using.
    new_ac, hit = typed_reactions.on_attack_hit(engine, attacker, reactor, {"range_ft": None}, total=30, natural=15, effective_ac=13)
    assert hit is True and new_ac == 13 and reactor.reaction_available


def test_generic_reaction_is_spent_for_the_round():
    """(d) a second trigger in the same round does nothing: the reaction was already used."""
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    typed_reactions.on_attack_hit(engine, attacker, reactor, {"range_ft": None}, total=15, natural=15, effective_ac=13)
    assert not reactor.reaction_available
    new_ac, hit = typed_reactions.on_attack_hit(engine, attacker, reactor, {"range_ft": None}, total=15, natural=15, effective_ac=13)
    assert hit is True and new_ac == 13  # no reaction left this round


def test_a_damaged_reaction_reduces_pending_damage_and_spends_its_cost():
    """(b) damage reduction, (e) costs are spent."""
    engine = _engine()
    reactor = engine.state.actors[REACTOR]
    reactor.reaction_available = True
    qi_before = reactor.resources["resource:core.qi"]
    reduced = typed_reactions.on_damage(engine, reactor, 10, 0, source_definition_id="action:test.attack", source_actor_id=AN)
    assert reduced == 5  # Iron Skin halves the pending amount
    assert reactor.resources["resource:core.qi"] == qi_before - 2
    assert not reactor.reaction_available
    resolved = [e for e in engine.events if e.source_definition_id == "IRON_SKIN" and e.event_type == "REACTION_RESOLVED"]
    assert resolved and resolved[-1].payload["pending_after"] == 5


def test_damage_reduction_keeps_the_attacker_actor_for_free_follow_up_range_checks():
    engine = _engine()
    target, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    target.position = type(target.position)(x=5, y=6)
    attacker.position = type(attacker.position)(x=6, y=6)
    target.reaction_available = True
    reduction = {"block": "damage_reduction", "feature_id": "TEST_REDUCE", "name": "Test Reduction",
                 "trigger": "any_damage", "minimum_damage": 1, "resource_id": "resource:core.qi", "cost": 1,
                 "dice": "", "bonus": 2}
    free_follow_up = {"block": "generic", "feature_id": "TEST_FREE_RANGE", "name": "Test Free Range",
                      "kind": "damaged", "costs": [], "effects": [], "free": True,
                      "range_ft": 5, "range_reference": "source"}
    engine.typed_reaction_rows[REACTOR] = [reduction, free_follow_up]

    assert typed_reactions.on_damage(engine, target, 10, 0, source_definition_id="action:test.attack", source_actor_id=AN) == 8
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "TEST_FREE_RANGE" for e in engine.events)


def test_declining_damage_reduction_preserves_actor_for_later_soak(monkeypatch):
    engine = _engine()
    target = engine.state.actors[REACTOR]
    target.reaction_available = True
    target.resources["resource:core.qi"] = 10
    reduction = {"block": "damage_reduction", "feature_id": "TEST_DECLINED", "name": "Test Declined",
                 "trigger": "any_damage", "minimum_damage": 1, "resource_id": "resource:core.qi", "cost": 1,
                 "dice": "", "bonus": 2}
    soak = {"block": "damage_soak", "feature_id": "TEST_SOAK", "name": "Test Soak",
            "trigger": "any_damage", "minimum_damage": 1, "resource_id": "resource:core.qi",
            "die": 8, "max_spend": 1}
    engine.typed_reaction_rows[REACTOR] = [reduction, soak]
    answers = iter((False,))
    monkeypatch.setattr(typed_reactions, "_consent", lambda *args, **kwargs: next(answers, True))

    typed_reactions.on_damage(engine, target, 10, 0, source_definition_id="action:test.attack", source_actor_id=AN)

    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "TEST_SOAK" for e in engine.events)


def test_a_missed_reaction_damages_the_attacker():
    """(c) a "when missed" reaction deals damage to the attacker."""
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    hp_before = attacker.current_hp
    typed_reactions.on_attack_missed(engine, attacker, reactor, {"range_ft": None}, None)
    assert attacker.current_hp < hp_before
    assert not reactor.reaction_available
    resolved = [e for e in engine.events if e.source_definition_id == "RIPOSTE" and e.event_type == "REACTION_RESOLVED"]
    assert resolved


def test_an_attacked_reaction_fires_before_the_roll():
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    typed_reactions.on_attacked(engine, attacker, reactor, {"range_ft": None}, None)
    assert not reactor.reaction_available  # Ward Stance fired (free, always worth a pre-emptive AC bump)
    assert any(m.target_field == "armor_class" and m.value == 2 for m in reactor.modifiers.values())


def test_a_bad_generic_row_logs_a_rider_instead_of_crashing_the_fight():
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    bad_row = {"feature_id": "BAD_ROW", "block": "generic", "name": "Broken Reflex", "kind": "hit",
              "costs": [], "effects": [{"type": "ac_bonus", "amount": "not-a-number"}]}
    engine.typed_reaction_rows[REACTOR] = [bad_row]
    # Must not raise; the malformed row is skipped (a GM rider records it) and the hit resolves normally.
    new_ac, hit = typed_reactions.on_attack_hit(engine, attacker, reactor, {"range_ft": None}, total=15, natural=15, effective_ac=13)
    assert (new_ac, hit) == (13, True)
    assert reactor.reaction_available  # the broken row never actually fired, so nothing was spent
    riders = [e for e in engine.events if e.event_type == "GM_RIDER" and e.source_definition_id == "BAD_ROW"]
    assert riders and "Broken Reflex" in riders[-1].payload["rider"]


def test_bad_row_logging_tolerates_a_non_actor_other_value():
    engine = _engine()
    typed_reactions._log_bad_row(engine, engine.state.actors[REACTOR], (AN,),
                                 {"feature_id": "BAD_OTHER", "name": "Broken Range"}, AttributeError("invalid source"))
    rider = next(e for e in engine.events if e.event_type == "GM_RIDER" and e.source_definition_id == "BAD_OTHER")
    assert rider.target_ids == ()


def test_other_creatures_moving_healing_and_dropping_trigger_reactions():
    """Step 8 (owner 2026-09-26): "a creature you perceive within 60 feet willingly moves" (Steal Momentum), "a creature within 60
    feet regains HP" (Grave Tax), "a creature you can perceive within 60 feet drops to 0 HP" (Harvest the Fallen)."""
    from combat import typed_reactions
    from tests.test_factory_combat_compiler import SHEET, _duel
    from tests.test_typed_executor import _intent

    talents = ["TAL_SCOUNDREL_STEAL_MOMENTUM", "TAL_DEATH_GRAVE_TAX", "TAL_DEATH_HARVEST_THE_FALLEN"]
    sheet = {**SHEET, "spheres_and_talents": {**SHEET["spheres_and_talents"],
                                              "learned_talent_record_ids": [*SHEET["spheres_and_talents"]["learned_talent_record_ids"], *talents]}}
    bundle = compile_character(sheet, actor_id="actor:factory.test")
    kinds = {row["feature_id"]: row["kind"] for row in bundle["typed_reactions"] if row.get("block") == "generic"}
    assert {kinds.get(t) for t in talents[1:]} == {"healed", "any_drop_to_zero"}
    assert any(row.get('feature_id') == talents[0] and row.get('block') == 'steal_momentum'
               for row in bundle['typed_passives'])  # native accepted movement checkpoint
    engine, me, foe = _duel(bundle, "CREATURE-EVENTS")
    resolved = lambda feature: [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == feature]  # noqa: E731
    engine.state.current_actor_id = foe.entity_id
    foe.turn_flags["disengaged"] = True  # otherwise the move draws the opportunity attack, which spends the Reaction first
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.actor_id == foe.entity_id
                                       and engine.grid.distance_ft(c.destination, me.position) <= 30)))
    assert resolved("TAL_SCOUNDREL_STEAL_MOMENTUM")
    me.reaction_available = True
    typed_reactions.on_creature_event(engine, foe, "healed")
    assert resolved("TAL_DEATH_GRAVE_TAX")
    me.reaction_available = True
    typed_reactions.on_creature_event(engine, foe, "any_drop_to_zero")
    assert resolved("TAL_DEATH_HARVEST_THE_FALLEN")
    # A reaction that acts against its trigger creature never answers an ally.
    ally_rows = [row for row in bundle["typed_reactions"] if row.get("feature_id") == "TAL_DEATH_GRAVE_TAX"]
    assert typed_reactions._stance(ally_rows[0]) == "harmful"


def test_a_data_denied_reactor_cannot_spend_a_generic_reaction_on_a_hit():
    """Fix 1: a reaction_denied datum (ling_qi nocturne_hindered, no typed_conditions rule) blocks a generic reaction."""
    engine = _engine()
    reactor, attacker = engine.state.actors[REACTOR], engine.state.actors[AN]
    reactor.reaction_available = True
    with engine._transaction("system:test.nocturne", "deny", attacker.entity_id):
        engine._apply_condition(reactor, "condition:ling_qi.nocturne_hindered", "system:test.nocturne", attacker.entity_id,
                                expires_on="UNTIL_REMOVED", data={"reaction_denied": True})
    new_ac, hit = typed_reactions.on_attack_hit(engine, attacker, reactor, {"range_ft": None}, total=15, natural=15, effective_ac=13)
    assert hit is True and new_ac == 13 and reactor.reaction_available
    assert not [e for e in engine.events if e.source_definition_id == "GUARD_REFLEX" and e.event_type == "REACTION_RESOLVED"]
