"""Hunt89 finding 1: a summon "Command ..." button must describe the command, not the summoning talent.

The table shows a fight button's help as its group description
(APP/static/tabletop/tabletop.js ``button.title = group.description``), filled by
``TabletopService._menu_descriptions`` -> ``engine_button_description`` ->
``action_text.describe_action``, which reads ``typed.source`` as a printed-text candidate.
``combat/summons.owner_actions`` sets that field to the *summoning talent* id, so the
command button printed the ritual that creates the creature: "Ritual Time: 1 hour ...
Duration: 24 hours ... Cost: 8 CP" on a button whose own cost tag reads "Bonus".

These tests read the real table menu, so they fail without the
``combat/ext/summon_command.py`` button_description hook.

The last one covers the range half of the rule: a command reaches only the creatures
whose own ``command_range_ft`` reaches back to the summoner
(``combat/summons.commandable``), so a hover that promises an action for every member of
a spread-out group misdescribes the button. It builds the mixed case out of ordinary
table acts -- Dash, walk, Command -- rather than by writing to fight state.
"""

import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER, FOE = [FACTORY_ACTOR_PREFIX + "h89-" + name for name in ("owner", "foe")]
CORPSE_SERVANT = "TAL_DEATH_CORPSE_SERVANT"   # arrives at the start, commanded as one "Death servants" group
GHOST_LANTERN = "TAL_DEATH_GHOST_LANTERN"     # an Action that calls a creature mid-fight

# Wording that belongs to the *summoning* ability, never to a Bonus Action that orders it.
SUMMONING_TEXT = ("Ritual Time", "Action Type:", "Control Load", "Prerequisite:")


def _install(tmp_path, talents, actor_id, name):
    doc = sheet(talents, cl=17, primary="Stamina")
    doc["identity"]["display_name"] = name
    doc["identity"]["proficiency_bonus"] = 4
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
    folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    return doc


def _table(tmp_path, foe_at=None):
    """A started table whose owner summons Death servants; the Fight menu is the owner's."""
    docs = [_install(tmp_path, (CORPSE_SERVANT, GHOST_LANTERN), OWNER, "Owner"),
            _install(tmp_path, (), FOE, "Foe")]
    bundles = [compile_character(doc, actor_id=actor_id) for actor_id, doc in zip((OWNER, FOE), docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
        {OWNER: {"x": 3, "y": 6}, FOE: foe_at or {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER], [FOE],
        control_modes={OWNER: "MANUAL", FOE: "LOCAL_AUTO"}, match_seed="H89-COMMAND",
        display_name="H89 command button regression", maximum_rounds=15)["match_id"]
    return combat, table, mid


def _commit(table, mid, candidate_id, menu):
    """Spend the given menu's current decision on one option, exactly as the table does."""
    answers = []
    for _ in range(12):
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice"):
            ids = [option["id"] for option in prompt["choice"]["options"]]
            answer.update(selection="USE", option_ids=["hold" if "hold" in ids else ids[0]])
        answers.append(answer)
    raise AssertionError("command choices did not finish")


def _group(menu, label_startswith):
    return next(group for group in menu["actions"] if str(group["label"]).startswith(label_startswith))


def test_command_button_describes_the_command_not_the_summoning_ritual(tmp_path):
    """The reported defect: a Bonus Action button quoting the creating ability's cost and duration."""
    _, table, mid = _table(tmp_path)
    menu = table.state(mid)["menu"]
    command = _group(menu, "Command ")

    assert command["economy"] == "BONUS_ACTION"
    text = command["description"]
    leaked = [marker for marker in SUMMONING_TEXT if marker in text]
    assert not leaked, f"command button still shows the summoning ability's rules ({leaked}): {text}"
    # Its own action type, and what the order actually spends: an action, not a resource.
    assert text.startswith("Bonus action:"), text
    assert "It uses your Bonus action" in text, text
    assert "costs no Qi, Stamina or other resource" in text, text
    assert "lasts only for each creature\'s next turn" in text, text
    # What it does, who it affects, and what an uncommanded creature does instead.
    assert "Death servants" in text
    assert "using only its own stat-block actions and movement" in text
    assert "acts on its own instincts" in text
    assert "takes the Dodge action" not in text
    # No internal ids or type codes leak into a player-facing hover.
    for jargon in ("TAL_DEATH", "corpse_servant", "grave_formation", "command_summons"):
        assert jargon not in text


def test_summon_button_still_describes_the_summoning_ability(tmp_path):
    """The hook answers for commands only; the ability that calls a creature keeps its own rules."""
    _, table, mid = _table(tmp_path)
    menu = table.state(mid)["menu"]
    labels = [str(group["label"]) for group in menu["actions"]]
    summoning = [label for label in labels
                 if "Ghost Lantern" in label and not label.startswith("Command ")]
    assert summoning, f"the Ghost Lantern summon button is gone: {labels}"

    for label in summoning:
        group = _group(menu, label)
        text = group["description"]
        assert "give an order to your" not in text, f"the command text hijacked {label!r}: {text}"
    # It still names what it does and what it costs.
    text = _group(menu, summoning[0])["description"]
    assert "Cost: 3 Stamina" in text, text  # CP names the actor's charged Path pool.
    assert "You summon a floating funerary lantern" in text, text


def test_command_button_text_survives_commit_and_reload(tmp_path):
    """The description is rebuilt from the persisted action catalog, not from live fight state."""
    combat, table, mid = _table(tmp_path)
    command = _group(table.state(mid)["menu"], "Command ")
    before = command["description"]

    state = table.state(mid)["menu"]
    result = _commit(table, mid, command["options"][0]["candidate_id"], state)
    assert result["status"] == "COMMITTED", result

    # Reload the fight from disk through a fresh service and rebuild the button's text the
    # same way the table does, so a stale in-memory catalog cannot hide a change. The row
    # is found by the id the menu reported, because other characters' rows are in the same
    # catalog (a "Command Cui" ability is a real, unrelated action there).
    from combat.tabletop import engine_button_description

    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    reloaded_action = next(action for action in engine.action_catalog.values()
                          if action.source_definition_id == command["source_definition_id"])
    after = engine_button_description(reloaded_action.model_dump(mode="json"))
    assert after == before
    assert not [marker for marker in SUMMONING_TEXT if marker in after]
    assert engine.state.actors[OWNER].summon is None  # the command moved creatures, not the owner
    assert any(actor.summon and actor.summon["commanded"]
               for actor in engine.state.actors.values()), "the committed command reached nobody"


def test_command_button_qualifies_recipients_and_reaches_only_those_in_range(tmp_path):
    """The range case the other tests miss: a group spread past one command's reach.

    ``combat/summons.commandable`` keeps only the creatures whose own
    ``command_range_ft`` reaches back to the summoner, so a command of a spread-out group
    gives an order to the near ones and leaves the rest to their instincts. The hover therefore
    has to say the order reaches some of the group, not that each one acts.

    Everything here is a real table act: the owner Dashes (an Action, which is what
    buys 60 ft of movement), walks out of the servants' 60 ft command range, then spends
    the Bonus Action. Nothing is repositioned by writing to fight state.
    """
    # The foe stands clear so the owner's walk is not blocked from the first square.
    combat, table, mid = _table(tmp_path, foe_at={"x": 16, "y": 11})

    state = table.state(mid)
    dash = next(option for group in state["menu"]["actions"] if group["label"].startswith("Dash")
                for option in group["options"])
    assert _commit(table, mid, dash["candidate_id"], state["menu"])["status"] == "COMMITTED"

    # Pick the walk the table itself offers that leaves the group genuinely split: some
    # members still inside their own command range, some outside it. The expected split is
    # worked out here from the grid and each creature's retained range, never from the
    # command's own bookkeeping, so the assertion cannot agree with a wrong engine.
    from combat.gate2_runtime_models import Position

    state = table.state(mid)
    engine = combat._load_session(mid).engine
    servants = [actor for actor in engine.state.actors.values()
                if (actor.summon or {}).get("command_group") == "death"]
    assert len(servants) > 1, "the group is too small to be split by range"

    def in_range_at(cell):
        return [actor for actor in servants
                if engine.grid.distance_ft(cell, actor.position) <= int(actor.summon["command_range_ft"])]

    split = None
    for move in state["menu"]["moves"]:
        cell = Position(x=move["destination"]["x"], y=move["destination"]["y"],
                        z=move["destination"].get("z", 0) or 0)
        reached = in_range_at(cell)
        if reached and len(reached) < len(servants):
            split = (move, cell, reached)
            break
    assert split, "no offered walk leaves part of the group out of command range"
    move, cell, reached = split
    stranded = [actor for actor in servants if actor not in reached]

    assert _commit(table, mid, move["candidate_id"], state["menu"])["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    assert owner.position.x == cell.x and owner.position.y == cell.y
    for actor in reached:
        assert engine._distance_actor_to_actor(owner, actor) <= int(actor.summon["command_range_ft"])
    for actor in stranded:
        assert engine._distance_actor_to_actor(owner, actor) > int(actor.summon["command_range_ft"])

    # The button is still offered and still costs the Bonus Action: a command that reached
    # nobody would be a different bug, and the fix is only ever the wording.
    command = _group(state_after := table.state(mid)["menu"], "Command ")
    assert command["economy"] == "BONUS_ACTION"
    assert owner.bonus_action_available
    text = command["description"]
    # The qualification: the order reaches some of the group, and a creature it does not
    # reach acts on its instincts. The old wording promised an action for every member.
    assert "Each one in range of the order follows your chosen order" in text, text
    assert "any that is out of range, or that you do not order, acts on its own instincts" in text, text
    assert "Each one takes a single action" not in text, f"the hover still promises every member acts: {text}"
    # The rest of the description is unchanged by the qualification.
    assert text.startswith("Bonus action:") and "Death servants" in text, text
    assert "It uses your Bonus action" in text and "lasts only for each creature\'s next turn" in text, text
    for jargon in ("TAL_DEATH", "corpse_servant", "grave_formation", "command_summons", "command_range_ft"):
        assert jargon not in text, f"{jargon!r} leaked into a player-facing hover: {text}"

    # And the recipients are the ones the hover now describes: the near servants act, the
    # stranded ones are left uncommanded (so they act on their own instincts).
    result = _commit(table, mid, command["options"][0]["candidate_id"], state_after)
    assert result["status"] == "COMMITTED", result
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    for actor in reached:
        assert engine.state.actors[actor.entity_id].summon["commanded"], \
            f"{actor.display_name} was in range but the command skipped it"
    for actor in stranded:
        assert not engine.state.actors[actor.entity_id].summon["commanded"], \
            f"{actor.display_name} was {engine._distance_actor_to_actor(engine.state.actors[OWNER], actor)} ft away, past its " \
            f"{actor.summon['command_range_ft']} ft command range, yet the command reached it"
    assert not engine.state.actors[OWNER].summon
