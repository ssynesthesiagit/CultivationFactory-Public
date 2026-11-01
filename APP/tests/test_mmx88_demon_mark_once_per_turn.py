"""MMX88: a "once per turn" rider must spend its use limit once per moment, not once per
damage component (HUNT93 finding #2, commit 42e43e14).

Demon Mark reads "While marked: once per turn when you damage it, add Proficiency Bonus
to the damage". The rider's per-turn flag is keyed to the current actor's turn identity
(round:slot:actor:turns_started). That identity moves while one resolution is still in
flight in synthetic tests, so the flag stopped matching and the same rider fired a
second time on the same creature inside a single moment. No live turn-granting reaction
has been established; this is a latent executor case.

Two levels of coverage live here, and they are deliberately different:

* ``executor level`` -- the first three tests call ``run_effects`` directly to force two damage
  components inside ONE moment. The turn identity is moved between them with a **synthetic**
  hook (a stand-in for the reaction or slot advance that would do it in a real fight; no
  plug-in in the app drives that path today). Useful, and the negative control for the fix, but
  it is not a table action and it never commits or reloads a fight.
* ``table level`` -- the final tests play a real owner character through ``TabletopService``:
  a real "Demon Mark" button, a real "Unarmed Strike" button, a real commit, a real fresh-service
  reload. Post-reload same-turn suppression is checked separately at executor level,
  because the service does not offer a second action in that turn.
  One service strike adds synthetic extra damage components and counter churn
  through the documented after_hit hook; it checks a real commit and reload.

The executor guards are kept because they still pin the per-moment rule directly; the table tests
pin the same rule at the level a player meets it.
"""
import json
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from combat import ext, typed_executor as ex
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_named_resources import SHEET

ACTOR = "actor:factory.mmx88"
FOES = (AN, LEE)


def engine_for(*foe_ids):
    sheet = deepcopy(SHEET)
    sheet["spheres_and_talents"] = {"learned_talent_record_ids": ["TAL_DAEMONIC_CULTIVATION_DEMON_MARK"]}
    bundle = compile_character(sheet, actor_id=ACTOR)
    roster = [ACTOR, *foe_ids]
    engine = Gate2Engine(APP, match_seed="MMX88", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": roster,
                                       "team_by_actor": {ACTOR: "team:a", **{f: "team:b" for f in foe_ids}}})
    for foe_id in foe_ids:
        engine.typed_actor_ids.add(foe_id)
        engine.typed_reaction_rows[foe_id] = []
    return engine


def mark_demon_mark(engine, target_id=None):
    """Apply the printed failed-save payload: the mark and the deferred once-per-turn rider."""
    actor = engine.state.actors[ACTOR]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ACTOR and a.display_name == "Demon Mark")
    save = action.parameters["typed"]["effects"][0]
    assert save["type"] == "save" and save["on_success"] == []
    foe = engine.state.actors[target_id or FOES[0]]
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [foe], foe), save["on_fail"])
    assert any(m.target_field == "typed_on_hit" for m in actor.modifiers.values())
    return action


def damage_action(pb=4):
    return ActionDefinition(source_definition_id="action:mmx88.damage", display_name="Save damage",
                            owner_id=ACTOR, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                            target_kind="HOSTILE_ENTITY",
                            parameters={"typed": {"numbers": {"pb": pb}, "effects": []}})


def damage_row(amount=5):
    return {"type": "damage", "flat": amount, "damage_types": ["force"]}


def churn_turn_identity(engine):
    """Synthetic counter churn, not evidence of a reaction or production caller."""
    original = engine._append_event

    def appending(kind, source, **kwargs):
        original(kind, source, **kwargs)
        if kind == "DAMAGE_COMMITTED":
            engine.state.actors[engine.state.current_actor_id].turns_started += 1

    engine._append_event = appending


def rider_packets(engine, start):
    return [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"]


def test_once_per_turn_rider_spends_once_across_the_components_of_one_moment():
    """The regression: one moment, two damage components, identity churned between them."""
    engine = engine_for(*FOES)
    mark_demon_mark(engine)
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[FOES[0]]
    action = damage_action()
    before = foe.current_hp
    start = len(engine.events)
    churn_turn_identity(engine)

    # One resolution: a single hit whose damage arrives as two components.
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [foe], foe),
                   [damage_row(5), damage_row(5)])

    dealt = before - foe.current_hp
    assert dealt == 14, {
        "expected": 14, "actual": dealt, "pb": 4,
        "why": "two 5-point components plus the rider's 4-point Proficiency Bonus once, "
               "not twice: a rider limited to once per turn cannot be spent twice in one moment",
        "damage_events": [e.payload for e in rider_packets(engine, start)],
    }


def test_the_moment_record_does_not_turn_a_bound_rider_into_a_global_one():
    """The rider watches the creature it was placed on ("when you damage it"), not everyone."""
    engine = engine_for(*FOES)
    mark_demon_mark(engine, FOES[0])
    actor = engine.state.actors[ACTOR]
    action = damage_action()

    unmarked = engine.state.actors[FOES[1]]
    before = unmarked.current_hp
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [unmarked], unmarked),
                   [damage_row(5)])
    assert before - unmarked.current_hp == 5, {
        "why": "the Proficiency Bonus belongs to the marked creature, so a different creature "
               "takes the 5 points alone; the per-moment record must not widen the rider",
    }

    marked = engine.state.actors[FOES[0]]
    before = marked.current_hp
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [marked], marked),
                   [damage_row(5)])
    assert before - marked.current_hp == 9, {
        "why": "the rider is still available for the creature it was actually placed on",
    }


def test_the_rider_is_available_again_on_a_later_turn():
    """The per-moment guard must not turn a once-per-turn rider into a once-per-fight one."""
    engine = engine_for(*FOES)
    mark_demon_mark(engine)
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[FOES[0]]
    action = damage_action()
    start = len(engine.events)
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [foe], foe),
                   [damage_row(5)])
    # A new turn for the creature whose turn the rider is counted against.
    engine.state.round_number += 1
    engine.state.actors[engine.state.current_actor_id].turns_started += 1
    before = foe.current_hp
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [foe], foe),
                   [damage_row(5)])

    assert before - foe.current_hp == 9, {
        "why": "on the next turn the rider is available again: 5 base plus the 4-point "
               "Proficiency Bonus, so the fix must not make the rider once per fight",
    }


# ------------------------------------------------------------------ table level
# A real owner character at a real table: the printed buttons, the commit, the reload.
ROOT = Path(__file__).resolve().parents[1]
MAP_NAME = "MMX88f1 close quarters"
ARENA = f"battlefield:map.{MAP_NAME.lower().replace(' ', '-')}"
MINE = FACTORY_ACTOR_PREFIX + "left"
FOE = FACTORY_ACTOR_PREFIX + "right"
PB = 4          # the sheet's proficiency bonus, so the rider is worth exactly 4 damage
STRIKE = 3      # Unarmed Strike on a character with +2 Strength: 1 + 2


def owner_sheet():
    """A finished owner character whose printed talent is Demon Mark."""
    return {
        "identity": {"proficiency_bonus": PB, "cultivation_level": 10, "path": "Qi Cultivation"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 60}, "speed": {"walking_ft": 30},
            "technique_save_dc": 15, "technique_attack_bonus": 7},
        "spheres_and_talents": {"learned_talent_record_ids": ["TAL_DAEMONIC_CULTIVATION_DEMON_MARK"]}}


def table_fight(tmp_path, monkeypatch):
    """Two real fighters, manual control, standing next to each other so every printed button is in range.

    The arena is a saved tabletop map: the two sides start one square apart. Rolls are pinned
    through the documented ``d20_result`` rewrite seam, not by touching the roller: the marked
    creature's saving throws fail, so the printed "Failed Save" branch runs, and the striker's
    attack rolls hit without critting, so the damage totals below are exact.
    """
    def rolls(engine, roll, intent):
        why = str(roll.reason).upper()
        if roll.actor_id == FOE and "SAVE" in why:
            return {"source_id": "test:mmx88f1.failed_save", "operation": "replace", "natural_result": 1}
        if roll.actor_id == MINE and "ATTACK" in why:
            return {"source_id": "test:mmx88f1.hit", "operation": "replace", "natural_result": 15}
        return None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "d20_result", [rolls])
    for side in ("left", "right"):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(owner_sheet()))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": MAP_NAME, "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    modes = {MINE: "MANUAL", FOE: "MANUAL"}
    mid = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FOE],
        control_modes=modes, arena_id=ARENA, match_seed="MMX88F1-TABLE")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def group_for(menu, needle):
    return next((g for g in menu["actions"] if needle in str(g["source_definition_id"])), None)


def use_button(table, mid, actor, needle, answer_reaction=True):
    """Play the named printed button with `actor`, ending the other fighter's turns on the way.

    Buttons that choose a creature carry one option per creature; the one aimed at the other
    fighter is taken, which is what a player clicks. A reaction the table asks for is answered
    with the first option, the ordinary way a manual player takes it.
    """
    for _ in range(120):
        state = table.state(mid)
        menu = state["menu"]
        if not menu or not menu.get("actions"):
            return None
        if menu["actor_id"] != actor:
            if table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"])["status"] != "COMMITTED":
                return None
            continue
        group = group_for(menu, needle)
        if group is None:
            return None
        option = next((o for o in group["options"] if FOE in (o.get("target_ids") or [])), group["options"][0])
        answers = []
        if answer_reaction:
            context = (group.get("metadata") or {}).get("reaction_context") or {}
            if context:
                answers = [{**context, "selection": "USE"}]
        result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] == "REACTION_REQUIRED" and answer_reaction:
            state = result.get("state") or {}
            menu = state.get("menu") or table.state(mid)["menu"]
            group = group_for(menu, needle) or group_for(menu, "OPPORTUNITY") or group_for(menu, "opportunity")
            if group is None:
                return result
            option = group["options"][0]
            context = (result.get("reaction") or {}).get("context") or {}
            result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                               state.get("last_sequence", state.get("last_sequence")),
                               [{**context, "selection": "USE"}] if context else [])
        return result
    return None


def rider_spend(combat, mid):
    """The one string this rider persists: the turn identity it has already been spent against."""
    actor = combat._load_session(mid).engine.state.actors[MINE]
    return {k: v for k, v in actor.turn_flags.items() if "_round_typed_on_hit" in k}


def foe_hp(combat, mid):
    return combat._load_session(mid).engine.state.actors[FOE].current_hp


def test_at_the_table_the_rider_spend_and_transient_cleanup_survive_reload(tmp_path, monkeypatch):
    """Real mark/strike/commit; reload preserves the spend, not transient scope."""
    combat, table, mid = table_fight(tmp_path, monkeypatch)
    assert use_button(table, mid, MINE, "DEMON_MARK")["status"] == "COMMITTED", "Demon Mark is a printed bonus action"

    before = foe_hp(combat, mid)
    assert use_button(table, mid, MINE, "unarmed_strike")["status"] == "COMMITTED"
    spent = rider_spend(combat, mid)
    assert len(spent) == 1, {"why": "the marked rider recorded the turn it was spent on", "flags": spent}
    assert before - foe_hp(combat, mid) == STRIKE + PB, {
        "why": f"the strike deals {STRIKE} and the marked rider adds the {PB}-point Proficiency Bonus once"}

    # Commit and reload from a brand new service, exactly as a saved fight comes back.
    reloaded = CombatService(ROOT, tmp_path)
    assert rider_spend(reloaded, mid) == spent, {
        "why": "the spend is a plain string in the actor's turn flags, so it survives the commit"}
    assert not hasattr(reloaded._load_session(mid).engine, "_typed_moment"), {
        "why": "the per-moment record is resolution state: it is cleared when the moment ends "
               "and is never written into a saved fight"}


def test_service_action_with_synthetic_counter_churn_spends_rider_once(tmp_path, monkeypatch):
    """Real service strike/commit with synthetic extra damage and counter churn.

    This test hook models two extra damage components within the hit's outer scope;
    it is not a printed ability or an observed turn-granting reaction.
    """
    combat, table, mid = table_fight(tmp_path, monkeypatch)
    assert use_button(table, mid, MINE, "DEMON_MARK")["status"] == "COMMITTED"

    def second_component(ctx, target, kind):
        if ctx.actor.entity_id != MINE:
            return
        ex.run_effects(ctx, [damage_row(5)])
        ctx.engine.state.actors[ctx.engine.state.current_actor_id].turns_started += 1
        ex.run_effects(ctx, [damage_row(5)])

    monkeypatch.setitem(ext._HOOKS, "after_hit", [second_component])
    before = foe_hp(combat, mid)
    assert use_button(table, mid, MINE, "unarmed_strike")["status"] == "COMMITTED"
    assert before - foe_hp(combat, mid) == STRIKE + 10 + PB
    reloaded = CombatService(ROOT, tmp_path)
    assert rider_spend(reloaded, mid) == rider_spend(combat, mid)
    assert foe_hp(reloaded, mid) == foe_hp(combat, mid)


def test_at_the_table_a_spent_rider_stays_spent_through_a_reload_and_returns_on_the_next_turn(
        tmp_path, monkeypatch):
    """Reloaded executor suppresses same-turn damage; reloaded table restores next-turn use."""
    combat, table, mid = table_fight(tmp_path, monkeypatch)
    assert use_button(table, mid, MINE, "DEMON_MARK")["status"] == "COMMITTED"
    assert use_button(table, mid, MINE, "unarmed_strike")["status"] == "COMMITTED"
    spent = rider_spend(combat, mid)
    assert len(spent) == 1, {"why": "the rider recorded the turn it was spent on"}
    assert all(isinstance(value, str) for value in spent.values())

    # The commit boundary, mid-turn: a brand new service reads the fight back off disk.
    reloaded = CombatService(ROOT, tmp_path)
    assert rider_spend(reloaded, mid) == spent, {
        "why": "the spend is a plain string in the actor's turn flags; a fresh service still sees it"}
    # Executor enforcement on the freshly loaded engine, without inventing another
    # legal service action. This probe is deliberately not committed to the table.
    engine = reloaded._load_session(mid).engine
    actor, foe = engine.state.actors[MINE], engine.state.actors[FOE]
    action = damage_action().model_copy(update={"owner_id": MINE})
    before = foe.current_hp
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [foe], foe),
                   [damage_row(5)])
    assert before - foe.current_hp == 5, "a persisted spend suppresses the bonus after reload"
    assert rider_spend(reloaded, mid) == spent

    # All subsequent service actions use a new table backed by the fresh service.
    combat, table = reloaded, TabletopService(reloaded, tmp_path)

    # Nothing else in the rest of that turn re-spends it: the turn simply closes.
    for _ in range(8):
        state = table.state(mid)
        menu = state["menu"]
        if not menu or not menu.get("actions"):
            break
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"])["status"] == "COMMITTED"
        if table.state(mid)["menu"]["actor_id"] == MINE:
            break
    assert rider_spend(combat, mid) == spent, {"why": "closing the turn did not change the spend"}

    # A later turn: a once-per-turn rider, not a once-per-fight one.
    before = foe_hp(combat, mid)
    assert use_button(table, mid, MINE, "unarmed_strike")["status"] == "COMMITTED", {
        "why": "the printed buttons are offered again on the next turn"}
    assert before - foe_hp(combat, mid) == STRIKE + PB, {
        "why": f"a new turn, so the rider is available again and adds its {PB}-point bonus once"}
    assert rider_spend(combat, mid) != spent, {"why": "the spend now names the new turn"}
