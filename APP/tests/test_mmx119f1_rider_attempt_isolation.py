"""MMX119f1: one printed bonus, one attack attempt, one creature -- review fixes 1, 2 and 3.

``combat/ext/roll_modifiers.py`` folds a printed "add ... to the damage (roll)" into the roll
it was printed to modify instead of committing it as its own packet. The pre-merge review of
66e29727 found the fold was reaching the wrong roll and the wrong point in the resolution:

1. the bound rider was folded into the dice an attack *sequence* shares across every strike
   and every target (typed_executor ``_damage_dice`` at the top of ``block_attack``), and it
   wrote its once-per-turn use there, so a marked creature paid the bonus on a miss and on
   every strike of a Barrage;
2. it was folded into the roll an *area* shares between all of its creatures, so a creature
   marked in a group either raised everyone's damage or (processed second) kept the old
   second packet;
3. the folded option skipped ``effect_eligibility.eligible`` and was suppressed *before* the
   executor recorded its ``modifier_once`` use gate, so the use was never paid for.

Engine tests drive ``typed_executor.run_effects`` / ``block_attack`` / ``block_save``
with synthetic rows shaped like compiler output. Table tests use real compiled Demon Mark.
The state serialization test is an engine JSON round-trip, not a service commit/reload.
"""
import json
import sys
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(APP / "tests") not in sys.path:
    sys.path.insert(0, str(APP / "tests"))

from combat import ext
from combat import typed_executor as ex
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark

from test_mmx119_rider_damage_roll import owner_sheet, use_button

ROOT = APP
MAP_NAME = "MMX119f1 close quarters"
ARENA = f"battlefield:map.{MAP_NAME.lower().replace(' ', '-')}"
MINE = FACTORY_ACTOR_PREFIX + "left"
FOE = FACTORY_ACTOR_PREFIX + "right"
PB = 4
ACTOR = "actor:factory.mmx119f1"

# Exactly what factory_compiler emits for a weapon attack, so the damage is a real printed
# roll (1d4 + 2) and the assertions are about the roll, not about a synthetic amount.
WEAPON = {"damage": {"count": 1, "sides": 4, "modifier": 2}, "damage_type": "BLUDGEONING",
          "damage_types": ["BLUDGEONING"]}
BASE_MODIFIER = WEAPON["damage"]["modifier"]  # the weapon's own printed +2, before any rider


# ---------------------------------------------------------------- engine fixtures

def _engine(actor_id=ACTOR, foes=(AN, LEE)):
    bundle = compile_character(owner_sheet(), actor_id=actor_id)
    engine = Gate2Engine(APP, match_seed="MMX119F1", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [actor_id, *foes],
                                       "team_by_actor": {actor_id: "team:a", **{f: "team:b" for f in foes}}})
    for foe in foes:
        engine.typed_actor_ids.add(foe)
        engine.typed_reaction_rows[foe] = []
    return engine


def _marked_engine(actor_id=ACTOR, foes=(AN, LEE)):
    """An engine whose fighter already bears Demon Mark on ``foes[0]``, as a failed save leaves it."""
    engine = _engine(actor_id, foes)
    actor, foe = engine.state.actors[actor_id], engine.state.actors[foes[0]]
    mark = next(a for a in engine.action_catalog.values()
                if a.owner_id == actor_id and a.display_name == "Demon Mark")
    ex.run_effects(ex.Context(engine, actor, mark, None, mark.parameters["typed"], [foe], foe),
                   mark.parameters["typed"]["effects"][0]["on_fail"])
    assert bears_mark(foe, actor_id, "Demon Mark"), "fixture: the mark must land"
    return engine


def _pin_attack(monkeypatch, naturals):
    """Make every d20 the fighter makes come from ``naturals``, in order."""
    queue = list(naturals)

    def d20(engine, roll, intent):
        if "ATTACK" not in str(roll.reason).upper():
            return None
        return {"source_id": "test:mmx119f1.pinned", "operation": "replace", "natural_result": queue.pop(0)}

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "d20_result", [d20])


def _action(actor_id, effects, **typed_extra):
    typed = {"numbers": {"pb": PB, "attack_bonus": 7}, "effects": effects}
    typed.update(typed_extra)
    return ActionDefinition(source_definition_id=f"action:{actor_id}.act", display_name="Act",
                            owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                            target_kind="HOSTILE_ENTITY", parameters={"typed": typed})


def _strike(count=1):
    """factory_compiler's weapon-attack row shape."""
    return {"type": "attack", "attack_kind": "weapon", "count": count,
            "on_hit": [{"type": "damage", "weapon_damage": True}], "on_miss": []}


def _hit(engine, actor, action, targets):
    """Run an action's effects and report each printed roll next to the packet it produced."""
    start = len(engine.events)
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], targets, targets[0]),
                   action.parameters["typed"]["effects"])
    out = []
    for event in engine.events[start:]:
        if event.event_type == "DAMAGE_ROLLED":
            out.append({"roll": int(event.payload.get("total") or 0),
                        "modifier": int(event.payload.get("modifier") or 0),
                        "target": (event.target_ids or [None])[0]})
        elif event.event_type == "DAMAGE_COMMITTED":
            out.append({"dealt": int(event.payload.get("hp_damage") or 0)
                        + int(event.payload.get("temporary_hp_absorbed") or 0),
                        "type": event.payload.get("damage_type"), "target": (event.target_ids or [None])[0]})
    return out


def _rolls(steps, target_id):
    return [s for s in steps if "roll" in s and s["target"] == target_id]


def _dealt(steps, target_id):
    return [s for s in steps if "dealt" in s and s["target"] == target_id]


# ---------------------------------------------------------------- review finding 1



def test_a_miss_in_a_two_strike_attack_does_not_pay_the_later_strike_twice(monkeypatch):
    """A miss spends no damage rider; only the later landed strike receives the bonus."""
    engine = _marked_engine()
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    _pin_attack(monkeypatch, [1, 20])  # first strike a natural 1, second a natural 20
    action = _action(ACTOR, [_strike(count=2)], weapon=WEAPON)

    steps = _hit(engine, actor, action, [foe])
    rolls, dealt = _rolls(steps, foe.entity_id), _dealt(steps, foe.entity_id)
    assert len(rolls) == 1, {
        "why": "only the strike that landed makes a printed roll; the missed one makes none",
        "steps": steps}
    assert rolls[0]["modifier"] - BASE_MODIFIER == PB, {
        "why": "the miss leaves the rider available for the landed strike", "steps": steps}
    assert len(dealt) == 1 and dealt[0]["dealt"] == rolls[0]["roll"], {
        "why": "only the landed strike deals damage, including its rider", "steps": steps}


def test_a_two_strike_attack_pays_the_rider_on_one_strike_only(monkeypatch):
    """Extra Attack: "once per turn" means once, not once per strike of the sequence."""
    engine = _marked_engine()
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    _pin_attack(monkeypatch, [20, 20])  # both strikes land
    action = _action(ACTOR, [_strike(count=2)], weapon=WEAPON)

    steps = _hit(engine, actor, action, [foe])
    rolls, dealt = _rolls(steps, foe.entity_id), _dealt(steps, foe.entity_id)
    assert len(dealt) == 2 and len(rolls) == 2, {"why": "two strikes make two rolls and two packets",
                                                 "steps": steps}
    extra = sorted(r["modifier"] - BASE_MODIFIER for r in rolls)
    assert extra == [0, PB], {
        "why": "Demon Mark says once per turn, so the Proficiency Bonus rides exactly one of the two "
               f"printed rolls. Getting {extra} means it was folded into the dice the sequence shares "
               "across its strikes", "modifiers": [r["modifier"] for r in rolls]}
    assert [d["dealt"] for d in dealt] == [r["roll"] for r in rolls], {
        "why": "each packet is exactly its own printed roll: the bonus rides a roll, it is not a packet",
        "dealt": [d["dealt"] for d in dealt], "rolls": [r["roll"] for r in rolls]}


def test_the_rider_only_ever_reaches_the_creature_it_is_bound_to(monkeypatch):
    """The bonus follows the creature that was actually damaged, not the ability's first target."""
    engine = _marked_engine()
    actor = engine.state.actors[ACTOR]
    marked, other = engine.state.actors[AN], engine.state.actors[LEE]
    _pin_attack(monkeypatch, [20, 20])
    action = _action(ACTOR, [_strike()], weapon=WEAPON)

    first = _hit(engine, actor, action, [marked])
    second = _hit(engine, actor, action, [other])

    assert [r["modifier"] - BASE_MODIFIER for r in _rolls(first, marked.entity_id)] == [PB], {
        "why": "the marked creature is damaged, so its own 'add Proficiency Bonus to the damage' applies",
        "rolls": _rolls(first, marked.entity_id)}
    assert [r["modifier"] - BASE_MODIFIER for r in _rolls(second, other.entity_id)] == [0], {
        "why": "the rider is bound to the marked creature, so a different creature in the same turn "
               "takes its printed roll and nothing else", "rolls": _rolls(second, other.entity_id)}


# ---------------------------------------------------------------- review finding 2

AREA_DAMAGE = {"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["FORCE"],
               "damage_label": "Burst", "evidence": "each creature in the area takes 1d6 force damage"}
AREA_SAVE = {"type": "save", "ability": "dex", "dc": 5, "applies_to": "enemies_in_area",
             "on_fail": [AREA_DAMAGE], "on_success": []}


def _area(engine, order):
    """One save-gated area whose single damage roll is shared by every creature in it.

    This is the exact path ``block_save`` runs: ``simultaneous`` over the area's subjects and
    ``_save_each``, which records the recipients under ``_area_targets`` so ``_damage_roll``
    makes one roll for all of them. Called directly so a unit test can put two creatures in
    one area without inventing grid geometry.
    """
    actor = engine.state.actors[ACTOR]
    marked, other = engine.state.actors[AN], engine.state.actors[LEE]
    subjects = [marked, other] if order == "marked-first" else [other, marked]
    action = _action(ACTOR, [AREA_SAVE], area={"size_ft": 20, "shape": "circle"})
    ctx = ex.Context(engine, actor, action, None, action.parameters["typed"], subjects, subjects[0])
    start = len(engine.events)
    with ex.simultaneous(ctx, subjects):
        ex._save_each(ctx, AREA_SAVE, subjects)
    steps = []
    for event in engine.events[start:]:
        if event.event_type == "DAMAGE_ROLLED":
            steps.append({"roll": int(event.payload.get("total") or 0),
                          "modifier": int(event.payload.get("modifier") or 0),
                          "target": (event.target_ids or [None])[0]})
        elif event.event_type == "DAMAGE_COMMITTED":
            steps.append({"dealt": int(event.payload.get("hp_damage") or 0)
                          + int(event.payload.get("temporary_hp_absorbed") or 0),
                          "type": event.payload.get("damage_type"),
                          "target": (event.target_ids or [None])[0]})
    rolls = [s for s in steps if "roll" in s]
    assert len(rolls) == 1, {"why": "an area rolls once for every creature in it", "steps": steps}
    return rolls[0], {s.entity_id: _dealt(steps, s.entity_id) for s in subjects}, marked, other


def _pin_saves(monkeypatch, natural):
    """Force every save to a fixed natural, so the area's outcomes are deterministic."""
    def d20(engine, roll, intent):
        if "SAVE" in str(roll.reason).upper():
            return {"source_id": "test:mmx119f1.save", "operation": "replace", "natural_result": natural}
        return None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "d20_result", [d20])


def test_a_bound_rider_does_not_change_the_shared_roll_of_an_area(monkeypatch):
    """One roll for the whole area: the marked creature's bonus is that creature's own damage."""
    for order in ("marked-first", "marked-last"):
        engine = _marked_engine()
        _pin_saves(monkeypatch, 1)  # both creatures fail, so both take the failing branch
        roll, packets, marked, other = _area(engine, order)
        assert [d["dealt"] for d in packets[other.entity_id]] == [roll["roll"]], {
            "why": f"[{order}] every creature takes the one roll the area printed. Getting "
                   f"{[d['dealt'] for d in packets[other.entity_id]]} against a roll of {roll['roll']} "
                   "means the marked creature's bonus was folded into the roll the whole area shares",
            "order": order, "roll": roll,
            "packets": {k: [d["dealt"] for d in v] for k, v in packets.items()}}
        assert [d["dealt"] for d in packets[marked.entity_id]] == [roll["roll"] + PB], {
            "why": f"[{order}] the marked creature is damaged by the area, so it alone takes the printed "
                   f"roll plus the Proficiency Bonus: {roll['roll']} + {PB}",
            "order": order, "roll": roll,
            "packets": {k: [d["dealt"] for d in v] for k, v in packets.items()}}


def test_an_areas_bonus_is_paid_only_to_the_creature_that_failed(monkeypatch):
    """Mixed outcomes: the mark is spent on the marked creature's damage, not the other's."""
    engine = _marked_engine()
    actor = engine.state.actors[ACTOR]
    other = engine.state.actors[LEE]

    def d20(engine, roll, intent):
        if roll.actor_id == other.entity_id and "SAVE" in str(roll.reason).upper():
            return {"source_id": "test:mmx119f1.save", "operation": "replace", "natural_result": 20}
        return None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "d20_result", [d20])
    roll, packets, marked, other = _area(engine, "passer-first")
    on_marked = [d["dealt"] for d in packets[marked.entity_id]]
    assert on_marked == [roll["roll"] + PB], {
        "why": "the marked creature failed and takes the printed roll plus its own Proficiency "
               f"Bonus; the other creature passed the save and is untouched", "roll": roll,
        "packets": {k: [d["dealt"] for d in v] for k, v in packets.items()}}
    assert packets[other.entity_id] == [], {
        "why": "the passing creature takes nothing, and the marked creature's bonus must not appear "
               "as damage to it", "roll": roll,
        "packets": {k: [d["dealt"] for d in v] for k, v in packets.items()}}


# ---------------------------------------------------------------- review finding 3

AUGMENT_ROW = {"type": "extra_damage", "applies_to": "target", "formula": "pb", "damage_types": [],
               "damage_label": "Bonus Damage", "evidence": "add Proficiency Bonus to one damage roll",
               "modifier_once": "TAL_PURSUIT_SPEAR_DAMAGE", "modifier_once_period": "turn"}
AUGMENT_EFFECTS = [{"type": "damage", "dice": {"count": 2, "sides": 6}, "damage_types": ["FORCE"]},
                   dict(AUGMENT_ROW)]


def _augment(actor_id="actor:factory.mmx119f1x"):
    """Synthetic option with a compiler-style per-turn modifier_once gate."""
    engine = _engine(actor_id)
    actor, foe = engine.state.actors[actor_id], engine.state.actors[AN]
    return engine, actor, foe, _action(actor_id, AUGMENT_EFFECTS)


def test_a_folded_once_per_turn_option_is_paid_for_only_once_per_turn():
    """Folding moves the bonus, not the use: a second activation in the turn gets none."""
    from combat.ext.roll_modifiers import is_roll_modifier

    engine, actor, foe, action = _augment()
    row = action.parameters["typed"]["effects"][1]
    assert is_roll_modifier(row), "the option row is a printed roll modifier"
    assert row["modifier_once"] and row["modifier_once_period"] == "turn", {
        "why": "the option carries the same once-per-turn gate factory_compiler records for it"}

    first = _hit(engine, actor, action, [foe])
    assert [r["modifier"] for r in _rolls(first, foe.entity_id)] == [PB] and len(_dealt(first, foe.entity_id)) == 1, {
        "why": "the first activation folds the option into its printed roll and commits one packet",
        "steps": first}

    second = _hit(engine, actor, action, [foe])
    assert [r["modifier"] for r in _rolls(second, foe.entity_id)] == [0], {
        "why": f"the option is limited to once per turn and folding must have recorded that use. "
               f"Getting {[r['modifier'] for r in _rolls(second, foe.entity_id)]} on a second activation "
               "in the same turn means the fold suppressed the row before the executor could record "
               "its gate", "steps": second}


def test_a_spent_once_per_turn_option_is_not_folded_for_another_option():
    """An already-spent gate is left to the ordinary path: no bonus, no charged use."""
    from combat.effect_eligibility import modifier_key

    engine, actor, foe, action = _augment()
    row = action.parameters["typed"]["effects"][1]
    actor.turn_flags[modifier_key(row)] = True  # the use was already spent through another option

    steps = _hit(engine, actor, action, [foe])
    assert [r["modifier"] for r in _rolls(steps, foe.entity_id)] == [0], {
        "why": f"the row's gate {row['modifier_once']} is already spent, so folding it would pay for a "
               f"use that never happened", "steps": steps}
    assert len(_dealt(steps, foe.entity_id)) == 1, {
        "why": "the ineligible row is skipped entirely, leaving only the printed damage effect",
        "steps": steps}


def test_a_spent_use_survives_an_engine_state_json_round_trip():
    """Engine serialization preserves the flag; service persistence is tested separately."""
    from combat.effect_eligibility import modifier_key

    engine, actor, foe, action = _augment()
    row = action.parameters["typed"]["effects"][1]
    first = _hit(engine, actor, action, [foe])
    assert [r["modifier"] for r in _rolls(first, foe.entity_id)] == [PB], {"why": "the use is spent",
                                                                         "steps": first}

    # Serialize state into a fresh engine; this does not exercise service persistence.
    saved = json.loads(engine.state.model_dump_json())
    saved.pop("schema_name", None)
    reloaded = _engine(actor.entity_id)
    reloaded.state = type(reloaded.state).model_validate(saved)
    actor2 = reloaded.state.actors[actor.entity_id]
    assert actor2.turn_flags.get(modifier_key(row)) is True, {
        "why": "the executor's per-turn use gate survives engine state serialization"}

    action2 = _action(actor.entity_id, AUGMENT_EFFECTS)
    steps = _hit(reloaded, actor2, action2, [reloaded.state.actors[AN]])
    assert [r["modifier"] for r in _rolls(steps, AN)] == [0], {
        "why": "after a reload in the same turn the use is still spent, so the option is not folded",
        "steps": steps}


# ---------------------------------------------------------------- table level

def table_fight(tmp_path, monkeypatch):
    def rolls(engine, roll, intent):
        why = str(roll.reason).upper()
        if roll.actor_id == FOE and "SAVE" in why:
            return {"source_id": "test:mmx119f1.failed_save", "operation": "replace", "natural_result": 1}
        if roll.actor_id == MINE and "ATTACK" in why:
            return {"source_id": "test:mmx119f1.hit", "operation": "replace", "natural_result": 15}
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
                                      control_modes=modes, arena_id=ARENA, match_seed="MMX119F1-TABLE")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def _packets(combat, mid, start_seq, target=FOE):
    engine = combat._load_session(mid).engine
    return [{"dealt": int(p.payload.get("hp_damage") or 0) + int(p.payload.get("temporary_hp_absorbed") or 0)}
            for p in engine.events
            if p.sequence > start_seq and p.event_type == "DAMAGE_COMMITTED"
            and p.actor_id == MINE and target in (p.target_ids or ())]


def _rolls_after(combat, mid, start_seq, target=FOE):
    engine = combat._load_session(mid).engine
    return [int(e.payload.get("modifier") or 0) for e in engine.events
            if e.sequence > start_seq and e.event_type == "DAMAGE_ROLLED"
            and MINE == e.actor_id and target in (e.target_ids or ())]


def test_a_mark_and_its_rider_survive_a_commit_and_reload_in_the_same_turn(tmp_path, monkeypatch):
    """Table level: reload the fight mid-turn; the mark and its once-per-turn rider both persist."""
    combat, table, mid = table_fight(tmp_path, monkeypatch)
    assert use_button(table, mid, MINE, "DEMON_MARK")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert bears_mark(engine.state.actors[FOE], MINE, "Demon Mark")

    # Commit and reload the fight with the same fighter's turn still open.
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.mechanical.replay()["status"] == "PASS", "the fight must still replay after a reload"
    seq = reloaded.engine.state.event_sequence
    state = table.state(mid)
    assert state["menu"]["actor_id"] == MINE, "the reload must leave the same fighter's turn open"
    assert bears_mark(combat._load_session(mid).engine.state.actors[FOE], MINE, "Demon Mark"), {
        "why": "the mark is saved fight state, so it must still be on the creature after a reload"}

    assert use_button(table, mid, MINE, "unarmed_strike")["status"] == "COMMITTED"
    packets = _packets(combat, mid, seq)
    assert len(packets) == 1, {
        "why": "the rider is folded into the printed roll, so the hit is a single packet", "packets": packets}
    modifiers = _rolls_after(combat, mid, seq)
    assert modifiers == [PB], {
        "why": f"the reloaded fighter's still-armed rider reaches the roll it was printed to modify: "
               f"the Proficiency Bonus {PB} is a modifier on that one roll", "modifiers": modifiers,
        "packets": packets}
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
