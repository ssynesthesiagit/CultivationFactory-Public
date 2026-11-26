"""PRO13f1: production regressions for the Insight behaviour families the first pass left bare.

``test_auto_insights`` covers nine representative Insights. These cover the
remaining distinct families at the table, not through isolated hook calls:
Dream Cage (an Action, a WIS save, a state condition and a timed immunity),
Legacy Iron Shirt and Legacy Threads of Intent (paid reactions on the owner's
turn and on the other side's turn), Hook Master, Quarantine Adept and Plague
Physician (changes to another ability), and Unyielding Grip (a real escape roll).

Nothing here injects a mechanical effect. Every benefit is the shipped reviewed
record read through the real compiled bundle, the real table transport and the
real engine; the fixtures only replace *incoming* stimulus (a push, an attack, a
grapple) so the family's own behaviour is what is observed.
"""

from __future__ import annotations

import copy
import json
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest

from combat import typed_executor
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.prepared_actions import SOURCE as READY
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_factory_live_match import ROOT
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install

OWNER_PROJECT = "aaaaaaaa"
CONTROL_PROJECT = "bbbbbbbb"
OWNER = FACTORY_ACTOR_PREFIX + OWNER_PROJECT
CONTROL = FACTORY_ACTOR_PREFIX + CONTROL_PROJECT
OWNER_NAME = "Insight Owner"
CONTROL_NAME = "Table Rival"
PUSH = "test:insights.push"
HOLD = "system:combat.hold_position"
RESONANCE = "resource:core.resonance"
STAMINA = "resource:core.stamina"

DREAM_CAGE = "insight.legacy-dream-cage"
IRON_SHIRT = "insight.legacy-iron-shirt"
THREADS = "insight.legacy-threads-of-intent"
HOOK_MASTER = "insight.hook-master"
QUARANTINE = "insight.quarantine-adept"
PLAGUE = "insight.plague-physician"
GRIP = "insight.unyielding-grip"
RESTRAINING_HOOK = "tianxia.talent.chains.restraining_hook"
FORWARD_CUT = "tianxia.talent.sabers.forward_cut"
RAISE_VEIL = "DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL"
PURGING_BREATH = "tianxia.talent.disease.purging_breath"
GRAPPLES = "insight.unyielding-grip"


def _sheet(insights: tuple[str, ...] = (), *, name: str = OWNER_NAME, resonance: bool = False,
           hopeless_saves: bool = False, certain_saves: bool = False, spheres: tuple[str, ...] = (),
           talents: tuple[str, ...] = (), bases: tuple[str, ...] = (), kit: bool = False) -> dict[str, Any]:
    """The shared compiler fixture: finalized statistics stay identical.

    ``resonance`` adds the pool the printed Spirit-Awakening Insights spend; without
    it the compiler cannot build their cost at all. ``hopeless_saves`` makes every
    save fail, which is how the failure branch of a printed saving throw is
    reached without faking the roll.
    """
    sheet = copy.deepcopy(SHEET)
    sheet["spheres_and_talents"] = {
        "sphere_record_ids": list(spheres),
        "learned_talent_record_ids": list(talents),
        "automatic_sphere_component_record_ids": list(bases),
        "cultivation_insight_record_ids": list(insights),
    }
    # An unarmed fighter has no weapon button; a talent that needs one keeps the kit.
    sheet["equipment"] = copy.deepcopy(SHEET["equipment"]) if kit else []
    sheet["identity"]["display_name"] = name
    if resonance:
        pool = json.loads(sheet["ability_scores_and_statistics"]["primary_resource"])
        pool["definitions"] = [{"name": "Resonance", "max": 10}]
        sheet["ability_scores_and_statistics"]["primary_resource"] = json.dumps(pool)
    if hopeless_saves or certain_saves:
        bonus = -20 if hopeless_saves else 30
        sheet["ability_scores_and_statistics"] = {
            **sheet["ability_scores_and_statistics"],
            "saving_throws": {ability: bonus for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}}
    return sheet


def _install(tmp_path, owner: dict[str, Any], control: dict[str, Any]) -> TabletopService:
    for project, sheet in ((OWNER_PROJECT, owner), (CONTROL_PROJECT, control)):
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.save_reactions(OWNER_PROJECT, {"mode": "ask"})  # owner 2026-09-26: Ask me for this character
    return table


def _match(tmp_path, owner: dict[str, Any], control: dict[str, Any], *, yard: str, seed: str,
           adjacent: bool = False) -> tuple[CombatService, TabletopService, str]:
    table = _install(tmp_path, owner, control)
    combat = table.combat
    combat.tabletop_maps.save({"display_name": yard, "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4 if adjacent else 5, 4]]}})
    mid = combat.create_factory_match(
        project_ids=[OWNER_PROJECT], opponent_actor_ids=[CONTROL],
        control_modes={OWNER: "MANUAL", CONTROL: "MANUAL"},
        arena_id=f"battlefield:map.{yard.lower().replace(' ', '-')}", match_seed=seed)["match_id"]
    return combat, table, mid


def _turn(table, mid) -> str:
    return table.state(mid)["menu"]["actor_id"]


def _end(table, mid) -> None:
    assert act(table, mid, "end")["status"] == "COMMITTED"


def _wait_for(table, mid, who: str, limit: int = 6) -> None:
    for _ in range(limit):
        if _turn(table, mid) == who:
            return
        _end(table, mid)
    assert _turn(table, mid) == who


def _choose(table, mid, suffix: str, answers: list[dict[str, Any]] | None = None):
    """Act the one menu option whose source id ends with ``suffix``."""
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"].endswith(suffix))
    return table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], list(answers or []))


def _answer(result, suffix: str, table, mid, previous: list[dict[str, Any]], selection: str = "USE",
            **extra: Any) -> tuple[Any, list[dict[str, Any]]]:
    """Answer a pending table decision the way the page does: reuse the pending
    candidate and carry every earlier answer with it."""
    assert result["status"] == "REACTION_REQUIRED", result
    answers = [*previous, {**result["reaction"]["context"], "selection": selection, **extra}]
    state, menu = result["state"], result["state"]["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"].endswith(suffix))
    return table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], answers), answers


def _events(engine, *types: str) -> list[Any]:
    return [event for event in engine.events if not types or event.event_type in types]


def _payloads(engine, event_type: str, source: str) -> list[dict[str, Any]]:
    return [event.payload for event in engine.events
            if event.event_type == event_type and event.source_definition_id == source]


def _check(payload: dict[str, Any]) -> dict[str, Any]:
    """A CHECK_ROLLED event files the roll itself under "actor"."""
    return payload.get("actor") or payload


def _walk(effects: Any) -> Iterator[dict[str, Any]]:
    """Every typed effect, including the ones nested inside a saving throw's branches."""
    for effect in effects or []:
        if isinstance(effect, dict):
            yield effect
            for key in ("on_fail", "on_success", "effects", "options"):
                yield from _walk(effect.get(key))


def _insight_rows(engine, actor_id: str) -> list[dict[str, Any]]:
    return [row for row in [*engine.typed_passive_rows.get(actor_id, []),
                            *engine.typed_reaction_rows.get(actor_id, [])]
            if str(row.get("feature_id") or "").startswith("insight.")]


def _reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded


# ------------------------------------------------------------------ Legacy Iron Shirt
def _push_both(monkeypatch) -> None:
    """Incoming stimulus only: each fighter is pushed 20 feet. Iron Shirt supplies the response.

    Repeated queries for one turn return the same option id, so the sealed
    Ready candidate remains legal when the service regenerates it. A later
    turn gets a new id and does not reuse the first preparation.
    """
    def resolve(engine, actor, option, event, intent):
        for who in (OWNER, CONTROL):
            aggressor = engine.state.actors[CONTROL if who == OWNER else OWNER]
            subject = engine.state.actors[who]
            effect = {"type": "forced_movement", "direction": "away", "distance_ft": 20, "applies_to": "target"}
            typed = {"effects": [effect], "numbers": {"pb": 6, "cl": 17}, "duration": {"kind": "instant"}}
            action = ActionDefinition(
                source_definition_id=PUSH, display_name="Incoming push", owner_id=aggressor.entity_id,
                economy="NONE", resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
                parameters={"typed": typed})
            typed_executor.block_forced_movement(
                typed_executor.Context(engine, aggressor, action, intent, typed, [subject], subject), effect)
        return True

    install(monkeypatch, "prepare_options", lambda engine, actor: [
        {"option_id": f"push-{actor.entity_id}-{actor.turns_started}", "source_id": PUSH, "label": "Push both fighters",
         "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *args: True)
    install(monkeypatch, "prepared_action", resolve)


def _push_cycle(table, mid):
    """Hold once so the prepared push fires, answer both questions it raises, and return
    whose turn the push landed on.

    The rival is the one who prepares: preparing spends the preparer's own Reaction
    (combat/prepared_actions.py ``on_event``), and Iron Shirt needs the owner's unspent
    one. A preparation also only fires for someone else's action, so this cycle always
    lands on the owner's own turn -- which is why the second half of the test shoves
    during the rival's turn instead.
    """
    _wait_for(table, mid, CONTROL)
    assert act(table, mid, READY)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    holder = _turn(table, mid)
    pending, answers = _choose(table, mid, HOLD), []
    while pending["status"] == "REACTION_REQUIRED":
        if pending["reaction"]["context"].get("reaction_source_id") == f"reaction:typed.{IRON_SHIRT}":
            _assert_iron_shirt_prompt(pending["reaction"])
        pending, answers = _answer(pending, HOLD, table, mid, answers)
    assert pending["status"] == "COMMITTED"
    return holder


def _assert_iron_shirt_prompt(prompt: dict[str, Any]) -> None:
    # Change standard 9: the question names the ability, the triggering moment and the creature.
    assert prompt["context"]["reaction_source_id"] == f"reaction:typed.{IRON_SHIRT}"
    assert prompt["reaction"] == "Iron Shirt"
    assert prompt["reactor"] == OWNER_NAME and prompt["affected"] == OWNER_NAME
    assert "1 Stamina" in prompt["cost"], prompt["cost"]
    assert OWNER_NAME in prompt["trigger"]
    # Native action context names the actual shove; the synthetic push fixture
    # describes the impending movement directly.
    assert "moved" in prompt["trigger"] or "Shove: Push 5 ft" in prompt["trigger"]


def test_iron_shirt_is_asked_on_the_owner_turn_and_cuts_a_twenty_foot_push_to_ten(monkeypatch, tmp_path):
    _push_both(monkeypatch)
    combat, table, mid = _match(tmp_path, _sheet((IRON_SHIRT,)), _sheet(name=CONTROL_NAME),
                                yard="Iron yard", seed="PRO13F1-IRON")
    assert _push_cycle(table, mid) == OWNER
    engine = combat._load_session(mid).engine
    assert [(row["distance_before"], row["distance_after"])
            for row in _payloads(engine, "REACTION_RESOLVED", IRON_SHIRT)] == [(20, 10)]
    travelled: dict[str, int] = {}
    for event in _events(engine, "MOVEMENT_COMMITTED"):
        travelled[event.actor_id] = travelled.get(event.actor_id, 0) + (len(event.payload["path"]) - 1) * 5
    assert travelled == {OWNER: 10, CONTROL: 20}  # only the owner cuts the push
    assert engine.state.actors[OWNER].resources[STAMINA] == 39
    assert engine.state.actors[CONTROL].resources[STAMINA] == 40
    assert _insight_rows(engine, OWNER) and _insight_rows(engine, CONTROL) == []
    reloaded = _reload(tmp_path, mid)
    assert {row["feature_id"] for row in _insight_rows(reloaded.engine, OWNER)} == {IRON_SHIRT}
    assert _insight_rows(reloaded.engine, CONTROL) == []
    assert reloaded.engine.state.actors[OWNER].resources[STAMINA] == 39


def test_iron_shirt_is_asked_on_the_rivals_turn_and_stops_a_shove(monkeypatch, tmp_path):
    """The same paid Reaction while another creature is the one acting: the rival's
    own shove is the incoming stimulus, so nothing here prepares anything."""
    combat, table, mid = _match(tmp_path, _sheet((IRON_SHIRT,), hopeless_saves=True),
                                _sheet(name=CONTROL_NAME),
                                yard="Shove yard", seed="PRO13F1-SHOVE", adjacent=True)
    _wait_for(table, mid, CONTROL)
    pending, answers = _choose(table, mid, "unarmed.shove_push"), []
    asked = 0
    while pending["status"] == "REACTION_REQUIRED":
        if pending["reaction"]["context"].get("reaction_source_id") == f"reaction:typed.{IRON_SHIRT}":
            _assert_iron_shirt_prompt(pending["reaction"])
            assert pending["reaction"]["action"] == "Shove: Push 5 ft"
            assert pending["reaction"]["by"] == CONTROL_NAME
            asked += 1
        pending, answers = _answer(pending, "unarmed.shove_push", table, mid, answers)
    assert pending["status"] == "COMMITTED" and asked == 1
    reloaded = _reload(tmp_path, mid)
    assert [(row["distance_before"], row["distance_after"])
            for row in _payloads(reloaded.engine, "REACTION_RESOLVED", IRON_SHIRT)] == [(5, 0)]
    assert reloaded.engine.state.actors[OWNER].resources[STAMINA] == 39
    assert reloaded.engine.state.actors[CONTROL].resources[STAMINA] == 40
    # The owner stayed put; the rival never paid for a Reaction of its own.
    assert reloaded.engine.state.actors[OWNER].position.x == 3
    assert not _events(reloaded.engine, "RESOURCE_SPENT") or all(
        event.actor_id == OWNER for event in _events(reloaded.engine, "RESOURCE_SPENT"))


# ------------------------------------------------------------------ Legacy Threads of Intent
def test_threads_of_intent_is_asked_before_the_attack_roll_and_spends_one_resonance(monkeypatch, tmp_path):
    combat, table, mid = _match(
        tmp_path, _sheet((THREADS,), resonance=True), _sheet(name=CONTROL_NAME, spheres=("tianxia.sphere.sabers",),
                                                           talents=(FORWARD_CUT,), kit=True),
        yard="Threads yard", seed="PRO13F1-THREADS", adjacent=True)
    _wait_for(table, mid, CONTROL)
    pending = _choose(table, mid, FORWARD_CUT)
    answers: list[dict[str, Any]] = []
    while pending["status"] == "REACTION_REQUIRED":
        prompt = pending["reaction"]
        assert prompt["context"]["reaction_source_id"] == f"reaction:typed.{THREADS}"
        assert prompt["reaction"] == "Threads of Intent" and prompt["reactor"] == OWNER_NAME
        assert "1 Resonance" in prompt["cost"], prompt["cost"]
        assert CONTROL_NAME in prompt["trigger"] and OWNER_NAME in prompt["trigger"]
        assert "Forward Cut" in prompt["trigger"]
        pending, answers = _answer(pending, FORWARD_CUT, table, mid, answers)
    assert pending["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    rolls = _payloads(engine, "ATTACK_ROLLED", _own_action(combat, mid, CONTROL, FORWARD_CUT))
    assert rolls and rolls[-1]["mode"] == "DISADVANTAGE" and len(rolls[-1]["dice"]) == 2
    assert engine.state.actors[OWNER].resources[RESONANCE] == 9
    assert RESONANCE not in engine.state.actors[CONTROL].resources
    reloaded = _reload(tmp_path, mid)
    assert reloaded.engine.state.actors[OWNER].resources[RESONANCE] == 9
    assert _insight_rows(reloaded.engine, CONTROL) == []


def test_threads_of_intent_leaves_an_attack_alone_when_the_owner_declines(monkeypatch, tmp_path):
    combat, table, mid = _match(
        tmp_path, _sheet((THREADS,), resonance=True), _sheet(name=CONTROL_NAME, spheres=("tianxia.sphere.sabers",),
                                                           talents=(FORWARD_CUT,), kit=True),
        yard="Threads yard", seed="PRO13F1-THREADS-DECLINE", adjacent=True)
    _wait_for(table, mid, CONTROL)
    pending = _choose(table, mid, FORWARD_CUT)
    answers: list[dict[str, Any]] = []
    while pending["status"] == "REACTION_REQUIRED":
        pending, answers = _answer(pending, FORWARD_CUT, table, mid, answers, selection="DECLINE")
    assert pending["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    rolls = _payloads(engine, "ATTACK_ROLLED", _own_action(combat, mid, CONTROL, FORWARD_CUT))
    assert rolls and rolls[-1]["mode"] == "NORMAL"
    assert engine.state.actors[OWNER].resources[RESONANCE] == 10  # declining pays nothing


# ------------------------------------------------------------------ Dream Cage
def _cage_match(tmp_path, *, saves: str, seed: str):
    return _match(tmp_path, _sheet((DREAM_CAGE,), resonance=True),
                  _sheet(name=CONTROL_NAME, hopeless_saves=saves == "fail", certain_saves=saves == "pass"),
                  yard="Cage yard", seed=seed)


def test_dream_cage_incapsacitates_on_a_failed_wisdom_save_and_leaves_the_rival_alone(tmp_path):
    combat, table, mid = _cage_match(tmp_path, saves="fail", seed="PRO13F1-CAGE-FAIL")
    _wait_for(table, mid, OWNER)
    assert _choose(table, mid, "legacy-dream-cage")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    saves = _payloads(engine, "SAVE_ROLLED", _own_action(combat, mid, OWNER, DREAM_CAGE))
    assert saves and saves[0]["reason"].endswith(":WIS"), saves[0]
    assert saves[0]["dc"] == 18 and saves[0]["success"] is False
    # "it is incapacitated until the end of your next turn": the Dream Cage user's turn.
    applied = [event for event in _events(engine, "CONDITION_APPLIED")
               if event.payload["condition_id"] == "condition:typed.incapacitated"]
    assert len(applied) == 1 and applied[0].payload["expires_on"].startswith("END_OF_SOURCE_TURN_AT:")
    assert engine.state.actors[OWNER].resources[RESONANCE] == 5
    assert not [c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id == "condition:typed.incapacitated"]
    assert [c.condition_id for c in engine.state.actors[CONTROL].conditions.values()] == ["condition:typed.incapacitated"]
    reloaded = _reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.incapacitated"
               for c in reloaded.engine.state.actors[CONTROL].conditions.values())
    assert reloaded.engine.state.actors[OWNER].resources[RESONANCE] == 5
    assert _insight_rows(reloaded.engine, CONTROL) == []


def test_dream_cage_timed_immunity_is_recorded_on_success_and_survives_reload(tmp_path):
    combat, table, mid = _cage_match(tmp_path, saves="pass", seed="PRO13F1-CAGE-SUCCESS")
    _wait_for(table, mid, OWNER)
    assert _choose(table, mid, "legacy-dream-cage")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    saves = _payloads(engine, "SAVE_ROLLED", _own_action(combat, mid, OWNER, DREAM_CAGE))
    assert saves and saves[0]["success"] is True
    immune = [c for c in engine.state.actors[CONTROL].conditions.values()
              if c.condition_id == "condition:typed.resist_ability"]
    assert immune and immune[0].data["mode"] == "immune"
    assert immune[0].data.get("label", "").endswith("Dream Cage")
    # The printed 24 hours is carried as a slot deadline the engine sweeps, not a
    # condition that quietly lasts the fight.
    assert immune[0].expires_on and immune[0].expires_on.startswith("START_OF_SLOT_AT:")
    assert not any(c.condition_id == "condition:typed.incapacitated"
                   for c in engine.state.actors[CONTROL].conditions.values())
    reloaded = _reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.resist_ability"
               for c in reloaded.engine.state.actors[CONTROL].conditions.values())


def _own_action(combat, mid, actor_id: str, contains: str) -> str:
    """The one action source id this fighter owns that carries ``contains``."""
    return next(action.source_definition_id for action in combat._load_session(mid).engine.action_catalog.values()
                if action.owner_id == actor_id and contains in action.source_definition_id)


# ------------------------------------------------------------------ Quarantine Adept / Plague Physician
def test_quarantine_adept_widens_the_veil_it_changes_and_leaves_another_owner_alone(tmp_path):
    combat, _table, mid = _match(
        tmp_path, _sheet((QUARANTINE,), spheres=("tianxia.sphere.disease",), bases=(RAISE_VEIL,)),
        _sheet(name=CONTROL_NAME, spheres=("tianxia.sphere.disease",), bases=(RAISE_VEIL,)),
        yard="Veil yard", seed="PRO13F1-VEIL")
    engine = combat._load_session(mid).engine
    def veils(actor_id):
        return [((action.parameters.get("typed") or {}).get("zone_spec") or {}).get("size_ft")
                for action in engine.action_catalog.values() if action.owner_id == actor_id
                and RAISE_VEIL in action.source_definition_id]
    assert veils(OWNER) == [15, 15]  # the printed 10-foot sphere, widened by 5
    assert veils(CONTROL) == [10, 10]
    assert [row["status"] for row in load_modifiers(combat, mid, OWNER) if row["id"] == QUARANTINE] == ["applied"]
    assert [row["status"] for row in load_modifiers(combat, mid, CONTROL) if row["id"] == QUARANTINE] == []


def test_plague_physician_adds_range_and_a_bonus_action_form_to_the_breath_it_changes(tmp_path):
    combat, _table, mid = _match(
        tmp_path, _sheet((PLAGUE,), spheres=("tianxia.sphere.disease",), talents=(PURGING_BREATH,)),
        _sheet(name=CONTROL_NAME, spheres=("tianxia.sphere.disease",), talents=(PURGING_BREATH,)),
        yard="Breath yard", seed="PRO13F1-BREATH")
    engine = combat._load_session(mid).engine
    def breaths(actor_id):
        return sorted((action.source_definition_id, str(action.economy), action.range_ft)
                      for action in engine.action_catalog.values() if action.owner_id == actor_id
                      and PURGING_BREATH in action.source_definition_id)
    owner_rows = breaths(OWNER)
    rival_rows = breaths(CONTROL)
    assert len(owner_rows) == 9 and len(rival_rows) == 3
    assert {row[2] for row in rival_rows} == {5}
    assert {row[2] for row in owner_rows} == {5, 30}  # touch, and 30 feet
    assert {row[1] for row in owner_rows} == {"ACTION", "BONUS_ACTION"}
    assert {row[1] for row in rival_rows} == {"ACTION"}
    assert [row["status"] for row in load_modifiers(combat, mid, OWNER) if row["id"] == PLAGUE] == ["applied"] * 2
    assert [row["status"] for row in load_modifiers(combat, mid, CONTROL) if row["id"] == PLAGUE] == []


def load_modifiers(combat, mid, actor_id):
    from combat.gate3_storage import load_typed_bundles

    for bundle in load_typed_bundles(combat._match_dir(mid)):
        if bundle["actor_id"] == actor_id:
            return bundle["modifiers"]
    return []


# ------------------------------------------------------------------ Hook Master
def test_hook_master_adds_its_pull_to_the_hook_it_names_and_only_for_that_owner(tmp_path):
    combat, _table, mid = _match(
        tmp_path, _sheet((HOOK_MASTER,), spheres=("tianxia.sphere.chains",), talents=(RESTRAINING_HOOK,)),
        _sheet(name=CONTROL_NAME, spheres=("tianxia.sphere.chains",), talents=(RESTRAINING_HOOK,)),
        yard="Hook yard", seed="PRO13F1-HOOK")
    engine = combat._load_session(mid).engine
    row = next(row for row in engine.typed_reaction_rows[OWNER] if row["feature_id"] == RESTRAINING_HOOK)
    menus = [effect for effect in _walk(row["effects"]) if effect.get("type") == "rider_menu"]
    assert len(menus) == 1, row["effects"]
    menu = menus[0]
    assert menu["id"] == "hook_master_pull" and menu["optional"] is True
    assert [option["id"] for option in menu["options"]] == ["pull"]
    pull = menu["options"][0]["effects"][0]
    assert pull["type"] == "forced_movement" and pull["applies_to"] == "target"
    assert pull["distance_ft"] == 5 and pull["direction"] == "toward"
    rival = next(row for row in engine.typed_reaction_rows[CONTROL] if row["feature_id"] == RESTRAINING_HOOK)
    assert not [effect for effect in _walk(rival["effects"]) if effect.get("type") == "rider_menu"]
    assert [row["status"] for row in load_modifiers(combat, mid, OWNER) if row["id"] == HOOK_MASTER] == ["applied"]
    assert [row["status"] for row in load_modifiers(combat, mid, CONTROL) if row["id"] == HOOK_MASTER] == []


# ------------------------------------------------------------------ Unyielding Grip
def _grapple_match(tmp_path, *, insights: tuple[str, ...], seed: str):
    combat, table, mid = _match(tmp_path, _sheet(insights), _sheet(name=CONTROL_NAME, hopeless_saves=True),
                                yard="Grip yard", seed=seed, adjacent=True)
    _wait_for(table, mid, OWNER)
    assert _choose(table, mid, "unarmed.grapple")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert any(c.condition_id == "condition:typed.grappled"
               for c in engine.state.actors[CONTROL].conditions.values())
    return combat, table, mid


def test_unyielding_grip_makes_a_real_escape_roll_disadvantaged_and_keeps_it_after_reload(tmp_path):
    combat, table, mid = _grapple_match(tmp_path, insights=(GRIP,), seed="PRO13F1-GRIP")
    _wait_for(table, mid, CONTROL)
    assert _choose(table, mid, "escape_grapple")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    rolls = [_check(payload) for payload in _payloads(engine, "CHECK_ROLLED", _own_action(combat, mid, CONTROL, "escape_grapple"))]
    assert len(rolls) == 1
    assert rolls[0]["mode"] == "DISADVANTAGE", rolls[0]
    assert len(rolls[0]["dice"]) == 2 and rolls[0]["discarded"], rolls[0]
    reloaded = _reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.grappled"
               for c in reloaded.engine.state.actors[CONTROL].conditions.values())
    assert sorted(row["kind"] for row in _insight_rows(reloaded.engine, OWNER)) == sorted([GRIP, "grapple_escape_mode"])


def test_a_grapple_from_a_holder_without_the_insight_rolls_the_escape_normally(tmp_path):
    """The negative control for the same roll: the trait is the only difference."""
    combat, table, mid = _grapple_match(tmp_path, insights=(), seed="PRO13F1-GRIP-NONE")
    _wait_for(table, mid, CONTROL)
    assert _choose(table, mid, "escape_grapple")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    rolls = [_check(payload) for payload in _payloads(engine, "CHECK_ROLLED", _own_action(combat, mid, CONTROL, "escape_grapple"))]
    assert len(rolls) == 1 and rolls[0]["mode"] == "NORMAL" and len(rolls[0]["dice"]) == 1


def test_the_trait_belongs_to_the_grappler_not_to_the_creature_that_escapes(tmp_path):
    """Plug-in scope: the holder's trait, never the escaped creature's own row."""
    combat, table, mid = _match(tmp_path, _sheet((GRIP,)), _sheet(name=CONTROL_NAME),
                                yard="Grip yard", seed="PRO13F1-GRIP-SCOPE", adjacent=True)
    _wait_for(table, mid, CONTROL)
    assert _choose(table, mid, "unarmed.grapple")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert _insight_rows(engine, CONTROL) == []            # the rival holds the Grapple
    assert any(c.condition_id == "condition:typed.grappled"
               for c in engine.state.actors[OWNER].conditions.values())
    _wait_for(table, mid, OWNER)
    assert _choose(table, mid, "escape_grapple")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    rolls = [_check(payload) for payload in _payloads(engine, "CHECK_ROLLED", _own_action(combat, mid, OWNER, "escape_grapple"))]
    assert len(rolls) == 1 and rolls[0]["mode"] == "NORMAL", rolls[0]
    assert any(row["kind"] == "grapple_escape_mode" for row in _insight_rows(engine, OWNER))
