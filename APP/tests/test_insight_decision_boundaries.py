"""PRO13r2f1: the Insight decision boundaries the first review round did not reach.

``test_auto_insight_families`` covers what each Insight *does*; this file covers where
it *decides*, through the real service and the real engine:

* Hook Master's consent. The optional pull is asked as its own named question at the
  moment its host ability's Strength save fails, answering it moves the target 5 feet
  toward the holder, declining it moves nothing, and the saved fight reloads with the
  answer already applied.
* Scope: a fighter without the Insight is never asked, and gets no boundary row.
* The same question when the fighter who owns the Insight is the AI. The AI answers
  for itself -- nothing reaches the player -- and its answer is recorded on the saved
  intent as its own decision (change standard 9).
* The same question while the *rival* is the AI: the owner is still asked, because a
  player-owned fighter is asked on an AI's turn too.
* Iron Shirt's paid Reaction on an AI owner, so "the AI decides" is shown for a
  Reaction and not only for a choice.

No injected effect and no monkeypatched rule: every fixture is the shipped reviewed
record read through the real compiled bundle, the real table transport and the real
engine. A fixture supplies only the incoming stimulus -- a creature that moves far
enough to trigger the hook, or one that is shoved.
"""

from __future__ import annotations

import copy
import json
import zipfile
from typing import Any

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_factory_live_match import ROOT

OWNER_PROJECT = "aaaaaaaa"
CONTROL_PROJECT = "bbbbbbbb"
OWNER = FACTORY_ACTOR_PREFIX + OWNER_PROJECT
CONTROL = FACTORY_ACTOR_PREFIX + CONTROL_PROJECT
OWNER_NAME = "Insight Owner"
CONTROL_NAME = "Table Rival"
HOOK_MASTER = "insight.hook-master"
IRON_SHIRT = "insight.legacy-iron-shirt"
RESTRAINING_HOOK = "tianxia.talent.chains.restraining_hook"
STAMINA = "resource:core.stamina"
HOOK = f"reaction:typed.{RESTRAINING_HOOK}"
OPPORTUNITY = "reaction:typed.opportunity_attack"
PULL_CHOICE = "choice:needle.hook_master_pull"


def _sheet(insights: tuple[str, ...] = (), *, name: str = OWNER_NAME, hopeless_saves: bool = False,
           attack_bonus: int | None = None, spheres: tuple[str, ...] = (),
           talents: tuple[str, ...] = ()) -> dict[str, Any]:
    """The shared compiler fixture. Finalized statistics stay identical to the other
    Insight modules; only ownership, spheres, talents and the rival's numbers differ.

    ``hopeless_saves`` fails every saving throw and ``attack_bonus`` raises the printed
    attack bonus, so an attack that only *reaches* the response under test is reached every
    time instead of depending on the dice.
    """
    sheet = copy.deepcopy(SHEET)
    sheet["spheres_and_talents"] = {
        "sphere_record_ids": list(spheres),
        "learned_talent_record_ids": list(talents),
        "automatic_sphere_component_record_ids": [],
        "cultivation_insight_record_ids": list(insights),
    }
    sheet["equipment"] = []
    sheet["identity"]["display_name"] = name
    numbers = dict(sheet["ability_scores_and_statistics"])
    if hopeless_saves:
        numbers["saving_throws"] = {ability: -20 for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    if attack_bonus is not None:
        numbers["technique_attack_bonus"] = attack_bonus
    sheet["ability_scores_and_statistics"] = numbers
    return sheet


def _match(tmp_path, owner: dict[str, Any], control: dict[str, Any], *, seed: str,
           rival_at: tuple[int, int] = (4, 4)) -> tuple[CombatService, TabletopService, str]:
    """Two real fighters on one saved map: the owner at (3,4) and the rival where asked.

    The default rival square is adjacent on purpose. Restraining Hook's printed trigger
    is a creature within its range moving more than 10 feet, and a rival that starts
    inside the owner's reach triggers the hook on leaving it. A rival that starts two
    squares away never enters the reach, so no Opportunity Attack competes for the same
    Reaction -- that is the geometry the AI-owner tests use, so the AI's own decision is
    the only one the question can be about.
    """
    for project, sheet in ((OWNER_PROJECT, owner), (CONTROL_PROJECT, control)):
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.save_reactions(OWNER_PROJECT, {"mode": "ask"})
    combat.tabletop_maps.save({"display_name": "Consent yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [list(rival_at)]}})
    mid = combat.create_factory_match(
        project_ids=[OWNER_PROJECT], opponent_actor_ids=[CONTROL],
        control_modes={OWNER: "MANUAL", CONTROL: "MANUAL"},
        arena_id="battlefield:map.consent-yard", match_seed=seed)["match_id"]
    return combat, table, mid


def _hook_match(tmp_path, *, insights: tuple[str, ...], seed: str,
                rival_at: tuple[int, int] = (4, 4)):
    """The Hook Master setup. The rival owns nothing: it is the creature the hook catches,
    and its Strength saving throw is hopeless, so the printed failed-save branch runs
    without faking a roll."""
    return _match(tmp_path,
                  _sheet(insights, spheres=("tianxia.sphere.chains",), talents=(RESTRAINING_HOOK,)),
                  _sheet(name=CONTROL_NAME, hopeless_saves=True),
                  seed=seed, rival_at=rival_at)


def _manual_turn(table, mid, who: str, limit: int = 8) -> dict[str, Any]:
    """Step the fight until ``who`` is the manual fighter to move, and return its menu.

    Initiative is rolled per fight, so a test must reach its own turn from wherever it
    starts: an AI turn is stepped for the AI, and a manual turn is simply ended. Nothing
    here plays a turn of the fighter under test.
    """
    for _ in range(limit):
        state = table.state(mid)
        if state["menu"]["actor_id"] == who and state["menu"]["manual"]:
            return state
        if state["menu"]["manual"]:
            table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
                      state["menu"]["state_version"], state["last_sequence"], [])
        else:
            table.auto_step(mid, 0, [])
    state = table.state(mid)
    assert state["menu"]["actor_id"] == who, state["menu"]["actor_id"]
    return state


def _move_to(table, mid, destination: dict[str, Any], cost_ft: int) -> str:
    """The one menu move that sends the rival exactly where this test needs it."""
    menu = table.state(mid)["menu"]
    for move in menu["moves"]:
        if move["cost_ft"] == cost_ft and all(move["destination"].get(key) == value
                                               for key, value in destination.items()):
            return move["candidate_id"]
    raise AssertionError(f"no {cost_ft}ft move to {destination}")


def _run_away_candidate(candidates, holder, *, from_menu: bool, whole_path: bool = False) -> str:
    """The candidate for a run of 15 feet or more that stays two squares from the holder.

    Two squares is what makes the printed 5-foot pull visible: it moves the target one
    square closer. Starting two squares out also keeps the run out of the holder's reach,
    so no Opportunity Attack competes for the same Reaction and the question is only ever
    about Hook Master. Which square it ends on depends on where the fight's initiative and
    speed put the pair, so the run is chosen by shape rather than named.

    ``candidates`` is the page's menu moves (``from_menu``) or the AI's own legal
    candidates; the AI sees a slightly different set, so each side is asked for its own.
    """
    rows = [{"destination": row["destination"], "cost_ft": row["cost_ft"], "path": row["path"],
             "candidate_id": row["candidate_id"]}
            for row in candidates] if from_menu else [
        {"destination": {"x": candidate.destination.x, "y": candidate.destination.y},
         "cost_ft": candidate.movement_cost_ft,
         "path": [{"x": step.x, "y": step.y} for step in (candidate.canonical_path or [])],
         "candidate_id": candidate.candidate_id}
        for candidate in candidates if candidate.destination is not None]

    def away(point: dict[str, Any]) -> int:
        return max(abs(point["x"] - holder[0]), abs(point["y"] - holder[1]))

    for row in sorted(rows, key=lambda item: (item["cost_ft"], item["destination"]["x"], item["destination"]["y"])):
        # Starting two squares out is what keeps an Opportunity Attack out of it: that
        # attack is a Reaction on a creature that leaves the holder's reach, and a run that
        # never began inside it cannot be leaving it.
        if (row["cost_ft"] or 0) >= 15 and away(row["destination"]) == 2 and row["path"] \
                and away(row["path"][0]) == 2 and (not whole_path or all(away(step) == 2 for step in row["path"])):
            return row["candidate_id"]
    raise AssertionError(f"no 15ft run to two squares from the holder at {holder}")


def _run_away_move(table, mid, holder: str, seed: str) -> str:
    """The same run, read from the page's menu while the rival is still a player."""
    return _run_away_candidate(table.state(mid)["menu"]["moves"], _position(table.combat, mid, holder),
                               from_menu=True, whole_path=True)


def _run(table, mid, cid: str, first_state: dict[str, Any], decide, limit: int = 8):
    """Run one table action the way the page does, answering each question as it is raised.

    ``decide(source, prompt)`` returns the answer body for a prompt, or None to decline
    it. Returns the final result and every prompt seen, so a test can assert both what
    was asked and what was done.
    """
    answers: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    state = first_state
    for _ in range(limit):
        result = table.act(mid, cid, state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result["status"]
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        source = str(prompt["context"].get("reaction_source_id") or "")
        answer = decide(source, prompt)
        if answer is not None:
            answers.append({**prompt["context"], **answer})
        else:
            answers.append({**prompt["context"], "selection": "DECLINE"})
        state = result["state"]
    raise AssertionError("too many prompts")


def _reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded


def _position(combat, mid: str, actor_id: str) -> tuple[int, int]:
    place = combat._load_session(mid).engine.state.actors[actor_id].position
    return (place.x, place.y)


def _payloads(engine, event_type: str, source: str) -> list[dict[str, Any]]:
    return [event.payload for event in engine.events
            if event.event_type == event_type and event.source_definition_id == source]


def _pulls(engine) -> list[dict[str, Any]]:
    """The Hook Master's own 5-foot pulls: forced moves of one square on the hook's source."""
    return [payload for payload in _payloads(engine, "MOVEMENT_COMMITTED", RESTRAINING_HOOK)
            if payload.get("forced") and len(payload.get("path") or []) == 2]


def _assert_pull_prompt_names_the_decision(prompt: dict[str, Any]) -> None:
    """Change standard 9: the question names the ability, the triggering action and the creature."""
    assert prompt["context"]["reaction_source_id"] == PULL_CHOICE, prompt["context"]
    assert prompt["reaction"] == "Hook Master: pull the target 5 feet", prompt["reaction"]
    assert prompt["reactor"] == OWNER_NAME, prompt["reactor"]
    assert prompt["context"]["reactor_id"] == OWNER, prompt["context"]
    # The triggering action and the creature it lands on are both named on the prompt.
    assert prompt["action"] == "Restraining Hook", prompt["action"]
    assert prompt["affected"] == CONTROL_NAME, prompt["affected"]
    assert prompt["cost"] == "1 Stamina", prompt["cost"]  # the hook this choice rides, priced
    choices = prompt["choice"]
    assert [option["id"] for option in choices["options"]] == ["pull"], choices
    assert choices["allow_decline"] is True, choices  # consent is the printed "you may"
    # The question says what it is, who it happens to and that it costs nothing extra;
    # the printed rules of the ability it rides come along beside it.
    assert prompt["trigger"] == ("Restraining Hook: Hook Master: pull the target 5 feet for Table Rival. "
                                 "Choose 1 effect. No extra cost. — Insight Owner uses Restraining Hook on "
                                 "Table Rival."), prompt["trigger"]
    assert "Strength saving throw" in prompt["summary"], prompt["summary"]


# The holder stands at (3,4). The rival's 20-foot run to (1,4) ends 10 feet away, inside
# the hook's printed range and outside the holder's 5-foot reach, so accepting the pull
# is visible as a one-square move from (1,4) to (2,4) -- five feet toward the holder.
_RUN_DESTINATION = {"x": 1, "y": 4}
_RUN_COST = 20


def _use_hook_and(source: str, prompt: dict[str, Any]) -> dict[str, Any] | None:
    """Use Restraining Hook itself, and answer nothing else."""
    return {"selection": "USE"} if source == HOOK else None


def test_hook_master_asks_before_pulling_and_the_accepted_pull_moves_the_target_five_feet(tmp_path):
    """The whole consent path: the owner is asked by name, the accepted pull moves the
    target 5 feet toward them, and the saved fight reloads with that applied."""
    combat, table, mid = _hook_match(tmp_path, insights=(HOOK_MASTER,), seed="PRO13R2F1-HOOK-TAKE")
    state = _manual_turn(table, mid, CONTROL)
    cid = _move_to(table, mid, _RUN_DESTINATION, _RUN_COST)
    result, prompts = _run(table, mid, cid, state,
                           lambda source, prompt: {"selection": "USE", "option_ids": ["pull"]}
                           if source == PULL_CHOICE else _use_hook_and(source, prompt))
    assert result["status"] == "COMMITTED"
    asked = [prompt for prompt in prompts if prompt["context"].get("reaction_source_id") == PULL_CHOICE]
    assert len(asked) == 1, [prompt["context"].get("reaction_source_id") for prompt in prompts]
    _assert_pull_prompt_names_the_decision(asked[0])
    # The hook was paid for and its save failed; the pull then moved the target 5 feet.
    engine = _reload(tmp_path, mid).engine
    assert _payloads(engine, "RESOURCE_SPENT", RESTRAINING_HOOK)
    saves = _payloads(engine, "SAVE_ROLLED", RESTRAINING_HOOK)
    assert saves and saves[0]["success"] is False, saves
    pulls = _pulls(engine)
    assert len(pulls) == 1, pulls
    assert pulls[0]["path"] == [{"x": 1, "y": 4}, {"x": 2, "y": 4}], pulls[0]
    actor = engine.state.actors[CONTROL]
    assert (actor.position.x, actor.position.y) == (2, 4)
    # The printed pull moves the target; it does not restrain it, and it costs no extra.
    assert not [condition for condition in actor.conditions.values()
                if condition.condition_id == "condition:typed.restrained"]
    assert engine.state.actors[OWNER].resources[STAMINA] == 39  # only the hook's own 1 Stamina


def test_declining_the_pull_leaves_the_target_where_the_run_put_it(tmp_path):
    """The same trigger with the choice refused: the hook still lands, the pull does not."""
    combat, table, mid = _hook_match(tmp_path, insights=(HOOK_MASTER,), seed="PRO13R2F1-HOOK-DECLINE")
    state = _manual_turn(table, mid, CONTROL)
    cid = _move_to(table, mid, _RUN_DESTINATION, _RUN_COST)
    _result, prompts = _run(table, mid, cid, state, _use_hook_and)
    assert [prompt["context"].get("reaction_source_id") for prompt in prompts].count(PULL_CHOICE) == 1, prompts
    engine = _reload(tmp_path, mid).engine
    assert _payloads(engine, "SAVE_ROLLED", RESTRAINING_HOOK), "the hook still ran"
    assert _pulls(engine) == [], "declining the pull must not move the target"
    actor = engine.state.actors[CONTROL]
    assert (actor.position.x, actor.position.y) == (1, 4)
    assert engine.state.actors[OWNER].resources[STAMINA] == 39  # the hook was paid for; the pull was free


def test_a_fighter_without_the_insight_is_never_asked_about_the_pull(tmp_path):
    """Scope: the optional pull belongs to the holder. Nobody else gets the question, no
    boundary row, and the hook without the Insight is unchanged at the table."""
    from combat.gate3_storage import load_typed_bundles

    combat, table, mid = _hook_match(tmp_path, insights=(), seed="PRO13R2F1-HOOK-NONE")
    bundles = {bundle["actor_id"]: bundle for bundle in load_typed_bundles(combat._match_dir(mid))}
    assert all(row["id"] != HOOK_MASTER for row in bundles[OWNER]["modifiers"]), bundles[OWNER]["modifiers"]
    assert all(row["id"] != HOOK_MASTER for row in bundles[CONTROL]["modifiers"])
    # A character that owns no Insight has no boundary block at all, so none of it can
    # reach a sheet (checklist 3: nothing global changes for other characters).
    assert "insights" not in bundles[OWNER]["diagnostics"], bundles[OWNER]["diagnostics"]
    state = _manual_turn(table, mid, CONTROL)
    cid = _move_to(table, mid, _RUN_DESTINATION, _RUN_COST)
    _result, prompts = _run(table, mid, cid, state, _use_hook_and)
    assert not [prompt for prompt in prompts
                if prompt["context"].get("reaction_source_id") == PULL_CHOICE], prompts
    engine = _reload(tmp_path, mid).engine
    assert _payloads(engine, "SAVE_ROLLED", RESTRAINING_HOOK), "the hook's own rule is unaffected"
    assert _pulls(engine) == []
    actor = engine.state.actors[CONTROL]
    assert (actor.position.x, actor.position.y) == (1, 4)


def _end_own_turn(table, mid, who: str) -> None:
    """Let ``who`` end its own opening turn by hand, so an AI owner never picks its own move."""
    state = _manual_turn(table, mid, who)
    assert table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"], [])["status"] == "COMMITTED"


def _one_square_closer(path: list[dict[str, Any]], holder: tuple[int, int]) -> bool:
    """The printed 5-foot pull, checked as the printed rule: one square, toward the holder."""
    assert len(path) == 2, path  # 5 feet is one square
    start, end = path[0], path[-1]
    before = max(abs(start["x"] - holder[0]), abs(start["y"] - holder[1]))
    after = max(abs(end["x"] - holder[0]), abs(end["y"] - holder[1]))
    return after == before - 1, before, after


def test_the_ai_owner_answers_the_pull_itself_and_the_player_is_never_asked(tmp_path):
    """Change standard 9: an AI actor decides for itself. Nothing reaches the player, the
    AI used its own paid hook, and its answer to the pull is saved on the intent as its
    own decision with the printed 5-foot pull applied."""
    combat, table, mid = _hook_match(tmp_path, insights=(HOOK_MASTER,), seed="PRO13R2F1-HOOK-AI",
                                     rival_at=(5, 4))
    _end_own_turn(table, mid, OWNER)
    holder = _position(combat, mid, OWNER)
    # The run is read while the rival is still a player, because an AI turn's menu is not
    # sent to the page; only then does the owner become the AI.
    cid = _run_away_move(table, mid, OWNER, "PRO13R2F1-HOOK-AI")
    state = table.state(mid)
    assert state["menu"]["actor_id"] == CONTROL, state["menu"]["actor_id"]
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    result, prompts = _run(table, mid, cid, state, lambda source, prompt: None)
    assert result["status"] == "COMMITTED"
    assert prompts == [], prompts  # an AI fighter is asked nothing
    engine = _reload(tmp_path, mid).engine
    # The AI used the hook (its own 1 Stamina) and its Strength save failed.
    assert _payloads(engine, "RESOURCE_SPENT", RESTRAINING_HOOK), "the AI did not use its own hook"
    saves = _payloads(engine, "SAVE_ROLLED", RESTRAINING_HOOK)
    assert saves and saves[0]["success"] is False, saves
    # Its answer to the pull is the AI's own saved decision, and the pull happened.
    decisions = _saved_reaction_decisions(combat, mid, PULL_CHOICE)
    assert decisions, "the AI answered the pull question and the answer was not saved"
    assert all(row["reactor_id"] == OWNER for row in decisions), decisions
    assert all(row["selection"] == "USE" and row["option_ids"] == ["pull"] for row in decisions), decisions
    pulls = _pulls(engine)
    assert len(pulls) == 1, pulls
    printed, before, after = _one_square_closer(pulls[0]["path"], holder)
    assert printed, f"the printed pull moved the target from {before} squares away to {after}"
    assert _position(combat, mid, CONTROL) == (pulls[0]["path"][-1]["x"], pulls[0]["path"][-1]["y"])
    assert engine.state.actors[OWNER].resources[STAMINA] == 39


def test_a_player_owner_is_still_asked_when_the_ai_fights_the_other_side(tmp_path):
    """The same boundary from the other side: the AI fighter's own run raises the owner's
    question, and the owner is asked even though the rival is the AI.

    The AI's move is forced to one specific run (the same trick ``tests.r1i_service_support``
    uses) so the stimulus is identical to the player-versus-player tests; the question the
    run raises still goes to the owner, because the owner is a player.
    """
    from tests.r1i_service_support import force_ai_candidate

    combat, table, mid = _hook_match(tmp_path, insights=(HOOK_MASTER,), seed="PRO13R2F1-HOOK-MIXED",
                                     rival_at=(5, 4))
    _end_own_turn(table, mid, OWNER)
    holder = _position(combat, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=CONTROL, controller_mode="LOCAL_AUTO")
    # The run is forced from the AI's own legal candidates: an AI turn's menu is not sent
    # to the page, and its candidate set is not identical to the player's.
    session = combat._load_session(mid)
    policy, _ = combat.policies.for_actor(CONTROL)
    from combat.gate4_context import build_decision_context

    context = build_decision_context(session.engine, policy, for_ai=True)
    cid = _run_away_candidate(context.legal_candidates, holder, from_menu=False)
    force_ai_candidate(combat, mid, CONTROL, cid)
    answers: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    for _ in range(8):
        result = table.auto_step(mid, 0, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result["status"]
            break
        prompt = result["reaction"]
        prompts.append(prompt)
        source = str(prompt["context"].get("reaction_source_id") or "")
        if source == PULL_CHOICE:
            answers.append({**prompt["context"], "selection": "USE", "option_ids": ["pull"]})
        elif source == HOOK:
            answers.append({**prompt["context"], "selection": "USE"})
        else:
            answers.append({**prompt["context"], "selection": "DECLINE"})
    else:
        raise AssertionError("too many prompts")
    asked = [prompt for prompt in prompts if prompt["context"].get("reaction_source_id") == PULL_CHOICE]
    assert len(asked) == 1, [prompt["context"].get("reaction_source_id") for prompt in prompts]
    _assert_pull_prompt_names_the_decision(asked[0])
    engine = _reload(tmp_path, mid).engine
    assert _payloads(engine, "SAVE_ROLLED", RESTRAINING_HOOK)
    pulls = _pulls(engine)
    assert len(pulls) == 1, pulls
    printed, before, after = _one_square_closer(pulls[0]["path"], holder)
    assert printed, f"the printed pull moved the target from {before} squares away to {after}"


# ------------------------------------------------------------------ an AI owner spends its own paid Reaction
# Iron Shirt's Reaction is asked through the same table transport as the Hook Master's
# choice, so the AI half of "a player is asked, an AI decides" is shown for a Reaction too.
def test_an_ai_owner_spends_its_own_paid_reaction_without_being_asked(tmp_path):
    """Iron Shirt on an AI owner: the rival's own printed shove is answered by the AI,
    the printed 10-foot cut lands on the AI's fighter, and no prompt reaches the player.

    The shove needs no prepared action or replacement rule -- it is a shipped button on the
    rival -- so the only thing this test supplies is who owns Iron Shirt and who plays it.
    ``hopeless_saves`` fails the shove's Strength saving throw on every fight, so the printed
    forced movement (and with it Iron Shirt's trigger) happens every time.
    """
    combat, table, mid = _match(tmp_path,
                                _sheet((IRON_SHIRT,), hopeless_saves=True),
                                _sheet(name=CONTROL_NAME, attack_bonus=100),
                                seed="PRO13R2F1-IRON-AI")
    state = _manual_turn(table, mid, CONTROL)
    cid = next(option["candidate_id"] for group in state["menu"]["actions"]
               for option in group["options"]
               if group["source_definition_id"].endswith("unarmed.shove_push"))
    # The run is chosen while the rival is a player; only then does the owner become the AI,
    # so the question the shove raises can only be the AI's to answer.
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    result, prompts = _run(table, mid, cid, state, lambda source, prompt: None)
    assert result["status"] == "COMMITTED"
    assert prompts == [], prompts  # the AI decided for itself, nothing reached the player
    engine = _reload(tmp_path, mid).engine
    resolved = _payloads(engine, "REACTION_RESOLVED", IRON_SHIRT)
    assert resolved, "the AI did not use its own Iron Shirt"
    # The printed 10-foot cut applied to the AI's own fighter's shove: 5 feet became 0.
    assert resolved[0]["distance_before"] == 5 and resolved[0]["distance_after"] == 0, resolved[0]
    assert engine.state.actors[OWNER].resources[STAMINA] == 39  # the AI paid its own 1 Stamina
    assert engine.state.actors[CONTROL].resources[STAMINA] == 40, "the rival owns no Iron Shirt"
    assert not [row for row in engine.typed_reaction_rows.get(CONTROL, [])
                if str(row.get("feature_id") or "").startswith("insight.")], "scope leaks to the rival"


def test_a_player_owner_is_asked_about_its_own_paid_reaction_on_the_rivals_turn(tmp_path):
    """The other half of the same boundary, for contrast: the identical shove with a player
    owner raises the question, and it names the ability, the moment and the creature."""
    combat, table, mid = _match(tmp_path,
                                _sheet((IRON_SHIRT,), hopeless_saves=True),
                                _sheet(name=CONTROL_NAME, attack_bonus=100),
                                seed="PRO13R2F1-IRON-PLAYER")
    state = _manual_turn(table, mid, CONTROL)
    cid = next(option["candidate_id"] for group in state["menu"]["actions"]
               for option in group["options"]
               if group["source_definition_id"].endswith("unarmed.shove_push"))
    result, prompts = _run(table, mid, cid, state,
                           lambda source, prompt: {"selection": "USE"}
                           if source == f"reaction:typed.{IRON_SHIRT}" else None)
    assert result["status"] == "COMMITTED"
    asked = [prompt for prompt in prompts if prompt["context"].get("reaction_source_id") == f"reaction:typed.{IRON_SHIRT}"]
    assert len(asked) == 1, [prompt["context"].get("reaction_source_id") for prompt in prompts]
    prompt = asked[0]
    assert prompt["reaction"] == "Iron Shirt", prompt["reaction"]
    assert prompt["reactor"] == OWNER_NAME and prompt["affected"] == OWNER_NAME, prompt
    assert "1 Stamina" in prompt["cost"], prompt["cost"]
    assert OWNER_NAME in prompt["trigger"] and "moved" in prompt["trigger"], prompt["trigger"]
    engine = _reload(tmp_path, mid).engine
    resolved = _payloads(engine, "REACTION_RESOLVED", IRON_SHIRT)
    assert resolved and resolved[0]["distance_after"] == 0, resolved


def _saved_reaction_decisions(combat, mid: str, source: str) -> list[dict[str, Any]]:
    """Every answer the saved fight carries for one question source, read from its journal.

    This is the fight's own record of who answered what, so it shows an AI's own answer
    rather than a default the runtime would have used with nobody there.
    """
    import pathlib

    journal = pathlib.Path(combat._match_dir(mid)) / "Journal.ndjson"
    found: list[dict[str, Any]] = []
    for line in journal.read_text(encoding="utf-8").splitlines():
        if source not in line:
            continue
        for row in json.loads(line).get("intent", {}).get("reaction_decisions") or []:
            if row.get("reaction_source_id") == source:
                found.append(row)
    return found