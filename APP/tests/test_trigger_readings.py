"""Trigger readings (owner 2026-09-26: "i want all the reactions usable ... remember we can update the phrasing").

authority/typed_mechanics/trigger_readings.jsonl holds a reviewed reading of each reaction trigger the phrase classifier
could not place: one or more events (a combat moment plus its limits), or none when combat can't observe it. The compiler
turns each event into its own row of the one reaction, and the hooks check the limits a reading adds.
"""

import hashlib
from pathlib import Path

from combat import reaction_triggers, typed_executor, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE

ROOT = Path(__file__).resolve().parents[1]
REACTOR = "actor:factory.readings"


def _reaction(key: str, trigger: str, effects: list) -> dict:
    return {"mechanic_id": key, "name": key.title(), "sphere_id": "tianxia.sphere.test", "kind": "talent",
            "activation": {"economy": "reaction", "trigger": trigger}, "effects": effects, "riders": [],
            "range": None, "area": None, "duration": {"kind": "instant"}, "cost": []}


SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 15, "technique_attack_bonus": 7,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["BRACE"]},
}
BRACE_TRIGGER = "You are knocked Prone, pushed, or struck by an attack"


def test_a_reading_with_two_events_compiles_one_reaction_with_two_rows(monkeypatch):
    import hashlib

    reading = {"mechanic_id": "BRACE", "text_sha256": hashlib.sha256(BRACE_TRIGGER.encode()).hexdigest(), "reading": "You are hit or damaged",
               "status": "auto", "events": [{"kind": "hit"}, {"kind": "damaged", "damage_types": ["fire"]}]}
    monkeypatch.setattr(reaction_triggers, "_reading_rows", lambda: {("BRACE", reading["text_sha256"]): reading})
    authority = {"mechanics": {"BRACE": _reaction("BRACE", BRACE_TRIGGER, [{"type": "ac_bonus", "amount": 2}])}}
    bundle = compile_character(SHEET, actor_id=REACTOR, typed_authority=authority)
    rows = [row for row in bundle["typed_reactions"] if row.get("feature_id") == "BRACE"]
    # The compiled row carries the engine's uppercase damage identifiers (typed_reactions._generic_damage_type_ok compares upper case);
    # the readings file states them lowercase, so a lowercase row would never match "take Fire damage" at runtime (sw-qiweaving review).
    assert [(row["kind"], row["damage_types"]) for row in rows] == [("hit", []), ("damaged", ["FIRE"])]
    assert [choice["id"] for choice in bundle["reaction_plan"]["choices"]].count("BRACE") == 1  # one reaction in the plan

    manual = {**reading, "status": "manual", "events": []}
    monkeypatch.setattr(reaction_triggers, "_reading_rows", lambda: {("BRACE", reading["text_sha256"]): manual})
    bundle = compile_character(SHEET, actor_id=REACTOR, typed_authority=authority)
    assert not any(row.get("feature_id") == "BRACE" for row in bundle["typed_reactions"])
    assert "Brace" in bundle["diagnostics"]["skipped"]["reaction"]


def _engine(rows: list[dict]) -> Gate2Engine:
    bundle = compile_character({**SHEET, "spheres_and_talents": {"learned_talent_record_ids": []}}, actor_id=REACTOR,
                               typed_authority={"mechanics": {}})
    engine = Gate2Engine(ROOT, match_seed="READINGS", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [REACTOR, LEE, AN], "team_by_actor": {REACTOR: "team:a", LEE: "team:a", AN: "team:b"}})
    engine.typed_reaction_rows[REACTOR] = rows
    engine.typed_actor_ids = {*engine.typed_actor_ids, LEE}  # the ally hooks offer to Factory fighters; LEE stands in as one
    return engine


def _row(kind: str, **extra) -> dict:
    return {"block": "generic", "feature_id": f"TEST_{kind.upper()}", "name": kind, "kind": kind, "costs": [], "numbers": {"pb": 4},
            "effects": [{"type": "damage_modifier", "flat": 5, "applies_to": "self"}], **extra}  # "reduce the damage by 5"


def _mark(engine: Gate2Engine, actor_id: str, name: str) -> None:
    engine._apply_condition(engine.state.actors[actor_id], typed_executor.mark_condition_id(name, REACTOR), "test:setup", REACTOR,
                            expires_on="UNTIL_REMOVED")


def test_an_ally_hook_checks_the_required_mark_on_the_attacker_or_on_the_harmed_ally():
    by_attacker = _row("ally_damaged", requires_mark="Debt Imprint")
    engine = _engine([by_attacker])
    reactor, ally, foe = (engine.state.actors[x] for x in (REACTOR, LEE, AN))
    assert typed_reactions._offer_ally_damaged(engine, ally, foe, 12, 0, AN) == 12  # the attacker bears no Debt Imprint
    _mark(engine, AN, "Debt Imprint")
    assert typed_reactions._offer_ally_damaged(engine, ally, foe, 12, 0, AN) == 7 and not reactor.reaction_available

    on_ally = _row("ally_damaged", requires_mark="Grace Imprint", mark_on="subject")
    engine = _engine([on_ally])
    ally, foe = engine.state.actors[LEE], engine.state.actors[AN]
    _mark(engine, AN, "Grace Imprint")  # on the attacker: not the creature the reading names
    assert typed_reactions._offer_ally_damaged(engine, ally, foe, 12, 0, AN) == 12
    _mark(engine, LEE, "Grace Imprint")
    assert typed_reactions._offer_ally_damaged(engine, ally, foe, 12, 0, AN) == 7 and not engine.state.actors[REACTOR].reaction_available


def test_an_opportunity_only_reading_answers_only_an_opportunity_attack():
    row = {**_row("attacked", opportunity_only=True), "effects": [{"type": "ac_bonus", "amount": 5}]}
    engine = _engine([row])
    reactor, foe = engine.state.actors[REACTOR], engine.state.actors[AN]
    spec = {"attack_bonus": 5, "range_ft": None, "parameters": {}}
    typed_reactions.on_attacked(engine, foe, reactor, spec, None)
    assert reactor.reaction_available  # an ordinary attack
    engine._typed_oa_attacker = AN
    typed_reactions.on_attacked(engine, foe, reactor, spec, None)
    assert not reactor.reaction_available


def test_an_allies_only_technique_reading_answers_an_allys_technique_not_an_enemys():
    row = {**_row("technique_used", allies_only=True), "effects": [{"type": "temp_hp", "flat": 3, "applies_to": "self"}]}
    engine = _engine([row])
    reactor = engine.state.actors[REACTOR]
    typed = {"numbers": {"pb": 4}, "effects": []}
    typed_reactions.on_technique_start(engine, engine.state.actors[AN], [], dict(typed))
    assert reactor.reaction_available and reactor.temporary_hp == 0  # an enemy's technique
    typed_reactions.on_technique_start(engine, engine.state.actors[LEE], [], dict(typed))
    assert not reactor.reaction_available and reactor.temporary_hp == 3


def test_every_unsupported_reaction_has_a_reading_tied_to_its_current_trigger():
    """Owner 2026-09-28 (auto-ironclad): SMOKE_BASE_SMOKE_RESPONSES's row is removed (276 -> 275). Its
    reviewed_final.d/ironclad.json trigger fix (rewording to escape a stale DeepSeek overlay classification,
    see test_generic_reactions.test_distribution_over_the_real_authority) makes it classify as kind "attacked"
    directly through the plain phrase matcher, so it is no longer one of the unsupported reactions this reading
    system exists for; keeping the old reading, keyed to the pre-fix trigger text's hash, would just be stale.

    Owner 2026-09-29 ("i want everything we can automated"; sys/menus-forms, combat/ext/jester.py): 275 -> 280. The five Jester
    Punchlines answer a marked Foil ("Compatible Proposition: Show Your Hand / Come Closer / Ignore the Fool"), a trigger no phrase
    classifier can place, so each got a reading with the Foil mark as its requirement: Excellent Idea and Absurd Agreement (Show Your
    Hand: technique_used), After You, Honored Guest (Come Closer: enters_range), Applaud the Master and The Audience Chooses the Hero
    (Ignore the Fool: ally_attacked). The last two assertions below check that all five are tied to their current trigger text.

    Round 23: riders/c13 (merge 51edf97d; approving C13r3.review.md) adds two current readings, 294 -> 296:
    Swaying Guard (07f2950f) answers an attack against its owner, correcting the overlay's any-ally interpretation;
    Complete Aim (5f1b4add) answers a Kindled Mark subject's attack roll. Both carry status "reviewed", descriptive
    provenance consumed like the other readings by reaction_triggers.readings_for, not a new runtime status.
    The exact events and reviewed-row identities below guard these additions as well as their trigger hashes."""
    import json

    authority = json.loads((ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())["mechanics"]
    rows = [json.loads(line) for line in (ROOT / "authority/typed_mechanics/trigger_readings.jsonl").read_text().splitlines() if line.strip()]
    # riders/c7 (merge de0c0817) added eight rows: Crown of Black Thorns,
    # Counter-Resonance, Circle of Uncounted Arms, Crowned Serpent,
    # Empty-Scabbard Step, Eye beneath the Skin, One-Legged Guard, and
    # Store the Collision. The last replaces its earlier reading: movement
    # now belongs to momentum_body.py, leaving the damage reading here.
    # C7 also superseded four older readings: Swallow Hostile Power and
    # Swallow the Technique now classify their reviewed "You take damage."
    # trigger directly; Hell-Tempered and Guardian at the Gate are passive
    # parents whose owned plug-ins handle their printed subfeatures.
    # 291 + 8 - 1 replaced row - 4 obsolete rows = 294 readings before C13's two additions.
    # AUTO85 (2026-10-05) replaced Laughing Theft of Timing's reading: its printed trigger "a creature you affected
    # with a Monkey Style Trick, Finish, or feint this turn" had been read as requiring any mark (requires_mark "*"),
    # a mark Monkey Style never places, so the Reaction could never fire. It now answers any enemy d20, and the printed
    # scope is kept by combat/ext/monkey.py (reaction_subject_allowed: a creature you hit, forced to save, or made to
    # miss this turn). A replacement, not an addition: 296 readings still.
    assert len(rows) == 296
    identities = [(row["mechanic_id"], row["text_sha256"]) for row in rows]
    assert len(set(identities)) == len(rows)  # no silent last-row-wins replacement
    assert all(row["text_sha256"] == hashlib.sha256(
        str(authority[row["mechanic_id"]]["activation"]["trigger"] or "").encode("utf-8")
    ).hexdigest() for row in rows)  # validate each row, not just the cached lookup
    assert {row["mechanic_id"] for row in rows if row["mechanic_id"].startswith("TAL_YANG_")} >= {
        "TAL_YANG_KINDLED_RESPONSES#complete_breath", "TAL_YANG_KINDLED_RESPONSES#complete_resolve",
        "TAL_YANG_OVERKINDLED_RESPONSES#overcommit_step", "TAL_YANG_OVERKINDLED_RESPONSES#overgrown_recovery",
        "TAL_YANG_APPLYING_A_RISING_MARK#force_the_rising", "TAL_YANG_OVERKINDLED_RESPONSES#overexpose",
        "TAL_YANG_OVERKINDLED_RESPONSES#overstrain_technique",
    }
    assert all(reaction_triggers.readings_for(authority[row["mechanic_id"]]) is not None for row in rows)  # none stale
    c13_events = {
        "TAL_DRUNKEN_STYLE_SWAYING_GUARD": [{"kind": "attacked"}],
        "TAL_YANG_KINDLED_RESPONSES#complete_aim": [
            {"includes_self": False, "kind": "creature_d20", "requires_mark": "Kindled Mark", "rolls": ["attack"]},
        ],
    }
    assert {row["mechanic_id"] for row in rows if row["status"] == "reviewed"} == set(c13_events)
    for row in rows:
        if row["mechanic_id"] in c13_events:
            assert row["events"] == c13_events[row["mechanic_id"]]
        else:
            assert row["status"] in {"auto", "hook", "manual", "zone"}
