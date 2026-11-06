"""MMX90: standing choices offered to the player (fight audit round 24, HUNT94 findings 1 and 2).

Finding 1 -- Meridian Regulation printed "Choose one poison, disease, or directly caused physical impairment affecting
the target" (tianxia.path.qi_cultivation.feature.meridian_regulation) was never asked: combat/ext/qi_path.py took the
first eligible condition in dict order. This drives the real table with an ally carrying two separate repeating-save
conditions and answers the printed choice, proving the chosen one is the one acted on.

Finding 2 -- a free standing choice (parameters['setting_only'], economy NONE) was offered on the table with a "Bonus"
caption under its button, though it costs no Action, no Bonus Action and no pool. The engine's charge was always right
(gate2_engine only spends the Bonus Action for EconomyKind.BONUS_ACTION); only the caption lied. gate2_engine is a
saved-fight lock file, so the correction is display-only: a general cost label from the action's own economy.

Fixtures are synthetic sheets and a generic injected "Test setup" action; no production class or function is patched.
"""
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_zones import ROOT, SHEET

MERIDIAN = "tianxia.path.qi_cultivation.feature.meridian_regulation"
CTE = "tianxia.path.body_refining.feature.core_tempering_expression"
CASTER, ALLY, FOE = "actor:factory.left", "actor:factory.mid", "actor:factory.right"
CHOICE = "choice:needle.meridian_regulation"

# Both repeating conditions are resolvable on any roll (CON 14 is +2, so the worst d20 total is 3 against DC 2), so the
# only thing that decides which condition is acted on is the player's answer. They are cast by someone else, which is
# what the printed target means ("a poison, disease, or directly caused physical impairment affecting the target").
REPEATING = [{"type": "condition", "condition": name, "applies_to": "target", "repeat_save": {"ability": "CON"},
              "evidence": f"Test setup: {name} repeats its Constitution saving throw."} for name in ("poisoned", "diseased")]
# A Bonus Action, so the caster can lay the taint and then regulate it in the same turn: a repeating-save condition
# also resolves on its bearer's own turn end (combat/ext/benefit_suppression.py repeat_saves), so the printed choice has
# to be answered before the ally's turn comes round again.
#
# The setup ability is a test double, and it says which PRINTED ability it stands in for through ``typed["source"]``.
# It has to: Meridian Regulation decides the printed category from the effect's own ability, and it only offers an
# effect whose ability the review has placed in one of the printed three (combat/ext/qi_path._affliction_category reads
# combat/rules/affliction_sources.json). An effect whose source names no printed ability is the GM's to rule on -- the
# printed rule says so -- so without this the fixture would test the GM's-to-rule-on path while claiming to test the
# choice. Pointing it at a real printed disease (Symptom Cascade: "Failed Save: Choose two symptoms ... the target
# repeats the saving throw, ending both symptoms on itself on a success") means the test drives the printed path, and a
# future change that drops a printed disease from the reviewed table fails here rather than passing quietly.
TAINT = (("taint", "Test setup", REPEATING, "ANY_CREATURE", "BONUS_ACTION",
          "tianxia.talent.disease.symptom_cascade"),)

# The same condition, the same save and the same DC from two DIFFERENT abilities and two different creatures: the two
# options can only be told apart by where each came from, which is what the labels must say (review finding 2). Both
# stand in for a printed poison that repeats its save (Poison Pill's Venom Pill: "Failed Save: 6d6 Poison damage and
# Poisoned for 1 minute. The target repeats the save at the end of each of its turns, ending the Poisoned condition on a
# success"), which is what makes both offered. That ability prints no "Target:" clause, so the test double's own
# ANY_CREATURE target stands: a printed ability that restricts who it can be used on (Five-Venom Formula needs "at least
# 1 Dose Mark or Toxin Burden from you") would decide the fixture's targets instead of the fixture.
SAME_TAINT = (("venom", "Test Snake Venom", REPEATING[:1], "ANY_CREATURE", "BONUS_ACTION",
               "TAL_ALCHEMY_POISON_PILL"),
              ("spore", "Test Spore Cloud", REPEATING[:1], "ANY_CREATURE", "BONUS_ACTION",
               "TAL_ALCHEMY_POISON_PILL"))


def sheet(*, name, path_feature, cl=5, ac=12, setup=()):
    out = copy.deepcopy(SHEET)
    out["identity"].update(display_name=name, cultivation_level=cl, proficiency_bonus=3, path="Qi Cultivation")
    out["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    out["ability_scores_and_statistics"]["primary_resource"] = {"name": "Qi", "maximum": 30}
    out["path_and_subpath"] = {"path_feature_record_ids": [path_feature]}
    out["spheres_and_talents"] = {"sphere_record_ids": [], "learned_talent_record_ids": []}
    return out


def _bundle(sheet_doc, actor_id, *, setup=()):
    bundle = compile_character(copy.deepcopy(sheet_doc), actor_id=actor_id)
    for action_id, display, effects, target_kind, economy, *rest in setup:
        source = rest[0] if rest else None
        action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
        action.update(source_definition_id=f"action:test.mmx90.{action_id}.{actor_id.rsplit('.', 1)[-1]}",
                      display_name=display, economy=economy, target_kind=target_kind, costs=[], range_ft=60)
        action["parameters"] = {"player_only": True, "typed": {
            "effects": effects, "numbers": {"cl": 5, "pb": 3, "save_dc": 2},
            "duration": {"kind": "instant"}, "riders": [], **({"source": source} if source else {})}}
        bundle["action_catalog"].append(action)
        bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundle


def fight(tmp_path, *, caster_setup=(), ally_setup=(), foe_setup=(), caster_feature=MERIDIAN):
    actors = [CASTER, ALLY, FOE]
    bundles = (
        _bundle(sheet(name="Regulator", path_feature=caster_feature), CASTER, setup=caster_setup),
        _bundle(sheet(name="Wounded Ally", path_feature="tianxia.path.qi_cultivation.feature.golden_core",
                      ac=16), ALLY, setup=ally_setup),
        _bundle(sheet(name="Brawler", path_feature="tianxia.path.qi_cultivation.feature.golden_core", ac=14), FOE,
                setup=foe_setup),
    )
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="MMX90-STANDING-CHOICE", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": actors,
                      "team_by_actor": {CASTER: "team:a", ALLY: "team:a", FOE: "team:b"},
                      "starting_positions": {CASTER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}}})
    mid = session.match_id
    for actor_id in actors:  # the table, as the page plays it: every fighter is the owner's
        service.set_controller_mode(mid, actor_id=actor_id, controller_mode="MANUAL")
    return service, TabletopService(service, tmp_path), mid


def menu_of(table, mid):
    return table.state(mid).get("menu") or {}


def group_for(menu, text, target=None):
    for group in menu.get("actions") or []:
        if text not in (group.get("label") or ""):
            continue
        for option in group.get("options") or []:
            if option.get("candidate_id") and (target is None or target in (option.get("target_ids") or [])):
                return group, option
    return None, None


def act(table, mid, candidate_id, menu, after, answer=lambda prompt: None):
    """Commit one table action, answering whatever it asks; returns the prompts it asked."""
    answers, prompts = [], []
    for _ in range(12):
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], after, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        picked = answer(prompt)
        answers.append({**prompt["context"],
                        "selection": "DECLINE" if picked is None else "USE", "option_ids": list(picked or [])})
    raise AssertionError("one action asked more prompts than it should")


def prompt_options(prompt):
    return prompt.get("choice", {}).get("options", [])


def turn_of(table, mid, actor_id, limit=30, *, advance=False):
    """Step the fight until ``actor_id`` is the fighter holding the table's buttons.

    ``advance`` first ends the turn in progress, so a fighter that just used its Action is asked again on its NEXT turn.
    """
    if advance:
        state = table.state(mid)
        menu = state.get("menu") or {}
        if menu.get("actor_id") == actor_id:
            act(table, mid, menu["end_turn"], menu, state["last_sequence"])
    for _ in range(limit):
        state = table.state(mid)
        menu = state.get("menu") or {}
        if menu.get("actor_id") == actor_id:
            return menu
        if menu.get("manual"):
            act(table, mid, menu["end_turn"], menu, state["last_sequence"])
        else:
            table.auto_step(mid, after=state["last_sequence"])
    raise AssertionError(f"{actor_id} never held the table's buttons")


def repeating_on(engine, entity_id):
    return sorted(c.condition_id.removeprefix("condition:typed.") for c in engine.state.actors[entity_id].conditions.values()
                  if (c.data or {}).get("repeat_save"))


def repeating_sources(engine, entity_id):
    """Which ability, and which creature, put each repeating-save effect on this creature."""
    rows = []
    for condition in engine.state.actors[entity_id].conditions.values():
        if not (condition.data or {}).get("repeat_save"):
            continue
        action = engine.action_catalog.get(condition.source_definition_id)
        source = engine.state.actors.get(condition.source_actor_id)
        rows.append((getattr(action, "display_name", condition.source_definition_id),
                     getattr(source, "display_name", condition.source_actor_id)))
    return sorted(rows)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_tabletop_client_parses_and_prints_the_cost_the_server_sent():
    """MMX90 review finding 1 (P0): the caption fallback was written ``${ACTION: "Action", ...}[row.kind]`` -- an object
    literal inside a template interpolation with its opening brace dropped. Parsing happens before short-circuit
    evaluation, so the whole tabletop module failed to load and every table lost its controls, including characters
    unrelated to this lane. The module must parse, and both captions must still print a real cost.
    """
    client = Path(__file__).resolve().parents[1] / "static" / "tabletop" / "tabletop.js"
    with client.open("rb") as source:
        subprocess.run(["node", "--check", "--input-type=module"], stdin=source, check=True)
    subprocess.run(["node", str(Path(__file__).with_name("tabletop_action_cost_label.test.mjs"))], check=True)


def test_two_effects_of_one_kind_are_offered_apart_and_the_one_chosen_is_the_one_acted_on(tmp_path):
    """The printed "choose one" is only answerable if two effects of one kind can be told apart (review finding 2).

    Both are Poisoned and both repeat the same save against the same DC, so the name and the DC cannot decide between
    them. The table must name the ability and the creature behind each, and the effect the player picks must be the one
    that is acted on -- here the other creature's, which is not the one the old code took silently.

    Initiative is Brawler, then Regulator, then Wounded Ally (seeded by starting position), so the Brawler's effect and
    the Regulator's are both on the ally before the ally ever ends a turn -- a repeating save resolves on the bearer's
    own turn end (combat/ext/benefit_suppression.py repeat_saves), and DC 2 always succeeds.
    """
    service, table, mid = fight(tmp_path, caster_setup=SAME_TAINT[:1], foe_setup=SAME_TAINT[1:])

    menu = turn_of(table, mid, FOE)
    _, option = group_for(menu, "Test Spore Cloud", target=ALLY)
    act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"])

    menu = turn_of(table, mid, CASTER)
    _, option = group_for(menu, "Test Snake Venom", target=ALLY)
    act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"])
    assert repeating_sources(service._load_session(mid).engine, ALLY) == [("Test Snake Venom", "Regulator"),
                                                                          ("Test Spore Cloud", "Brawler")]

    menu = menu_of(table, mid)  # the Regulator's own turn continues: the venom was a Bonus Action
    group, option = group_for(menu, "Meridian Regulation", target=ALLY)
    assert group is not None, "Meridian Regulation is not offered on the ally carrying two Poisoned effects"

    def pick_the_spore_cloud(prompt):
        wanted = [row["id"] for row in prompt_options(prompt) if "Test Spore Cloud" in (row.get("label") or "")]
        assert len(wanted) == 1, f"the Brawler's effect is not offered as an option of its own: {prompt_options(prompt)}"
        return wanted

    before = len(service._load_session(mid).engine.events)
    prompts = act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"], pick_the_spore_cloud)
    assert len(prompts) == 1, "the printed 'choose one' was not asked"
    labels = [row.get("label") for row in prompt_options(prompts[0])]
    assert len(labels) == 2 and len(set(labels)) == 2, f"two same-kind effects printed the same words: {labels}"
    assert all(label.startswith("Poisoned (Constitution saving throw, DC 2)") for label in labels), labels
    assert any("Test Snake Venom, cast by Regulator" in label for label in labels), labels
    assert any("Test Spore Cloud, cast by Brawler" in label for label in labels), labels

    # The effect that was asked for is the one acted on; the other, identical in name and DC, is still on the target.
    assert repeating_sources(service._load_session(mid).engine, ALLY) == [("Test Snake Venom", "Regulator")]
    assert [e.payload.get("condition_id") for e in service._load_session(mid).engine.events[before:]
            if e.event_type == "CONDITION_REMOVED"] == ["condition:typed.poisoned"]


def test_meridian_regulation_asks_which_of_the_targets_effects_and_regulates_that_one(tmp_path):
    service, table, mid = fight(tmp_path, caster_setup=TAINT)
    menu = turn_of(table, mid, CASTER)
    _, option = group_for(menu, "Test setup", target=ALLY)
    act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"])
    assert repeating_on(service._load_session(mid).engine, ALLY) == ["diseased", "poisoned"]

    menu = turn_of(table, mid, CASTER)
    group, option = group_for(menu, "Meridian Regulation", target=ALLY)
    assert group is not None, "Meridian Regulation is not offered on the wounded ally"
    assert group["kind"] == "ACTION" and group["cost_label"] == "Action, 1 Qi"

    def pick_the_disease(prompt):
        return [row["id"] for row in prompt_options(prompt) if "Diseased" in (row.get("label") or "")]

    before = len(service._load_session(mid).engine.events)
    prompts = act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"], pick_the_disease)
    assert len(prompts) == 1, "the printed 'choose one' was not asked"
    labels = [row.get("label") for row in prompt_options(prompts[0])]
    # Every option says what it is, what it repeats, what it would take, and where it came from and how long it lasts,
    # so two effects of one kind are told apart (review finding 2; the labels gained their source and duration clauses).
    assert len(set(labels)) == 2, f"the two effects print the same words: {labels}"
    for label, name in zip(sorted(labels), ("Diseased", "Poisoned")):
        assert label.startswith(f"{name} (Constitution saving throw, DC 2)"), label
        assert "Test setup, cast by Regulator" in label, "the option does not say which ability cast it: " + label
        assert "until Wounded Ally's next turn ends" in label, "the option does not say how long it lasts: " + label
    asked = prompts[0]
    assert asked["action"] == "Meridian Regulation"   # names the ability
    assert "Wounded Ally" in f"{asked.get('moment', '')} {asked.get('trigger', '')}"  # and the creature affected
    assert asked["title"] == "Meridian Regulation", "the prompt title must read plainly, not as an internal id"

    # The printed "choose one": the chosen effect is the one acted on, and the other one is still there.
    assert repeating_on(service._load_session(mid).engine, ALLY) == ["poisoned"]
    removed = [e.payload.get("condition_id") for e in service._load_session(mid).engine.events[before:]
               if e.event_type == "CONDITION_REMOVED"]
    assert removed == ["condition:typed.diseased"]

    fresh = CombatService(ROOT, tmp_path)
    reloaded = fresh._load_session(mid)
    assert reloaded.engine.state.model_dump(mode="json") == service._load_session(mid).engine.state.model_dump(mode="json")
    assert TabletopService(fresh, tmp_path).events(mid, 0) == TabletopService(service, tmp_path).events(mid, 0)
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_meridian_regulation_with_nothing_to_choose_still_asks_nothing_and_says_so(tmp_path):
    """The bearer's own doing is not the printed target: nothing to choose means nothing to ask."""
    service, table, mid = fight(tmp_path, caster_setup=TAINT)
    menu = turn_of(table, mid, CASTER)
    _, option = group_for(menu, "Test setup", target=ALLY)
    act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"])
    assert repeating_on(service._load_session(mid).engine, ALLY) == ["diseased", "poisoned"]

    menu = turn_of(table, mid, CASTER)
    group, option = group_for(menu, "Meridian Regulation", target=CASTER)
    assert group is not None, "Meridian Regulation is not offered on the caster itself"
    prompts = act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"], lambda prompt: None)
    assert prompts == []  # it carries no ailment of its own: there is nothing to choose, so nothing is asked
    assert repeating_on(service._load_session(mid).engine, ALLY) == ["diseased", "poisoned"]


def test_a_free_standing_choice_is_offered_as_free_and_costs_no_bonus_action(tmp_path):
    """Core Tempering Expression is a real ``setting_only`` selector: economy NONE, no costs, no printed Action Type."""
    service, table, mid = fight(tmp_path, caster_feature=CTE)
    menu = turn_of(table, mid, CASTER)
    group, option = group_for(menu, "Core Tempering Expression")
    assert group is not None
    action = service._load_session(mid).engine.action_catalog[group["source_definition_id"]]
    assert action.economy == "NONE" and action.parameters["setting_only"] is True and not action.costs

    # The engine still reports its group as a Bonus Action candidate (gate2_engine, a saved-fight lock file, untouched);
    # the table now says what the press actually costs.
    assert group["kind"] == "BONUS_ACTION"
    assert group["cost_label"] == "Free"

    actor = CASTER
    before = service._load_session(mid).engine.state.actors[actor]
    economy = (before.action_available, before.bonus_action_available, before.reaction_available)
    act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"])
    after = service._load_session(mid).engine.state.actors[actor]
    assert (after.action_available, after.bonus_action_available, after.reaction_available) == economy


@pytest.mark.parametrize("economy,expected", [("ACTION", "Action"), ("BONUS_ACTION", "Bonus"), ("REACTION", "Reaction")])
def test_ordinary_costs_keep_their_caption(tmp_path, economy, expected):
    """The seam is keyed on the action's own economy, not on any ability: real actions are unchanged."""
    from combat.tabletop_service import _press_cost_label
    from combat.tabletop import _cost_text
    from types import SimpleNamespace

    action = SimpleNamespace(economy=economy, costs=())
    assert _press_cost_label(action, _cost_text) == expected
    priced = SimpleNamespace(economy="NONE", costs=(("resource:core.stamina", 3),))
    assert _press_cost_label(priced, _cost_text) == "3 Stamina"  # "No Action" that still costs a pool
    assert json.dumps(expected)


def test_the_built_in_ai_regulates_without_being_asked_and_keeps_the_first_effect(tmp_path):
    """An AI owner decides for itself and must not stall the fight on the new choice (MMX86: units miss AI changes).

    The built-in AI's own policy does not pick Meridian Regulation on its own here, so the candidate is forced through
    the AI controller (the pattern in tests/hunt31_support.py) -- what is under test is that the AI's execution path
    answers the choice for itself and keeps going. Nobody answering takes ``preferred``, the same first eligible
    condition the old code took silently, so an AI fight that did use it replays as it did.
    """
    from combat.gate4_adapters import ManualControllerAdapter

    service, table, mid = fight(tmp_path, caster_setup=TAINT)
    menu = turn_of(table, mid, CASTER)
    _, option = group_for(menu, "Test setup", target=ALLY)
    act(table, mid, option["candidate_id"], menu, table.state(mid)["last_sequence"])

    chosen = next(c for c in service._load_session(mid).engine.legal_candidates()
                  if c.display_name == "Meridian Regulation" and ALLY in c.target_ids)
    original = service.controller

    class Selected:
        def choose_primary_action(self, context):
            legal = service._load_session(mid).engine.legal_candidates()
            pick = next(c for c in legal if c.source_definition_id == chosen.source_definition_id
                        and c.target_ids == chosen.target_ids)
            return ManualControllerAdapter(lambda _: (pick.candidate_id, ())).choose_primary_action(
                context.model_copy(update={"legal_candidates": tuple(legal)}))

        def __getattr__(self, name):
            return getattr(original, name)

    service.controller = Selected()
    service.set_controller_mode(mid, actor_id=CASTER, controller_mode="LOCAL_AUTO")
    try:
        result = table.auto_step(mid, table.state(mid)["last_sequence"])
    finally:
        service.controller = original
        service.set_controller_mode(mid, actor_id=CASTER, controller_mode="MANUAL")
    assert result.get("status") != "REACTION_REQUIRED", "the AI fight stalled on a choice it should answer itself"
    engine = service._load_session(mid).engine
    # The grant is read from the engine's own records: a granted repeat save is rolled with Advantage under the
    # granting ability, and the removal it causes carries the GRANTED_REPEAT checkpoint (the owner's own turn-end
    # repeats use END_OF_TURN/START_OF_TURN). No ability-specific payload key is needed.
    granted = [e for e in engine.events if e.event_type == "SAVE_ROLLED"
               and e.source_definition_id == chosen.source_definition_id and e.payload.get("mode") == "ADVANTAGE"]
    assert granted, "the AI did not regulate anything"
    # Poisoned is the first eligible condition in the engine's own order, which is the one the old code took silently.
    regulated = [e.payload.get("condition_id") for e in engine.events if e.event_type == "CONDITION_REMOVED"
                 and e.payload.get("checkpoint") == "GRANTED_REPEAT"]
    assert regulated == ["condition:typed.poisoned"], regulated
    assert repeating_on(engine, ALLY) == ["diseased"]
