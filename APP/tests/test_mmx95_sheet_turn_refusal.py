"""MMX95: the pop-out sheet was told "It is not <name>'s turn to act." for an action the table would
have accepted (owner playtest 2026-10-03 23:01, live round 24, 42e43e14).

These service tests check the unchanged server contract, separately from client regressions:

  1. An ordinary legal action commits, and repeating its obsolete decision is refused as stale.
     This does not create a client placement or exercise multiple windows.
  2. Every refusal states its real cause. TABLETOP_STALE, TABLETOP_PENDING and TABLETOP_NOT_YOUR_TURN
     are three different problems and each says so.

MMX95f1 review fix. The review found the augment half of the claim below was unsupported, and these
tests now check the real thing. combat/tabletop.py _augment_button() emits ``augment: True`` and NO
``shape``, so an augment never matched the client's ``if (button.shape && button.variant_of)`` branch;
it goes down the ordinary action path, where its own free toggle candidate is submitted. The claim
that augment clicks "committed nothing" was wrong: the dead lookup MMX95 added could not have run.
What is real is that a client's augment press submits exactly one toggle candidate, in both
directions, so ``test_the_real_augment_toggle_turns_it_on_and_off`` drives the engine and the
fixture-drift test keeps the JavaScript regression honest about the payload it is handed.

The client-side half of the bug (an answered choice staying open) has no server state to assert on;
it is covered at the level it showed, in APP/tests/tabletop_sheet_turn_refusal.test.mjs.
"""

import json

import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopError, TabletopService
from tests.test_factory_live_match import _install, ROOT


def table_match(tmp_path):
    for side in ("left", "right"):
        _install(tmp_path, side)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "MMX95 yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    modes = {FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("left", "right")}
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"],
        control_modes=modes, match_seed="MMX95-TABLE")
    return combat, TabletopService(combat, tmp_path), view["match_id"]


def first_action(table, mid):
    """The menu's first non-move action group, as a client would read it."""
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["options"])
    return state, menu, group


# ---------------------------------------------------------------- unchanged server decision contract

def test_a_legal_service_action_commits_and_its_old_decision_is_stale(tmp_path):
    """Unchanged server contract; no client placement or second window is created here."""
    combat, table, mid = table_match(tmp_path)
    state, menu, group = first_action(table, mid)

    candidates = {option["candidate_id"] for option in group["options"]}
    assert candidates, "the action group offers legal candidates"

    # Submit an ordinary candidate from the current service menu.
    result = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"])
    assert result["status"] == "COMMITTED"

    # And the table afterwards agrees the fight moved on -- so a refusal on the NEXT request is
    # stale-state, not a turn.
    state2 = table.state(mid)
    assert state2["menu"]["decision_id"] != menu["decision_id"]
    with pytest.raises(TabletopError) as stale:
        table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                  state2["last_sequence"])
    assert stale.value.code == "TABLETOP_STALE"


def test_a_window_that_is_behind_is_told_the_table_moved_on_not_that_the_turn_ended(tmp_path):
    """What the browser said instead: "It is not Tabik Damu's turn to act." for a fighter mid-turn."""
    combat, table, mid = table_match(tmp_path)
    state, menu, group = first_action(table, mid)
    table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
              state["last_sequence"])

    # A second window still holds the decision it read before that commit.
    with pytest.raises(TabletopError) as refused:
        table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                  state["last_sequence"])
    assert refused.value.code == "TABLETOP_STALE"
    message = str(refused.value)
    assert "moved on" in message, message
    for wrong in ("turn to act", "not your turn", "turn to move"):
        assert wrong not in message, f"a stale window must not be told about turns: {message!r}"


def test_the_same_fighter_may_act_again_on_the_same_turn(tmp_path):
    """The guard that was mislabelled: it is the same turn, so the second action is simply legal."""
    combat, table, mid = table_match(tmp_path)
    state, menu, group = first_action(table, mid)
    table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
              state["last_sequence"])
    state2, menu2, group2 = first_action(table, mid)
    assert menu2["actor_id"] == menu["actor_id"], "the fighter did not lose the turn by acting"
    result = table.act(mid, group2["options"][0]["candidate_id"], menu2["decision_id"], menu2["state_version"],
                       state2["last_sequence"])
    assert result["status"] == "COMMITTED"


# ---------------------------------------------------------------- every refusal names its real cause

def test_a_saved_question_is_reported_as_a_question_not_as_a_turn(tmp_path):
    """A pending Ask-me choice is a saved question; a different action says so, in those words."""
    combat, table, mid = table_match(tmp_path)
    state, menu, _ = first_action(table, mid)
    table._save_pending_action(mid, {"schema": "TabletopPendingAction.v2", "method": "act",
        "request": {"candidate_id": menu["actions"][0]["options"][0]["candidate_id"],
                    "decision_id": menu["decision_id"], "state_version": menu["state_version"], "after": 0},
        "reactions": [], "reaction": {"reaction": "Something", "context": {"reactor_id": menu["actor_id"]}}})

    group = next(g for g in menu["actions"] if g["options"])
    with pytest.raises(TabletopError) as pending:
        table.act(mid, "a-different-candidate", menu["decision_id"], menu["state_version"], 0)
    assert pending.value.code == "TABLETOP_PENDING"
    message = str(pending.value)
    assert "choice" in message or "question" in message, message
    assert "turn" not in message.lower(), f"a saved question is not a turn: {message!r}"


def test_an_ai_controlled_fighter_is_the_only_thing_reported_as_a_turn(tmp_path):
    combat, table, mid = table_match(tmp_path)
    state = table.state(mid)
    menu = state["menu"]
    actor = menu["actor_id"]
    group = next(g for g in menu["actions"] if g["options"])
    combat._load_session(mid)  # a readable session before the mode flips
    table.combat.set_controller_mode(mid, actor_id=actor, controller_mode="API_AUTO")

    with pytest.raises(TabletopError) as refused:
        table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                  state["last_sequence"])
    assert refused.value.code == "TABLETOP_NOT_YOUR_TURN"
    assert "AI" in str(refused.value), str(refused.value)


def test_the_four_refusals_are_four_different_sentences(tmp_path):
    """A refusal the player cannot act on is the bug. Each cause must be distinguishable."""
    combat, table, mid = table_match(tmp_path)
    state, menu, group = first_action(table, mid)
    seen = set()

    with pytest.raises(TabletopError) as illegal:
        table.act(mid, "no-such-candidate", menu["decision_id"], menu["state_version"], 0)
    assert illegal.value.code == "TABLETOP_STALE"
    seen.add(str(illegal.value))

    with pytest.raises(TabletopError) as stale:
        table.act(mid, group["options"][0]["candidate_id"], "an-old-decision", menu["state_version"], 0)
    assert stale.value.code == "TABLETOP_STALE"
    seen.add(str(stale.value))

    # A saved Ask-me question is in play; a different action is the third distinct refusal.
    table._save_pending_action(mid, {"schema": "TabletopPendingAction.v2", "method": "act",
        "request": {"candidate_id": "the-question-this-window-is-answering",
                    "decision_id": menu["decision_id"], "state_version": menu["state_version"], "after": 0},
        "reactions": [], "reaction": {"reaction": "Something", "context": {"reactor_id": menu["actor_id"]}}})
    with pytest.raises(TabletopError) as pending:
        table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], 0)
    assert pending.value.code == "TABLETOP_PENDING"
    seen.add(str(pending.value))

    actor = menu["actor_id"]
    table.combat.set_controller_mode(mid, actor_id=actor, controller_mode="API_AUTO")
    with pytest.raises(TabletopError) as ai:
        table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"], 0)
    assert ai.value.code == "TABLETOP_NOT_YOUR_TURN"
    seen.add(str(ai.value))

    assert len(seen) == 4, f"each cause says something different: {seen}"


# ---------------------------------------------------------------- the shape data the sheet relies on

def test_shaped_abilities_publish_talents_and_augments_in_separate_lists():
    """combat/zones.py _shaped is the contract the sheet path depends on: talent choices in
    "options", augment toggles in "augments", each carrying the button id the sheet sends back.

    Driven on the owner's own Darkness, so the contract is checked against real compiled data."""
    from tests.test_auto_tabik import _engine

    engine, _ = _engine(["TAL_DARK_CLINGING_DARKNESS", "TAL_DARK_ETERNAL_DARKNESS",
                         "TAL_DARK_NUMBING_DARKNESS"])
    relevant = [action for action in engine.action_catalog.values()
                if (action.parameters or {}).get("zone_shape") or (action.parameters or {}).get("augment_toggle")]
    assert relevant, "Tabik's Darkness has shaping choices and augment toggles"

    menu = {"actor_id": "actor:factory.tabik", "manual": True,
            "actions": [{"source_definition_id": action.source_definition_id, "options": [{"candidate_id": "c"}]}
                        for action in relevant]}
    shapes = TabletopService._shapes(menu, engine)
    entries = [entry for rows in shapes.values() for entry in rows]
    assert entries, "the fight publishes a shape entry for the Darkness"

    for entry in entries:
        for talent in entry["options"]:
            assert talent["button_id"] and talent["button_id"].startswith("act:"), talent
            assert "talents" in talent, talent
        for augment in entry["augments"]:
            assert augment["button_id"] and augment["button_id"].startswith("act:"), augment
            assert "on" in augment, augment
        assert [row["button_id"] for row in entry["options"]] != [row["button_id"] for row in entry["augments"]]

    clinging = [row for entry in entries for row in entry["augments"] if row["name"] == "Clinging Darkness"]
    assert clinging, "Clinging Darkness is published as an augment toggle, not as a talent"
    assert clinging[0]["candidate_id"], "and it carries the free candidate that toggles it"


# ---------------------------------------------------------------- the augment, with production's own payload

def _toggle_action(engine, needle):
    return next(action for action in engine.action_catalog.values()
                if (action.parameters or {}).get("augment_toggle")
                and (action.parameters or {}).get("augment_key")
                and needle in json.dumps(action.parameters, default=str).upper())


def test_an_augment_sheet_button_carries_no_shape_so_the_talent_path_cannot_claim_it():
    """The fact MMX95's test got wrong. _augment_button() marks the row ``augment: True`` and sends
    no ``shape`` at all, so the client's ``if (button.shape && button.variant_of)`` branch is
    unreachable for an augment and the augment lookup MMX95 added inside it could never have run.

    This is why the old claim -- that augment clicks "committed nothing" -- was unsupported: they
    were already going down the ordinary action path."""
    from combat import tabletop as tt
    from tests.test_auto_tabik import _engine

    engine, _ = _engine(["TAL_DARK_CLINGING_DARKNESS", "TAL_DARK_ETERNAL_DARKNESS",
                         "TAL_DARK_NUMBING_DARKNESS"])
    toggle = _toggle_action(engine, "CLINGING")
    button = tt._augment_button(
        {"source_definition_id": toggle.source_definition_id, "display_name": toggle.display_name,
         "parameters": toggle.parameters},
        {toggle.parameters["augment_toggle"]: (toggle.parameters.get("augment_loadout") or {})})

    assert button["augment"] is True
    assert "shape" not in button, "an augment is not a shaped area, so it must not claim the talent path"
    assert button["variant_of"] == "act:" + toggle.parameters["augment_toggle"]
    assert button["combat"]["source_definition_id"] == toggle.source_definition_id
    assert button["tags"] == ["augment"]


def test_a_talent_sheet_button_does_carry_a_shape_so_the_two_paths_stay_separate():
    from combat import tabletop as tt
    from tests.test_auto_tabik import _engine

    engine, _ = _engine(["TAL_DARK_CLINGING_DARKNESS", "TAL_DARK_NUMBING_DARKNESS"])
    talent = next(action for action in engine.action_catalog.values() if (action.parameters or {}).get("zone_shape"))
    button = tt._shape_button({"source_definition_id": talent.source_definition_id,
                               "display_name": talent.display_name, "parameters": talent.parameters})
    assert "shape" in button and button["shape"]["talents"]
    assert "augment" not in button


def test_the_real_augment_toggle_turns_it_on_and_off():
    """What a sheet press actually submits, in both directions, on the real engine: the augment's own
    free toggle candidate. The sheet advertises "turn on or off" (sheet.js:480), so a press is a
    toggle and nothing else -- no cast, and no second press of the ability it augments."""
    from combat import loadout
    from combat.gate2_runtime_models import ActionIntent
    from tests.test_auto_tabik import _engine, ME

    engine, _ = _engine(["TAL_DARK_CLINGING_DARKNESS"])
    toggle = _toggle_action(engine, "CLINGING")
    family = toggle.parameters["augment_toggle"]
    key = toggle.parameters["augment_key"]
    actor = engine.state.actors[ME]
    assert loadout.chosen(actor, family) in (None, []), "nothing is on to begin with"

    def press():
        candidate = next(c for c in engine.legal_candidates()
                         if c.source_definition_id == toggle.source_definition_id and c.actor_id == ME)
        assert candidate.candidate_id, "the toggle offers a free candidate"
        assert candidate.kind == "BONUS_ACTION", candidate.kind
        engine.execute_intent(ActionIntent(
            intent_id=f"augment-{engine.state.event_sequence}", decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=ME, target_ids=list(candidate.target_ids), destination=candidate.destination))
        return loadout.chosen(actor, family)

    assert press() == [key], "the first press turns it on"
    assert press() == [], "the second press turns it off"
    assert press() == [key], "and it can be turned on again"


def test_the_javascript_augment_fixture_is_generated_from_production():
    """The JS regression must be handed the payload production really sends, or it drifts back into
    testing an invented one -- which is exactly how MMX95's augment tests passed against a branch no
    real augment could reach. Regenerating the fixture from the live builders fails on any drift."""
    from tests._mmx95f1_make_fixture import build, OUT

    committed = json.loads(OUT.read_text())
    fresh = build()
    assert committed == fresh, (
        "tests/fixtures/mmx95f1_augment_payload.json is stale; "
        f"regenerate it with: python {OUT.relative_to(OUT.parents[3])}")
    # And the fact the client path depends on, straight from the committed fixture.
    assert "shape" not in committed["augment_clinging"]
    assert committed["augment_clinging"]["augment"] is True
    assert committed["menu_group_clinging_option_count"] == 1, (
        "the ordinary action path submits the toggle directly because the group has one option")
