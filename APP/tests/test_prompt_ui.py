"""Choice presentation at the table boundary; browser checks are explicitly opt-in."""
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from combat.canonical import canonical_sha256
from combat.choice_presentation import capture_space_positions
from combat.factory_compiler import compile_character
from combat.footprints import ActorFootprintDefinition
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_riders_lane2 import A, ME, FOE, ROOT, ELBOW, IRON_FIST, STRIKE


@pytest.fixture
def elbow_table(tmp_path):
    bundles = []
    for actor in (ME, FOE):
        bundle = compile_character(A._sheet(IRON_FIST if actor == ME else None,
                                           [ELBOW] if actor == ME else [], A.AXE_KIT), actor_id=actor)
        bundle["actor_template"].update(armor_class=0, maximum_hp=400,
                                        initiative_bonus=100 if actor == ME else -100)
        for action in bundle["action_catalog"]:
            if action["display_name"] == STRIKE:
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="PROMPTUI", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    table = TabletopService(combat, tmp_path)
    menu = table.state(session.match_id)["menu"]
    candidate = next(c for c in combat.decision(session.match_id)["context"]["legal_candidates"]
                     if c["display_name"] == STRIKE and c["target_ids"] == [FOE])
    def send(answers=()):
        return table.act(session.match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, list(answers))
    return combat, table, session.match_id, send


def test_own_attack_space_prompt_has_rules_positions_and_unchanged_answer(elbow_table):
    combat, table, mid, send = elbow_table
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["title"] == "Elbow in the Door: choose a space"
    assert prompt["cost"] == "No additional action or resource cost"
    assert "choose one space adjacent to both you and the target" in prompt["rules"]
    assert "difficult terrain" in prompt["summary"]
    assert STRIKE in prompt["trigger"]
    assert prompt["choice"]["space_map"]["origin"] == {"x": 3, "y": 6}
    assert {token["id"] for token in prompt["choice"]["space_map"]["tokens"]} == {ME, FOE}
    assert all(option["description"] == "" for option in prompt["choice"]["options"])
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send()["reaction"] == prompt
    picked = prompt["choice"]["options"][0]
    assert send([{**prompt["context"], "selection": "USE", "option_ids": [picked["id"]]}])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    from combat.ext import placed
    zone, = placed.of(loaded.engine, "iron_elbow")
    assert [{"x": cell.x, "y": cell.y} for cell in zone.affected_cells] == [picked["cell"]]
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("options,space", [(["cell:4,5", "cell:5,6"], True), (["4,5", "5,6"], True),
                                          (["actor:a"], False), (["cell:4,5", "trip"], False)])
def test_generic_space_detection_uses_pause_positions_without_state_mutation(options, space):
    actor = SimpleNamespace(display_name="Chooser", active=True, position=SimpleNamespace(x=4, y=4))
    engine = SimpleNamespace(state=SimpleNamespace(actors={"a": actor}), action_catalog={},
                             typed_reaction_rows={}, typed_passive_rows={},
                             grid=SimpleNamespace(width=12, height=12, blocked={(0, 0)}))
    positions = capture_space_positions(engine, options)
    actor.position.x = 2  # table loads the rolled-back state; the chooser had moved before the pause
    service = TabletopService.__new__(TabletopService)
    service._names_for = lambda mid: ({"a": "Chooser"}, {})
    context = {"reactor_id": "a", "reaction_source_id": "choice:needle.example", "checkpoint": "example",
               "extension_choice": {"option_ids": options},
               "choice_trigger": {"name": "Example", "space_positions": positions}}
    prompt = service._reaction_prompt("match", context, engine=engine)
    assert ("space_map" in prompt["choice"]) == space
    if space:
        assert prompt["choice"]["space_map"]["origin"] == {"x": 4, "y": 4}
        assert prompt["choice"]["space_map"]["blocked"] == [{"x": 0, "y": 0}]
    assert [option["id"] for option in prompt["choice"]["options"]] == options
    assert actor.position.x == 2


def test_table_space_map_preserves_pause_footprints_and_legacy_anchors(elbow_table):
    """Exercise the table payload with real authority, then simulate action rollback."""
    import json
    combat, table, mid, send = elbow_table
    prompt = send()["reaction"]
    engine = combat._load_session(mid).engine
    engine.actor_footprints[FOE] = ActorFootprintDefinition.rectangle(
        2, 2, footprint_id="test:large", source_definition_id="test:large")
    options = [option["id"] for option in prompt["choice"]["options"]]
    context = {**prompt["context"], "extension_choice": {"option_ids": options},
               "choice_trigger": {"name": prompt["reaction"]}}
    positions = capture_space_positions(engine, options)
    engine.state.actors[FOE].position = engine.state.actors[FOE].position.model_copy(update={"x": 9})
    before = engine.state.model_dump(mode="json")
    authority_before = {key: value.model_dump(mode="json") for key, value in engine.actor_footprints.items()}
    context = {**context, "choice_trigger": {**context["choice_trigger"], "space_positions": positions}}
    updated = table._reaction_prompt(mid, context, engine=engine)
    target = next(token for token in updated["choice"]["space_map"]["tokens"] if token["id"] == FOE)
    assert target["position"] == {"x": 4, "y": 6}
    assert target["cells"] == [{"x": 4, "y": 6}, {"x": 4, "y": 7}, {"x": 5, "y": 6}, {"x": 5, "y": 7}]
    assert updated["choice"]["space_map"]["square_size_ft"] == engine.grid.square_size_ft
    assert [option["id"] for option in updated["choice"]["options"]] == options
    assert engine.state.model_dump(mode="json") == before
    assert {key: value.model_dump(mode="json") for key, value in engine.actor_footprints.items()} == authority_before
    # An older pause must remain loadable without pretending its anchor snapshot
    # recorded the footprint at that time.
    legacy = {key: {"x": value["x"], "y": value["y"]} for key, value in json.loads(positions).items()}
    context["choice_trigger"]["space_positions"] = json.dumps(legacy)
    old = table._reaction_prompt(mid, context, engine=engine)
    target = next(token for token in old["choice"]["space_map"]["tokens"] if token["id"] == FOE)
    assert target["cells"] == [target["position"]]
    context["choice_trigger"].pop("space_positions")
    current = table._reaction_prompt(mid, context, engine=engine)
    target = next(token for token in current["choice"]["space_map"]["tokens"] if token["id"] == FOE)
    assert target["cells"] == [{"x": 9, "y": 6}, {"x": 9, "y": 7}, {"x": 10, "y": 6}, {"x": 10, "y": 7}]


@pytest.mark.parametrize("free,title", [(False, "Reaction"), (True, "Example")])
def test_title_uses_compiled_reaction_economy(free, title):
    actor = SimpleNamespace(display_name="Chooser")
    engine = SimpleNamespace(state=SimpleNamespace(actors={"a": actor}), action_catalog={}, typed_passive_rows={},
        typed_reaction_rows={"a": [{"feature_id": "EXAMPLE", "name": "Example", "free": free}]})
    service = TabletopService.__new__(TabletopService)
    service._names_for = lambda mid: ({"a": "Chooser"}, {"EXAMPLE": "Example"})
    prompt = service._reaction_prompt("match", {"reactor_id": "a", "reaction_source_id": "reaction:typed.EXAMPLE",
                                             "checkpoint": "TYPED:ATTACK_DECLARED@1"}, engine=engine)
    assert prompt["title"] == title


def test_node_choice_rendering():
    subprocess.run(["node", str(Path(__file__).with_name("prompt_ui.cjs"))], check=True)


def test_ordinary_opportunity_attack_is_still_a_named_reaction():
    service = TabletopService.__new__(TabletopService)
    service._names_for = lambda mid: ({"a": "Chooser", "b": "Mover"}, {})
    prompt = service._reaction_prompt("match", {"reactor_id": "a", "attacking_actor_id": "b",
        "reaction_source_id": "system:combat.opportunity_attack", "checkpoint": "LEAVE_REACH"})
    assert prompt["title"] == "Reaction"
    assert prompt["reaction"] == "Opportunity Attack"
    assert prompt["cost"].startswith("Reaction;")


@pytest.mark.parametrize("cost,title", [("Action now; Reaction when triggered", "Example"),
                                       ("Reaction now; preparation was paid earlier", "Reaction")])
def test_title_distinguishes_current_cost_from_later_reaction_cost(cost, title):
    from combat.decision_text import build_decision_text
    context = {"reactor_id": "a", "reaction_source_id": "choice:needle.example",
               "extension_choice": {"option_ids": ["prepare"]}, "choice_trigger": {"cost": cost}}
    prompt = build_decision_text(None, context, {"reactor": "Player", "reaction": "Example", "moment": "Choose a trigger"}, {}, {}, {})
    assert prompt["title"] == title


@pytest.mark.parametrize("rules,description", [
    ("", ""),
    ("Trip: The target falls Prone; standing costs half its movement.",
     "Trip: The target falls Prone; standing costs half its movement."),
])
def test_choice_description_omits_label_fallback_but_keeps_printed_explanation(rules, description):
    """Keep fix/prompt-ui's distinct explanations while avoiding repeated labels."""
    from combat.decision_text import build_decision_text
    context = {"reactor_id": "a", "reaction_source_id": "choice:needle.example",
               "extension_choice": {"option_ids": ["trip"]},
               "choice_trigger": {"feature_id": "example"}}
    choice = {"options": [{"id": "trip", "label": "Trip"}], "allow_decline": True}
    prompt = {"reactor": "Player", "reaction": "Example", "moment": "Choose an effect",
              "choice": choice}
    result = build_decision_text(None, context, prompt, {}, {}, {"example": rules})
    assert result["choice"] == {"options": [{"id": "trip", "label": "Trip",
                                           "description": description}], "allow_decline": True}
    assert prompt["choice"] == {"options": [{"id": "trip", "label": "Trip"}], "allow_decline": True}


@pytest.mark.skipif(os.environ.get("N4_BROWSER") != "1", reason="Lead must run with N4_BROWSER=1 outside the sandbox")
def test_browser_space_picker(elbow_table):
    """Opt-in real DOM/keyboard check using production renderer and a real table pause."""
    from playwright.sync_api import sync_playwright
    prompt = elbow_table[3]()["reaction"]
    source = (ROOT / "static/tabletop/tabletop.js").read_text()
    functions = source[source.index("function decisionText("):source.index("// The Items panel")]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 480, "height": 800})
            page.set_content('<dialog id="ttReaction" aria-labelledby="ttReactionTitle"><h2 id="ttReactionTitle"></h2>'
                             '<div id="ttReactionText"></div><button data-answer="USE">Use</button>'
                             '<button data-answer="DECLINE">Pass</button></dialog>')
            page.add_style_tag(path=str(ROOT / "static/tabletop/tabletop.css"))
            page.add_script_tag(content='const $ = s => document.querySelector(s); const toast = () => {}; '
                'const escapeHtml = v => String(v || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(\'"\', "&quot;");\n' + functions)
            page.evaluate("p => { window.answer = null; askReaction(p).then(a => window.answer = a); }", prompt)
            assert page.locator("#ttReactionTitle").inner_text() == prompt["title"]
            assert page.locator(".tt-space:disabled").count() > 0
            page.locator(".tt-space.is-legal").first.click()
            page.wait_for_function("window.answer !== null")
            expected = {"selection": "USE", "option_ids": [prompt["choice"]["options"][0]["id"]]}
            # Grid order is row-major; legal IDs in the pause need not be row-major.
            assert page.evaluate("window.answer.selection") == "USE"
            assert page.evaluate("window.answer.option_ids[0]") in [o["id"] for o in prompt["choice"]["options"]]
            page.evaluate("p => { window.answer = null; askReaction(p).then(a => window.answer = a); }", prompt)
            page.locator(".tt-choice-list button").first.focus()
            page.keyboard.press("Enter")
            page.wait_for_function("window.answer !== null")
            assert page.evaluate("window.answer") == expected
            # Lead-only layout/keyboard check for a creature occupying several squares.
            large_prompt = {**prompt, "choice": {**prompt["choice"], "space_map": {
                "origin": {"x": 3, "y": 6}, "chooser_id": "me", "width": 12, "height": 12,
                "square_size_ft": 5, "blocked": [], "tokens": [
                    {"id": "me", "name": "Chooser", "position": {"x": 3, "y": 6}},
                    {"id": "foe", "name": "Large Spirit", "position": {"x": 4, "y": 6},
                     "cells": [{"x": x, "y": y} for x in (4, 5) for y in (6, 7)]}],
            }, "options": [{"id": "cell:6,7", "label": "cell:6,7", "cell": {"x": 6, "y": 7}}]}}
            page.evaluate("p => { window.answer = null; askReaction(p).then(a => window.answer = a); }", large_prompt)
            assert page.locator(".tt-space", has_text="LS").count() == 4
            assert "beside Large Spirit" in page.locator(".tt-choice-list button").inner_text()
            assert page.locator("#ttReaction").evaluate("d => d.getBoundingClientRect().width <= window.innerWidth")
            page.locator(".tt-space.is-legal").focus()
            page.keyboard.press("Enter")
            page.wait_for_function("window.answer !== null")
            assert page.evaluate("window.answer") == {"selection": "USE", "option_ids": ["cell:6,7"]}
        finally:
            browser.close()
