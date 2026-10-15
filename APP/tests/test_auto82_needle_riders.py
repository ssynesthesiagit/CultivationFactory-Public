"""AUTO82 (automation lane, The Piercing Needle): the printed lines this sphere's GM list still carried, made the engine's own.

Three riders retired, each for a stated reason, and two effects that were never actually applied:

* Sovereign Needle Incarnation "attacks you make count as magical for the purpose of overcoming Resistance or Immunity to
  nonmagical attacks and damage" was never applied: ``condition:typed.needle_magical`` was declared in
  combat/rules/typed_conditions.json and named in combat/condition_text.py, and nothing set it. It is now put on when the
  Incarnation starts and taken off when it ends, and it drives the new general seam ``attack_magical``
  (combat/typed_reactions.py ``_counts_as_mundane``, documented in combat/ext/__init__.py).
* Traitorous Blade's catch was offered without ever checking the printed condition "you have at least one free hand", and its
  GM rider claimed the Bonus Action attack was not offered (it has been, since rider lane 10).
* Vacuum Cut's variant was offered on any action, although its printed trigger names the Attack action.

AUTO82f1 (independent review, MERGE AFTER FIXES) kept the first and the Attack-action gate and corrected two things:

* the catch asked ``weapon_requirement``, which measures the hands an **attack** needs, so a fencer with one free hand was
  refused a Two-Handed or Versatile weapon. It now reads ``hand_occupancy.holding_hands`` -- the hands the object rests in --
  which is what "the object can be held in that hand" means; attacking with what you caught stays the separate check.
* Vacuum Cut's draw rider was retired on an argument the engine cannot carry (nothing records when a weapon was drawn), so the
  line is restored and only the Attack-action half of the trigger is the engine's.

Everything runs through the real compiler, the real controller and the real damage commit; the persistence case runs through a
real table commit and a reload from storage.
"""

import json
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_auto_lane4 as L4
from tests.test_carry import KIT
from tests.test_needle import FOCUS, NEEDLE, _answers, _bears, _pin, _said

ROOT = Path(__file__).resolve().parents[1]
FENCER, IRON = "actor:factory.fencer", "actor:factory.iron"
BELL_TOWER = ["TAL_IRON_FIST_BELL_TOWER_BODY"]
AUTHORITY = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
#: A Two-Handed weapon ("Reach, Heavy, Two-Handed") and a Versatile one ("Finesse, Versatile 1d10"): both are held in one
#: hand and need their second hand only to attack, which is the case AUTO82 got wrong.
TWO_HANDED = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.ji", "name": "Ji (Halberd)", "quantity": 1}]}}
VERSATILE = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "name": "Jian (Straight Sword)", "quantity": 1}]}}


def _duel(*, fencer_talents, subject_talents=(), subject_sphere=L4.BRUTE, subject_kit=KIT):
    """FENCER (the Needle fencer with a dagger, one hand free) beside IRON (subject_sphere's fighter) at 5 feet."""
    mine = compile_character(L4.t._sheet(NEEDLE, list(fencer_talents), {"starting_kit": KIT}), actor_id=FENCER)
    theirs = compile_character(L4.t._sheet(subject_sphere, list(subject_talents),
                                          {"starting_kit": subject_kit} if "items" in subject_kit else subject_kit), actor_id=IRON)
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO82", typed_bundles=(mine, theirs),
                                   roster_setup={"primary_actor_ids": [FENCER, IRON], "team_by_actor": {FENCER: "team:a", IRON: "team:b"},
                                                 "starting_positions": {FENCER: {"x": 3, "y": 6}, IRON: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(FENCER)
    engine.state.current_actor_id = FENCER
    engine._system_start_turn()
    me = engine.state.actors[FENCER]
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    return engine


def _use(engine, actor_id, name):
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    engine.state.current_actor_id = actor_id
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id)
    engine.execute_intent(ActionIntent(intent_id=f"auto82-{name}-{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination))


def _defense_rows(engine, target):
    """The defender's own always-on defense rows, as the fight reads them."""
    from combat.typed_reactions import _rows

    return _rows(engine, target.entity_id, "defense")


def _magic_marks(engine, actor_id=FENCER):
    return _bears(engine.state.actors[actor_id], "needle_magical")


# ----------------------------------------------------------------------------------- Sovereign Needle Incarnation: attacks count as magical
def test_sovereign_needle_incarnation_marks_its_owner_s_attacks_magical_for_the_minute_it_prints():
    engine = _duel(fencer_talents=["TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"])
    _answers(engine, {})
    assert not _magic_marks(engine)  # nothing before it is used
    _use(engine, FENCER, "Sovereign Needle Incarnation")
    me = engine.state.actors[FENCER]
    (mark,) = _magic_marks(engine)
    assert mark.expires_on == _bears(me, "needle_sovereign")[0].expires_on  # exactly as long as the Incarnation
    from combat import condition_text

    assert "magical" in condition_text.READING["needle_magical"]  # the sheet can say what it does


def test_the_magical_mark_ends_the_moment_the_incarnation_does():
    engine = _duel(fencer_talents=["TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"])
    _answers(engine, {})
    _use(engine, FENCER, "Sovereign Needle Incarnation")
    assert _magic_marks(engine)
    engine._apply_condition(engine.state.actors[FENCER], "condition:typed.incapacitated", "test", FENCER, expires_on="UNTIL_REMOVED")
    assert not _magic_marks(engine) and _said(engine, "the Martial Domain ends")


def _hammered_by(*, sovereign):
    """A pinned dagger hit on an Iron Fist fighter holding Martial Focus with Bell Tower Body: "reduce B/P/S damage from
    nonmagical attacks by PB". Returns the Hit Points it lost."""
    engine = _duel(fencer_talents=["TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"], subject_talents=BELL_TOWER,
                   subject_sphere="tianxia.sphere.iron_fist")
    _pin(engine, ATTACK=20, DAMAGE=4)
    _answers(engine, {})
    me, foe = engine.state.actors[FENCER], engine.state.actors[IRON]
    foe.resources[FOCUS] = 1  # "While holding Martial Focus"
    if sovereign:
        _use(engine, FENCER, "Sovereign Needle Incarnation")
        assert _magic_marks(engine)
    before = foe.current_hp
    _use(engine, FENCER, "Bi Shou (Dagger) attack")
    return before - foe.current_hp, me, foe


def test_a_sovereign_fencers_ordinary_dagger_is_not_reduced_by_a_nonmagical_only_defense():
    magical, _me, _foe = _hammered_by(sovereign=True)
    mundane, _me, _foe = _hammered_by(sovereign=False)
    assert magical == mundane + _foe.proficiency_bonus > mundane  # the same pinned hit, kept whole


def test_without_sovereign_the_same_dagger_is_reduced_as_printed():
    """The control for the test above: the defense is real, and it only ever met nonmagical attacks."""
    engine = _duel(fencer_talents=[], subject_talents=BELL_TOWER, subject_sphere="tianxia.sphere.iron_fist")
    assert [row for row in _defense_rows(engine, engine.state.actors[IRON]) if row.get("mundane_only")]


def test_the_seam_is_default_inert_for_any_but_the_marked_fighter():
    """A different creature's attack is unchanged: the seam answers for the attacker, not the weapon or the fight."""
    engine = _duel(fencer_talents=[], subject_talents=BELL_TOWER, subject_sphere="tianxia.sphere.iron_fist")
    from combat.typed_reactions import _counts_as_mundane

    assert _counts_as_mundane(engine, {"mundane": True}, FENCER) is True
    _use(engine, FENCER, "Bi Shou (Dagger) attack")
    assert not _magic_marks(engine)


# ------------------------------------------------------- the same thing through a real table commit and a reload
def _table_fight(tmp_path, *, sovereign, seed):
    """A real saved fight (CombatService + TabletopService): the Needle fencer against the Iron Fist with Bell Tower Body."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_lock2_persistence import act

    mine = compile_character(L4.t._sheet(NEEDLE, ["TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"] if sovereign else [],
                                         {"starting_kit": KIT}), actor_id=FENCER)
    theirs = compile_character(L4.t._sheet("tianxia.sphere.iron_fist", BELL_TOWER, {"starting_kit": KIT}), actor_id=IRON)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        (mine, theirs), [FENCER, IRON], {FENCER: "team:a", IRON: "team:b"},
        {FENCER: {"x": 3, "y": 6}, IRON: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [FENCER], [IRON],
        control_modes={FENCER: "MANUAL", IRON: "MANUAL"}, match_seed=seed,
        display_name=f"AUTO82f1 {seed}", maximum_rounds=20)["match_id"]
    for _ in range(4):
        if table.state(mid)["menu"]["actor_id"] == FENCER:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def _hammered_after_a_reload(tmp_path, sovereign):
    """The Incarnation committed through the table, the fight reloaded from storage, then the same pinned dagger attack.

    Returns the Hit Points the defender lost, so the two arms can be compared.
    """
    from combat.gate5_service import CombatService

    combat, table, mid = _table_fight(tmp_path, sovereign=sovereign, seed=f"AUTO82F1-PERSIST-{sovereign}")
    if sovereign:
        state = table.state(mid)
        group = next(g for g in state["menu"]["actions"] if g["source_definition_id"].endswith("TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"))
        assert table.act(mid, group["options"][0]["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                         state["last_sequence"], [])["status"] == "COMMITTED"
    # A real reload: the table's engine objects are gone; this is the state read back out of storage.
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    assert bool(_magic_marks(engine)) is sovereign
    if sovereign:
        (mark,) = _magic_marks(engine)
        assert mark.expires_on == _bears(engine.state.actors[FENCER], "needle_sovereign")[0].expires_on  # the Incarnation's own expiry
        assert all(isinstance(value, (int, str)) for value in mark.data.values() if not isinstance(value, dict))
        assert mark.data.get("kind") == "sovereign"
    foe = engine.state.actors[IRON]
    assert foe.resources[FOCUS] == 1  # "While holding Martial Focus"
    _pin(engine, ATTACK=20, DAMAGE=4)
    before = foe.current_hp
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Bi Shou (Dagger) attack" and c.actor_id == FENCER)
    session.submit_intent(ActionIntent(intent_id=f"auto82f1-reload-{sovereign}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=FENCER, target_ids=candidate.target_ids), primary_decision_record=None,
                          reaction_provider=None)
    after = CombatService(ROOT, tmp_path)._load_session(mid)   # the damage is read back from storage too
    lost = before - after.engine.state.actors[IRON].current_hp
    assert after.verify()["status"] == "PASS" and after.mechanical.replay()["status"] == "PASS"
    assert bool(_magic_marks(after.engine)) is sovereign  # and so is the mark that decided it
    return lost


def test_the_mark_survives_a_table_commit_and_a_reload_and_still_decides_the_defense(tmp_path):
    """The mark is ordinary fight state, so it must come back after a table commit and a reload from storage -- and the
    reloaded fight must reach the printed damage answer, whole against a "nonmagical" defence (AUTO82 review, checklist 7)."""
    magical = _hammered_after_a_reload(tmp_path / "sovereign", True)
    mundane = _hammered_after_a_reload(tmp_path / "plain", False)
    assert magical == mundane + 4 > mundane  # +4 is the Iron Fist's Proficiency Bonus, the reduction AUTO82's seam removes


# ----------------------------------------------------------------------------------- Traitorous Blade: the printed free hand
def _disarm(engine, *, catch=True, hold_the_other_hand=False):
    """A won Disarm by the fencer, with the printed catch offered or not. ``hold_the_other_hand`` fills the fencer's free hand
    through the documented hand_occupants seam, the way a second held item or a bound limb would. The subscriber is registered
    for this one call and removed again in ``finally``: a hook left in the global table would silently change every later
    engine in the process (AUTO82 review finding 3)."""
    if hold_the_other_hand:
        from combat.ext import _HOOKS

        def occupy(_engine, actor):
            return {} if actor.entity_id != FENCER else {"hand:right": "item:auto82.test"}

        subscribers = _HOOKS.setdefault("hand_occupants", [])
        subscribers.append(occupy)
    try:
        _pin(engine, ATTACK=20, SAVE=1, CHECK=20)
        _answers(engine, {"traitorous_blade": ("catch",) if catch else ("let_fall",), "traitorous_attack": ("pass",)})
        _use(engine, FENCER, "Bi Shou (Dagger) attack: Disarm")
    finally:
        if hold_the_other_hand:
            subscribers.remove(occupy)


def _caught_weapon(engine):
    """The weapon the catch put in the catcher's hand, as the fight records it."""
    foe = engine.state.actors[IRON]
    caught = [c for c in foe.conditions.values() if c.condition_id.endswith("disarmed") and (c.data or {}).get("held_by") == FENCER]
    return caught[0].data["disables_action"] if caught else None


def test_traitorous_blade_catches_the_disarmed_weapon_in_a_free_hand_and_says_which():
    engine = _duel(fencer_talents=["TAL_FENCING_TRAITOROUS_BLADE"])
    _disarm(engine)
    foe = engine.state.actors[IRON]
    assert _caught_weapon(engine) and _said(engine, "catches") and any(" in its " in str((e.payload or {}).get("trigger")) for e in engine.events
                                                                      if e.event_type == "PASSIVE_TRIGGERED")


@pytest.mark.parametrize("kit", [TWO_HANDED, VERSATILE], ids=["two_handed", "versatile"])
def test_traitorous_blade_catches_a_weapon_that_only_needs_two_hands_to_swing_with_one_free_hand(kit):
    """"... you have at least one free hand; the object can be held in that hand". A Two-Handed or Versatile weapon rests in one
    hand (combat/ext/hand_occupancy.py: a second hand is needed only to attack), so one free hand catches it. AUTO82 measured
    the hands needed to *attack* with it and refused a legal catch."""
    engine = _duel(fencer_talents=["TAL_FENCING_TRAITOROUS_BLADE"], subject_kit=kit)
    from combat.ext.hand_occupancy import holding_hands, weapon_requirement

    _disarm(engine)
    weapon = _caught_weapon(engine)
    assert weapon, "the catch was refused even though the weapon rests in one hand"
    assert holding_hands(engine, weapon) == 1
    assert weapon_requirement(engine, engine.action_catalog[weapon])[1] == 2  # the attack still needs both hands
    assert _said(engine, "catches")


def test_traitorous_blade_lets_the_weapon_fall_when_the_player_declines():
    engine = _duel(fencer_talents=["TAL_FENCING_TRAITOROUS_BLADE"])
    _disarm(engine, catch=False)
    foe = engine.state.actors[IRON]
    assert not [c for c in foe.conditions.values() if (c.data or {}).get("held_by") == FENCER]
    assert [c for c in foe.conditions.values() if c.condition_id.endswith("disarmed")]  # it is still on the ground


def test_traitorous_blade_refuses_the_catch_with_no_free_hand_and_says_why():
    engine = _duel(fencer_talents=["TAL_FENCING_TRAITOROUS_BLADE"])
    _disarm(engine, hold_the_other_hand=True)
    assert _caught_weapon(engine) is None
    assert _said(engine, "no free hand to catch")


def test_the_no_free_hand_case_does_not_leak_into_the_next_fight():
    """The hand_occupants subscriber above is registered for one call only: the same catch must still land afterwards, in the
    same process, whatever order the cases run in (AUTO82 review finding 3)."""
    filled = _duel(fencer_talents=["TAL_FENCING_TRAITOROUS_BLADE"])
    _disarm(filled, hold_the_other_hand=True)
    assert _caught_weapon(filled) is None
    afterwards = _duel(fencer_talents=["TAL_FENCING_TRAITOROUS_BLADE"])
    _disarm(afterwards)
    assert _caught_weapon(afterwards) is not None


def test_the_catch_is_a_pending_table_question_that_resumes_and_survives_a_reload(tmp_path, monkeypatch):
    """The catch is the player's decision, so at the table it must be asked, hold nothing, and be answerable afterwards.

    A real saved fight: the fencer wins a Disarm against a fighter holding a Two-Handed halberd, the question comes back as
    REACTION_REQUIRED with the fight unchanged, and answering it leaves the halberd in the fencer's hand after a reload from
    storage (AUTO82 review, checklist 7 and 9).
    """
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.gate5_service import CombatService
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight

    halberd = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.ji", "name": "Ji (Halberd)", "quantity": 1}]}}
    combat, table, mid = table_fight(tmp_path, ["TAL_FENCING_TRAITOROUS_BLADE"], cl=20, kit={"starting_kit": KIT},
                                     ask=True, ally_talents=[], kits={"right": halberd})
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"

    original = DeterministicRollAuthority.d20

    def forced(self, **kwargs):  # a sure hit on the attack, a failed save for the target
        roll = original(self, **kwargs)
        value = 20 if str(kwargs.get("reason") or "").startswith("ATTACK") else 1
        return roll.model_copy(update={"natural_result": value, "total": value + int(kwargs.get("modifier") or 0), "dice": (value,)})

    monkeypatch.setattr(DeterministicRollAuthority, "d20", forced)
    state, menu = table.state(mid), table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if "weapon.bi_shou#disarm" in g["source_definition_id"])
    candidate_id = group["options"][0]["candidate_id"]

    def send(answers):
        return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)

    before = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json")
    first = send([])
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.traitorous_blade"
    assert prompt["reactor"] == "Left" and "Traitorous Blade" in prompt["moment"] and "Right" in prompt["moment"]
    assert [option["id"] for option in prompt["choice"]["options"]] == ["catch", "let_fall"]
    assert any("right" in option["label"] for option in prompt["choice"]["options"])  # it names the hand it would use
    assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before  # nothing committed
    answers = [{**prompt["context"], "selection": "USE", "option_ids": ["catch"]}]
    second = send(answers)
    if second["status"] == "REACTION_REQUIRED":  # "you may use a Bonus Action to make one attack with it"
        assert second["reaction"]["context"]["reaction_source_id"] == "choice:needle.traitorous_attack"
        answers.append({**second["reaction"]["context"], "selection": "USE", "option_ids": ["pass"]})
        second = send(answers)
    assert second["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    caught = [c for c in loaded.engine.state.actors[RIGHT].conditions.values()
              if c.condition_id.endswith("disarmed") and (c.data or {}).get("held_by") == LEFT]
    assert caught and caught[0].data["disables_action"].endswith("weapon.ji")  # the Two-Handed halberd, in one hand
    assert "dropped_at" not in caught[0].data
    assert loaded.verify()["status"] == "PASS" and loaded.mechanical.replay()["status"] == "PASS"


# ----------------------------------------------------------------------------------- Vacuum Cut: the printed Attack action
def test_vacuum_cut_is_offered_only_on_the_printed_attack_action():
    engine = _duel(fencer_talents=["TAL_FENCING_VACUUM_CUT"])
    from combat.gate2_runtime_models import EconomyKind

    engine.state.actors[IRON].position = type(engine.state.actors[IRON].position)(x=5, y=6)  # 10 feet: beyond the dagger
    names = [getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates()
             if c.actor_id == FENCER]
    assert any(name and name.endswith(": Vacuum Cut") for name in names)
    from combat.ext.needle_vacuum import vacuum_variants

    info = {"owned": {"TAL_FENCING_VACUUM_CUT"}, "mechanics": {},
            "actions": [action for action in engine.action_catalog.values()
                        if action.owner_id == FENCER and action.economy == EconomyKind.BONUS_ACTION and "attack" in action.display_name]}
    assert vacuum_variants(info) is None  # "When you take the Attack action ...": never on a Bonus Action


def test_vacuum_cut_still_asks_the_game_master_about_a_turn_on_which_no_weapon_was_drawn():
    """The printed trigger has two halves: "When you take the Attack action" (the engine's, above) and "during the same turn
    that you draw or otherwise equip the weapon used for that attack" (the Game Master's). Nothing in the fight records when a
    weapon was drawn or equipped, so the second half must stay a GM line rather than be retired as done work (review finding 2)."""
    record = json.loads(AUTHORITY.read_text(encoding="utf-8"))["mechanics"]["TAL_FENCING_VACUUM_CUT"]
    assert record["coverage"] == "CORE_WITH_RIDERS" and len(record["riders"]) == 1
    line = record["riders"][0]
    assert "Game Master" in line and "drew or equipped" in line and "Attack action" in line


# ----------------------------------------------------------------------------------- the retired GM lines
def test_the_four_records_with_nothing_left_to_ask_carry_no_rider():
    mechanics = json.loads(AUTHORITY.read_text(encoding="utf-8"))["mechanics"]
    for key in ("TAL_FENCING_SHADOW_STRIKE", "TAL_FENCING_SOUL_STRIKE", "TAL_FENCING_EMPTY_HAND_OPEN_MERIDIAN",
                "TAL_FENCING_TRAITOROUS_BLADE"):
        assert mechanics[key]["riders"] == [] and mechanics[key]["coverage"] == "FULL", key
    # The printed "is a magical effect" sentence each of those three carried is still typed, as the row's own classification.
    for key in ("TAL_FENCING_SHADOW_STRIKE", "TAL_FENCING_SOUL_STRIKE", "TAL_FENCING_EMPTY_HAND_OPEN_MERIDIAN"):
        saves = [row for row in mechanics[key]["effects"] if row.get("type") == "save"]
        assert saves and saves[0]["mundane"] is False, key
    # Sovereign Needle Incarnation keeps exactly the one line the engine cannot reach: Fatal Thrust is not in the catalog.
    sovereign = mechanics["TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION"]
    assert len(sovereign["riders"]) == 1 and "Fatal Thrust" in sovereign["riders"][0]
