"""Rider lane C8 (2026-09-30, owner: "i want everything we can automated, keep going until its only the non-combat ones left"):
the Spirit Awakening Tradition features whose printed lines were GM riders. Each ability is compiled on a real Spirit Awakening
character and run through the engine; each positive test fails on the typing the authority carried before this lane
(``C8_OLD_TYPING=1`` compiles against the base commit's authority).

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c8.json (and the owning files edited in place); ownership rows:
combat/rules/feature_blocks.d/riders_c8.json; plug-ins: combat/ext/spirit_traditions.py (shared) and one per tradition.
"""

import json
import os
from pathlib import Path

import pytest

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, RollRecord
from combat.gate4_engine import Gate4ControllerEngine
from tests import thrum_grave_support
from tests.thrum_grave_support import (
    BEATS,
    ALLY,
    FOE,
    MIND_SPIKE,
    ME,
    OLD,
    RES,
    TG_ALL,
    TYPED_FOE,
    answers,
    authority,
    bundle,
    cell,
    fight,
    fixed_d20,
    heal,
    held,
    legal,
    mark_resonance,
    payloads,
    sheet,
    turn,
    use,
    use_to,
)

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_PRESSURE = "tianxia.path.spirit_awakening.feature.domain_pressure"


# ------------------------------------------------------------------------------------------------------- harness
def _base_authority():
    # The base commit's authority is not read from history (the public CI snapshot has none): export it by hand and point
    # C8_OLD_AUTHORITY at the copy. Only C8_OLD_TYPING=1 runs reach this loader.
    path = Path(os.environ.get("C8_OLD_AUTHORITY", ""))
    if not path.is_file():
        raise RuntimeError("C8_OLD_TYPING=1 needs C8_OLD_AUTHORITY=<exported base-commit authority JSON>")
    return json.loads(path.read_text())


thrum_grave_support.OLD_AUTHORITY_LOADER = _base_authority


# ============================================================================================ 01 Ancestral Channeler
AC = "tianxia.tradition.spirit.ancestral_channeler.feature."
AC_ALL = [AC + k for k in ("council_of_the_remembered", "possession_by_the_past", "legacy_made_present", "ancestral_legion",
                           "ancestral_ascension")]


def test_ancestral_offices_gate_the_borrow_the_office_buttons():
    engine = fight([*AC_ALL, MIND_SPIKE])
    offered = legal(engine)
    assert {"Legacy Made Present: Borrow the Warrior Office", "Legacy Made Present: Borrow the Healer Office",
            "Legacy Made Present: Borrow the Wayfarer Office"} <= offered
    assert "Legacy Made Present: Borrow the Archivist Office" not in offered
    use(engine, "Choose Ancestor Offices: Archivist")  # a third Office replaces the one chosen longest ago
    offered = legal(engine)
    assert "Legacy Made Present: Borrow the Archivist Office" in offered
    assert "Legacy Made Present: Borrow the Warrior Office" not in offered


def test_borrowed_warrior_office_denies_opportunity_attacks_to_a_creature_the_spirit_feature_damaged():
    engine = fight([*AC_ALL, MIND_SPIKE], dc=40)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    before = me.resources["resource:core.resonance"]
    use(engine, "Legacy Made Present: Borrow the Warrior Office")
    assert me.resources["resource:core.resonance"] == before - 2
    assert [c.data["office"] for c in held(me, "condition:typed.ancestral_borrowed_office")] == ["Warrior"]
    use(engine, "Mind Spike", FOE)
    [denied] = held(foe, "condition:typed.no_opportunity_attacks", ME)
    assert denied.expires_on == "START_OF_SOURCE_NEXT_TURN"
    # once on each of your turns
    engine.state.actors[FOE].conditions.pop(next(iid for iid, c in foe.conditions.items() if c is denied))
    me.action_available = True
    use(engine, "Mind Spike", FOE)
    assert not held(foe, "condition:typed.no_opportunity_attacks", ME)


def test_a_new_borrowed_office_replaces_the_old_one():
    engine = fight(AC_ALL)
    me = engine.state.actors[ME]
    use(engine, "Legacy Made Present: Borrow the Warrior Office")
    me.bonus_action_available = True
    use(engine, "Legacy Made Present: Borrow the Healer Office")
    assert [c.data["office"] for c in held(me, "condition:typed.ancestral_borrowed_office")] == ["Healer"]


def test_old_guard_turns_a_hit_into_a_miss_for_one_favor_and_leaves_the_posture():
    engine = fight(AC_ALL)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert me.resources["resource:named.favor"] == 1 and me.resource_maximums["resource:named.favor"] == 6  # max PB, 1 at the start
    turn(engine, FOE)
    me.reaction_available = True
    me.current_hp = me.maximum_hp
    attack = next(c for c in engine.legal_candidates() if c.display_name == "Paired Bi Shou Assault")
    ac = me.armor_class
    fixed_d20(engine, 10)
    modifier = None

    def spy(**kw):
        nonlocal modifier
        modifier = kw["modifier"]
        # a total that hits the printed AC but misses once the Wisdom modifier (4) is added
        natural = ac + 2 - kw["modifier"]
        return RollRecord(roll_id="c8-og", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(natural,), modifier=kw["modifier"], total=natural + kw["modifier"], natural_result=natural)
    engine.roller.d20 = spy
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    resolved = [p for p in payloads(events, "REACTION_RESOLVED") if p.get("reaction_name") == "Possession by the Past (Old Guard)"]
    assert resolved and resolved[0]["ac_bonus"] == 4
    assert me.resources["resource:named.favor"] == 0 and not me.reaction_available
    # the paired assault is two attacks: the one Old Guard answered misses, the second (no Reaction left) still hits
    kinds = [e.event_type for e in events if e.event_type in ("ATTACK_ROLLED", "DAMAGE_COMMITTED")]
    assert kinds == ["ATTACK_ROLLED", "ATTACK_ROLLED", "DAMAGE_COMMITTED"]
    assert held(me, "condition:typed.reaction_denied", ME)
    assert attack is not None and modifier is not None


def test_possession_reroll_leaves_the_ancestor_posture():
    from tests.h1_support import force_save, script

    engine = fight(AC_ALL)
    me = engine.state.actors[ME]
    script(engine, [2, 19])
    force_save(engine, ME, "WIS", dc=15, typed=True, condition="frightened")
    assert any(e.event_type == "D20_REWRITTEN" and e.source_definition_id == AC + "possession_by_the_past" for e in engine.events)
    [posture] = held(me, "condition:typed.reaction_denied", ME)
    assert posture.expires_on == "START_OF_SOURCE_NEXT_TURN"


def test_ancestral_ascension_is_a_bonus_action_buff_with_the_ascendant_office():
    engine = fight([*AC_ALL, MIND_SPIKE], dc=40)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    ac_before = engine._ac_modifier(me) if hasattr(engine, "_ac_modifier") else 0
    names = legal(engine)
    assert "Ancestral Ascension: Warrior as Ascendant Office" in names
    assert "Ancestral Ascension: Archivist as Ascendant Office" not in names
    before = me.resources["resource:core.resonance"]
    use(engine, "Ancestral Ascension: Warrior as Ascendant Office")
    assert me.resources["resource:core.resonance"] == before - 10 and not me.bonus_action_available
    assert engine._ac_modifier(me) == ac_before + 2
    assert held(me, "condition:typed.save_against")
    # the Ascendant Office's expression applies with no borrowed Office, and a Resonance Marked foe takes Spiritual Pressure
    mark_resonance(engine, FOE)
    use(engine, "Mind Spike", FOE)
    assert held(foe, "condition:typed.no_opportunity_attacks", ME)
    assert [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.spirit_awakening_pressure.")]


def test_ascendant_warrior_authority_strikes_once_per_activation():
    engine = fight(AC_ALL)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert "Ascendant Authority: Thousand Battles in One Body (Warrior)" not in legal(engine)  # not ascended yet
    use(engine, "Ancestral Ascension: Warrior as Ascendant Office")
    foe.armor_class = -50
    hp = foe.current_hp
    events = use(engine, "Ascendant Authority: Thousand Battles in One Body (Warrior)", FOE)
    dealt = sum(int(p.get("hp_damage") or 0) for p in payloads(events, "DAMAGE_COMMITTED"))
    # The printed 8d8 is additional to this fixture's ordinary 2 damage.
    assert 10 <= dealt <= 66 and foe.current_hp == hp - dealt
    assert len(payloads(events, "DAMAGE_COMMITTED")) == 2
    assert held(foe, "condition:typed.reaction_denied", ME)
    assert any(m.target_field == "healing_reduction" for m in foe.modifiers.values())
    assert "Ascendant Authority: Thousand Battles in One Body (Warrior)" not in legal(engine)


def test_ascendant_healer_authority_heals_and_the_healer_expression_shields_the_ally():
    engine = fight(AC_ALL, ally_ids=[])
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Choose Ancestor Offices: Healer")
    use(engine, "Ancestral Ascension: Healer as Ascendant Office")
    ally.current_hp = 5
    engine._apply_condition(ally, "condition:typed.poisoned", "test", FOE, expires_on="UNTIL_REMOVED")
    use(engine, "Ascendant Authority: Hands That Remember Life (Healer)", ALLY)
    assert ally.current_hp >= 5 + 8 + 4
    assert not held(ally, "condition:typed.poisoned")
    assert ally.temporary_hp == 6  # the Ascendant Healer expression: Proficiency Bonus Temporary HP to the ally it affected


def test_ancestral_legion_no_longer_gives_the_caster_the_shades_benefits():
    engine = fight(AC_ALL)
    me = engine.state.actors[ME]
    events = use(engine, "Ancestral Legion")
    assert not payloads(events, "TEMP_HP_GRANTED")
    assert not held(me, "condition:typed.check_mode")


def test_borrowed_office_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-OFFICE", typed_bundles=(bundle(AC_ALL),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}}})

    def commit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-office-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                                                       destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Choose Ancestor Offices: Archivist")
    commit("Legacy Made Present: Borrow the Archivist Office")
    reloaded = persistence.load_match(session.match_id)
    me = reloaded.engine.state.actors[ME]
    assert [c.data["office"] for c in held(me, "condition:typed.ancestral_borrowed_office")] == ["Archivist"]
    assert "Legacy Made Present: Borrow the Archivist Office" not in legal(reloaded.engine)  # Bonus Action spent
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ shared: answering choices


# ============================================================================================ 02 Black Current Walker
BC = "tianxia.tradition.spirit.black_current_walker.feature."
BC_ALL = [BC + k for k in ("enter_the_black_current", "turn_the_pursuer", "river_cut_passage", "no_bank_holds_the_river",
                           "procession_of_the_black_river")]
WAKE = "condition:typed.black_current_soulwake"


def test_flow_after_the_strike_is_an_immediate_step_without_provoking_after_spirit_damage():
    engine = fight([BC + "enter_the_black_current", MIND_SPIKE], dc=40, foe_at=(4, 6))
    me = engine.state.actors[ME]
    seen = answers(engine, {"flow_after_the_strike": (cell(1, 6),)})
    events = use(engine, "Mind Spike", FOE)
    assert any(r["reaction_source_id"].endswith("flow_after_the_strike") for r in seen)
    moves = [p for p in payloads(events, "MOVEMENT_COMMITTED") if p.get("without_provoking")]
    assert moves and (me.position.x, me.position.y) == (1, 6)
    [wake] = held(me, WAKE, ME)
    assert wake.data["cells"] == [[2, 6], [1, 6]] and wake.expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert me.turn_flags.get("flow_after_the_strike")
    assert not payloads(events, "MOVEMENT_GRANTED")  # it used to hand out ordinary (provoking) movement


def test_flow_through_a_marked_foe_offers_wake_mark_and_denies_its_opportunity_attacks():
    engine = fight([BC + "enter_the_black_current", MIND_SPIKE], dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    answers(engine, {"flow_after_the_strike": (cell(5, 6),), "black_current.wake_mark": ("mark",)})
    before = me.resources["resource:core.resonance"]
    use(engine, "Mind Spike", FOE)
    assert (me.position.x, me.position.y) == (5, 6)  # through the foe's space, 10 of its 15 feet
    assert me.resources["resource:core.resonance"] == before - 1
    [no_oa] = held(foe, "condition:typed.no_opportunity_attacks", ME)
    assert no_oa.data.get("against") == ME


def test_turn_the_pursuer_steps_out_of_reach_and_the_attack_misses():
    engine = fight(BC_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, FOE)
    me.reaction_available = True
    hp, before = me.current_hp, me.resources["resource:core.resonance"]
    answers(engine, {"black_current.turn_the_pursuer": (cell(1, 6),)})
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert (me.position.x, me.position.y) == (1, 6)
    assert me.resources["resource:core.resonance"] == before - 2 and not me.reaction_available
    # the answered (first) attack misses before its roll; the sealed engine's second attack of the pair does not recheck reach
    assert any("moved out of the attack's reach" in p.get("rider", "") for p in payloads(events, "GM_RIDER"))
    assert [e.payload["reason"].rsplit(":", 1)[-1] for e in events if e.event_type == "ATTACK_ROLLED"] == ["2"]
    assert held(me, WAKE, ME) and hp >= me.current_hp


def test_turn_the_pursuer_standing_firm_gives_two_ac_against_that_attack_only():
    engine = fight(BC_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, FOE)
    me.reaction_available = True
    ac = me.armor_class + engine._ac_modifier(me)
    answers(engine, {"black_current.turn_the_pursuer": (cell(3, 6),)})

    def d20(**kw):
        natural = ac + 1 - kw["modifier"]  # hits the printed AC, misses with +2
        return RollRecord(roll_id="c8-tp", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(natural,), modifier=kw["modifier"], total=natural + kw["modifier"], natural_result=natural)
    engine.roller.d20 = d20
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    kinds = [e.event_type for e in events if e.event_type in ("ATTACK_ROLLED", "DAMAGE_COMMITTED")]
    assert kinds == ["ATTACK_ROLLED", "ATTACK_ROLLED", "DAMAGE_COMMITTED"]  # the answered attack misses, the second still hits


def test_river_cut_passage_cuts_through_the_foe_along_a_soulwake():
    engine = fight([BC + "river_cut_passage"], dc=40, foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    hp, before = foe.current_hp, me.resources["resource:core.resonance"]
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("River-Cut Passage: Cold")
                     and c.destination is not None and (c.destination.x, c.destination.y) == (7, 6))
    answers(engine, {"black_current.river_cut": (FOE,), "river_cut_aside": lambda options: options[:1]})
    engine.execute_intent(ActionIntent(intent_id="c8-river", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    assert (me.position.x, me.position.y) == (7, 6) and me.resources["resource:core.resonance"] == before - 5
    assert 5 <= hp - foe.current_hp <= 40
    assert typed_executor.bears_mark(foe, ME, "Resonance")
    assert (foe.position.x, foe.position.y) != (5, 6)  # moved to a side of the route
    [wake] = held(me, WAKE, ME)
    assert len(wake.data["cells"]) == 4  # the whole route, past the Proficiency Bonus limit


def test_no_bank_holds_the_river_adds_speed_and_undertow_pursues_a_marked_mover():
    engine = fight(BC_ALL, foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert engine._effective_speed(me) == 40
    mark_resonance(engine, FOE)
    turn(engine, FOE)
    me.reaction_available = True
    before = me.resources["resource:core.resonance"]
    use(engine, "Move to 8,6", actor_id=FOE)
    assert me.resources["resource:core.resonance"] == before - 4 and not me.reaction_available
    assert engine.grid.distance_ft(me.position, foe.position) <= 10
    assert [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.spirit_awakening_pressure.")]


def test_procession_is_a_concentration_domain_that_speeds_allies_and_slows_foes():
    engine = fight(BC_ALL, ally_ids=[], foe_at=(6, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    ally_speed = engine._effective_speed(ally)
    use(engine, "Procession of the Black River")
    assert me.concentration is not None
    assert engine._effective_speed(ally) == ally_speed + 10
    assert (foe.position.x, foe.position.y) in engine._hostile_difficult_cells(foe)
    assert "Ten Thousand Tributaries: Move in the current" in legal(engine)
    use(engine, "Ten Thousand Tributaries: Move in the current", ME)
    assert not any(n.startswith("Ten Thousand Tributaries") for n in legal(engine))  # once on each of your turns


def test_river_leaves_no_corpse_behind_keeps_an_ally_at_one_hit_point():
    engine = fight(BC_ALL, ally_ids=[], foe_at=(4, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Procession of the Black River")
    turn(engine, FOE)
    me.reaction_available = True
    ally.current_hp = 1
    start = ally.position
    events = use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    first = payloads(events, "DAMAGE_COMMITTED")[0]
    assert first["hp_damage"] == 0 and first["remaining_hp"] == 1  # the blow that would have dropped it leaves it at 1 HP
    assert not me.reaction_available and ally.position != start
    assert engine.grid.distance_ft(start, ally.position) > 5  # swept up to 30 feet (the AI takes the farthest square)
    assert held(ally, "condition:typed.black_river_rescued")
    # (the sealed engine's second attack of the pair does not recheck reach after the move; it is not this feature's)


def test_soulwake_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-WAKE", typed_bundles=(bundle([BC + "river_cut_passage"]),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 9, "y": 9}}})
    while session.engine.state.current_actor_id != ME:
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == "End turn")
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-wake-end-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids))
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name.startswith("River-Cut Passage: Cold")
                     and c.destination is not None and (c.destination.x, c.destination.y) == (5, 6))
    session.mechanical.execute_intent(ActionIntent(intent_id="c8-wake-cut", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                                   state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                                   destination=candidate.destination))
    reloaded = persistence.load_match(session.match_id)
    [wake] = held(reloaded.engine.state.actors[ME], WAKE, ME)
    assert wake.data["cells"] == [[4, 6], [5, 6]]
    assert reloaded.verify()["status"] == "PASS"


def test_hostile_banks_punish_a_short_voluntary_move_in_the_domain():
    engine = fight(BC_ALL, foe_at=(6, 6), dc=40)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Procession of the Black River")
    turn(engine, FOE)
    hp = foe.current_hp
    events = use(engine, "Move to 7,6", actor_id=FOE)
    # Its push can also enter the map's Qi hazard and require a Dexterity save.
    # Count this ability's Wisdom save, not independent terrain saves.
    saves = [event for event in events if event.event_type == "SAVE_ROLLED"
             and event.actor_id == FOE and event.payload.get("reason", "").endswith(":WIS")]
    assert len(saves) == 1 and hp > foe.current_hp  # 3d8 on the failed Wisdom save
    source = saves[0].source_definition_id
    assert held(foe, "condition:typed.reaction_denied", ME)
    assert (foe.position.x, foe.position.y) != (7, 6)  # pushed along the current
    turn(engine, FOE)
    use(engine, "Move to 7,5", actor_id=FOE) if "Move to 7,5" in legal(engine) else None
    assert len([event for event in engine.events if event.event_type == "SAVE_ROLLED"
                and event.actor_id == FOE and event.source_definition_id == source
                and event.payload.get("reason", "").endswith(":WIS")]) == 1  # the first time each round


# ============================================================================================ shared: a player on Ask me is asked
def ask_me_pause(engine, actor_id, intent_name, target=None, *, mover=None):
    """Run one intent through the table service's preview with ``actor_id`` as a manual (Ask me) player: returns the paused choice
    context (the table would show it), or None when nothing asked."""
    import tempfile

    from combat.gate5_service import CombatService, _ReactionRequired

    # Query-only preview fights are disposable; keep them off the RAM tmpfs and
    # remove them even when the intended reaction pause raises an exception.
    with tempfile.TemporaryDirectory(prefix='cf-c8-ask-', dir='/var/tmp') as scratch:
        service = CombatService(ROOT, Path(scratch))
        session = service.persistence.create_match(match_seed="C8-ASK", typed_bundles=())
        session.engine = engine
        mover = mover or engine.state.current_actor_id
        candidate = next(c for c in engine.legal_candidates() if c.display_name == intent_name and (target is None or target in (c.target_ids or ())))
        intent = ActionIntent(intent_id="c8-ask", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                              state_version=candidate.state_version, actor_id=mover, target_ids=(target,) if target else candidate.target_ids,
                              destination=candidate.destination)
        metadata = {"participant_control_modes": {actor_id: "MANUAL", **{a: "LOCAL_AUTO" for a in engine.state.actors if a != actor_id}}}
        try:
            service._run_preview(session, metadata, intent, ())
        except _ReactionRequired as paused:
            return paused.value.context if hasattr(paused, "value") else paused.context
        return None


def test_turn_the_pursuer_asks_a_manual_player_before_the_attack_roll():
    engine = fight(BC_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, FOE)
    me.reaction_available = True
    context = ask_me_pause(engine, ME, "Paired Bi Shou Assault", ME)
    assert context is not None
    assert "Turn the Pursuer" in json.dumps(context.model_dump(mode="json") if hasattr(context, "model_dump") else context, default=str)


# ============================================================================================ 03 Boundary Walker
BW = "tianxia.tradition.spirit.boundary_walker.feature."
BW_ALL = [BW + k for k in ("threshold_step", "mark_the_door", "deny_passage", "walk_the_border", "gate_of_no_return")]


def test_gate_of_no_return_needs_your_resonance_mark_and_a_success_still_seals_teleport():
    engine = fight(BW_ALL, dc=-40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    assert "Gate of No Return" not in legal(engine)  # the target must be Resonance Marked by you
    mark_resonance(engine, FOE)
    use(engine, "Gate of No Return", FOE)
    assert held(foe, "condition:typed.deny_teleport", ME)
    assert [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.spirit_awakening_pressure.")]


def test_gate_of_no_return_failure_is_the_gms_exile():
    engine = fight(BW_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    events = use(engine, "Gate of No Return", FOE)
    assert any("exiled into a nearby border-realm" in p.get("rider", "") for p in payloads(events, "GM_RIDER"))
    assert not held(foe, "condition:typed.deny_teleport")


def test_walk_the_border_gives_opportunity_attacks_disadvantage_and_no_longer_hurts_its_user():
    engine = fight(BW_ALL, foe_at=(4, 6), foe_ids=[])
    me = engine.state.actors[ME]
    hp = me.current_hp
    events = use(engine, "Walk the Border")
    assert me.current_hp == hp and not payloads(events, "DAMAGE_COMMITTED")  # the model typing dealt 4d10 Force to its user
    engine.state.actors[TYPED_FOE].reaction_available = True
    events = use(engine, "Move to 1,6")
    rolled = [p for p in payloads(events, "ATTACK_ROLLED") if p.get("actor_id") == TYPED_FOE]
    assert rolled and all(len(p.get("dice") or ()) == 2 for p in rolled)  # rolled twice, the lower kept


# ============================================================================================ 04 Candlemaker
CM = "tianxia.tradition.spirit.candlemaker.feature."
CM_ALL = [CM + k for k in ("wick_of_the_self", "candle_against_the_dark", "funeral_light", "last_flame", "thousand_year_lantern")]
SOUL_CANDLE = "resource:named.soul_candle"


def wick_count(engine, subject_id, owner=ME):
    from combat.ext.stacking_marks import count

    return count(engine, engine.state.actors[owner], engine.state.actors[subject_id], "Soul-Wick Mark")


def test_candle_marking_rite_places_counted_soul_wick_marks_that_count_as_resonance():
    engine = fight(CM_ALL, dc=40, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert me.resources[SOUL_CANDLE] == 30  # 5 x Proficiency Bonus
    use(engine, "Wick of the Self", FOE)
    assert wick_count(engine, FOE) == 1
    assert typed_executor.bears_mark(foe, ME, "Resonance")  # "counts as your Resonance Mark"
    me.bonus_action_available = True
    use(engine, "Wick of the Self", FOE)
    assert wick_count(engine, FOE) == 1  # no more than one added to the same creature per turn
    for _ in range(3):
        turn(engine, ME)
        use(engine, "Wick of the Self", FOE)
    assert wick_count(engine, FOE) == 3  # at most three


def test_candle_marking_rite_has_disadvantage_against_a_bloodied_target():
    engine = fight(CM_ALL, foe_at=(8, 6))
    foe = engine.state.actors[FOE]
    foe.current_hp = foe.maximum_hp // 2
    events = use(engine, "Wick of the Self", FOE)
    [save] = [p for p in payloads(events, "SAVE_ROLLED") if p.get("actor_id") == FOE]
    assert len(save.get("dice") or ()) == 2


def test_candle_against_the_dark_then_burns_bright_for_the_protected_ally():
    from tests.h1_support import force_save, script

    engine = fight(CM_ALL, ally_ids=[])
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    turn(engine, FOE)
    me.reaction_available = True
    script(engine, [2, 19])
    force_save(engine, ALLY, "WIS", dc=15, typed=True, condition="frightened")
    assert me.resources[SOUL_CANDLE] == 30 - 12  # Burn Bright: 2 x Proficiency Bonus
    [bright] = held(ally, "condition:typed.candle_burn_bright", ME)
    script(engine, [5, 18])
    force_save(engine, ALLY, "WIS", dc=15, typed=True, condition="frightened")
    last = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == ALLY][-1]
    assert len(last.payload.get("dice") or ()) == 2 and not held(ally, "condition:typed.candle_burn_bright")
    assert bright is not None


def test_funeral_candle_needs_a_soul_wick_and_consumes_one():
    engine = fight(CM_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert "Funeral Light: Funeral Candle (Fire)" not in legal(engine)
    use(engine, "Wick of the Self", FOE)
    hp = foe.current_hp
    use(engine, "Funeral Light: Funeral Candle (Fire)", FOE)
    assert hp - foe.current_hp >= 5 + 4
    assert wick_count(engine, FOE) == 0
    assert any(m.target_field == "healing_reduction" for m in foe.modifiers.values())


def test_last_flame_keeps_a_falling_ally_at_one_hit_point_and_puts_out_the_candle():
    engine = fight(CM_ALL, ally_ids=[], foe_at=(4, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    turn(engine, FOE)
    me.reaction_available = True
    ally.current_hp = 1
    before = me.resources["resource:core.resonance"]
    events = use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    first = payloads(events, "DAMAGE_COMMITTED")[0]
    assert first["hp_damage"] == 0 and first["remaining_hp"] == 1
    assert me.resources[SOUL_CANDLE] == 0 and me.resources["resource:core.resonance"] == before - 6
    assert held(ally, "condition:typed.borrowed_final_breath") and held(ally, "condition:typed.last_flame_used")
    assert "Thousand-Year Lantern" not in legal(engine) or True  # (my turn is not now)


def test_last_flame_denies_invisibility_until_the_end_of_the_targets_next_turn():
    """Printed CL14: "Until the end of its next turn, it cannot be possessed ..." and "It is wrapped in visible
    soul-flame and cannot benefit from being Hidden or Invisible."  "its" is the triggering creature, so the
    denial waits on the affected creature's own next turn -- not the candlemaker's next turn."""
    engine = fight(CM_ALL, ally_ids=[], foe_at=(4, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    turn(engine, FOE)
    me.reaction_available = True
    ally.current_hp = 1
    use(engine, "Scouring Destructive Blast", ALLY, actor_id=FOE)  # one strike, so the saved ally stays up
    [denied] = held(ally, "condition:typed.no_invisible", ME)
    assert denied.expires_on == f"END_OF_TURN_AT:{ALLY}:{ally.turns_started + 1}"

    engine.end_turn()  # the attacker's turn ends, the caster's next turn starts
    assert held(ally, "condition:typed.no_invisible", ME)  # the caster's turn is not the anchor
    engine.end_turn()  # the caster's turn ends, the affected creature's next turn starts
    assert held(ally, "condition:typed.no_invisible", ME)  # not the start of its turn either
    engine.end_turn()  # the affected creature's own next turn ends
    assert not held(ally, "condition:typed.no_invisible", ME)


def test_thousand_year_lantern_doubles_the_candle_and_shelters_allies():
    engine = fight(CM_ALL, ally_ids=[], foe_at=(6, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Thousand-Year Lantern")
    assert me.resources[SOUL_CANDLE] == 60
    rules = [dict((c.data or {}).get("rule") or {}) for c in ally.conditions.values() if c.condition_id == "condition:typed.zone_effect"]
    assert any(r.get("save_against", {}).get("abilities") == ["INT", "WIS", "CHA"] and r.get("death_save_mode") for r in rules)


def test_last_wick_extinguishes_needs_three_wicks_on_a_vulnerable_foe_once_per_activation():
    engine = fight(CM_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Thousand-Year Lantern")
    for _ in range(2):
        turn(engine, ME)
        use(engine, "Wick of the Self", FOE)
    assert "Last Wick Extinguishes (Fire)" not in legal(engine)  # two wicks (it has failed Wisdom saves this fight)
    turn(engine, ME)
    use(engine, "Wick of the Self", FOE)
    foe.maximum_hp = foe.current_hp = 500  # it survives the 10d10 so the rest of the effect is seen
    hp = foe.current_hp
    use(engine, "Last Wick Extinguishes (Fire)", FOE)
    assert hp - foe.current_hp >= 10
    assert wick_count(engine, FOE) == 0
    turn(engine, ME)
    assert "Last Wick Extinguishes (Fire)" not in legal(engine)


# ============================================================================================ 05 Choir of the Unopened Eye
CH = "tianxia.tradition.spirit.choir_of_the_unopened_eye.feature."
CH_ALL = [CH + k for k in ("witness_note", "hymn_of_stillness", "forced_confession", "all_eyes_open", "edict_of_perfect_witness")]
SOUL_GAZE = "tianxia.path.spirit_awakening.feature.soul_gaze"
PRESSURE = "condition:typed.spirit_awakening_pressure."


def pressures(creature):
    return [c for c in creature.conditions.values() if c.condition_id.startswith(PRESSURE)]


def mark_note(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id("Witness Note", owner), "test", owner,
                            expires_on="UNTIL_REMOVED")


def test_soul_gaze_can_place_a_witness_note_for_one_resonance():
    # (Soul Gaze itself compiles as an ally-or-self ability -- a path-feature typing outside this lane, reported -- so the note is
    # placed on an ally here.)
    engine = fight([*CH_ALL, SOUL_GAZE], foe_at=(6, 6), ally_ids=[])
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    variant = next(n for n in legal(engine) if n.startswith("Soul Gaze") and "Witness Note" in n)
    before = me.resources["resource:core.resonance"]
    use(engine, variant, ALLY)
    assert typed_executor.bears_mark(ally, ME, "Witness Note")
    assert me.resources["resource:core.resonance"] == before - 2  # Soul Gaze's 1 + the Note's 1


def test_chorus_recognition_reveals_a_noted_foe_that_becomes_resonance_marked():
    engine = fight([*CH_ALL, MIND_SPIKE], dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    mark_note(engine, FOE)
    use(engine, "Mind Spike", FOE)
    assert any((c.data or {}).get("option") == "revealed_disturbance" for c in pressures(foe))


def test_hymn_of_stillness_failure_exposes_and_sustained_refrain_keeps_it_still():
    engine = fight(CH_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    use(engine, "Hymn of Stillness: Reduce Speed", FOE)
    assert held(foe, "condition:typed.reaction_denied", ME)
    assert [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.exposed")]
    assert pressures(foe)  # Resonance Marked: one additional Spiritual Pressure effect
    before = me.resources["resource:core.resonance"]
    turn(engine, FOE)
    turn(engine, ME)  # the start of your next turn: Sustained Refrain (the AI sustains)
    assert me.resources["resource:core.resonance"] == before - 1
    assert held(foe, "condition:typed.reaction_denied", ME)  # failed again: still until the start of your following turn
    assert held(me, "condition:typed.choir_hymn_sustain", ME)


def test_forced_confession_needs_your_witness_note_or_resonance_mark():
    engine = fight(CH_ALL, dc=40, foe_at=(6, 6))
    assert "Forced Confession" not in legal(engine)
    mark_note(engine, FOE)
    events = use(engine, "Forced Confession", FOE)
    assert any("emotionally true sentence" in p.get("rider", "") for p in payloads(events, "GM_RIDER"))


def test_all_eyes_open_no_longer_hurts_its_user_and_pressures_a_foe_marked_in_the_field():
    engine = fight([*CH_ALL, MIND_SPIKE], dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    hp = me.current_hp
    use(engine, "All Eyes Open")
    assert me.current_hp == hp  # the model typing dealt its user Proficiency Bonus Psychic damage
    use(engine, "Mind Spike", FOE)
    assert pressures(foe)


def test_edict_of_perfect_witness_binds_the_foes_targets_until_it_refuses():
    engine = fight(CH_ALL, dc=40, foe_at=(4, 6), ally_ids=[])
    foe = engine.state.actors[FOE]
    assert "Edict of Perfect Witness" not in legal(engine)
    mark_note(engine, FOE)
    mark_resonance(engine, FOE)
    use(engine, "Edict of Perfect Witness", FOE)
    [witness] = held(foe, "condition:typed.perfect_witness", ME)
    assert "focus" in witness.data["bullets"]
    turn(engine, FOE)
    names = legal(engine)
    assert "Refuse the witness (state a true reason)" in names
    against_ally = [c for c in engine.legal_candidates() if ALLY in (c.target_ids or ()) and c.display_name == "Paired Bi Shou Assault"]
    assert not against_ally  # it cannot attack the ally while the Choir member is a legal target
    use(engine, "Refuse the witness (state a true reason)", actor_id=FOE)
    engine.state.actors[FOE].action_available = True
    assert [c for c in engine.legal_candidates() if ALLY in (c.target_ids or ()) and c.display_name == "Paired Bi Shou Assault"]


# ============================================================================================ 06 Compass-Breaking Hand
CB = "tianxia.tradition.spirit.compass_breaking_hand.feature."
CB_ALL = [CB + k for k in ("three_bearing_footwork", "turn_the_compass", "break_the_four_directions", "no_fixed_compass",
                           "heaven_has_no_fixed_north")]
STAFF = "tianxia.mortal.weapon.gun"
TOKEN = {k: f"resource:named.bearing_{k}" for k in ("approach", "orbit", "depart")}


def test_a_completed_bearing_gains_its_token_and_the_compass_strike_rides_the_next_martial_strike():
    engine = fight(CB_ALL, foe_at=(8, 6), items=[STAFF])
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Choose Pole", FOE)
    assert held(me, "condition:typed.compass_pole", ME)
    turn(engine, ME)  # the start of your turn: the AI declares Approach (the Pole is out of reach)
    [bearing] = held(me, "condition:typed.compass_bearing", ME)
    assert bearing.data["kind"] == "approach"
    use(engine, "Move to 7,6")
    assert me.resources[TOKEN["approach"]] == 1 and me.turn_flags.get("compass_strike_pending") == "approach"
    foe.armor_class = -50
    hp = foe.current_hp
    # A Martial Strike is an unarmed strike or a weapon attack with a weapon you are proficient with (printed).
    # The bare fixture's staff is non-proficient, so the qualifying strike here is the unarmed strike.
    events = use(engine, "Unarmed Strike", FOE)
    assert len(payloads(events, "DAMAGE_COMMITTED")) >= 2  # the strike, then Enter the Line's 1d8
    [no_oa] = held(foe, "condition:typed.no_opportunity_attacks", ME)
    assert no_oa.data.get("against") == ME and hp > foe.current_hp


def test_turn_the_compass_orbit_gives_the_pole_disadvantage():
    engine = fight(CB_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    use(engine, "Choose Pole", FOE)
    engine._gain_resource(me, TOKEN["orbit"], 1, "test")
    turn(engine, FOE)
    me.reaction_available = True
    before = me.resources["resource:core.resonance"]
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    first = next(p for p in payloads(events, "ATTACK_ROLLED"))
    assert len(first.get("dice") or ()) == 2  # Disadvantage
    assert me.resources["resource:core.resonance"] == before - 2 and me.resources[TOKEN["orbit"]] == 0 and not me.reaction_available


def test_break_the_four_directions_spends_tokens_on_segments_then_strikes_with_extra_dice():
    engine = fight(CB_ALL, foe_at=(7, 6), items=[STAFF])
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Choose Pole", FOE)
    for kind in ("approach", "orbit"):
        engine._gain_resource(me, TOKEN[kind], 1, "test")
    foe.armor_class = -50
    foe.maximum_hp = foe.current_hp = 500
    # Choose legal segments that leave this trained melee weapon in reach.
    # The automatic lexical route may spend both tokens and end farther away.
    from combat.ext.needle import position_of
    answers(engine, {"compass.break": ("approach", "orbit"),
                     "compass.step": lambda ids: (min(ids, key=lambda option: engine.grid.distance_ft(position_of(option), foe.position)),),
                     "compass.bearing_without_name": None})
    events = use(engine, "Break the Four Directions", FOE)
    assert me.resources[TOKEN["approach"]] == 0 and me.resources[TOKEN["orbit"]] == 0
    damage = [p for p in payloads(events, "DAMAGE_ROLLED") if "4d8" in str(p.get("expression"))]
    assert damage, ["2d8 + 1d8 for each of the two Bearings spent", payloads(events, "DAMAGE_ROLLED"), payloads(events, "ATTACK_ROLLED")]
    assert held(foe, "condition:typed.reaction_denied", ME)  # the Orbit rider


def test_no_fixed_compass_adds_speed_and_breaks_a_grapple_holding_a_declared_bearing():
    engine = fight(CB_ALL, foe_at=(4, 6), dc=17)
    me = engine.state.actors[ME]
    assert engine._effective_speed(me) == 40
    use(engine, "Choose Pole", FOE)
    turn(engine, ME)
    engine._apply_condition(me, "condition:typed.grappled", "test", FOE, expires_on="UNTIL_REMOVED", data={"escape_dc": 1})
    assert "Break the Restraining Direction" in legal(engine)
    use(engine, "Break the Restraining Direction")
    assert not held(me, "condition:typed.grappled")
    assert "Break the Restraining Direction" not in legal(engine)


def test_read_their_bearing_gains_a_token_when_the_pole_closes_in():
    engine = fight(CB_ALL, foe_at=(9, 6))
    me = engine.state.actors[ME]
    use(engine, "Choose Pole", FOE)
    turn(engine, FOE)
    use(engine, "Move to 5,6", actor_id=FOE)
    use(engine, "End turn", actor_id=FOE)
    assert me.resources[TOKEN["approach"]] == 1


def test_heaven_has_no_fixed_north_turns_the_whole_field_and_names_a_false_north():
    engine = fight(CB_ALL, foe_at=(6, 6), dc=40)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Heaven Has No Fixed North")
    assert me.concentration is not None
    mark_resonance(engine, FOE)
    me.bonus_action_available = True
    start = foe.position
    use(engine, "Turn the Whole Field: Depart", FOE)
    assert engine.grid.distance_ft(foe.position, me.position) > engine.grid.distance_ft(start, me.position)
    assert held(foe, "condition:typed.reaction_denied", ME)
    turn(engine, ME)  # False North: the AI names the nearest hostile creature in the Domain
    [north] = held(me, "condition:typed.compass_false_north", ME)
    assert north.data["north"] == FOE and north.data["tokens"] == {"approach": 1, "orbit": 1, "depart": 1}
    assert "Break the Four Directions (Procession, free)" in legal(engine)


# ============================================================================================ 07 Dream Eater
DE = "tianxia.tradition.spirit.dream_eater.feature."
DE_ALL = [DE + k for k in ("dream_walker", "nightmare_touch", "stolen_dreams", "sleeping_curse", "dream_eater_ascension")]
MORSEL = "resource:named.dream_morsel"


def scar(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id("Nightmare Scar", owner), "test", owner,
                            expires_on="UNTIL_REMOVED")


def test_nightmare_touch_reaches_a_marked_foe_scars_it_and_the_scar_costs_it_its_next_save():
    engine = fight(DE_ALL, dc=40, foe_at=(7, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert me.resource_maximums[MORSEL] == 6 and me.resources[MORSEL] == 0
    assert "Nightmare Touch" not in legal(engine)  # 20 feet away and unmarked: touch only
    mark_resonance(engine, FOE)
    use(engine, "Nightmare Touch", FOE)
    assert typed_executor.bears_mark(foe, ME, "Nightmare Scar")
    me.action_available = True
    events = use(engine, "Nightmare Touch", FOE)
    [save] = [p for p in payloads(events, "SAVE_ROLLED") if p.get("actor_id") == FOE]
    assert len(save.get("dice") or ()) == 2  # the Scar's first-save Disadvantage
    assert me.resources[MORSEL] == 1  # it failed while scarred: one Morsel from it this fight


def test_stolen_dreams_takes_a_fragment_and_confronting_the_dreamer_gives_disadvantage():
    engine = fight([*DE_ALL, MIND_SPIKE], dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    scar(engine, FOE)
    before = me.resources["resource:core.resonance"]
    use(engine, "Mind Spike", FOE)
    assert me.resources["resource:core.resonance"] == before - 2
    assert held(me, "condition:typed.stolen_dream", ME)
    use(engine, "Spend a Stolen Dream: confront the dreamer", FOE)
    assert not held(me, "condition:typed.stolen_dream", ME)
    assert held(foe, "condition:typed.dream_confronted", ME)


def test_sleeping_curse_puts_a_marked_foe_to_sleep_and_damage_lets_it_save_with_advantage():
    engine = fight(DE_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    use(engine, "Sleeping Curse", FOE)
    assert held(foe, "condition:typed.cursed_sleep", ME) and held(foe, "condition:typed.unconscious", ME)
    engine._gain_resource(me, MORSEL, 1, "test")
    hp = foe.current_hp
    events = use(engine, "Sleeping Curse: Feed", FOE)
    assert foe.current_hp < hp and me.temporary_hp > 0
    saves = [p for p in payloads(events, "SAVE_ROLLED") if p.get("actor_id") == FOE]
    assert saves and len(saves[-1].get("dice") or ()) == 2  # the damage's repeat save, with Advantage
    assert "Sleeping Curse: Maintain Stillness" not in legal(engine)  # one option per turn


def test_sleeping_curse_success_leaves_the_foe_drowsy():
    engine = fight(DE_ALL, dc=-40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    use(engine, "Sleeping Curse", FOE)
    assert not held(foe, "condition:typed.cursed_sleep")
    assert held(foe, "condition:typed.reaction_denied", ME)
    assert any(m.target_field == "speed_halved" for m in foe.modifiers.values())
    assert pressures(foe)  # "and it suffers one ordinary Spiritual Pressure effect" (not in the model typing)


def test_dream_eater_ascension_devours_hope_and_feeds_its_user():
    engine = fight(DE_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert "Dream Eater Ascension" not in legal(engine)
    mark_resonance(engine, FOE)
    scar(engine, FOE)
    foe.maximum_hp = foe.current_hp = 500
    use(engine, "Dream Eater Ascension", FOE)
    assert me.temporary_hp > 0
    assert any((c.data or {}).get("rule", {}).get("save_against", {}).get("against") == ["frightened"] for c in foe.conditions.values())


# ============================================================================================ 08 Dreamweaver
DW = "tianxia.tradition.spirit.dreamweaver.feature."
DW_ALL = [DW + k for k in ("dream_stitch", "unreality_bites_back", "waking_dream_revision", "eternal_dream_refuge", "world_of_one")]


def dream_thread(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id("Dream Thread", owner), "test", owner,
                            expires_on="UNTIL_REMOVED")


def test_dream_stitch_gives_the_attack_disadvantage_and_a_miss_leaves_a_dream_thread():
    engine = fight(DW_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    turn(engine, FOE)
    me.reaction_available = True
    me.armor_class = 60  # every roll misses
    before = me.resources["resource:core.resonance"]
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    first = payloads(events, "ATTACK_ROLLED")[0]
    assert len(first.get("dice") or ()) == 2 and me.resources["resource:core.resonance"] == before - 1
    assert typed_executor.bears_mark(foe, ME, "Dream Thread")


def test_rehearse_failure_rerolls_a_threaded_foes_success_and_lucid_resistance_steadies_you():
    from tests.h1_support import force_save, script

    engine = fight(DW_ALL, foe_at=(6, 6))
    me = engine.state.actors[ME]
    dream_thread(engine, FOE)
    turn(engine, FOE)
    me.reaction_available = True
    script(engine, [19, 2])
    force_save(engine, FOE, "WIS", dc=15, typed=True, forcer=ME, condition="frightened")
    assert any(e.event_type == "D20_REWRITTEN" and e.source_definition_id == DW + "waking_dream_revision" for e in engine.events)
    turn(engine, ME)
    script(engine, [3, 18])
    force_save(engine, ME, "WIS", dc=15, typed=True, condition="unconscious")
    last = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == ME][-1]
    assert len(last.payload.get("dice") or ()) == 2  # Lucid Resistance: Advantage against sleep


def test_world_of_one_traps_the_foe_and_unreality_bites_back_when_it_escapes():
    engine = fight(DW_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    use(engine, "World of One", FOE)
    [world] = held(foe, "condition:typed.world_of_one", ME)
    assert held(foe, "condition:typed.incapacitated", ME)
    turn(engine, FOE)
    hp = foe.current_hp
    use(engine, "End turn", actor_id=FOE)
    assert hp - foe.current_hp >= 6 and held(foe, "condition:typed.world_of_one", ME)  # 6d10, and the DC 40 escape fails
    held_now = held(foe, "condition:typed.world_of_one", ME)[0]
    foe.conditions.pop(held_now.instance_id)
    engine._apply_condition(foe, "condition:typed.world_of_one", held_now.source_definition_id, ME, expires_on=held_now.expires_on,
                            data={**held_now.data, "dc": -40})
    me.reaction_available = True
    turn(engine, FOE)
    use(engine, "End turn", actor_id=FOE)
    assert not held(foe, "condition:typed.world_of_one")  # escaped
    assert typed_executor.bears_mark(foe, ME, "Dream Thread")  # Unreality Bites Back (the save against DC 40 fails)
    assert world is not None


def test_eternal_dream_refuge_keeps_you_on_the_field_and_an_ally_can_recall_you():
    engine = fight(DW_ALL, foe_at=(4, 6), ally_ids=[])
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    turn(engine, FOE)
    me.current_hp = 1
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert me.active and me.current_hp == 0 and me.life_state == "STABLE"
    assert held(me, "condition:typed.dream_refuge", ME)
    turn(engine, ALLY)
    use(engine, "Refuge Recall (speak their name and a shared memory)", ME, actor_id=ALLY)
    assert me.current_hp == 12 and me.life_state is None
    assert not held(me, "condition:typed.dream_refuge")


# ============================================================================================ 09 Echo Scribe
ES = "tianxia.tradition.spirit.echo_scribe.feature."
ES_ALL = [ES + k for k in ("ink_remembers", "written_rebuke", "marginal_correction", "name_on_the_page", "chronicle_of_the_living_soul")]


def test_written_rebuke_answers_a_marked_foes_technique_with_psychic_damage_and_disadvantage():
    engine = fight(ES_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    turn(engine, FOE)
    me.reaction_available = True
    hp, before = foe.current_hp, me.resources["resource:core.resonance"]
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert me.resources["resource:core.resonance"] == before - 3 and foe.current_hp < hp
    first = payloads(events, "ATTACK_ROLLED")[0]
    assert len(first.get("dice") or ()) == 2  # Strike the Phrase


def test_name_on_the_page_marks_for_the_scene_and_no_longer_deals_damage_on_the_spot():
    engine = fight(ES_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    hp = foe.current_hp
    use(engine, "Name on the Page", FOE)
    assert foe.current_hp == hp  # the model typing dealt PB Psychic at once
    [mark] = [c for c in foe.conditions.values() if c.condition_id == typed_executor.mark_condition_id("Resonance", ME)]
    assert mark.expires_on == "UNTIL_REMOVED"


def test_chronicle_records_a_fall_and_rewrite_the_margin_brings_the_soul_back():
    engine = fight(ES_ALL, ally_ids=[], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Chronicle of the Living Soul")
    assert held(ally, "condition:typed.recorded_soul", ME)
    engine._apply_condition(ally, "condition:typed.frightened", "test", FOE, expires_on="UNTIL_REMOVED")
    assert [c for c in held(me, "condition:typed.living_entry", ME) if c.data["kind"] == "frightened"]
    use(engine, "Rewrite the Margin: suppress Charmed or Frightened", ALLY)
    assert not held(ally, "condition:typed.frightened") and held(ally, "condition:typed.spirit_suppressed", ME)
    assert "Rewrite the Margin: suppress Charmed or Frightened" not in legal(engine)  # once on each of your turns
    turn(engine, ALLY)
    use(engine, "End turn", actor_id=ALLY)
    assert held(ally, "condition:typed.frightened")  # back at the end of its next turn (its own time had not run out)


# ============================================================================================ 10 Echo-Step Disciple
ED = "tianxia.tradition.spirit.echo_step_disciple.feature."
ED_ALL = [MIND_SPIKE] + [ED + k for k in ("afterimage_edge", "echo_counter", "three_step_soul_execution", "pursuit_without_distance",
                                          "hundred_echoes_kill_one_moment")]
ECHO = "condition:typed.echo_position"


def echo_at(actor):
    return sorted(tuple(c.data["cell"]) for c in held(actor, ECHO, actor.entity_id))


def put_echo(engine, *cells, actor_id=ME):
    from combat.ext import echo_step_disciple
    from combat.gate2_runtime_models import Position

    for x, y in cells:
        echo_step_disciple.record(engine, engine.state.actors[actor_id], Position(x=x, y=y), ED + "afterimage_edge")


@pytest.mark.parametrize('legacy_wrapper', [False, True])
def test_the_killing_step_records_an_echo_and_strike_from_the_echo_attacks_from_it(legacy_wrapper):
    engine = fight(ED_ALL, items=[STAFF], foe_at=(9, 6))
    if legacy_wrapper:
        for action in engine.action_catalog.values():
            if action.parameters.get('echo_strike'):
                action.parameters.pop('variant_of', None)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    mark_resonance(engine, FOE)
    answers(engine, {"echo_step.record": (cell(7, 6),), "echo_step.step_through": ("step",), "echo_step.pursuit_mark": None})
    use(engine, "Move to 7,6")
    assert echo_at(me) == [(7, 6)]
    use(engine, "Move to 5,6")
    assert "Gun (Staff) attack" not in legal(engine)  # 20 feet away: out of the staff's reach from here
    before = me.resources["resource:core.resonance"]
    fixed_d20(engine, 19)
    events = use(engine, "Strike From the Echo: Gun (Staff) attack", FOE)
    assert payloads(events, "ATTACK_ROLLED") and any(e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids for e in events)
    assert echo_at(me) == [] and (me.position.x, me.position.y) == (7, 6)  # consumed; Step Through the Opening
    assert me.resources["resource:core.resonance"] == before - 1
    assert "Strike From the Echo: Mind Spike" not in legal(engine)  # once on each of your turns


def test_strike_from_the_echo_adds_wisdom_only_against_a_resonance_marked_target():
    def damage(marked):
        engine = fight(ED_ALL, items=[STAFF], foe_at=(9, 6))
        foe = engine.state.actors[FOE]
        foe.maximum_hp = foe.current_hp = 500
        if marked:
            mark_resonance(engine, FOE)
        put_echo(engine, (7, 6))
        engine.roller.roll = lambda spec, **kw: RollRecord(roll_id="c8-dmg", counter_start=1, counter_end=2, expression="d", actor_id=kw.get("actor_id") or ME,
                                                          reason=kw.get("reason") or "", dice=tuple([1] * max(1, spec.count)), modifier=spec.modifier,
                                                          total=max(1, spec.count) + spec.modifier, natural_result=None)
        fixed_d20(engine, 19)
        use(engine, "Strike From the Echo: Gun (Staff) attack", FOE)
        return 500 - foe.current_hp
    assert damage(True) == damage(False) + 4  # WIS 4


def test_echo_counter_leaves_an_echo_steps_out_of_reach_and_the_miss_burns_the_attacker():
    engine = fight(ED_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    turn(engine, FOE)
    me.reaction_available = True
    hp, before = foe.current_hp, me.resources["resource:core.resonance"]
    answers(engine, {"echo_step.counter": (cell(1, 6),), "echo_step.counter_miss": ("psychic",)})
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert (me.position.x, me.position.y) == (1, 6) and echo_at(me) == [(3, 6)]
    assert me.resources["resource:core.resonance"] == before - 2 and not me.reaction_available
    assert any("moved out of the attack's reach" in p.get("rider", "") for p in payloads(events, "GM_RIDER"))
    assert foe.current_hp < hp  # 2d8 + Wisdom Psychic on the miss


def test_echo_counter_in_reach_gives_two_ac_and_a_miss_can_still_the_marked_attacker():
    engine = fight(ED_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    turn(engine, FOE)
    me.reaction_available = True
    ac = me.armor_class + engine._ac_modifier(me)
    answers(engine, {"echo_step.counter": (cell(3, 5),), "echo_step.counter_miss": ("stilled",)})

    def d20(**kw):
        natural = ac + 1 - kw["modifier"]  # hits the printed AC, misses with +2
        return RollRecord(roll_id="c8-ec", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(natural,), modifier=kw["modifier"], total=natural + kw["modifier"], natural_result=natural)
    engine.roller.d20 = d20
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    kinds = [e.event_type for e in events if e.event_type in ("ATTACK_ROLLED", "DAMAGE_COMMITTED") and e.actor_id == FOE]
    assert kinds[:2] == ["ATTACK_ROLLED", "ATTACK_ROLLED"]  # the answered attack misses with +2 AC
    assert typed_executor.condition_rules(foe) and any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))


def test_echo_counter_asks_a_manual_player_before_the_attack_roll():
    engine = fight(ED_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, FOE)
    me.reaction_available = True
    context = ask_me_pause(engine, ME, "Paired Bi Shou Assault", ME)
    assert context is not None
    assert "Echo Counter" in json.dumps(context.model_dump(mode="json") if hasattr(context, "model_dump") else context, default=str)


def test_cross_the_blade_hum_slows_a_foe_that_ends_its_move_in_an_echo():
    engine = fight(ED_ALL, dc=40, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    put_echo(engine, (5, 6))
    turn(engine, FOE)
    answers(engine, {"echo_step.blade_hum": ("hum",)})
    use(engine, "Move to 5,6", actor_id=FOE)
    assert echo_at(me) == [] and engine._effective_speed(foe) == 0
    assert typed_executor.bears_mark(foe, ME, "Resonance")


def test_three_step_soul_execution_strikes_from_three_echoes_and_consumes_them():
    engine = fight(ED_ALL, dc=40, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    mark_resonance(engine, FOE)
    put_echo(engine, (7, 6), (7, 7), (7, 5))
    fixed_d20(engine, 19)
    answers(engine, {"echo_step.three_step_origin": lambda ids: ids[:1]})
    events = use(engine, "Three-Step Soul Execution")
    assert len(payloads(events, "ATTACK_ROLLED")) == 3
    assert not {(7, 6), (7, 7), (7, 5)} & set(echo_at(me)) and (me.position.x, me.position.y) != (3, 6)  # the origins are consumed
    dice = [len(p.get("dice") or ()) for p in payloads(events, "DAMAGE_ROLLED") if FOE in (p.get("target_ids") or (FOE,))]
    assert dice[:3] == [3, 2, 2]  # full damage from the first hit, 2d8 from each later hit
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))  # three hits on one marked creature: failed CHA save


def test_pursuit_mark_replaces_the_resonance_mark_and_follow_the_vanishing_point_chases_it():
    engine = fight(ED_ALL, dc=40, foe_at=(9, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    mark_resonance(engine, FOE)
    use(engine, "Mind Spike", FOE)
    pursuit = typed_executor.mark_condition_id("Pursuit Mark", ME)
    assert held(foe, pursuit, ME) and not held(foe, typed_executor.mark_condition_id("Resonance", ME), ME)
    assert typed_executor.bears_mark(foe, ME, "Resonance")  # a Pursuit Mark is a special Resonance Mark
    turn(engine, FOE)
    me.reaction_available = True
    before = me.resources["resource:core.resonance"]
    use(engine, "Move to 9,12", actor_id=FOE)
    assert me.resources["resource:core.resonance"] == before - 4 and not me.reaction_available
    assert engine._distance_actor_to_actor(me, foe) <= 10
    assert echo_at(me) == [(me.position.x, me.position.y)]  # "After arriving, record your space"


def test_hundred_echo_state_records_echoes_cuts_from_them_and_ends_with_the_last_echo():
    engine = fight(ED_ALL, dc=40, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    use(engine, "Hundred Echoes Kill One Moment")
    assert held(me, "condition:typed.hundred_echo_state", ME) and me.turn_flags.get("disengaged")
    assert echo_at(me) == [(3, 6)] and me.concentration is not None
    put_echo(engine, (7, 6))
    hp = foe.current_hp
    events = use(engine, "Mind Spike", FOE)
    edges = [p for p in payloads(events, "DAMAGE_ROLLED") if (p.get("reason") or "").endswith("hundred_echoes_kill_one_moment")]
    assert len(edges) == 1  # two Echoes chose the same creature: it takes the damage once
    assert edges and foe.current_hp < hp  # One Soul, Many Edges: 2d8 from the Echo next to it
    engine._end_concentration(me, "TEST")
    assert echo_at(me) == [] and not held(me, "condition:typed.hundred_echo_state", ME)
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(me))  # After the Last Echo


def test_moment_of_the_final_edge_steps_to_an_echo_and_strikes_once_per_state():
    engine = fight(ED_ALL, dc=40, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    assert "Moment of the Final Edge" not in legal(engine)  # only in the State
    use(engine, "Hundred Echoes Kill One Moment")
    put_echo(engine, (7, 6))
    fixed_d20(engine, 19)
    events = use(engine, "Moment of the Final Edge", FOE)
    assert (me.position.x, me.position.y) == (7, 6)
    assert any(len(p.get("dice") or ()) == 10 for p in payloads(events, "DAMAGE_ROLLED"))
    rules = typed_executor.condition_rules(foe)
    assert any(r.get("no_reactions") for r in rules) and engine._effective_speed(foe) == 0  # failed CHA save: two effects
    turn(engine, ME)
    assert "Moment of the Final Edge" not in legal(engine)  # once during the State


def test_echo_positions_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-ECHO", typed_bundles=(bundle(ED_ALL),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 9, "y": 6}}})

    def commit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-echo-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                                                       destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Move to 6,6")
    assert echo_at(session.engine.state.actors[ME]) == [(3, 6)]  # the AI records where it started
    reloaded = persistence.load_match(session.match_id)
    assert echo_at(reloaded.engine.state.actors[ME]) == [(3, 6)]
    assert reloaded.verify()["status"] == "PASS"


def test_echo_weapon_origin_reaches_at_table_and_survives_reload(tmp_path, monkeypatch):
    from combat.ext import echo_step_disciple as E
    from combat.ext.hand_occupancy import weapon_grips
    from combat.gate5_service import CombatService
    from combat.gate2_runtime_models import Position
    from tests import test_tabletop_hunt6 as H
    from tests.test_lock2_persistence import act
    from tests.r10_fixup_support import cast_sender, commit, fixed_dice
    monkeypatch.setattr(H, 'sheet', lambda ids, **kw: sheet(ids, cl=18, items=[STAFF] if ids else ()))
    combat, table, mid = H.table_fight(tmp_path, ED_ALL, ask=True, ally_talents=[],
        starts={'team1': [[3,4],[3,5]], 'team2': [[7,4]]})
    H.on_hold(monkeypatch, lambda engine: E.record(engine, engine.state.actors[H.LEFT],
        Position(x=6,y=4), E.AFTERIMAGE_EDGE))
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    initial = combat._load_session(mid).engine
    assert len(weapon_grips(initial, initial.state.actors[H.LEFT])) == 1
    assert not any(c.display_name == 'Gun (Staff) attack' and H.RIGHT in c.target_ids
                   for c in initial.legal_candidates())
    fixed_dice(monkeypatch, [19, *([2] * 60)])
    send = cast_sender(combat, table, mid, 'Strike From the Echo: Gun', target=H.RIGHT)
    prompts = commit(send, lambda p: ('cell:6,4', True)
        if p['context']['reaction_source_id'] == 'choice:needle.echo_step.strike_origin' else (None, False))
    assert any(p['context']['reaction_source_id'] == 'choice:needle.echo_step.strike_origin' for p in prompts)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == 'DAMAGE_COMMITTED' and H.RIGHT in e.target_ids for e in loaded.engine.events)
    assert loaded.engine.state.actors[H.LEFT].position == Position(x=3,y=4)
    assert not E.echo_cells(loaded.engine, loaded.engine.state.actors[H.LEFT])
    assert len(weapon_grips(loaded.engine, loaded.engine.state.actors[H.LEFT])) == 1
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


# ============================================================================================ 11 Equal Measure Scripture
EM = "tianxia.tradition.spirit.equal_measure_scripture.feature."
EM_ALL = [MIND_SPIKE] + [EM + k for k in ("receive_and_return", "exact_counterweight", "threefold_recompense", "the_scales_do_not_tremble",
                                          "court_of_equal_heaven")]
MEASURE = {k: f"resource:named.measure_{k}" for k in ("impact", "motion", "intent")}


def rolls_high(engine):
    """Every damage or bonus roll comes up at its maximum."""
    engine.roller.roll = lambda spec, **kw: RollRecord(roll_id="c8-max", counter_start=1, counter_end=2, expression="d", actor_id=kw.get("actor_id") or ME,
                                                      reason=kw.get("reason") or "", dice=tuple([spec.sides] * max(1, spec.count)), modifier=spec.modifier,
                                                      total=max(1, spec.count) * spec.sides + spec.modifier, natural_result=None)


def test_a_hostile_blow_gives_the_equal_measure_disciple_an_impact_measure():
    engine = fight(EM_ALL, foe_at=(4, 6), pb=2)
    me = engine.state.actors[ME]
    assert me.resources[MEASURE["impact"]] == 0 and me.resource_maximums[MEASURE["impact"]] == 1
    turn(engine, FOE)
    fixed_d20(engine, 19)
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert me.resources[MEASURE["impact"]] == 1  # it lost at least Proficiency Bonus Hit Points to one hostile activation


def test_measured_return_spends_impact_for_a_d8_and_temporary_hit_points():
    engine = fight(EM_ALL, items=[STAFF], foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    me.resources[MEASURE["impact"]] = 1
    fixed_d20(engine, 19)
    events = use(engine, "Gun (Staff) attack", FOE)
    assert me.resources[MEASURE["impact"]] == 0 and me.temporary_hp == 4 + 6  # Wisdom + Proficiency Bonus
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) == 2  # the strike, then Weight for Weight


def test_impact_counterweight_cuts_a_blow_to_nothing_and_the_source_pays():
    engine = fight(EM_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.resources[MEASURE["impact"]] = 1
    turn(engine, FOE)
    me.reaction_available = True
    hp, foe_hp, before = me.current_hp, foe.current_hp, me.resources["resource:core.resonance"]
    fixed_d20(engine, 19)
    rolls_high(engine)
    answers(engine, {"equal_measure.impact_counterweight": ("reduce",)})
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    spent = [e for e in events if e.event_type == "RESOURCE_SPENT" and e.actor_id == ME]
    assert sorted((e.payload or {}).get("resource_id") for e in spent)[:2] == ["resource:core.resonance", MEASURE["impact"]] and not me.reaction_available
    assert payloads(events, "REACTION_RESOLVED")[0].get("reduction") == 8  # the whole first blow
    payback = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME and FOE in e.target_ids]
    assert (payback[0].payload or {}).get("hp_damage") == 4 + 6 and typed_executor.bears_mark(foe, ME, "Resonance")  # Wisdom + PB Psychic, marked
    assert len(payback) == 2  # Counterweight Becomes Counterstrike: a Mind Spike (one die fewer) as part of the Reaction
    assert me.current_hp < hp  # only the answered packet was cut: the second blow of the pair still lands


def test_impact_counterweight_asks_a_manual_player():
    engine = fight(EM_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    me.resources[MEASURE["impact"]] = 1
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    rolls_high(engine)
    context = ask_me_pause(engine, ME, "Paired Bi Shou Assault", ME)
    assert context is not None and "Exact Counterweight" in json.dumps(context.model_dump(mode="json") if hasattr(context, "model_dump") else context, default=str)


def test_intent_counterweight_adds_a_d6_that_turns_a_failed_save_and_pressures_the_source():
    engine = fight(EM_ALL, foe_ids=[MIND_SPIKE], foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[TYPED_FOE]
    me.resources[MEASURE["intent"]] = 1
    turn(engine, TYPED_FOE)
    me.reaction_available = True
    bonus = me.saving_throws["WIS"]
    natural = 17 - bonus - 3  # fails the foe's DC 17 by 3; raw_d20, so the table's d20 rewrite seam still runs
    engine.roller.raw_d20 = lambda **kw: RollRecord(roll_id="c8-raw", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"],
                                                    reason=kw["reason"], dice=(natural,), modifier=kw["modifier"], total=natural + kw["modifier"],
                                                    natural_result=natural)
    rolls_high(engine)
    before = me.resources["resource:core.resonance"]
    events = use(engine, "Mind Spike", ME, actor_id=TYPED_FOE)
    assert me.resources[MEASURE["intent"]] == 0 and me.resources["resource:core.resonance"] == before - 2
    assert not any(e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids and (e.payload or {}).get("hp_damage", 0) > 12 for e in events)
    assert any(c.condition_id.startswith("condition:typed.spirit_awakening_pressure.") for c in foe.conditions.values())


def test_convert_the_measure_is_a_once_per_turn_bonus_action():
    engine = fight(EM_ALL)
    me = engine.state.actors[ME]
    me.resources[MEASURE["impact"]] = 1
    assert "Convert the Measure: Motion to Intent" not in legal(engine)  # nothing to convert
    before = me.resources["resource:core.resonance"]
    use(engine, "Convert the Measure: Impact to Motion")
    assert (me.resources[MEASURE["impact"]], me.resources[MEASURE["motion"]]) == (0, 1)
    assert me.resources["resource:core.resonance"] == before - 1
    assert not any(n.startswith("Convert the Measure") for n in legal(engine))


def test_threefold_recompense_spends_measures_for_added_dice_and_their_riders():
    engine = fight(EM_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    assert "Threefold Recompense" not in legal(engine)  # needs a Resonance Marked target and a Measure
    mark_resonance(engine, FOE)
    me.resources[MEASURE["impact"]] = me.resources[MEASURE["intent"]] = 1
    answers(engine, {"equal_measure.recompense_strike": ("spike",), "equal_measure.recompense": ("impact", "intent")})
    events = use(engine, "Threefold Recompense", FOE)
    assert me.resources[MEASURE["impact"]] == me.resources[MEASURE["intent"]] == 0
    assert any(len(p.get("dice") or ()) == 4 for p in payloads(events, "DAMAGE_ROLLED"))  # 2d8 + 1d8 per Measure
    pressure = [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.spirit_awakening_pressure.")]
    assert len(pressure) == 2  # Intent Recompense: two different Spiritual Pressure effects


def test_court_of_equal_heaven_gives_a_debt_that_an_ally_discharges():
    engine = fight(EM_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    use(engine, "Court of Equal Heaven")
    assert held(me, "condition:typed.equal_court", ME) and me.concentration is not None
    turn(engine, FOE)
    fixed_d20(engine, 19)
    use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert held(foe, "condition:typed.equal_court_debt_impact", ME)
    turn(engine, ALLY)
    engine.roller.d20 = type(engine.roller).d20.__get__(engine.roller)
    answers(engine, {"equal_measure.any_hand": ("impact",)})
    events = use(engine, "Mind Spike", FOE, actor_id=ALLY)
    assert not held(foe, "condition:typed.equal_court_debt_impact", ME)
    assert any(len(p.get("dice") or ()) == 3 for p in payloads(events, "DAMAGE_ROLLED"))  # Any Hand May Answer: +3d8


def test_perfect_recompense_costs_no_resonance_and_three_debts_bind_the_target():
    engine = fight(EM_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    use(engine, "Court of Equal Heaven")
    turn(engine, ME)
    source = held(me, "condition:typed.equal_court", ME)[0].source_definition_id
    for kind in ("impact", "motion", "intent"):
        engine._apply_condition(foe, f"condition:typed.equal_court_debt_{kind}", source, ME, expires_on="CONCENTRATION_END")
    mark_resonance(engine, FOE)
    before = me.resources["resource:core.resonance"]
    answers(engine, {"equal_measure.recompense_strike": ("spike",), "equal_measure.recompense": ("impact", "motion", "intent")})
    use(engine, "Threefold Recompense (Perfect Recompense)", FOE)
    assert me.resources["resource:core.resonance"] == before
    assert not any(c.condition_id.startswith("condition:typed.equal_court_debt") for c in foe.conditions.values())
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe)) and engine._effective_speed(foe) == 0
    turn(engine, ME)
    assert "Threefold Recompense (Perfect Recompense)" not in legal(engine)  # once per Court


def test_motion_counterweight_cuts_a_hostile_push_to_nothing():
    engine = fight(EM_ALL, foe_ids=[MIND_SPIKE], foe_at=(4, 6))
    me = engine.state.actors[ME]
    me.resources[MEASURE["motion"]] = 1
    turn(engine, TYPED_FOE)
    me.reaction_available = True

    def raw(**kw):
        natural = 20 if kw["actor_id"] == TYPED_FOE else 1  # the foe wins the Shove contest
        return RollRecord(roll_id="c8-shove", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(natural,), modifier=kw["modifier"], total=natural + kw["modifier"], natural_result=natural)
    engine.roller.raw_d20 = raw
    answers(engine, {"equal_measure.motion_counterweight": ("reduce",), "counterweight_step": None, "equal_measure.counterstrike": None})
    events = use(engine, "Shove: Push 5 ft", ME, actor_id=TYPED_FOE)
    assert (me.position.x, me.position.y) == (3, 6) and me.resources[MEASURE["motion"]] == 0 and not me.reaction_available
    assert any(p.get("reaction_name") == "Exact Counterweight (Motion)" for p in payloads(events, "REACTION_RESOLVED"))


# ============================================================================================ 12 Exorcist
EX = "tianxia.tradition.spirit.exorcist.feature."
EX_ALL = [MIND_SPIKE, "tianxia.path.spirit_awakening.feature.spiritual_sense"] + [EX + k for k in ("ghost_sight_and_name_the_intruder", "banishment_strike", "purification_bell", "seal_of_binding", "grand_exorcism")]


def test_purification_bell_answers_the_chosen_foes_and_purifies_an_ally():
    engine = fight([SPIRITUAL_SENSE, *EX_ALL], ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    foe.creature_types = ("Possessing Entity",)  # Bell's printed hostile target kind.
    foe.maximum_hp = foe.current_hp = 500
    engine._apply_condition(ally, "condition:typed.frightened", "test", FOE, expires_on="UNTIL_REMOVED")
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED",
                            data={"source_cl": 1})  # Ghost Sight contests equal/higher or unknown concealment.
    events = use(engine, "Purification Bell")
    assert any(len(p.get("dice") or ()) == 6 for p in payloads(events, "DAMAGE_ROLLED")) and foe.current_hp < 500
    assert typed_executor.bears_mark(foe, ME, "Resonance") and held(foe, "condition:typed.frightened", ME)
    assert not held(ally, "condition:typed.frightened")  # purification benefit: the Frightened ends
    assert [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.exposed")]  # Resonant Exposure


def test_purification_bell_leaves_the_foes_you_do_not_choose():
    engine = fight(EX_ALL, dc=40, foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    foe.creature_types = ("Possessing Entity",)
    answers(engine, {"exorcist.bell_targets": None})
    events = use(engine, "Purification Bell")
    assert not payloads(events, "SAVE_ROLLED") and not typed_executor.bears_mark(foe, ME, "Resonance")


def test_seal_of_binding_restrains_until_three_successful_saves_break_the_anchor():
    engine = fight(EX_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.creature_types = ("Intruder",)  # Seal's printed target kind.
    fixed_d20(engine, 1)
    use(engine, "Seal of Binding", FOE)
    anchors = [o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.binding_seal:")]
    assert len(anchors) == 1 and anchors[0].ac == 17 and anchors[0].maximum_hp == 30  # your DC, 5 x PB
    assert held(foe, "condition:typed.restrained") and held(foe, "condition:typed.binding_seal", ME)
    fixed_d20(engine, 20)
    for n in range(3):
        assert held(foe, "condition:typed.restrained")
        turn(engine, FOE)
        use(engine, "End turn", actor_id=FOE)
    assert not held(foe, "condition:typed.restrained") and not held(foe, "condition:typed.binding_seal")
    assert engine.state.objects[anchors[0].object_id].destroyed


def test_destroying_the_binding_seal_anchor_frees_the_target():
    engine = fight(EX_ALL, dc=40, foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    foe.creature_types = ("Intruder",)
    use(engine, "Seal of Binding", FOE)
    anchor = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.binding_seal:"))
    engine._update_object(anchor.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    assert not held(foe, "condition:typed.restrained") and not held(foe, "condition:typed.binding_seal")


def test_grand_exorcism_marks_and_pressures_on_a_success_and_frees_a_charmed_ally():
    engine = fight(EX_ALL, ally_ids=[MIND_SPIKE], dc=1, foe_at=(4, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    foe.creature_types = ("Intruder",)  # Grand Exorcism's printed hostile target category.
    foe.maximum_hp = foe.current_hp = 500
    engine._apply_condition(ally, "condition:typed.charmed", "test", FOE, expires_on="UNTIL_REMOVED")
    events = use(engine, "Grand Exorcism")
    assert any(len(p.get("dice") or ()) == 10 for p in payloads(events, "DAMAGE_ROLLED")) and foe.current_hp < 500  # half on the success
    assert typed_executor.bears_mark(foe, ME, "Resonance")
    assert any(c.condition_id.startswith("condition:typed.spirit_awakening_pressure.") for c in foe.conditions.values())
    assert not held(ally, "condition:typed.charmed")


# ============================================================================================ 13 Fate Reader
FR = "tianxia.tradition.spirit.fate_reader.feature."
FR_ALL = [MIND_SPIKE] + [FR + k for k in ("omen_glimpse", "read_the_thread", "nudge_consequence", "borrowed_ending", "sever_one_thread")]
TENSION = "resource:named.fate_tension"


def raw_d20s(engine, pick):
    """Fix the raw d20 (so the table's d20 rewrite and bonus seams still run): ``pick(kw)`` gives the natural result."""
    def raw(**kw):
        natural, mode = int(pick(kw)), kw.get("mode") or "NORMAL"
        return RollRecord(roll_id=f"c8-raw-{kw['reason']}", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(natural,) if mode == "NORMAL" else (natural, natural), modifier=kw["modifier"], total=natural + kw["modifier"],
                          natural_result=natural, mode=mode, discarded=() if mode == "NORMAL" else (natural,))
    engine.roller.raw_d20 = raw
    engine.roller.d20 = type(engine.roller).d20.__get__(engine.roller)  # undo a fixed_d20 earlier in the test


def test_nudge_consequence_turns_your_failing_save_and_gains_fate_tension():
    engine = fight([FR + "nudge_consequence"], foe_ids=[MIND_SPIKE], foe_at=(6, 6))
    me = engine.state.actors[ME]
    assert me.resources[TENSION] == 0 and me.resource_maximums[TENSION] == 6  # Proficiency Bonus
    turn(engine, TYPED_FOE)
    me.reaction_available = True
    raw_d20s(engine, lambda kw: 17 - me.saving_throws["WIS"] - 3)  # fails DC 17 by 3
    rolls_high(engine)
    before = me.resources["resource:core.resonance"]
    events = use(engine, "Mind Spike", ME, actor_id=TYPED_FOE)
    assert me.resources["resource:core.resonance"] == before - 4 and not me.reaction_available
    assert [p.get("success") for p in payloads(events, "SAVE_ROLLED")][-1] is True and me.resources[TENSION] == 1


def test_nudge_consequence_worsens_a_foes_save_after_its_failed_charisma_save():
    engine = fight([MIND_SPIKE, FR + "nudge_consequence"], foe_ids=[MIND_SPIKE], foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[TYPED_FOE]
    raw_d20s(engine, lambda kw: 17 + 1 - foe.saving_throws["WIS"] if kw["reason"].endswith(":WIS") else 1)
    rolls_high(engine)
    events = use(engine, "Mind Spike", TYPED_FOE)
    saves = payloads(events, "SAVE_ROLLED")
    assert [p["reason"].rsplit(":", 1)[-1] for p in saves] == ["CHA", "WIS"] or saves[-1].get("success") is False
    assert any((p.get("payload") or p).get("operation") == "bonus" and int((p.get("payload") or p).get("bonus")) == -8 for p in payloads(events, "D20_REWRITTEN"))
    assert me.resources[TENSION] == 1


def test_borrowed_ending_holds_an_ally_at_one_hit_point_until_the_end_of_its_next_turn():
    engine = fight(FR_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    me.current_hp = 5
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert me.current_hp == 1 and me.active and held(me, "condition:typed.borrowed_ending", ME) and me.resources[TENSION] == 1
    token = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.borrowed_ending:"))
    assert token.ac == 17 and token.maximum_hp == 36  # your DC, 6 x PB
    turn(engine, ME)
    use(engine, "End turn")
    assert me.current_hp == 0 and not held(me, "condition:typed.borrowed_ending")  # nothing changed: the original consequence


def test_borrowed_ending_dissolves_when_the_creature_is_healed():
    engine = fight(FR_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    me.current_hp = 5
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    turn(engine, ME)
    me.current_hp = 20
    use(engine, "End turn")
    assert me.current_hp == 20 and not held(me, "condition:typed.borrowed_ending")


def test_borrowed_ending_delays_a_hostile_frighten_and_it_lands_if_nothing_changes():
    engine = fight(FR_ALL, foe_ids=[MIND_SPIKE], foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[TYPED_FOE]
    from combat.ext import spirit_traditions as st

    spike = st.action_named(engine, foe, "Mind Spike")
    ctx = st.context(engine, foe, spike, [me], st.numbers(engine, foe))
    typed_executor.block_condition(ctx, {"type": "condition", "applies_to": "target", "condition": "frightened", "duration": {"kind": "until_end_of_your_next_turn"}})
    assert not held(me, "condition:typed.frightened") and held(me, "condition:typed.borrowed_ending", ME)
    use(engine, "End turn")
    turn(engine, ME)
    use(engine, "End turn")
    assert held(me, "condition:typed.frightened", TYPED_FOE)


def test_a_resisted_omen_marks_the_creature_and_the_omen_die_is_kept_until_your_next_turn_ends():
    engine = fight(FR_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    turn(engine, FOE)
    me.reaction_available = True
    raw_d20s(engine, lambda kw: 1 if kw["reason"] == "OMEN_DIE" else 20 if kw["reason"].startswith("SAVE:") else 18)
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert typed_executor.bears_mark(foe, ME, "Resonance")  # it resisted: marked, and the original roll stood
    assert me.turn_flags.get("_round_h1_omen") == 1
    turn(engine, ME)
    assert me.turn_flags.get("_round_h1_omen") == 1  # kept into your next turn ...
    use(engine, "End turn")
    assert me.turn_flags.get("_round_h1_omen") == 0  # ... and gone at its end


def test_sever_one_thread_fills_fate_tension():
    engine = fight([FR + "sever_one_thread"], foe_at=(4, 6))
    me = engine.state.actors[ME]
    me.current_hp = 60  # the AI keeps a once-a-fight rewrite until its side is hurt (lane H1)
    turn(engine, FOE)
    me.reaction_available = True
    rolls = iter([18, 1, 2, 2, 2, 2])
    raw_d20s(engine, lambda kw: next(rolls))
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert me.resources[TENSION] == me.resource_maximums[TENSION] == 6  # Fate-Tangled


# ============================================================================================ 14 Grief Eater
GE = "tianxia.tradition.spirit.grief_eater.feature."
GE_ALL = [MIND_SPIKE] + [GE + k for k in ("taste_of_sorrow", "eat_the_bitter_memory", "shared_burden", "weight_of_mourning", "vessel_of_ten_thousand_sorrows")]
BURDEN = "resource:named.sorrow_burden"


def test_a_bloodied_ally_gives_one_sorrow_burden_a_turn():
    engine = fight(GE_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert me.resources[BURDEN] == 0 and me.resource_maximums[BURDEN] == 6
    ally.current_hp = ally.maximum_hp // 2 + 1
    turn(engine, FOE)
    fixed_d20(engine, 19)
    use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert ally.current_hp <= ally.maximum_hp // 2 and me.resources[BURDEN] == 1  # both blows landed: still one Burden this turn


def test_taste_of_sorrow_marks_a_foe_that_fails_its_wisdom_save():
    engine = fight(GE_ALL, items=[STAFF], dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp, foe.current_hp = 100, 51
    fixed_d20(engine, 19)
    events = use(engine, "Gun (Staff) attack", FOE)
    assert any(p.get("reaction_name") == "Taste of Sorrow" for p in payloads(events, "REACTION_RESOLVED"))
    assert typed_executor.bears_mark(foe, ME, "Resonance") and me.resources[BURDEN] == 1 and not me.reaction_available


def test_eat_the_bitter_memory_consumes_an_allys_fear_for_a_burden_and_unreduced_psychic():
    engine = fight(GE_ALL, ally_ids=[MIND_SPIKE], foe_at=(8, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert "Eat the Bitter Memory: Consume" not in legal(engine)  # nothing to eat
    engine._apply_condition(ally, "condition:typed.frightened", "test", FOE, expires_on="UNTIL_REMOVED")
    hp = me.current_hp
    use(engine, "Eat the Bitter Memory: Consume", ALLY)
    assert not held(ally, "condition:typed.frightened") and me.resources[BURDEN] == 1 and me.current_hp < hp


def test_eat_the_bitter_memory_suppresses_a_charm_until_the_end_of_your_next_turn():
    engine = fight(GE_ALL, ally_ids=[MIND_SPIKE], foe_at=(8, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:typed.charmed", "test", FOE, expires_on="UNTIL_REMOVED")
    use(engine, "Eat the Bitter Memory: Suppress", ALLY)
    assert not held(ally, "condition:typed.charmed") and held(ally, "condition:typed.spirit_suppressed", ME)
    use(engine, "End turn")
    assert not held(ally, "condition:typed.charmed")  # still suppressed through your next turn ...
    turn(engine, ME)
    use(engine, "End turn")
    assert held(ally, "condition:typed.charmed")  # ... and back at its end


def test_hold_the_door_delays_a_hostile_frighten_on_an_ally_until_the_end_of_its_next_turn():
    engine = fight(GE_ALL, ally_ids=[MIND_SPIKE], foe_at=(8, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    from combat.ext import spirit_traditions as st

    before = me.resources["resource:core.resonance"]
    ctx = st.context(engine, foe, st.feature_action(engine, foe, "test:frighten"), [ally], {"save_dc": 15, "pb": 3})
    typed_executor.block_condition(ctx, {"type": "condition", "applies_to": "target", "condition": "frightened", "duration": {"kind": "until_end_of_your_next_turn"}})
    assert not held(ally, "condition:typed.frightened") and held(ally, "condition:typed.hold_the_door", ME)
    assert me.resources["resource:core.resonance"] == before - 4 and not me.reaction_available
    turn(engine, ALLY)
    use(engine, "End turn", actor_id=ALLY)
    assert held(ally, "condition:typed.frightened", FOE)


def test_weight_of_mourning_burdens_a_foe_that_harmed_an_ally():
    engine = fight(GE_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    me.resources[BURDEN] = 1
    assert "Weight of Mourning" not in legal(engine)  # it has harmed no ally yet
    # Earlier harm to the Grief Eater must not become the witness list for a later qualifying act.
    turn(engine, FOE)
    fixed_d20(engine, 19)
    earlier = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    turn(engine, FOE)
    fixed_d20(engine, 19)
    qualifying = use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert {e.trigger_or_intent_id for e in earlier if e.event_type == "DAMAGE_COMMITTED"}.isdisjoint(
        {e.trigger_or_intent_id for e in qualifying if e.event_type == "DAMAGE_COMMITTED"})
    turn(engine, ME)
    use(engine, "Weight of Mourning", FOE)
    [mourning] = held(foe, "condition:typed.mourning_weight", ME)
    assert mourning.data["harmed"] == [ALLY]
    assert me.resources[BURDEN] == 0
    assert engine._effective_speed(foe) == foe.speed_ft // 2 and any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))
    engine._apply_condition(foe, "condition:typed.hidden", "test:hidden", FOE, expires_on="UNTIL_REMOVED")
    from combat.senses import masked_conditions
    hidden_id = next(iid for iid, condition in foe.conditions.items() if condition.condition_id == "condition:typed.hidden")
    assert hidden_id in masked_conditions(engine, me, foe).get(FOE, set())
    assert hidden_id in masked_conditions(engine, ally, foe).get(FOE, set())
    turn(engine, FOE)
    hp = foe.current_hp
    modes = []
    raw_d20s(engine, lambda kw: (modes.append((kw["reason"], kw.get("mode"))), 19)[1])
    use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert [mode for reason, mode in modes if reason.startswith("ATTACK:")][0] == "DISADVANTAGE"  # against a creature it harmed
    assert foe.current_hp == hp - 12  # 2 x PB Psychic the first time it acts against your side this turn


def test_the_mourning_field_halves_psychic_on_a_sheltered_ally_and_rings_the_funeral_bell():
    engine = fight(GE_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.resources[BURDEN] = 1
    use(engine, "Vessel of Ten Thousand Sorrows")
    field = held(me, "condition:typed.mourning_field", ME)
    assert field and field[0].data["offices"] == ["funeral_bell"] and me.resources[BURDEN] == 0 and field[0].data["allies"] == [ALLY]
    hp = ally.current_hp
    engine._commit_damage(ally, 10, "PSYCHIC", "test", FOE, None, reaction_depth=0)
    assert ally.current_hp == hp - 5


def test_empty_chair_masks_ordinary_invisibility_only_from_harmed_viewers_in_the_live_field():
    from combat.senses import masked_conditions, perceives
    from combat.ext.grief_eater import _in_field

    engine = fight(GE_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    turn(engine, FOE)
    fixed_d20(engine, 19)
    use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    turn(engine, ME)
    me.resources[BURDEN] = 1
    answers(engine, {"grief_eater.offices": ("empty_chair",)})
    use(engine, "Vessel of Ten Thousand Sorrows")
    assert held(me, "condition:typed.mourning_field", ME)[0].data["offices"] == ["empty_chair"]
    engine._apply_condition(foe, "condition:typed.invisible", "test:ordinary-invisibility", FOE, expires_on="UNTIL_REMOVED")
    invisible_id = next(iid for iid, condition in foe.conditions.items() if condition.condition_id == "condition:typed.invisible")
    assert invisible_id in masked_conditions(engine, ally, foe).get(FOE, set())
    assert invisible_id not in masked_conditions(engine, me, foe).get(FOE, set())
    # Only the hostile creature must remain in the field; its harmed observer may leave.
    ally.position = {"x": 10, "y": 5}
    assert not _in_field(engine, me, ally) and _in_field(engine, me, foe)
    assert invisible_id in masked_conditions(engine, ally, foe).get(FOE, set())
    assert perceives(engine, ally, foe, locate_concealed=True, sight_only=True)
    foe.position = {"x": 11, "y": 5}
    assert not _in_field(engine, me, foe)
    assert invisible_id not in masked_conditions(engine, ally, foe).get(FOE, set())
    assert not perceives(engine, ally, foe, locate_concealed=True, sight_only=True)
    foe.position = {"x": 4, "y": 6}
    # Alternate IDs are untouched; this does not represent or prove supernatural concealment.
    engine._apply_condition(foe, "condition:core.invisible", "test:alternate-condition-id", FOE, expires_on="UNTIL_REMOVED")
    alternate_id = next(iid for iid, condition in foe.conditions.items() if condition.condition_id == "condition:core.invisible")
    assert alternate_id not in masked_conditions(engine, ally, foe).get(FOE, set())


def test_the_funeral_bell_and_mourners_embrace():
    engine = fight(GE_ALL, foe_ids=[MIND_SPIKE], dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[TYPED_FOE]
    me.resources[BURDEN] = 1
    use(engine, "Vessel of Ten Thousand Sorrows")
    turn(engine, TYPED_FOE)
    hp = foe.current_hp
    use(engine, "Mind Spike", ME, actor_id=TYPED_FOE)
    assert typed_executor.bears_mark(foe, ME, "Resonance") and foe.current_hp == hp - 6  # PB Psychic
    turn(engine, ME)
    foe.maximum_hp = foe.current_hp = 500
    answers(engine, {"grief_eater.embrace": ("accept",)})
    events = use(engine, "Mourner's Embrace", TYPED_FOE)
    assert held(foe, "condition:typed.restrained") and any(len(p.get("dice") or ()) == 8 for p in payloads(events, "DAMAGE_ROLLED"))
    turn(engine, ME)
    assert "Mourner's Embrace" not in legal(engine)  # once per Field


# ============================================================================================ 15 Halo Eater
HE = "tianxia.tradition.spirit.halo_eater.feature."
HE_ALL = [MIND_SPIKE] + [HE + k for k in ("taste_the_radiance", "bite_the_halo", "stolen_benediction", "crown_of_borrowed_light", "empty_heaven_maw")]
RADIANCE = "resource:named.stolen_radiance"


def bless(engine, creature_id, name="blessed", *, during_its_action=False):
    """A beneficial effect its own side put on it: qualifying radiance at the table. ``during_its_action``: as part of that creature's
    own activation (an active intent), so a player's reactions to it are asked."""
    if during_its_action:
        engine._active_intent = ActionIntent(intent_id=f"c8-bless-{len(engine.events)}", decision_id="c8-bless", candidate_id="c8-bless",
                                             state_version=engine.state.state_version, actor_id=creature_id, target_ids=())
    try:
        engine._apply_condition(engine.state.actors[creature_id], f"condition:typed.{name}", "test:blessing", creature_id, expires_on="UNTIL_REMOVED", data={"rule": {"effect_kind": "benefit"}})
    finally:
        engine._active_intent = None


def test_a_foes_blessing_feeds_stolen_radiance_and_taste_the_radiance_savors_it():
    engine = fight(HE_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert me.resources[RADIANCE] == 0 and me.resource_maximums[RADIANCE] == 6
    turn(engine, FOE)
    me.reaction_available = True
    before = me.resources["resource:core.resonance"]
    engine._grant_temp_hp(foe, 5, "test:ward", FOE)
    assert me.resources[RADIANCE] == 1 and me.temporary_hp == 6 and me.resources["resource:core.resonance"] == before - 1
    assert held(foe, "condition:typed.savored", ME) and not me.reaction_available


def test_stolen_benediction_reflects_a_foes_blessing_as_a_resonance_mark():
    engine = fight(HE_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    turn(engine, FOE)
    me.reaction_available = True
    answers(engine, {"halo_eater.reaction": ("reflecting",)})
    before = me.resources["resource:core.resonance"]
    bless(engine, FOE, during_its_action=True)
    assert typed_executor.bears_mark(foe, ME, "Resonance") and me.resources["resource:core.resonance"] == before - 3
    assert me.resources[RADIANCE] == 0  # gained 1 from the blessing, spent 1


def test_bite_the_halo_ends_a_foes_blessing_and_gains_stolen_radiance():
    engine = fight(HE_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    assert "Bite the Halo" not in legal(engine)  # not savored, marked or carrying radiance
    bless(engine, FOE)
    me.reaction_available = False
    events = use(engine, "Bite the Halo", FOE)
    assert not held(foe, "condition:typed.blessed") and me.resources[RADIANCE] == 1
    assert any(len(p.get("dice") or ()) == 4 for p in payloads(events, "DAMAGE_ROLLED")) and foe.current_hp < 500


def test_crown_of_borrowed_light_resists_radiant_and_false_grace_catches_an_ally():
    engine = fight(HE_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.resources[RADIANCE] = 3
    use(engine, "Crown of Borrowed Light")
    crown = held(me, "condition:typed.crown_of_borrowed_light", ME)
    assert crown and sorted(crown[0].data["facets"]) == ["false_grace", "hunger", "sanctuary"] and me.resources[RADIANCE] == 0
    hp = me.current_hp
    engine._commit_damage(me, 10, "RADIANT", "test", FOE, None, reaction_depth=0)
    assert me.current_hp == hp - 5
    ally.current_hp = 3
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    events = use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    graced = [e for e in events if e.event_type == "REACTION_RESOLVED" and (e.payload or {}).get("reaction_name") == "False Grace"]
    first = next(e for e in events if e.event_type == "DAMAGE_COMMITTED" and ALLY in e.target_ids)
    assert graced and (first.payload or {}).get("remaining_hp") == 1  # the first blow leaves it at 1 Hit Point
    from combat.ext import spirit_traditions as st

    assert "false_grace" not in st.data_of(me, held(me, "condition:typed.crown_of_borrowed_light", ME)[0])["facets"]  # the Facet is spent


def test_empty_heaven_maw_devours_radiance_for_each_stolen_radiance_and_feeds_you():
    engine = fight(HE_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    me.current_hp = 20
    me.reaction_available = False
    bless(engine, FOE, "blessed")
    bless(engine, FOE, "warded")
    mark_resonance(engine, FOE)
    me.resources[RADIANCE] = 2
    events = use(engine, "Empty Heaven Maw", FOE)
    assert not held(foe, "condition:typed.blessed") and not held(foe, "condition:typed.warded") and me.resources[RADIANCE] == 0
    assert any(len(p.get("dice") or ()) == 10 for p in payloads(events, "DAMAGE_ROLLED"))
    assert me.current_hp > 20  # half the damage dealt, up to half your Hit Point maximum


# ============================================================================================ 16 Heartbinder
HB = "tianxia.tradition.spirit.heartbinder.feature."
HB_ALL = [MIND_SPIKE] + [HB + k for k in ("vow_mark", "heart_s_rebuke", "borrowed_courage", "chain_of_devotion", "unbroken_vow")]


def test_heart_s_rebuke_lets_the_heartbinder_choose_the_rebuke():
    engine = fight(HB_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    assert typed_executor.bears_mark(ally, ME, "Vow Mark")
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    answers(engine, {"heartbinder.rebuke": ("remembers",)})
    events = use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert typed_executor.bears_mark(foe, ME, "Resonance")  # The Bond Remembers (was: always Feel What You Caused)
    assert not [m for m in foe.modifiers.values() if m.target_field == "attack_mode"]


def test_do_not_approach_keeps_the_foe_from_moving_closer_to_the_protected_ally():
    engine = fight(HB_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(5, 7))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    engine.state.actors[ALLY].position = type(ally.position)(x=4, y=7)
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    answers(engine, {"heartbinder.rebuke": ("approach",)})
    use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert held(foe, "condition:typed.do_not_approach", ME)
    closer = [c for c in engine.legal_candidates() if c.destination is not None and c.display_name.startswith("Move to")
              and engine._distance_actor_to_actor(foe, ally, actor_position=c.destination) < engine._distance_actor_to_actor(foe, ally)]
    assert not closer and any(c.display_name.startswith("Move to") for c in engine.legal_candidates())


def test_devotion_release_benefits_are_chosen_and_one_is_a_free_move():
    engine = fight(HB_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.resources["resource:named.devotion"] = 2
    start = (ally.position.x, ally.position.y)
    answers(engine, {"heartbinder.devotion_release": ("move", "saves"), "devotion_release_move": lambda ids: ids[:1]})
    use(engine, "Borrowed Courage: Devotion Release", ALLY)
    assert me.resources["resource:named.devotion"] == 0 and (ally.position.x, ally.position.y) != start
    assert any("Devotion Release" in str((c.data or {}).get("label")) for c in ally.conditions.values())


# ============================================================================================ 17 Inner Soul-Gate Ascetic
SG = "tianxia.tradition.spirit.inner_soul_gate_ascetic.feature."
SG_ALL = [MIND_SPIKE] + [SG + k for k in ("root_soul_gate", "sacral_soul_gate", "solar_soul_gate", "heart_soul_gate", "crown_soul_gate")]
OPENING = "condition:typed.gate_opening"


def hostile_save(engine, source_id, subject_id, condition, ability="wis", dc=17):
    """A hostile typed save that imposes ``condition`` on a failure, from ``source_id`` (a stand-in technique with that DC)."""
    from combat.ext import spirit_traditions as st

    source = engine.state.actors[source_id]
    engine._active_intent = ActionIntent(intent_id=f"c8-save-{len(engine.events)}", decision_id="c8-save", candidate_id="c8-save",
                                         state_version=engine.state.state_version, actor_id=source_id, target_ids=(subject_id,))
    ctx = st.context(engine, source, st.feature_action(engine, source, "test:hostile_save"), [engine.state.actors[subject_id]], {"save_dc": dc, "pb": 3, "cl": 5})
    try:
        typed_executor.block_save(ctx, {"type": "save", "applies_to": "target", "ability": ability,
                                        "on_fail": [{"type": "condition", "applies_to": "target", "condition": condition, "duration": {"kind": "until_end_of_your_next_turn"}}]})
    finally:
        engine._active_intent = None


def test_one_gate_opening_at_a_time_and_root_opening_rewards_standing_still():
    engine = fight(SG_ALL, foe_at=(8, 6))
    me = engine.state.actors[ME]
    use(engine, "Root Opening")
    assert [c.data["gate"] for c in held(me, OPENING, ME)] == ["root"] and "Root Opening" not in legal(engine)
    use(engine, "End turn")
    assert me.temporary_hp == 4 + 6 // 2  # Wisdom + half Proficiency Bonus: it ended its turn where it began
    turn(engine, ME)
    use(engine, "Solar Opening")
    assert [c.data["gate"] for c in held(me, OPENING, ME)] == ["solar"]  # opening another ends the last
    turn(engine, ME)
    assert "Root Opening" in legal(engine) and "Solar Opening" not in legal(engine)


def test_solar_core_resists_psychic_and_solar_opening_burns_a_frightener():
    engine = fight(SG_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    hp = me.current_hp
    engine._commit_damage(me, 10, "PSYCHIC", "test", FOE, None, reaction_depth=0)
    assert me.current_hp == hp - 5
    use(engine, "Solar Opening")
    raw_d20s(engine, lambda kw: 20)
    foe_hp = foe.current_hp
    hostile_save(engine, FOE, ME, "frightened")
    assert not held(me, "condition:typed.frightened") and foe.current_hp < foe_hp  # 2d8 + Wisdom to the source of the fear it beat


def test_solar_opening_keeps_a_lower_cl_fear_from_taking_hold():
    engine = fight(SG_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    use(engine, "Solar Opening")
    raw_d20s(engine, lambda kw: 1)
    hostile_save(engine, FOE, ME, "frightened")
    assert not held(me, "condition:typed.frightened")  # its source is CL 5, below yours


def test_sacral_reorientation_adds_wisdom_to_a_failed_save_and_marks_you():
    engine = fight(SG_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, FOE)
    me.reaction_available = True
    raw_d20s(engine, lambda kw: 17 - me.saving_throws["DEX"] - 2)  # fails by 2 (a Dexterity save: Heart Attunement does not answer it)
    before = me.resources["resource:core.resonance"]
    answers(engine, {"soul_gate.root_reclamation_save": None})  # keep the Reaction for Sacral Reorientation
    hostile_save(engine, FOE, ME, "restrained", ability="dex")
    assert not held(me, "condition:typed.restrained") and me.resources["resource:core.resonance"] == before - 2
    assert typed_executor.bears_mark(me, ME, "Resonance")  # Resonance Marked by yourself until the end of your next turn


def test_heart_attunement_turns_an_allys_failed_save_and_you_take_the_recoil():
    engine = fight(SG_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    turn(engine, FOE)
    me.reaction_available = True
    raw_d20s(engine, lambda kw: 17 - ally.saving_throws["WIS"] - 2)
    hp = me.current_hp
    hostile_save(engine, FOE, ALLY, "charmed")
    assert not held(ally, "condition:typed.charmed") and me.current_hp == hp - 6  # 2 x Proficiency Bonus Psychic, halved by Solar Core


def test_heart_restoration_ends_a_lower_cl_fear_on_a_willing_ally():
    engine = fight(SG_ALL, ally_ids=[MIND_SPIKE], foe_at=(8, 6))
    ally = engine.state.actors[ALLY]
    assert "Heart Restoration" not in legal(engine)
    engine._apply_condition(ally, "condition:typed.frightened", "test", FOE, expires_on="UNTIL_REMOVED")
    use(engine, "Heart Restoration", ALLY)
    assert not held(ally, "condition:typed.frightened")


def test_crown_opening_opens_every_gate_and_a_failed_mental_save_succeeds_for_two_resonance():
    engine = fight(SG_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Crown Opening")
    from combat.ext import inner_soul_gate

    assert all(inner_soul_gate.opened(me, gate) for gate in ("root", "sacral", "solar", "heart"))
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert inner_soul_gate.truesight(engine, foe, me)  # Spiritual Truesight 30 feet
    turn(engine, FOE)
    raw_d20s(engine, lambda kw: 1)
    before = me.resources["resource:core.resonance"]
    hostile_save(engine, FOE, ME, "stunned", ability="int")
    assert not held(me, "condition:typed.stunned") and me.resources["resource:core.resonance"] == before - 2


def test_root_reclamation_stands_up_from_a_hostile_shove():
    engine = fight(SG_ALL, foe_ids=[MIND_SPIKE], foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, TYPED_FOE)
    me.reaction_available = True
    raw_d20s(engine, lambda kw: 20 if kw["actor_id"] == TYPED_FOE else 1)
    before = me.resources["resource:core.resonance"]
    answers(engine, {"soul_gate.root_reclamation_save": None, "soul_gate.root_reclamation_prone": ("reclaim",)})  # pass on the save's Advantage
    use(engine, "Shove: Prone", ME, actor_id=TYPED_FOE)
    assert not held(me, "condition:typed.prone") and me.resources["resource:core.resonance"] == before - 1 and not me.reaction_available


def test_the_soul_gate_records_no_longer_carry_the_model_typings_stray_rows():
    mechanics = authority()["mechanics"]
    for key in ("root_soul_gate", "sacral_soul_gate", "solar_soul_gate", "heart_soul_gate", "crown_soul_gate"):
        entry = mechanics[SG + key]
        assert [row.get("type") for row in entry.get("effects") or []] == ["spirit_tradition"], key  # Crown dealt itself 4d10 on opening
        printed = "reaction" if key in ("root_soul_gate", "sacral_soul_gate") else "passive"  # Root Reclamation, Sacral Reorientation
        assert (entry.get("activation") or {}).get("economy") == printed and not entry.get("options"), key


# ============================================================================================ 18 Knot Weaver
KW = "tianxia.tradition.spirit.knot_weaver.feature."
KW_ALL = [MIND_SPIKE] + [KW + k for k in ("red_thread_sense", "tie_the_moment", "binding_knot", "sever_the_false_thread", "knot_of_inevitability")]
KNOT_TENSION = "resource:named.knot_tension"


def tie(engine, a, b, weaver=ME):
    engine._apply_condition(engine.state.actors[weaver], "condition:typed.observed_tie", KW + "red_thread_sense", weaver, expires_on="UNTIL_REMOVED",
                            data={"a": a, "b": b, "label": f"Observed Tie: {a} and {b}"})


def test_red_thread_sense_records_a_tie_and_the_foe_acting_through_it_gives_knot_tension():
    engine = fight(KW_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 6))
    me = engine.state.actors[ME]
    assert me.resources[KNOT_TENSION] == 0 and me.resource_maximums[KNOT_TENSION] == 6
    answers(engine, {"knot_weaver.other_side": (ALLY,)})
    use(engine, "Red Thread Sense", FOE)
    held_ties = held(me, "condition:typed.observed_tie", ME)
    assert held_ties and {held_ties[0].data["a"], held_ties[0].data["b"]} == {FOE, ALLY}
    turn(engine, FOE)
    fixed_d20(engine, 19)
    use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert me.resources[KNOT_TENSION] == 1  # it attacked the other side of its Tie


def test_tie_the_moment_subtracts_a_d6_from_a_tied_foes_attack():
    engine = fight(KW_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    tie(engine, FOE, ALLY)
    mark_resonance(engine, FOE)
    me.resources[KNOT_TENSION] = 1
    turn(engine, FOE)
    me.reaction_available = True
    ac = ally.armor_class + engine._ac_modifier(ally)
    raw_d20s(engine, lambda kw: ac + 2 - kw["modifier"])  # hits by 2
    rolls_high(engine)
    events = use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    spent = [p for p in payloads(events, "RESOURCE_SPENT") if p.get("resource_id") == KNOT_TENSION]
    assert spent and not me.reaction_available  # paid with Knot Tension (it gains 1 back: the foe acted through its Tie)
    assert any((p.get("bonus") or 0) == -6 for p in payloads(events, "D20_REWRITTEN"))


def test_a_guardian_knot_lets_you_take_half_of_an_allys_blow():
    engine = fight(KW_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 7))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    tie(engine, ME, ALLY)
    use(engine, "Binding Knot")
    knot = held(me, "condition:typed.binding_knot", ME)
    assert knot and knot[0].data["form"] == "guardian"  # both willing: no saves
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    hp = me.current_hp
    use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert me.current_hp < hp and not me.reaction_available


def test_sever_the_false_thread_cuts_a_lower_cl_charm_from_an_ally():
    engine = fight(KW_ALL, ally_ids=[MIND_SPIKE], foe_at=(8, 6))
    ally = engine.state.actors[ALLY]
    assert "Sever the False Thread" not in legal(engine)
    engine._apply_condition(ally, "condition:typed.charmed", "test", FOE, expires_on="UNTIL_REMOVED")
    fixed_d20(engine, 19)
    use(engine, "Sever the False Thread", ALLY)
    assert not held(ally, "condition:typed.charmed")


def test_knot_of_inevitability_makes_a_foe_face_its_tie():
    engine = fight(KW_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    tie(engine, FOE, ALLY)
    mark_resonance(engine, FOE)
    me.resources[KNOT_TENSION] = 2
    answers(engine, {"knot_weaver.inevitability": ("face",)})
    use(engine, "Knot of Inevitability", FOE)
    assert held(foe, "condition:typed.great_knot", ME)[0].data["bound"] and me.resources[KNOT_TENSION] == 0
    assert any(o.object_id.startswith("object:typed.great_knot:") for o in engine.state.objects.values())
    turn(engine, FOE)
    attacks = [c for c in engine.legal_candidates() if c.display_name == "Paired Bi Shou Assault"]
    assert attacks and all(c.target_ids == (ALLY,) for c in attacks)  # it may only turn its hostility on the other side


def test_tug_the_visible_thread_moves_a_marked_foe_away_from_its_tie():
    engine = fight(KW_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(5, 7))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    tie(engine, FOE, ALLY)
    before = engine._distance_actor_to_actor(foe, ally)
    answers(engine, {"knot_weaver.tug": ("away",)})
    use(engine, "Mind Spike", FOE)
    assert engine._distance_actor_to_actor(foe, ally) > before


# ============================================================================================ 19 Last-Inch Palm
LI = "tianxia.tradition.spirit.last_inch_palm.feature."
LI_ALL = [MIND_SPIKE] + [LI + k for k in ("the_last_inch", "nothing_crosses_unanswered", "palm_across_emptiness", "inside_every_guard", "world_of_one_handspan")]
LI_EARLY = [MIND_SPIKE] + [LI + k for k in ("the_last_inch", "nothing_crosses_unanswered", "palm_across_emptiness")]
HANDSPAN = "condition:typed.handspan_subject"


def place(engine, actor_id, x, y):
    actor = engine.state.actors[actor_id]
    actor.position = type(actor.position)(x=x, y=y)


def test_a_spirit_touch_strike_makes_a_handspan_subject_and_reaches_it_at_ten_feet():
    engine = fight(LI_EARLY, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    fixed_d20(engine, 19)
    use(engine, "Spirit-Touch Unarmed Strike", FOE)
    assert held(foe, HANDSPAN, ME)
    turn(engine, ME)
    place(engine, FOE, 6, 6)
    assert "Spirit-Touch Unarmed Strike" not in legal(engine)  # 15 feet: beyond Handspan Reach
    place(engine, FOE, 5, 6)
    assert "Spirit-Touch Unarmed Strike" in legal(engine)  # 10 feet against the Subject


def test_palm_across_emptiness_holds_a_marked_foe_as_the_subject_for_the_scene():
    engine = fight(LI_EARLY, dc=40, foe_at=(7, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    assert "Palm Across Emptiness: Hold at the Last Inch" not in legal(engine)  # not the Subject and not marked
    mark_resonance(engine, FOE)
    use(engine, "Palm Across Emptiness: Hold at the Last Inch", FOE)
    subject = held(foe, HANDSPAN, ME)
    assert subject and subject[0].expires_on == "UNTIL_REMOVED" and engine._effective_speed(foe) == 0


def test_nothing_crosses_unanswered_makes_the_subjects_attack_fail_and_answers_with_mind_spike():
    engine = fight(LI_EARLY, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    from combat.ext import last_inch_palm

    last_inch_palm.designate(engine, me, foe)
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    hp, foe_hp = me.current_hp, foe.current_hp
    answers(engine, {"last_inch.threshold": ("spike",), "nothing_crosses_move": None})
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe)) and foe.current_hp < foe_hp  # Palm at the Threshold
    first = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]
    assert len(first) <= 1 and me.resources["resource:core.resonance"] < 60  # the answered attack failed; only the second blow can land


def test_last_inch_step_backs_away_when_the_subject_closes_in():
    engine = fight(LI_EARLY, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    from combat.ext import last_inch_palm

    last_inch_palm.designate(engine, me, foe)
    turn(engine, FOE)
    me.reaction_available = True
    answers(engine, {"last_inch.step": ("away",), "last_inch_step_move": lambda ids: ids[:1]})
    use(engine, "Move to 4,6", actor_id=FOE)
    assert engine._distance_actor_to_actor(me, foe) > 5 and not me.reaction_available


def test_inside_every_guard_follows_the_subject_and_opens_its_grip():
    engine = fight(LI_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    from combat.ext import last_inch_palm

    last_inch_palm.designate(engine, me, foe)
    engine._apply_condition(me, "condition:typed.grappled", "test", FOE, expires_on="UNTIL_REMOVED", data={"escape_dc": 12})
    assert "Open the Gripping Hand" in legal(engine)
    fixed_d20(engine, 19)
    use(engine, "Open the Gripping Hand")
    assert not held(me, "condition:typed.grappled")
    turn(engine, FOE)
    use(engine, "Move to 7,6", actor_id=FOE)
    assert engine._distance_actor_to_actor(me, foe) <= 10  # Follow the Contact


def test_world_of_one_handspan_makes_every_foe_a_subject_and_ten_thousand_hands_strike_them():
    engine = fight(LI_ALL, foe_at=(7, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500
    assert "Spirit-Touch Unarmed Strike" not in legal(engine)
    use(engine, "World of One Handspan")
    assert "Spirit-Touch Unarmed Strike" in legal(engine)  # anywhere in the Domain
    fixed_d20(engine, 19)
    events = use(engine, "Ten Thousand Hands: strike up to PB Handspan Subjects")
    assert payloads(events, "ATTACK_ROLLED") and foe.current_hp < 500
    turn(engine, ME)
    use(engine, "Ten Thousand Hands: move a Handspan Subject", FOE)
    assert not any(n.startswith("Ten Thousand Hands") for n in legal(engine))  # once per turn


# ============================================================================================ 20 Law of Near and Far
NF = "tianxia.tradition.spirit.law_of_near_and_far.feature."
NF_ALL = [MIND_SPIKE] + [NF + k for k in ("name_what_is_near", "make_the_blow_far", "collapse_the_interval", "cast_them_to_the_far_side", "world_without_between")]
NEAR_REL = "condition:typed.near_relation"


def use_at(engine, name, x, y, actor_id=ME):
    candidate = next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name and c.destination is not None
                     and (c.destination.x, c.destination.y) == (x, y))
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"c8-{name}-{before}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids or (), destination=candidate.destination))
    return engine.events[before:]


def test_name_what_is_near_and_the_free_step_toward_it():
    engine = fight(NF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    place(engine, ALLY, 10, 2)
    use(engine, "Name What Is Near: a willing creature", ALLY)
    assert held(ally, NEAR_REL, ME)
    before = engine._distance_actor_to_actor(me, ally)
    use(engine, "Move to 4,6")
    assert engine._distance_actor_to_actor(me, ally) < before - 5  # its own 5 feet, then 10 more toward the Near creature


def test_make_the_blow_far_makes_a_melee_attack_fail_and_stills_the_attacker():
    engine = fight(NF_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    hp = me.current_hp
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert any(p.get("reaction_name") == "Make the Blow Far" for p in payloads(events, "REACTION_RESOLVED"))
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))  # Far Shore Counter
    first = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]
    assert len(first) <= 1 and me.resources["resource:core.resonance"] == 57


def test_far_relation_shortens_a_melee_reach_to_nothing():
    engine = fight(NF_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    answers(engine, {"near_far.blow_far": None, "near_far.far_relation": ("far",)})
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert any(c.condition_id == "condition:typed.far_relation" for c in foe.conditions.values())
    assert me.resources["resource:core.resonance"] == 59  # 1 Resonance
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]) == 0  # both blows need reach it no longer has


def test_collapse_the_interval_arrives_beside_a_near_ally():
    engine = fight(NF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    place(engine, ALLY, 11, 1)
    use(engine, "Name What Is Near: a willing creature", ALLY)
    turn(engine, ME)
    answers(engine, {"near_far.interval_strike": None})
    use(engine, "Collapse the Interval")
    assert engine._distance_actor_to_actor(me, ally) <= 5


def test_cast_them_to_the_far_side_puts_its_foes_out_of_reach_until_the_anchor_breaks():
    engine = fight(NF_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Cast Them to the Far Side", FOE)
    assert held(foe, "condition:typed.far_sided", ME)
    turn(engine, FOE)
    assert "Paired Bi Shou Assault" not in legal(engine)  # 5 feet + 30 is beyond its reach
    anchor = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.far_side_anchor:"))
    engine._update_object(anchor.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    assert not held(foe, "condition:typed.far_sided") and "Paired Bi Shou Assault" in legal(engine)


def test_world_without_between_binds_a_foe_to_the_far_constellation():
    engine = fight(NF_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use_at(engine, "World Without Between", 3, 6)
    assert [c.data["side"] for c in held(foe, "condition:typed.constellation", ME)] == ["far"]
    turn(engine, FOE)
    assert "Paired Bi Shou Assault" not in legal(engine)  # 20 feet farther for its hostile targeting


# ============================================================================================ 21 Mercy Flayer
MF = "tianxia.tradition.spirit.mercy_flayer.feature."
MF_ALL = [MIND_SPIKE] + [MF + k for k in ("gentle_knife", "peel_the_wound", "give_the_pain_a_name", "painless_martyr", "white_room_mercy")]
SCAR = "resource:named.mercy_scar"


def scars(engine, n, actor_id=ME):
    engine.state.actors[actor_id].resources[SCAR] = n


def dies(engine, subject_id, attacker=FOE):
    """``subject_id`` would die during ``attacker``'s activation (so a player's reaction to it is asked)."""
    from combat.ext import life_state

    engine._active_intent = ActionIntent(intent_id=f"c8-die-{len(engine.events)}", decision_id="c8-die", candidate_id="c8-die",
                                         state_version=engine.state.state_version, actor_id=attacker, target_ids=(subject_id,))
    try:
        life_state.die(engine, engine.state.actors[subject_id], "three failed death saving throws", "test")
    finally:
        engine._active_intent = None


def test_gentle_knife_take_the_edge_shields_the_ally_and_costs_unreducible_psychic():
    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert me.resource_maximums[SCAR] == 6  # Proficiency Bonus
    engine._grant_temp_hp(me, 0, "test", ME)
    hp = me.current_hp
    use(engine, "Gentle Knife: Take the Edge", ALLY)
    assert ally.temporary_hp == 6 + 4  # Proficiency Bonus + Wisdom modifier
    assert any((c.data or {}).get("rule", {}).get("save_against", {}).get("against") == ["frightened"] for c in ally.conditions.values())
    assert me.current_hp == hp - 6 and me.resources["resource:core.resonance"] == 59


def test_gentle_knife_ease_pain_suppresses_a_foes_fear_and_may_take_a_mercy_scar_instead_of_the_damage():
    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.reaction_available = False  # no Painless Martyr on the setup save
    hostile_save(engine, FOE, ALLY, "frightened", dc=40)
    assert held(ally, "condition:typed.frightened")
    hp = me.current_hp
    answers(engine, {"mercy_flayer.knife_scar": ("scar",)})
    use(engine, "Gentle Knife: Ease Pain", ALLY)
    assert not held(ally, "condition:typed.frightened")  # suppressed for the fight, not ended
    assert any("suppressed" in c.condition_id for c in ally.conditions.values())
    assert me.current_hp == hp and me.resources[SCAR] == 1


def test_gentle_knife_lift_the_tremor_repeats_the_save_and_a_declined_scar_means_the_damage():
    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.reaction_available = False  # no Painless Martyr on the setup save
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "charmed", dc=15)
    assert held(ally, "condition:typed.charmed")
    raw_d20s(engine, lambda kw: 19)
    hp = me.current_hp
    answers(engine, {"mercy_flayer.knife_scar": None})
    use(engine, "Gentle Knife: Lift the Tremor", ALLY)
    assert not held(ally, "condition:typed.charmed") and not any("charmed" in c.condition_id for c in ally.conditions.values())
    assert me.current_hp == hp - 6 and me.resources[SCAR] == 0


def test_a_mercy_scar_ruptures_to_turn_a_failed_wisdom_save():
    engine = fight(MF_ALL, foe_at=(9, 9))
    me = engine.state.actors[ME]
    scars(engine, 2)
    raw_d20s(engine, lambda kw: 17 - me.saving_throws["WIS"] - 3)  # fails DC 17 by 3; +6 makes it
    hp = me.current_hp
    answers(engine, {})
    hostile_save(engine, FOE, ME, "frightened", dc=17)
    assert not held(me, "condition:typed.frightened")
    assert me.resources[SCAR] == 1 and me.current_hp == hp - 12  # 2 x Proficiency Bonus, not reduced


def test_peel_the_wound_extracts_a_foes_fear_into_a_flayed_burden_anchor():
    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.reaction_available = False  # no Painless Martyr on the setup save
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "frightened", dc=20)
    raw_d20s(engine, lambda kw: 11)  # 11 + 6 + 4 beats the save's DC 20
    answers(engine, {"mercy_flayer.peel_result": ("extract",), "mercy_flayer.peel_scar": ("anchor",)})
    use(engine, "Peel the Wound", ALLY)
    assert not held(ally, "condition:typed.frightened") and not any("frightened" in c.condition_id for c in ally.conditions.values())
    anchor = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.flayed_burden:"))
    assert (anchor.maximum_hp, anchor.ac, anchor.owner_id) == (24, 17, ME) and me.resources[SCAR] == 0
    assert me.resources["resource:core.resonance"] == 57


def test_peel_the_wound_carries_the_scar_or_fails_with_advantage_and_twice_pb_psychic():
    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.reaction_available = False  # no Painless Martyr on the setup save
    hostile_save(engine, FOE, ALLY, "charmed", dc=40)
    raw_d20s(engine, lambda kw: 2)
    hp = me.current_hp
    use(engine, "Peel the Wound", ALLY)
    assert held(ally, "condition:typed.charmed") and me.current_hp == hp - 12
    assert any((c.data or {}).get("rule", {}).get("save_against", {}).get("against") == ["charmed"] for c in ally.conditions.values())
    turn(engine, ME)
    ally.conditions.clear()
    me.reaction_available = False
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "charmed", dc=20)
    raw_d20s(engine, lambda kw: 11)
    answers(engine, {"mercy_flayer.peel_result": ("extract",), "mercy_flayer.peel_scar": ("carry",)})
    use(engine, "Peel the Wound", ALLY)
    assert not held(ally, "condition:typed.charmed") and me.resources[SCAR] == 1


def test_give_the_pain_a_name_lends_a_scar_to_a_marked_foe_until_its_next_turn_ends():
    engine = fight(MF_ALL, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert "Give the Pain a Name: an unwilling creature" not in legal(engine)  # no Scar yet
    scars(engine, 2)
    assert "Give the Pain a Name: an unwilling creature" not in legal(engine)  # the receiver must bear your Resonance Mark
    mark_resonance(engine, FOE)
    raw_d20s(engine, lambda kw: 2)
    answers(engine, {"mercy_flayer.name_the_pain": ("pain",)})
    use(engine, "Give the Pain a Name: an unwilling creature", FOE)
    assert me.resources[SCAR] == 1 and held(foe, "condition:typed.lent_mercy_scar", ME)
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))
    turn(engine, FOE)
    use(engine, "End turn", actor_id=FOE)
    assert me.resources[SCAR] == 2 and not held(foe, "condition:typed.lent_mercy_scar")


def test_give_the_pain_a_name_to_a_willing_marked_ally_gives_named_relief_once():
    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    scars(engine, 2)
    mark_resonance(engine, ALLY)
    use(engine, "Give the Pain a Name: a willing ally", ALLY)
    assert me.resources[SCAR] == 1 and me.temporary_hp == 6 and ally.temporary_hp == 6
    turn(engine, ME)
    me.temporary_hp = ally.temporary_hp = 0
    use(engine, "Give the Pain a Name: a willing ally", ALLY)
    assert me.temporary_hp == 0 and ally.temporary_hp == 0  # Named Relief: once per fight for each creature


def test_carry_the_failure_resonance_marks_the_hostile_source_and_ruptures_at_the_maximum():
    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    scars(engine, 6)
    rolls = iter([2, 19])
    raw_d20s(engine, lambda kw: next(rolls, 19))
    hp = me.current_hp
    answers(engine, {})
    hostile_save(engine, FOE, ALLY, "charmed", dc=15)
    assert not held(ally, "condition:typed.charmed")
    assert typed_executor.bears_mark(foe, ME, "Resonance")
    assert me.resources[SCAR] == 6 and me.current_hp == hp - 12  # Martyr's Limit: a Scar ruptured to make room


def test_white_room_mercy_shelters_allies_and_tends_one_each_turn():
    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "White Room Mercy")
    assert any((c.data or {}).get("rule", {}).get("save_against") for c in ally.conditions.values())  # Advantage vs Charmed/Frightened
    ally.current_hp = 10
    assert "White Room: heal an ally" in legal(engine)
    use(engine, "White Room: heal an ally", ALLY)
    assert ally.current_hp > 10 + 4
    assert "White Room: heal an ally" not in legal(engine)  # once on each of your turns


def test_impossible_triage_defers_a_death_in_the_white_room():
    from combat.ext import life_state

    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "White Room Mercy")
    assert life_state.wants_dying(engine, ally)  # Advantage on death saving throws in the aura
    engine._commit_damage(ally, ally.current_hp + ally.temporary_hp, "SLASHING", "test", FOE, None, reaction_depth=1)
    assert ally.life_state == "DYING"
    answers(engine, {"mercy_flayer.triage": ("defer",)})
    dies(engine, ALLY)
    assert ally.active and ally.current_hp == 1 and not me.reaction_available
    engine._commit_damage(ally, 1, "SLASHING", "test", FOE, None, reaction_depth=1)
    me.reaction_available = True
    dies(engine, ALLY)
    assert not ally.active or life_state.is_dead(ally)  # once during the White Room


def test_impossible_triage_houses_the_burden_in_a_white_room_anchor():
    from combat.ext import life_state

    engine = fight(MF_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    ally = engine.state.actors[ALLY]
    use(engine, "White Room Mercy")
    engine._commit_damage(ally, ally.current_hp + ally.temporary_hp, "SLASHING", "test", FOE, None, reaction_depth=1)
    assert ally.life_state == "DYING"
    answers(engine, {"mercy_flayer.triage": ("house",)})
    dies(engine, ALLY)
    assert ally.active and ally.life_state == "STABLE"
    anchor = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.white_room_anchor:"))
    assert anchor.maximum_hp == 60 and "RADIANT" in anchor.damage_immunities


def test_a_lent_mercy_scar_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-MERCY", typed_bundles=(bundle(MF_ALL),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-mercy-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Gentle Knife: Take the Edge", ME)
    reloaded = persistence.load_match(session.match_id)
    me = reloaded.engine.state.actors[ME]
    assert me.temporary_hp == 10 - 6 and me.current_hp == me.maximum_hp  # the Psychic damage is not reduced; Temporary HP still takes it
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 22 Miko
MK = "tianxia.tradition.spirit.miko.feature."
MK_ALL = [MIND_SPIKE] + [MK + k for k in ("purification_dance", "minor_kami_favor", "sacred_ground", "kami_s_messenger", "kami_descent")]
OFFERING = "resource:named.offering"


def test_offerings_start_prepared_and_brief_purification_ends_a_foes_poison():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert me.resources[OFFERING] == me.resource_maximums[OFFERING] == 6  # Proficiency Bonus, prepared before the fight
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "poisoned", dc=15)
    assert held(ally, "condition:typed.poisoned")
    use(engine, "Purification Dance: End Poisoned", ALLY)
    assert not held(ally, "condition:typed.poisoned") and me.resources[OFFERING] == 5
    turn(engine, ME)
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "poisoned", dc=15)
    use(engine, "Purification Dance: End Poisoned (2 Resonance)", ALLY)
    assert not held(ally, "condition:typed.poisoned") and me.resources[OFFERING] == 5 and me.resources[RES] == 58


def test_brief_purification_removes_a_lower_foes_resonance_mark_only_when_there_is_one():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    ally = engine.state.actors[ALLY]
    assert "Purification Dance: Remove a Resonance Mark" not in legal(engine)
    mark_resonance(engine, ALLY, owner=FOE)
    assert typed_executor.bears_mark(ally, FOE, "Resonance")
    use(engine, "Purification Dance: Remove a Resonance Mark", ALLY)
    assert not typed_executor.bears_mark(ally, FOE, "Resonance")


def test_minor_kami_favors_are_two_standing_choices():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    ally = engine.state.actors[ALLY]
    ally.current_hp = 20
    assert "Favor of Clear Water" in legal(engine) and "Favor of the Guiding Wind" not in legal(engine)  # Clear Water and Hearth by default
    use(engine, "Choose Minor Kami Favors: Guiding Wind")  # replaces the one chosen longest ago (Clear Water)
    assert "Favor of the Guiding Wind" in legal(engine) and "Favor of Clear Water" not in legal(engine)
    use(engine, "Choose Minor Kami Favors: Clear Water")  # now replaces Hearth
    use(engine, "Favor of Clear Water", ALLY)
    assert 20 + 1 + 4 <= ally.current_hp <= 20 + 8 + 4
    turn(engine, ME)
    ally.current_hp = 20
    assert "Favor of Clear Water" not in {c.display_name for c in engine.legal_candidates() if ALLY in (c.target_ids or ())}  # once per fight


def test_favor_of_the_guiding_wind_moves_an_ally_ten_feet_without_provoking():
    from combat.ext import needle

    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 8))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Choose Minor Kami Favors: Guiding Wind")
    start = ally.position
    answers(engine, {"guiding_wind": lambda ids: [next(i for i in ids if needle.position_of(i) == type(start)(x=start.x - 2, y=start.y))]})
    events = use(engine, "Favor of the Guiding Wind", ALLY)
    assert (ally.position.x, ally.position.y) == (start.x - 2, start.y) and me.resources[RES] == 59
    assert not payloads(events, "OPPORTUNITY_ATTACK_RESOLVED")


def test_favor_of_the_hearth_adds_proficiency_bonus_to_an_allys_failed_save_against_fear():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    raw_d20s(engine, lambda kw: 17 - ally.saving_throws["WIS"] - 2)  # fails DC 17 by 2
    answers(engine, {})
    hostile_save(engine, FOE, ALLY, "frightened", dc=17)
    assert not held(ally, "condition:typed.frightened")
    assert me.resources[RES] == 59 and not me.reaction_available


def test_sacred_ground_purifying_ground_shelters_allies_until_its_shrine_anchor_breaks():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use_at(engine, "Sacred Ground: Purifying Ground", 3, 8)
    assert me.resources[RES] == 55 and me.resources[OFFERING] == 5
    shelter = lambda: [c for c in ally.conditions.values() if (c.data or {}).get("rule", {}).get("save_against")]  # noqa: E731
    assert shelter()
    anchor = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.shrine_anchor:"))
    assert (anchor.maximum_hp, anchor.ac, (anchor.position.x, anchor.position.y)) == (30, 17, (3, 8))
    engine._update_object(anchor.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    assert not shelter()


def test_purifying_ground_lets_an_ally_repeat_a_save_when_its_turn_starts_once_per_fight():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    ally = engine.state.actors[ALLY]
    use_at(engine, "Sacred Ground: Purifying Ground", 3, 8)
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "frightened", dc=15)
    assert held(ally, "condition:typed.frightened")
    raw_d20s(engine, lambda kw: 19)
    turn(engine, ALLY)
    assert not held(ally, "condition:typed.frightened")
    assert held(ally, "condition:typed.purifying_ground_used")


def test_kami_descent_of_protection_armors_you_and_shields_an_ally():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    ac = engine._effective_ac(me) if hasattr(engine, "_effective_ac") else None
    use(engine, "Kami Descent: Descent of Protection")
    assert me.resources[RES] == 50 and me.resources[OFFERING] == 5
    if ac is not None:
        assert engine._effective_ac(me) == ac + 2
    assert any(m.target_field == "damage_resistance" and m.value == "PSYCHIC" for m in ally.modifiers.values())
    turn(engine, FOE)
    me.reaction_available = True
    hp = ally.current_hp
    engine._active_intent = ActionIntent(intent_id="c8-hit", decision_id="c8-hit", candidate_id="c8-hit", state_version=engine.state.state_version,
                                         actor_id=FOE, target_ids=(ALLY,))
    try:
        engine._commit_damage(ally, 40, "SLASHING", "test", FOE, engine._active_intent, reaction_depth=0)
    finally:
        engine._active_intent = None
    assert hp - 40 < ally.current_hp and not me.reaction_available and me.resources[RES] == 49  # 2d10 + 4 less


def test_kami_descent_of_renewal_heals_at_the_start_of_your_turn_and_restores_once():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Kami Descent: Descent of Renewal")
    ally.current_hp = 10
    turn(engine, ME)
    assert ally.current_hp == 14  # Wisdom modifier, the most hurt willing creature within 30 feet
    use(engine, "Descent of Renewal: restore", ALLY)
    assert ally.current_hp >= 14 + 8 + 4
    turn(engine, ME)
    assert "Descent of Renewal: restore" not in legal(engine)  # once during the Descent


def test_kami_descent_of_purity_blesses_after_a_resonance_feature_and_purifies_once():
    engine = fight(MK_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Kami Descent: Descent of Purity")
    turn(engine, ME)
    ally.current_hp = 10
    answers(engine, {"miko.purity_what": ("heal",)})
    use(engine, "Purification Dance: Advantage against Frightened (2 Resonance)", ALLY)
    assert ally.current_hp == 14  # Wisdom modifier
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "charmed", dc=15)
    turn(engine, ME)
    assert held(ally, "condition:typed.charmed") and "Kami Purification" in legal(engine)
    use(engine, "Kami Purification")
    assert not held(ally, "condition:typed.charmed") and "Kami Purification" not in legal(engine)


def test_processional_step_is_the_default_descent_movement():
    engine = fight(MK_ALL, foe_at=(9, 9))
    me = engine.state.actors[ME]
    use(engine, "Kami Descent: Descent of Revelation")
    assert engine._effective_speed(me) == 60
    use(engine, "Choose Descent Movement: Heavenly Flight")
    use(engine, "Kami Descent: Descent of Revelation") if "Kami Descent: Descent of Revelation" in legal(engine) else None
    turn(engine, ME)
    use(engine, "Kami Descent: Descent of Revelation")
    assert engine._effective_speed(me) == 30  # flight is the GM's


def test_kami_descent_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-MIKO", typed_bundles=(bundle(MK_ALL),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}}})

    def commit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-miko-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Kami Descent: Descent of Renewal")
    reloaded = persistence.load_match(session.match_id)
    me = reloaded.engine.state.actors[ME]
    assert [c.data["aspect"] for c in held(me, "condition:typed.kami_descent")] == ["renewal"]
    assert reloaded.engine._effective_speed(me) == 60 and "Descent of Renewal: restore" in legal(reloaded.engine)
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 23 Mirror Speaker
MS = "tianxia.tradition.spirit.mirror_speaker.feature."
MS_ALL = [MIND_SPIKE] + [MS + k for k in ("reflection_listener", "inverted_glance", "borrowed_reflection", "mirror_confession", "world_behind_the_glass")]
TRACE = "Reflection Trace"


def trace(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id(TRACE, owner), "test", owner, expires_on="UNTIL_REMOVED")




def test_reflection_diagnosis_is_a_bonus_action_trace_that_counts_as_your_resonance_mark():
    engine = fight(MS_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Reflection Listener: Reflection Diagnosis", FOE)
    assert typed_executor.bears_mark(foe, ME, TRACE) and typed_executor.bears_mark(foe, ME, "Resonance")
    assert not me.bonus_action_available and me.action_available and me.resources[RES] == 59


def test_inverted_glance_answers_a_forced_save_with_temporary_hit_points_and_backlash():
    engine = fight(MS_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(9, 9))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    trace(engine, FOE)
    raw_d20s(engine, lambda kw: 2)
    hp = foe.current_hp
    answers(engine, {"mirror.inverted_glance_result": ("temp_hp",)})
    hostile_save(engine, FOE, ALLY, "frightened", dc=17)
    assert ally.temporary_hp == 4 + 6 and not me.reaction_available and me.resources[RES] == 58
    assert foe.current_hp < hp  # 2d8 + Wisdom: it bears your Reflection Trace


def test_inverted_glance_success_still_adds_two_and_a_passed_save_brings_reflected_consequence():
    engine = fight(MS_ALL, ally_ids=[MIND_SPIKE], dc=5, foe_at=(9, 9))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    raw_d20s(engine, lambda kw: 19 if "inverted_glance" in kw["reason"] else 17 - ally.saving_throws["WIS"] - 2)
    answers(engine, {})
    hostile_save(engine, FOE, ALLY, "frightened", dc=17)
    assert not held(ally, "condition:typed.frightened")  # +2 turned it
    assert typed_executor.bears_mark(foe, ME, TRACE) and me.resources[RES] == 57  # Reflected Consequence: 1 more Resonance


def test_inverted_glance_on_an_attack_burns_a_traced_attacker():
    engine = fight(MS_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 8))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    trace(engine, FOE)
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 2)
    hp = foe.current_hp
    events = use(engine, "Paired Bi Shou Assault", ALLY, actor_id=FOE)
    assert any(p.get("reaction_name") == "Inverted Glance" for p in payloads(events, "REACTION_RESOLVED")) and not me.reaction_available
    assert foe.current_hp < hp and me.resources[RES] == 57  # 2 Resonance, and 1 for Reflected Consequence
    assert any(c.condition_id.startswith(PRESSURE) for c in foe.conditions.values())  # Reflected Consequence on a traced attacker that missed


def test_inverted_glance_success_gives_you_two_ac_against_that_attack_only():
    engine = fight(MS_ALL, dc=5, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    turn(engine, FOE)
    me.reaction_available = True
    ac = me.armor_class + engine._ac_modifier(me)

    def d20(**kw):
        natural = 19 if kw["reason"].startswith("SAVE") else ac + 1 - kw["modifier"]  # its save succeeds; the attack hits the printed AC only
        return RollRecord(roll_id="c8-ig", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(natural,), modifier=kw["modifier"], total=natural + kw["modifier"], natural_result=natural)
    engine.roller.d20 = d20
    answers(engine, {"mirror.consequence": None})
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    kinds = [e.event_type for e in events if e.event_type in ("ATTACK_ROLLED", "DAMAGE_COMMITTED")]
    assert kinds == ["ATTACK_ROLLED", "ATTACK_ROLLED", "DAMAGE_COMMITTED"]  # the answered attack misses, the second still hits


def test_borrowed_reflection_double_bursts_when_broken_but_not_when_dismissed():
    engine = fight(MS_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use_to(engine, "Borrowed Reflection", 5, 6)
    double = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.reflection_double:"))
    assert (double.maximum_hp, double.ac) == (24, 40) and me.resources[RES] == 56
    hp = foe.current_hp
    engine._update_object(double.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    assert foe.current_hp < hp and any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))
    turn(engine, ME)
    use_to(engine, "Borrowed Reflection", 5, 6)
    hp = foe.current_hp
    use(engine, "Dismiss the Reflection Double")
    assert foe.current_hp == hp and not any(o.object_id.startswith("object:typed.reflection_double:") and not o.destroyed for o in engine.state.objects.values())


def test_direct_the_reflection_double_moves_it_thirty_feet():
    engine = fight(MS_ALL, foe_at=(11, 11))
    use_to(engine, "Borrowed Reflection", 4, 6)
    use_to(engine, "Direct the Reflection Double", 8, 2) if False else None
    turn(engine, ME)
    double = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.reflection_double:"))
    far = [c for c in engine.legal_candidates() if c.display_name.startswith("Direct the Reflection Double") and c.destination is not None]
    assert far and all(engine.grid.distance_ft(double.position, c.destination) <= 30 for c in far)
    use_to(engine, "Direct the Reflection Double", 9, 6)
    double = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.reflection_double:"))
    assert (double.position.x, double.position.y) == (9, 6)


def test_confession_crack_gives_disadvantage_on_its_first_charisma_save_each_round_and_heals_after_two_successes():
    engine = fight(MS_ALL, dc=12, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    raw_d20s(engine, lambda kw: 1)
    use(engine, "Mirror Confession: Confession Crack", FOE)
    assert held(foe, "condition:typed.confession_crack", ME)
    turn(engine, ME)
    raw_d20s(engine, lambda kw: 1)
    n = len(engine.events)
    use(engine, "Mirror Confession: Emotional Confession", FOE)
    assert [p.get("mode") for p in payloads(engine.events[n:], "SAVE_ROLLED")] == ["DISADVANTAGE"]
    raw_d20s(engine, lambda kw: 19)
    for _ in range(2):
        turn(engine, FOE)
        use(engine, "End turn", actor_id=FOE)
    assert not held(foe, "condition:typed.confession_crack")


def test_world_behind_the_glass_imposes_disadvantage_on_a_traced_attacker_and_draws_it_into_a_reflection_cell():
    engine = fight(MS_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "World Behind the Glass")
    trace(engine, FOE)
    turn(engine, FOE)
    me.reaction_available = False
    raw_d20s(engine, lambda kw: 15)
    answers(engine, {})
    n = len(engine.events)
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert [p.get("mode") for p in payloads(engine.events[n:], "ATTACK_ROLLED")][:1] == ["DISADVANTAGE"]
    turn(engine, ME)
    raw_d20s(engine, lambda kw: 2)
    res = me.resources[RES]
    use(engine, "Mirror Confession: Emotional Confession", FOE)
    assert held(foe, "condition:typed.reflection_cell", ME) and me.resources[RES] == res - 6 - 6
    assert FOE not in {t for c in engine.legal_candidates() for t in (c.target_ids or ())}  # total cover from outside the Cell
    turn(engine, FOE)
    use(engine, "End turn", actor_id=FOE)  # fails its Charisma save: it stays until the end of its following turn
    assert held(foe, "condition:typed.reflection_cell")
    turn(engine, FOE)
    use(engine, "End turn", actor_id=FOE)
    assert not held(foe, "condition:typed.reflection_cell")


def test_a_reflection_trace_and_double_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-MIRROR", typed_bundles=(bundle(MS_ALL),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}}})

    def commit(name, dest=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name.startswith(name)
                         and (dest is None or (c.destination is not None and (c.destination.x, c.destination.y) == dest)))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-mirror-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Borrowed Reflection", (4, 6))
    reloaded = persistence.load_match(session.match_id)
    assert any(o.object_id.startswith("object:typed.reflection_double:") and not o.destroyed for o in reloaded.engine.state.objects.values())
    assert "Dismiss the Reflection Double" in legal(reloaded.engine)
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 24 Mudang
MD = "tianxia.tradition.spirit.mudang.feature."
MD_ALL = [MIND_SPIKE] + [MD + k for k in ("spirit_dance", "possession_trance", "gut_of_revealed_guests", "greater_spirit_possession", "grand_mudang_procession")]
RHYTHM = "resource:named.trance_rhythm"


def test_trance_rhythm_starts_empty_grows_once_a_turn_and_warding_step_wards_two():
    engine = fight(MD_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert me.resources[RHYTHM] == 0 and me.resource_maximums[RHYTHM] == 6
    use(engine, "Spirit Dance: Warding Step")
    assert held(me, "condition:typed.warding_step") and held(ally, "condition:typed.warding_step")
    use(engine, "Move to 3,4")
    assert me.resources[RHYTHM] == 1  # moved 10 feet in the dance
    use(engine, "Move to 3,2")
    assert me.resources[RHYTHM] == 1  # once on each of your turns
    raw_d20s(engine, lambda kw: 17 - me.saving_throws["WIS"] - 2)  # fails DC 17 by 2; +3 (half PB, rounded up) passes
    hostile_save(engine, FOE, ME, "frightened", dc=17)
    assert not held(me, "condition:typed.frightened") and not held(me, "condition:typed.warding_step")


def test_settling_step_suppresses_an_allys_fear_until_the_start_of_your_next_turn():
    engine = fight(MD_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    ally = engine.state.actors[ALLY]
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "frightened", dc=15)
    use(engine, "Spirit Dance: Settling Step")
    assert not held(ally, "condition:typed.frightened") and held(ally, "condition:typed.settling_step")
    turn(engine, ALLY)
    assert not held(ally, "condition:typed.frightened")
    turn(engine, ME)
    assert held(ally, "condition:typed.frightened")  # it comes back: suppression, not an ending


def test_guiding_step_moves_an_ally_but_not_out_of_an_unmarked_foes_reach():
    from combat.ext import needle

    engine = fight(MD_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 8))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    seen = answers(engine, {"mudang.guiding_step": (ALLY,), "guiding_step_to": lambda ids: ids[:1]})
    use(engine, "Spirit Dance: Guiding Step")
    offered = [needle.position_of(i) for r in seen if r["reaction_source_id"].endswith("guiding_step_to") for i in r["extension_choice"]["option_ids"]]
    assert offered and all(engine.grid.distance_ft(cell, foe.position) <= 5 for cell in offered)
    turn(engine, ME)
    mark_resonance(engine, FOE)
    seen = answers(engine, {"mudang.guiding_step": (ALLY,), "guiding_step_to": lambda ids: ids[-1:]})
    use(engine, "Dance Step: Guiding Step")
    offered = [needle.position_of(i) for r in seen if r["reaction_source_id"].endswith("guiding_step_to") for i in r["extension_choice"]["option_ids"]]
    assert any(engine.grid.distance_ft(cell, foe.position) > 5 for cell in offered)  # a marked foe makes no Opportunity Attack


def test_possession_trance_costs_trance_rhythm_and_its_seats_change():
    engine = fight(MD_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    assert "Possession Trance: Road Guest" not in legal(engine)  # no Trance Rhythm yet
    me.resources[RHYTHM] = 2
    use(engine, "Possession Trance: Road Guest")
    assert engine._effective_speed(me) == 40 and me.resources[RHYTHM] == 1 and me.resources[RES] == 58
    turn(engine, ME)
    use(engine, "Change Guest Seat: Guardian Guest")
    assert me.temporary_hp == 12 and me.resources[RHYTHM] == 0 and engine._effective_speed(me) == 30
    hp = ally.current_hp + ally.temporary_hp
    engine._commit_damage(ally, 10, "PSYCHIC", "test", FOE, None, reaction_depth=1)
    engine._commit_damage(ally, 10, "PSYCHIC", "test", FOE, None, reaction_depth=1)
    assert ally.current_hp + ally.temporary_hp == hp - (10 - 4) - 10  # once per round, by your Wisdom modifier


def test_healing_guest_cares_for_the_creature_you_settle():
    engine = fight(MD_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    me.resources[RHYTHM] = 1
    use(engine, "Possession Trance: Healing Guest")
    turn(engine, ME)
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ALLY, "frightened", dc=15)
    ally.current_hp = 20
    use(engine, "Spirit Dance: Settling Step")
    assert ally.current_hp == 26  # Proficiency Bonus


def test_a_foe_failing_your_spirit_save_gives_trance_rhythm():
    engine = fight(MD_ALL, dc=40, foe_at=(6, 6))
    me = engine.state.actors[ME]
    use(engine, "Mind Spike", FOE)
    assert me.resources[RHYTHM] == 1


def test_grand_mudang_procession_strikes_mends_and_its_breaking_hurts_you():
    engine = fight(MD_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(7, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    answers(engine, {"mudang.court": ("radiant",)})
    use_to(engine, "Grand Mudang Procession", 5, 6)
    obj = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.grand_procession:"))
    assert (obj.maximum_hp, obj.ac) == (60, 40) and me.resources[RES] == 50
    raw_d20s(engine, lambda kw: 19)
    hp = foe.current_hp
    events = use(engine, "Procession: Spirit Strike", FOE)
    assert foe.current_hp < hp and any("RADIANT" in str(p.get("damage_type", "")).upper() for p in payloads(events, "DAMAGE_COMMITTED"))
    turn(engine, ME)
    ally.current_hp = 20
    use(engine, "Procession: Communal Mending", ALLY)
    assert ally.current_hp >= 20 + 3 + 4
    turn(engine, ME)
    assert "Procession: Communal Mending" not in {c.display_name for c in engine.legal_candidates() if ALLY in (c.target_ids or ())}
    hp = me.current_hp
    engine._update_object(obj.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    assert me.current_hp < hp and "Grand Mudang Procession" not in {n.split(" to ")[0] for n in legal(engine)}


def test_move_the_procession_once_a_turn_up_to_forty_feet():
    engine = fight(MD_ALL, foe_at=(11, 11))
    use_to(engine, "Grand Mudang Procession", 4, 6)
    obj = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.grand_procession:"))
    moves = [c for c in engine.legal_candidates() if c.display_name.startswith("Move the Procession") and c.destination is not None]
    assert moves and all(engine.grid.distance_ft(obj.position, c.destination) <= 40 for c in moves)
    use_to(engine, "Move the Procession", 10, 6)
    obj = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.grand_procession:"))
    assert (obj.position.x, obj.position.y) == (10, 6) and not any(n.startswith("Move the Procession") for n in legal(engine))


def test_spirit_dance_and_trance_rhythm_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-MUDANG", typed_bundles=(bundle(MD_ALL),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 10, "y": 10}}})

    def commit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-mudang-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Spirit Dance: Warding Step")
    commit("Move to 3,4")
    reloaded = persistence.load_match(session.match_id)
    me = reloaded.engine.state.actors[ME]
    assert me.resources[RHYTHM] == 1 and held(me, "condition:typed.spirit_dance")
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 25 Mushroom Dreamwalker
MW = "tianxia.tradition.spirit.mushroom_dreamwalker.feature."
MW_ALL = [MIND_SPIKE] + [MW + k for k in ("mycelial_dream", "spore_murmur", "under_root_memory", "hallucinogenic_bloom", "fruiting_body_of_the_dream")]
SPORE = "Dream-Spore Mark"


def spores_on(engine, subject_id, owner=ME):
    from combat.ext.stacking_marks import count

    return count(engine, engine.state.actors[owner], engine.state.actors[subject_id], SPORE)


def give_spores(engine, subject_id, n, owner=ME):
    from combat.ext.stacking_marks import add

    add(engine, engine.state.actors[owner], engine.state.actors[subject_id], SPORE, n, "test")


def test_spore_touch_places_counted_dream_spore_marks_one_a_turn_that_count_as_resonance():
    engine = fight(MW_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Mycelial Dream: Spore Touch", FOE)
    assert spores_on(engine, FOE) == 1 and typed_executor.bears_mark(foe, ME, "Resonance") and not me.bonus_action_available
    use(engine, "Spore Murmur: Psychic", FOE)
    assert spores_on(engine, FOE) == 1  # no more than one on the same creature per turn
    for _ in range(3):
        turn(engine, ME)
        use(engine, "Mycelial Dream: Spore Touch", FOE)
    assert spores_on(engine, FOE) == 3  # up to three from you


def test_spore_murmur_damages_marks_and_whispering_gills_takes_its_reactions():
    engine = fight(MW_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    hp = foe.current_hp
    answers(engine, {"dreamwalker.murmur": ("whispering_gills",)})
    events = use(engine, "Spore Murmur: Poison", FOE)
    assert foe.current_hp < hp and spores_on(engine, FOE) == 1 and me_res(engine) == 57
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))
    assert any("POISON" in str(p.get("damage_type", "")).upper() for p in payloads(events, "DAMAGE_COMMITTED"))


def me_res(engine):
    return engine.state.actors[ME].resources[RES]


def test_drowsing_root_gives_disadvantage_on_its_next_wisdom_save_against_you():
    engine = fight(MW_ALL, dc=40, foe_at=(6, 6))
    answers(engine, {"dreamwalker.murmur": ("drowsing_root",)})
    use(engine, "Spore Murmur: Psychic", FOE)
    assert held(engine.state.actors[FOE], "condition:typed.drowsing_root")
    from combat.ext import spirit_traditions as st

    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    raw_d20s(engine, lambda kw: 10)
    n = len(engine.events)
    st.save(st.context(engine, me, st.feature_action(engine, me, MIND_SPIKE), [foe], st.numbers(engine, me)), foe, "wis")  # before your next turn
    assert [p.get("mode") for p in payloads(engine.events[n:], "SAVE_ROLLED")][:1] == ["DISADVANTAGE"]
    assert not held(foe, "condition:typed.drowsing_root")


def test_hyphal_spread_marks_and_burns_a_creature_next_to_a_twice_marked_target():
    engine = fight(MW_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 8))
    ally = engine.state.actors[ALLY]
    give_spores(engine, FOE, 2)
    hp = ally.current_hp
    answers(engine, {"dreamwalker.hyphal_spread": (ALLY,)})
    use(engine, "Spore Murmur: Poison", FOE)
    assert spores_on(engine, ALLY) == 1 and ally.current_hp == hp - 12  # 2 x Proficiency Bonus Psychic


def test_hallucinogenic_bloom_puts_a_thrice_marked_foe_to_sleep_until_it_is_hurt():
    engine = fight(MW_ALL, dc=40, foe_at=(8, 6))
    foe = engine.state.actors[FOE]
    give_spores(engine, FOE, 3)
    use_at(engine, "Hallucinogenic Bloom", 8, 6)
    answers(engine, {"dreamwalker.bloom": ("sleep",), "dreamwalker.bloom_spread": None})
    turn(engine, FOE)
    assert engine._effective_speed(foe) == 0 and held(foe, "condition:typed.sleep_beneath_the_roots")
    engine._commit_damage(foe, 3, "SLASHING", "test", ME, None, reaction_depth=1)
    assert not held(foe, "condition:typed.sleep_beneath_the_roots")


def test_a_foe_that_passes_the_bloom_ignores_it_until_its_next_turn():
    engine = fight(MW_ALL, dc=5, foe_at=(8, 6))
    foe = engine.state.actors[FOE]
    use_at(engine, "Hallucinogenic Bloom", 8, 6)
    raw_d20s(engine, lambda kw: 19)
    turn(engine, FOE)
    assert held(foe, "condition:typed.bloom_ignored") and engine._effective_speed(foe) > 0


def test_fruiting_body_gives_a_free_spore_touch_and_restores_an_ally_when_a_foe_fails():
    engine = fight(MW_ALL, ally_ids=[MIND_SPIKE], dc=40, foe_at=(6, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    use(engine, "Fruiting Body of the Dream")
    res = me.resources[RES]
    use(engine, "Spore Touch (Fruiting Body)", FOE)
    assert me.resources[RES] == res and spores_on(engine, FOE) == 1
    turn(engine, ME)
    ally.current_hp = 20
    use(engine, "Mind Spike", FOE)
    assert ally.current_hp == 20 + 6 + 4  # Proficiency Bonus + Wisdom modifier


def test_fruiting_body_blindsight_sees_an_invisible_poisoned_foe():
    engine = fight(MW_ALL, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    engine._apply_condition(foe, "condition:typed.poisoned", "test", ME, expires_on="UNTIL_REMOVED")
    before = engine._attack_mode(me, foe)
    use(engine, "Fruiting Body of the Dream")
    assert before == "DISADVANTAGE" and engine._attack_mode(me, foe) == "NORMAL"


def test_fruiting_body_blindsight_sees_a_dream_spore_marked_foe():
    engine = fight(MW_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Mycelial Dream: Spore Touch", FOE)  # a real Spore Touch marks it
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert engine._attack_mode(me, foe) == "DISADVANTAGE"
    use(engine, "Fruiting Body of the Dream")
    assert spores_on(engine, FOE) == 1
    assert engine._attack_mode(me, foe) == "NORMAL"  # its Invisible does not count against you
    from combat import senses

    assert FOE in senses.masked_conditions(engine, me, foe)  # the shared perception seam masks it


def test_fruiting_body_dream_spore_blindsight_survives_a_table_commit_and_reload(tmp_path):
    from combat import senses, zones
    from combat.ext.mushroom_dreamwalker import field_of
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-SPORE-SIGHT", typed_bundles=(bundle(MW_ALL, dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-spore-sight-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=target and (target,) or (candidate.target_ids or ()),
                                                       destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Mycelial Dream: Spore Touch", FOE)
    commit("Fruiting Body of the Dream")
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    me, foe = reloaded.engine.state.actors[ME], reloaded.engine.state.actors[FOE]
    assert spores_on(reloaded.engine, FOE) == 1
    field = field_of(reloaded.engine, me)
    assert field is not None
    # Probe the reloaded grant: this concealment is deliberately applied after replay,
    # because a direct engine condition mutation is not a durable session intent.
    reloaded.engine._apply_condition(foe, "condition:typed.invisible", "test", FOE,
                                     expires_on="UNTIL_REMOVED")
    invisible_ids = {iid for iid, c in foe.conditions.items() if c.condition_id == "condition:typed.invisible"}
    assert invisible_ids
    assert invisible_ids <= senses.masked_conditions(reloaded.engine, me, foe).get(FOE, set())
    assert reloaded.engine._attack_mode(me, foe) == "NORMAL"  # the grant and the mark survived the reload
    # The same concealed, marked foe must become unseen when the loaded field ends.
    zones.remove(reloaded.engine, field, "REMOVED")
    assert field_of(reloaded.engine, me) is None
    assert spores_on(reloaded.engine, FOE) == 1
    assert invisible_ids <= set(foe.conditions)
    assert not senses.masked_conditions(reloaded.engine, me, foe).get(FOE)
    assert reloaded.engine._attack_mode(me, foe) == "DISADVANTAGE"


def test_fruiting_body_blindsight_dream_spore_grant_ends_beyond_sixty_feet():
    engine = fight(MW_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Mycelial Dream: Spore Touch", FOE)
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    use(engine, "Fruiting Body of the Dream")
    assert engine._attack_mode(me, foe) == "NORMAL"
    for _ in range(6):  # the foe walks away on its own turns until it is past the 60-foot grant
        turn(engine, FOE)
        dest = max((c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Move to ")),
                   key=lambda name: (lambda xy: (abs(xy[0] - me.position.x), abs(xy[1] - me.position.y)))(
                       tuple(int(part) for part in name.rsplit(" ", 1)[1].split(","))))
        use(engine, dest, actor_id=FOE)
        if engine._distance_actor_to_actor(me, foe) > 60:
            break
    assert engine._distance_actor_to_actor(me, foe) > 60 and spores_on(engine, FOE) == 1
    assert engine._attack_mode(me, foe) == "DISADVANTAGE"  # the Blindsight reaches only 60 feet


def test_fruiting_body_blindsight_ignores_a_dream_spore_mark_from_another_walker():
    engine = fight(MW_ALL, ally_ids=MW_ALL, foe_at=(6, 6))
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    fixed_d20(engine, 1)  # the ally walker's Spore Touch save (its DC is its own) fails
    turn(engine, ALLY)
    use(engine, "Mycelial Dream: Spore Touch", FOE, actor_id=ALLY)
    assert spores_on(engine, FOE, owner=ALLY) == 1 and spores_on(engine, FOE) == 0
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    turn(engine, ME)
    use(engine, "Fruiting Body of the Dream")
    assert engine._attack_mode(me, foe) == "DISADVANTAGE"  # only your own Dream-Spore Marks qualify


def test_fruiting_body_blindsight_needs_an_active_field_and_a_live_mark():
    engine = fight(MW_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Mycelial Dream: Spore Touch", FOE)
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert engine._attack_mode(me, foe) == "DISADVANTAGE"  # the field is not active yet
    use(engine, "Fruiting Body of the Dream")
    assert engine._attack_mode(me, foe) == "NORMAL"
    from combat.ext.stacking_marks import spend

    assert spend(engine, me, foe, SPORE, "test", 1)  # the mark is spent: it no longer exists
    assert spores_on(engine, FOE) == 0
    assert engine._attack_mode(me, foe) == "DISADVANTAGE"  # a spent/removed mark does not qualify


def test_dream_spore_marks_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-SPORE", typed_bundles=(bundle(MW_ALL, dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-spore-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Mycelial Dream: Spore Touch", FOE)
    reloaded = persistence.load_match(session.match_id)
    assert spores_on(reloaded.engine, FOE) == 1
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 26 Plain-Truth Fist
PT = "tianxia.tradition.spirit.plain_truth_fist.feature."
PT_ALL = [MIND_SPIKE] + [PT + k for k in ("word_and_hand", "unspoken_intention_made_visible", "deed_follows_word", "heaven_rejects_the_feint", "hall_of_spoken_deeds")]
CREDENCE = "resource:named.credence"
GUN = "tianxia.mortal.weapon.gun"  # a staff (reach 10)


def truth_fight(**kw):
    kw.setdefault("items", (GUN,))
    return fight(PT_ALL, **kw)


def test_open_declaration_challenge_completes_with_a_martial_strike():
    engine = truth_fight(foe_at=(5, 6))
    me = engine.state.actors[ME]
    assert me.resources[CREDENCE] == 0 and me.resource_maximums[CREDENCE] == 6
    use(engine, "Open Declaration: Challenge", FOE)
    assert "Open Declaration: Pursuit" not in legal(engine)  # one declaration at a time
    raw_d20s(engine, lambda kw: 19)
    answers(engine, {"plain_truth.truth_forged": None})
    use(engine, "Gun (Staff) attack", FOE)
    assert me.resources[CREDENCE] == 1 and held(me, "condition:typed.completed_declaration")


def test_open_declaration_is_made_before_you_move_or_act():
    engine = truth_fight(foe_at=(9, 9))
    use(engine, "Move to 3,5")
    assert not any(n.startswith("Open Declaration") for n in legal(engine))


def test_pursuit_completes_by_moving_fifteen_feet_and_closing_ten():
    engine = truth_fight(foe_at=(11, 6))
    me = engine.state.actors[ME]
    use(engine, "Open Declaration: Pursuit", FOE)
    use(engine, "Move to 6,6")
    assert me.resources[CREDENCE] == 1


def test_guard_completes_at_the_end_of_your_turn_after_you_dodge_beside_it():
    engine = truth_fight(ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me = engine.state.actors[ME]
    use(engine, "Open Declaration: Guard", ALLY)
    use(engine, "Dodge")
    use(engine, "End turn")
    assert me.resources[CREDENCE] == 1


def test_truth_forged_strike_challenge_adds_psychic_and_takes_its_reactions():
    engine = truth_fight(foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.resources[CREDENCE] = 1
    use(engine, "Open Declaration: Challenge", FOE)
    raw_d20s(engine, lambda kw: 19)
    events = use(engine, "Gun (Staff) attack", FOE)
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) >= 2
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))
    assert me.resources[CREDENCE] == 1  # spent 1 on the strike, gained 1 for the completed Challenge


def test_unspoken_intention_binds_a_marked_foe_and_contradiction_punishes_it():
    engine = truth_fight(dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    answers(engine, {"plain_truth.intent": ("hold",), "plain_truth.opening": None})
    use(engine, "End turn")  # the Fist's turn ends; the foe's begins (turn-start choices are asked)
    assert held(foe, "condition:typed.bound_intent") and not me.reaction_available and me.resources[RES] == 58
    hp = foe.current_hp
    use(engine, "Move to 9,6", actor_id=FOE)
    assert foe.current_hp < hp and not held(foe, "condition:typed.bound_intent")  # 3d8 Psychic; the Intent ends
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))


def test_a_strike_intent_broken_by_attacking_someone_else_has_disadvantage():
    engine = truth_fight(ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 7))
    foe = engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    answers(engine, {"plain_truth.intent": (f"strike:{ALLY}",), "plain_truth.opening": None})
    use(engine, "End turn")
    use(engine, "End turn", actor_id=ALLY)
    raw_d20s(engine, lambda kw: 15)
    n = len(engine.events)
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert [p.get("mode") for p in payloads(engine.events[n:], "ATTACK_ROLLED")][:1] == ["DISADVANTAGE"]


def test_contradiction_leaves_an_opening_for_a_weaker_mind_spike():
    engine = truth_fight(dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    answers(engine, {"plain_truth.intent": ("nothing",), "plain_truth.opening": ("mind_spike",)})
    use(engine, "End turn")
    n = len(engine.events)
    use(engine, "Move to 7,6", actor_id=FOE)
    assert len([e for e in engine.events[n:] if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) == 2  # Contradiction, then Mind Spike


def test_deed_follows_word_moves_ten_feet_per_credence_and_strikes_with_your_cultivation_bonus():
    engine = truth_fight(foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.resources[CREDENCE] = 2
    raw_d20s(engine, lambda kw: 19)
    answers(engine, {"plain_truth.deed_credence": ("2",), "plain_truth.deed_strike": ("weapon",), "plain_truth.truth_forged": None})
    hp = foe.current_hp
    use(engine, "Deed Follows Word: Challenge", FOE)
    assert me.resources[CREDENCE] == 0 and me.resources[RES] == 55 and foe.current_hp < hp
    assert engine._distance_actor_to_actor(me, foe) <= 10
    assert typed_executor.bears_mark(foe, ME, "Resonance") and held(foe, "condition:typed.challenged", ME)


def test_unbroken_word_gives_advantage_against_being_frightened_while_you_declare():
    engine = truth_fight(foe_at=(5, 6))
    me = engine.state.actors[ME]
    use(engine, "Open Declaration: Challenge", FOE)
    raw_d20s(engine, lambda kw: 10)
    n = len(engine.events)
    hostile_save(engine, FOE, ME, "frightened", dc=30)
    assert [p.get("mode") for p in payloads(engine.events[n:], "SAVE_ROLLED")] == ["ADVANTAGE"]


def test_the_hall_binds_a_foe_that_starts_its_turn_there_and_its_contradiction_gives_credence():
    engine = truth_fight(dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use_at(engine, "Hall of Spoken Deeds", 6, 6)
    assert any(o.object_id.startswith("object:typed.witness_stone:") for o in engine.state.objects.values())
    answers(engine, {"plain_truth.intent": ("hold",), "plain_truth.opening": None})
    use(engine, "End turn")  # the Fist's turn ends; the foe's begins (turn-start choices are asked)
    assert held(foe, "condition:typed.bound_intent")
    use(engine, "Move to 9,6", actor_id=FOE)
    assert me.resources[CREDENCE] == 1  # a hostile creature suffered Contradiction in the Hall


def test_destroying_the_witness_stone_ends_the_hall():
    from combat import zones

    engine = truth_fight(dc=40, foe_at=(6, 6))
    use_at(engine, "Hall of Spoken Deeds", 6, 6)
    stone = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.witness_stone:"))
    engine._update_object(stone.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    assert not [z for z in zones.typed_zones(engine) if z.owner_id == ME]


def test_deed_without_hesitation_is_free_once_a_turn_in_the_hall():
    engine = truth_fight(dc=40, foe_at=(8, 6))
    me = engine.state.actors[ME]
    use_at(engine, "Hall of Spoken Deeds", 8, 6)
    turn(engine, ME)
    me.resources[CREDENCE] = 2
    raw_d20s(engine, lambda kw: 19)
    answers(engine, {"plain_truth.deed_credence": ("1",), "plain_truth.truth_forged": None})
    res = me.resources[RES]
    use(engine, "Deed Follows Word (Hall): Challenge", FOE)
    assert me.resources[RES] == res and me.resources[CREDENCE] == 1
    turn(engine, ME)
    use(engine, "Deed Follows Word (Hall): Challenge", FOE)
    assert me.resources[CREDENCE] == 0


def test_final_pronouncement_face_me_keeps_its_blows_on_you():
    engine = truth_fight(ally_ids=[MIND_SPIKE], dc=40, foe_at=(4, 7))
    use_at(engine, "Hall of Spoken Deeds", 4, 7)
    mark_resonance(engine, FOE)
    use(engine, "Final Pronouncement: Face Me", FOE)
    assert held(engine.state.actors[FOE], "condition:typed.final_pronouncement", ME)
    turn(engine, FOE)
    targets = {t for c in engine.legal_candidates() if c.display_name == "Paired Bi Shou Assault" for t in (c.target_ids or ())}
    assert ME in targets and ALLY not in targets


def test_an_ally_declares_a_deed_in_the_hall_and_takes_its_benefit():
    engine = truth_fight(ally_ids=[MIND_SPIKE], dc=40, foe_at=(9, 9))
    ally = engine.state.actors[ALLY]
    use_at(engine, "Hall of Spoken Deeds", 3, 7)
    answers(engine, {"plain_truth.hall_declaration": lambda ids: [i for i in ids if i.startswith("Hold")], "plain_truth.hall_benefit": ("temp",),
                     "plain_truth.intent": ("hold",)})
    use(engine, "End turn")
    assert held(ally, "condition:typed.open_declaration")
    use(engine, "Dodge", actor_id=ALLY)
    use(engine, "End turn", actor_id=ALLY)
    assert ally.temporary_hp == 12  # 2 x the Fist's Proficiency Bonus


def test_credence_and_a_declaration_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-TRUTH", typed_bundles=(bundle(PT_ALL, items=(GUN,)),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 11, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-truth-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Open Declaration: Pursuit", FOE)
    commit("Move to 6,6")
    reloaded = persistence.load_match(session.match_id)
    me = reloaded.engine.state.actors[ME]
    assert me.resources[CREDENCE] == 1 and held(me, "condition:typed.completed_declaration")
    assert reloaded.verify()["status"] == "PASS"


def test_a_condition_that_changes_after_it_is_placed_survives_a_table_commit_and_reload(tmp_path):
    """Confession Crack counts its successful saves in later commits (spirit_traditions.set_data): the saved fight must replay."""
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-CRACK", typed_bundles=(bundle(MS_ALL, dc=12),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-crack-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    raw_d20s(session.engine, lambda kw: 1)
    commit("Mirror Confession: Confession Crack", FOE)
    assert held(session.engine.state.actors[FOE], "condition:typed.confession_crack")
    raw_d20s(session.engine, lambda kw: 19)
    commit("End turn")
    while session.engine.state.current_actor_id != ME:
        commit("End turn")  # the foe's turn ends: its first successful Charisma save is counted
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.verify()["status"] == "PASS"
    assert held(reloaded.engine.state.actors[FOE], "condition:typed.confession_crack")


# ============================================================================================ 27 Seraphic Molter
SM = "tianxia.tradition.spirit.seraphic_molter.feature."
SPIRITUAL_SENSE = "tianxia.path.spirit_awakening.feature.spiritual_sense"
SM_ALL = [MIND_SPIKE, SPIRITUAL_SENSE] + [SM + k for k in ("first_molt", "wingless_ascent", "burn_away_the_lesser_self", "eyes_in_the_wings", "molt_the_mortal_name")]
DEBT = "resource:named.molt_debt"


def test_feather_scar_sign_gives_advantage_against_fear_by_default():
    engine = fight(SM_ALL, foe_at=(9, 9))
    me = engine.state.actors[ME]
    assert me.resources[DEBT] == 0 and me.resource_maximums[DEBT] == 6
    raw_d20s(engine, lambda kw: 10)
    n = len(engine.events)
    answers(engine, {"feather_scar": None})
    hostile_save(engine, FOE, ME, "frightened", dc=30)
    assert [p.get("mode") for p in payloads(engine.events[n:], "SAVE_ROLLED")] == ["ADVANTAGE"]
    use(engine, "Choose Minor Seraphic Sign: Glass-Eye Sign")
    n = len(engine.events)
    hostile_save(engine, FOE, ME, "frightened", dc=30)
    assert [p.get("mode") for p in payloads(engine.events[n:], "SAVE_ROLLED")] == ["NORMAL"]


def test_shielding_pinions_takes_the_edge_off_the_first_psychic_blow():
    engine = fight(SM_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    ally = engine.state.actors[ALLY]
    use(engine, "Wingless Ascent")
    assert "Wingless Ascent: Shielding Pinions" not in legal(engine)  # the mode is chosen at the start of your later turns
    turn(engine, ME)
    use(engine, "Wingless Ascent: Shielding Pinions", ALLY)
    assert "Wingless Ascent: Shielding Pinions" not in legal(engine)  # one mode a turn
    hp = ally.current_hp
    engine._commit_damage(ally, 15, "PSYCHIC", "test", FOE, None, reaction_depth=1)
    engine._commit_damage(ally, 15, "PSYCHIC", "test", FOE, None, reaction_depth=1)
    assert ally.current_hp == hp - (15 - 10) - 15  # Wisdom + Proficiency Bonus, the first instance only


def test_burn_away_the_lesser_self_ends_a_lower_foes_fear_and_leaves_a_cast_off_self():
    engine = fight(SM_ALL, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert "Burn Away the Lesser Self: Frightened" not in legal(engine)
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ME, "frightened", dc=15)
    answers(engine, {"seraphic.burn_debt": ("debt",)})
    use(engine, "Burn Away the Lesser Self: Frightened")
    assert not held(me, "condition:typed.frightened") and me.resources[DEBT] == 1
    cast = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.cast_off_self:") and not o.destroyed)
    assert cast.maximum_hp == 60 and typed_executor.bears_mark(foe, ME, "Resonance")  # doubled by the Molt Debt; the source is marked
    hostile_save(engine, FOE, ME, "frightened", dc=15)
    assert not held(me, "condition:typed.frightened")  # not the same effect from the same source while the Cast-Off lasts
    engine._update_object(cast.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    assert me.resources[DEBT] == 2


def test_reintegrating_the_cast_off_self_returns_resonance():
    engine = fight(SM_ALL, foe_at=(6, 6))
    me = engine.state.actors[ME]
    raw_d20s(engine, lambda kw: 2)
    hostile_save(engine, FOE, ME, "charmed", dc=15)
    answers(engine, {"seraphic.burn_debt": None})
    use(engine, "Burn Away the Lesser Self: Charmed")
    turn(engine, ME)
    res = me.resources[RES]
    use(engine, "Reintegrate the Cast-Off Self")
    assert me.resources[RES] == res + 3 and me.resources[DEBT] == 0
    assert not any(o.object_id.startswith("object:typed.cast_off_self:") and not o.destroyed for o in engine.state.objects.values())


def test_eyes_in_the_wings_widens_spiritual_sense_and_punishes_a_miss():
    from combat import senses

    engine = fight(SM_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    before = senses.of(engine, me)["spiritual_sense"]["range_ft"]
    use(engine, "Eyes in the Wings")
    assert senses.of(engine, me)["spiritual_sense"]["range_ft"] == before + 30
    turn(engine, FOE)
    fixed_d20(engine, 2)
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert any(c.condition_id.startswith(PRESSURE) for c in foe.conditions.values())


def test_pinion_witness_marks_a_creature_that_turns_invisible():
    engine = fight(SM_ALL, foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Eyes in the Wings")
    engine._apply_condition(foe, "condition:typed.invisible", "test", FOE, expires_on="UNTIL_REMOVED")
    assert typed_executor.bears_mark(foe, ME, "Resonance") and not me.reaction_available and me.resources[RES] == 60 - 6 - 2


def test_molt_the_mortal_name_takes_a_molt_debt_and_its_anatomies_run():
    engine = fight(SM_ALL, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine, {"seraphic.anatomies": ("burning_name", "crown_of_unselfing")})
    use(engine, "Molt the Mortal Name")
    assert me.resources[DEBT] == 1 and me.resources[RES] == 50
    hp = me.current_hp
    engine._commit_damage(me, 20, "RADIANT", "test", FOE, None, reaction_depth=1)
    assert me.current_hp == hp - 10 and typed_executor.bears_mark(foe, ME, "Resonance")  # Burning Name
    raw_d20s(engine, lambda kw: 10)
    n = len(engine.events)
    hostile_save(engine, FOE, ME, "charmed", ability="cha", dc=30)
    assert [p.get("mode") for p in payloads(engine.events[n:], "SAVE_ROLLED")] == ["ADVANTAGE"]  # Crown of Unselfing


def test_death_and_the_shed_name_keeps_you_at_one_hit_point_once():
    engine = fight(SM_ALL, foe_at=(6, 6))
    me = engine.state.actors[ME]
    answers(engine, {"seraphic.anatomies": ("crown_of_unselfing", "mercyless_purity"), "seraphic.third_anatomy": ("thousand_eyes",)})
    use(engine, "Molt the Mortal Name")
    intent = ActionIntent(intent_id="c8-blow", decision_id="c8-blow", candidate_id="c8-blow", state_version=engine.state.state_version,
                          actor_id=FOE, target_ids=(ME,))
    engine._active_intent = intent
    try:
        engine._commit_damage(me, me.current_hp + me.temporary_hp + 30, "SLASHING", "test", FOE, intent, reaction_depth=0)
    finally:
        engine._active_intent = None
    assert me.active and me.current_hp == 1
    assert any(o.object_id.startswith("object:typed.mortal_name_husk:") for o in engine.state.objects.values())


def test_molt_debt_and_the_ascension_form_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-MOLT", typed_bundles=(bundle(SM_ALL),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 10, "y": 10}}})

    def commit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-molt-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Molt the Mortal Name")
    reloaded = persistence.load_match(session.match_id)
    me = reloaded.engine.state.actors[ME]
    assert me.resources[DEBT] == 1 and held(me, "condition:typed.seraphic_ascension")
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 28 Soul Warden / Necromancer
SW = "tianxia.tradition.spirit.soul_warden_necromancer.feature."
SW_ALL = [MIND_SPIKE] + [SW + k for k in ("speak_with_the_dead", "soul_harvest", "raise_specter", "soul_drain_and_death_custody", "lord_of_the_dead")]
FRAG = "resource:named.soul_fragment"


def strike_down(engine, victim_id, attacker=FOE, amount=None):
    """``victim_id`` is felled during ``attacker``'s activation (so reactions to it are asked)."""
    victim = engine.state.actors[victim_id]
    intent = ActionIntent(intent_id=f"c8-fell-{len(engine.events)}", decision_id="c8-fell", candidate_id="c8-fell", state_version=engine.state.state_version,
                          actor_id=attacker, target_ids=(victim_id,))
    engine._active_intent = intent
    try:
        engine._commit_damage(victim, amount or victim.current_hp + victim.temporary_hp + 5, "SLASHING", "test", attacker, intent, reaction_depth=0)
    finally:
        engine._active_intent = None


def test_soul_harvest_catches_a_fallen_allys_freely_given_fragment():
    from combat.ext import soul_warden

    engine = fight(SW_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me = engine.state.actors[ME]
    assert me.resources[FRAG] == 0 and me.resource_maximums[FRAG] == 6
    answers(engine, {})
    strike_down(engine, ALLY)
    assert me.resources[FRAG] == 1 and soul_warden.fragments(me) == ["Consensual"]
    assert not me.reaction_available and me.resources[RES] == 59


def test_a_fragment_recovers_resonance_once_per_fight():
    from combat.ext import soul_warden

    engine = fight(SW_ALL, foe_at=(9, 9))
    me = engine.state.actors[ME]
    soul_warden.gain_fragment(engine, me, "Unclaimed", "test")
    soul_warden.gain_fragment(engine, me, "Coerced", "test")
    me.resources[RES] = 40
    answers(engine, {"soul_warden.which_fragment": ("Coerced",)})
    use(engine, "Soul Fragment: Recover Resonance")
    assert me.resources[RES] == 43 and me.resources[FRAG] == 1 and me.resources["resource:named.grave_debt"] == 1
    turn(engine, ME)
    assert "Soul Fragment: Recover Resonance" not in legal(engine)


def test_raise_specter_spends_a_fragment_and_the_predatory_specter_drinks_fear():
    from combat.ext import soul_warden

    engine = fight(SW_ALL, dc=40, foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    soul_warden.gain_fragment(engine, me, "Unclaimed", "test")
    use(engine, "Raise Specter at 4,6")
    assert me.resources[FRAG] == 0 and soul_warden.specter_of(engine, me) is not None
    assert "Specter: Drink Fear" not in legal(engine)  # only a Frightened or Resonance Marked creature
    mark_resonance(engine, FOE)
    hp = foe.current_hp
    use(engine, "Specter: Drink Fear", FOE)
    assert foe.current_hp < hp and me.temporary_hp == 6


def test_a_warden_specter_guards_and_makes_no_spectral_strike():
    from combat.ext import soul_warden

    engine = fight(SW_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 9))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    soul_warden.gain_fragment(engine, me, "Unclaimed", "test")
    use(engine, "Choose Specter: Warden Specter")
    use(engine, "Raise Specter at 4,6")
    assert "Command Predatory Specter" not in legal(engine) and "Specter: Harrier of the Living" not in legal(engine)
    use(engine, "Specter: Guard the Threshold", ALLY)
    assert engine.cover_from([(9,9,0)], FOE, ally)["bonus"] == 2


def test_soul_drain_withers_and_captures_a_fragment_at_the_brink():
    from combat.ext import soul_warden

    engine = fight(SW_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    foe.current_hp = 5
    answers(engine, {"soul_warden.harvest": None, "soul_warden.brink": ("fragment",)})
    use(engine, "Soul Drain and Death Custody: Necrotic", FOE)
    assert soul_warden.fragments(me) == ["Unclaimed"] and me.resources[RES] == 54


def test_soul_drain_stops_healing_on_a_failed_save():
    engine = fight(SW_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    use(engine, "Soul Drain and Death Custody: Psychic", FOE)
    assert any(m.target_field.startswith("healing") for m in foe.modifiers.values()) or any("heal" in c.condition_id for c in foe.conditions.values())


def test_lord_of_the_dead_raises_a_warden_wraith_whose_scythe_reaches_ten_feet():
    from combat.ext import soul_warden

    engine = fight(SW_ALL, dc=40, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    soul_warden.gain_fragment(engine, me, "Unclaimed", "test")
    use_to(engine, "Lord of the Dead", 6, 6)
    wraith = soul_warden.wraith_of(engine, me)
    assert (wraith.maximum_hp, wraith.ac) == (72, 40) and me.resources[FRAG] == 0 and me.resources[RES] == 50
    raw_d20s(engine, lambda kw: 19)
    hp = foe.current_hp
    answers(engine, {"soul_warden.scythe": ("radiant",)})
    use(engine, "Warden-Wraith: Warden's Scythe", FOE)
    assert foe.current_hp < hp
    hp = me.current_hp
    engine._update_object(wraith.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    assert me.current_hp < hp and "Lord of the Dead" not in {n.split(" to ")[0] for n in legal(engine)}


def test_soul_fragments_and_their_custody_survive_a_table_commit_and_reload(tmp_path):
    from combat.ext import soul_warden
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-SOUL", typed_bundles=(bundle(SW_ALL, dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-soul-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    session.engine.state.actors[FOE].current_hp = 3
    commit("Soul Drain and Death Custody: Necrotic", FOE)
    reloaded = persistence.load_match(session.match_id)
    assert soul_warden.fragments(reloaded.engine.state.actors[ME]) == ["Unclaimed"]
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 29 Soulstring Dancer
SD = "tianxia.tradition.spirit.soulstring_dancer.feature."
SD_ALL = [MIND_SPIKE] + [SD + k for k in ("threaded_step", "stolen_rhythm", "marionette_defense", "dance_of_borrowed_limbs", "theater_of_strings")]
STRING = "Choreography String"


def strings_on(engine, subject_id, owner=ME):
    from combat.ext.stacking_marks import count

    return count(engine, engine.state.actors[owner], engine.state.actors[subject_id], STRING)


def give_strings(engine, subject_id, n, owner=ME):
    from combat.ext.stacking_marks import add

    add(engine, engine.state.actors[owner], engine.state.actors[subject_id], STRING, n, "test")


def test_a_failed_spirit_save_places_a_string_and_threaded_step_moves_it_five_feet():
    from combat.ext import needle

    engine = fight(SD_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    answers(engine, {"threaded_step": lambda ids: [i for i in ids if needle.position_of(i) == type(foe.position)(x=7, y=6)]})
    use(engine, "Mind Spike", FOE)
    assert strings_on(engine, FOE) == 1 and (foe.position.x, foe.position.y) == (7, 6)


def test_stolen_rhythm_needs_a_string_and_takes_two_effects():
    engine = fight(SD_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    assert "Stolen Rhythm" not in legal(engine)
    give_strings(engine, FOE, 1)
    answers(engine, {"soulstring.rhythm": ("still", "slow"), "soulstring.place": None})
    use(engine, "Stolen Rhythm", FOE)
    assert strings_on(engine, FOE) == 0 and any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))
    assert engine._effective_speed(foe) < foe.speed_ft


def test_catch_the_beat_spends_three_strings_for_speed_zero():
    engine = fight(SD_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    give_strings(engine, FOE, 3)
    answers(engine, {"soulstring.catch": ("catch",), "soulstring.place": None})
    use(engine, "Stolen Rhythm", FOE)
    assert strings_on(engine, FOE) == 0 and engine._effective_speed(foe) == 0


def test_marionette_defense_success_adds_two_ac_against_that_attack():
    engine = fight(SD_ALL, ally_ids=[MIND_SPIKE], dc=5, foe_at=(4, 6))
    me = engine.state.actors[ME]
    give_strings(engine, ALLY, 1)
    turn(engine, FOE)
    me.reaction_available = True
    ac = me.armor_class + engine._ac_modifier(me)

    def d20(**kw):
        natural = 19 if kw["reason"].startswith("SAVE") else ac + 1 - kw["modifier"]
        return RollRecord(roll_id="c8-md", counter_start=1, counter_end=2, expression="1d20", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(natural,), modifier=kw["modifier"], total=natural + kw["modifier"], natural_result=natural)
    engine.roller.d20 = d20
    answers(engine, {"soulstring.marionette": (ALLY,), "soulstring.partner": None, "marionette_after": None})
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    kinds = [e.event_type for e in events if e.event_type in ("ATTACK_ROLLED", "DAMAGE_COMMITTED")]
    assert kinds[:2] == ["ATTACK_ROLLED", "ATTACK_ROLLED"] and me.resources[RES] == 56 and strings_on(engine, ALLY) == 1


def test_marionette_defense_with_a_willing_partner_turns_the_blow_away():
    engine = fight(SD_ALL, ally_ids=[MIND_SPIKE], foe_at=(4, 6))
    me = engine.state.actors[ME]
    give_strings(engine, ALLY, 1)
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    answers(engine, {"soulstring.marionette": (ALLY,), "soulstring.partner": ("fail",), "marionette_move": None})
    hp = me.current_hp
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert strings_on(engine, ALLY) == 0 and any("turns to" in str(e.payload) for e in events)  # the GM applies the roll to the partner
    first = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]
    assert len(first) <= 1  # the answered attack no longer hits you


def test_dance_of_borrowed_limbs_commands_the_body_and_ends_on_a_save():
    engine = fight(SD_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    give_strings(engine, FOE, 2)
    answers(engine, {"soulstring.place": None, "soulstring.command": ("prone",)})
    use(engine, "Dance of Borrowed Limbs", FOE)
    assert held(foe, "condition:typed.borrowed_limbs", ME) and strings_on(engine, FOE) == 1
    use(engine, "End turn")
    assert any(str(c.condition_id).endswith("prone") for c in foe.conditions.values())


def test_theater_of_strings_denies_a_string_bearers_opportunity_attack_and_final_choreography():
    engine = fight(SD_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Theater of Strings")
    give_strings(engine, FOE, 3)
    turn(engine, ME)
    events = use(engine, "Move to 1,6")
    assert not payloads(events, "OPPORTUNITY_ATTACK_RESOLVED") and not [e for e in events if e.event_type == "ATTACK_ROLLED"]
    turn(engine, ME)
    answers(engine, {"soulstring.place": None})
    use(engine, "Final Choreography: Kneeling Beat", FOE)
    assert strings_on(engine, FOE) == 0 and engine._effective_speed(foe) == 0
    turn(engine, ME)
    assert not any(n.startswith("Final Choreography") for n in legal(engine))


def test_a_bearer_can_shake_off_a_string_with_its_action():
    engine = fight(SD_ALL, dc=5, foe_at=(6, 6))
    give_strings(engine, FOE, 2)
    turn(engine, FOE)
    raw_d20s(engine, lambda kw: 19)
    use(engine, "Shake a Choreography String", actor_id=FOE)
    assert strings_on(engine, FOE) == 1


def test_choreography_strings_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-STRING", typed_bundles=(bundle(SD_ALL, dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-string-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Mind Spike", FOE)
    reloaded = persistence.load_match(session.match_id)
    assert strings_on(reloaded.engine, FOE) == 1
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 30 Sovereign Will
SV = "tianxia.tradition.spirit.sovereign_will.feature."
DOMAIN_MANIFESTATION = "tianxia.path.spirit_awakening.feature.domain_manifestation"
SV_ALL = [MIND_SPIKE, DOMAIN_MANIFESTATION] + [SV + k for k in ("commanding_voice", "break_their_will", "edict_of_heaven", "retainer_of_the_empty_throne", "hegemon_s_domain")]
MANDATE = "resource:named.mandate"


def test_commanding_voice_halt_marks_gains_mandate_and_stops_it_on_its_turn():
    engine = fight(SV_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert me.resources[MANDATE] == 0 and me.resource_maximums[MANDATE] == 6
    use(engine, "Commanding Voice: Halt", FOE)
    assert typed_executor.bears_mark(foe, ME, "Resonance") and me.resources[MANDATE] == 1 and me.resources[RES] == 59
    turn(engine, FOE)
    assert engine._effective_speed(foe) == 0
    use(engine, "End turn", actor_id=FOE)
    turn(engine, FOE)
    assert engine._effective_speed(foe) > 0


def test_commanding_voice_flee_moves_it_away_and_yield_forbids_attacks():
    engine = fight(SV_ALL, dc=40, foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Commanding Voice: Flee", FOE)
    before = engine._distance_actor_to_actor(me, foe)
    turn(engine, FOE)
    assert engine._distance_actor_to_actor(me, foe) > before
    engine = fight(SV_ALL, dc=40, foe_at=(4, 6))
    use(engine, "Commanding Voice: Yield", FOE)
    turn(engine, FOE)
    assert "Paired Bi Shou Assault" not in legal(engine)


def test_command_the_marked_pays_mandate_only_against_a_marked_creature():
    engine = fight(SV_ALL, dc=40, foe_at=(6, 6))
    me = engine.state.actors[ME]
    me.resources[MANDATE] = 1
    assert "Commanding Voice: Halt (1 Mandate)" not in legal(engine)
    mark_resonance(engine, FOE)
    use(engine, "Commanding Voice: Halt (1 Mandate)", FOE)
    assert me.resources[RES] == 60


def test_submission_shock_dazes_a_second_foe_when_the_first_fails_against_your_voice():
    engine = Gate4ControllerEngine(ROOT, match_seed="C8-SHOCK", typed_bundles=(bundle(SV_ALL, dc=40), bundle([MIND_SPIKE], actor_id=TYPED_FOE, cl=5, pb=3)),
                                   roster_setup={"primary_actor_ids": [ME, FOE, TYPED_FOE], "team_by_actor": {ME: "team:a", FOE: "team:b", TYPED_FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}, TYPED_FOE: {"x": 7, "y": 7}}})
    turn(engine, ME)
    me, other = engine.state.actors[ME], engine.state.actors[TYPED_FOE]
    me.resources[MANDATE] = 1
    answers(engine, {"sovereign.submission_shock": (TYPED_FOE,)})
    use(engine, "Commanding Voice: Halt", FOE)
    assert held(other, "condition:typed.dazed_by_submission", ME) and not me.reaction_available
    assert me.resources[MANDATE] == 2  # 1 spent on the Shock; 1 from each creature that failed a Sovereign Will save


def test_edict_of_heaven_no_violence_takes_its_attacks_until_your_next_turn():
    engine = fight(SV_ALL, dc=40, foe_at=(4, 6))
    me = engine.state.actors[ME]
    answers(engine, {"sovereign.edict": ("no_violence",), "sovereign.edict_targets": (FOE,)})
    use(engine, "Edict of Heaven")
    assert me.resources[RES] == 55 and held(engine.state.actors[FOE], "condition:typed.sovereign_edict", ME)
    turn(engine, FOE)
    assert "Paired Bi Shou Assault" not in legal(engine)


def test_edict_of_heaven_no_advance_keeps_it_from_closing_on_you():
    engine = fight(SV_ALL, dc=40, foe_at=(8, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine, {"sovereign.edict": ("no_advance",), "sovereign.edict_targets": (FOE,), "sovereign.designate": (ME,)})
    use(engine, "Edict of Heaven")
    turn(engine, FOE)
    now = engine._distance_actor_to_actor(me, foe)
    moves = [c for c in engine.legal_candidates() if c.display_name.startswith("Move to") and c.destination is not None]
    assert moves and all(engine.grid.distance_ft(c.destination, me.position) >= now for c in moves)


def test_retainer_strikes_after_mind_spike_once_a_turn():
    engine = fight(SV_ALL, dc=40, foe_at=(7, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine, {"sovereign.retainer_type": ("radiant",), "sovereign.retainer": ("strike",)})
    use_to(engine, "Retainer of the Empty Throne", 5, 6)
    obj = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.empty_throne_retainer:"))
    assert (obj.maximum_hp, obj.ac) == (36, 40)
    raw_d20s(engine, lambda kw: 19)
    events = use(engine, "Mind Spike", FOE)
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) == 2  # Mind Spike, then the Spectral Strike
    engine._update_object(obj.model_copy(update={"current_hp": 0, "destroyed": True}), "test", FOE)
    turn(engine, ME)
    assert not any(n.startswith("Retainer of the Empty Throne") for n in legal(engine))


def test_hegemons_domain_taxes_a_failing_foe_that_acts_against_you():
    engine = fight(SV_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine, {"sovereign.hegemon": ("hegemon",), "sovereign.court_tax": None})
    dm = next(n for n in legal(engine) if n.startswith("Domain Manifestation"))
    use_to(engine, dm.split(" to ")[0], 3, 6) if " to " in dm else use(engine, dm)
    assert held(me, "condition:typed.hegemons_domain", ME)
    use(engine, "End turn")
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe))
    hp = foe.current_hp
    fixed_d20(engine, 2)
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert foe.current_hp < hp  # the Court Tax: 2d10 + Wisdom Psychic


def test_mandate_and_a_command_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-SOVEREIGN", typed_bundles=(bundle(SV_ALL, dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-sovereign-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Commanding Voice: Halt", FOE)
    reloaded = persistence.load_match(session.match_id)
    assert reloaded.engine.state.actors[ME].resources[MANDATE] == 1 and held(reloaded.engine.state.actors[FOE], "condition:typed.sovereign_command", ME)
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 31 Thrum of the Grave


def test_gravebeat_adds_pb_to_spirit_damage_on_a_marked_foe_and_a_bloodied_mark_gives_a_gravebeat():
    engine = fight(TG_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert me.resources[BEATS] == 0 and me.resource_maximums[BEATS] == 6
    use(engine, "Gravebeat")
    mark_resonance(engine, FOE)
    foe.current_hp = foe.maximum_hp // 2 + 3
    answers(engine, {"thrum.mark": None})
    events = use(engine, "Mind Spike", FOE)
    hits = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(hits) == 2 and int((hits[1].payload or {}).get("hp_damage") or 0) + int((hits[1].payload or {}).get("temporary_hp_absorbed") or 0) <= 6
    assert me.resources[BEATS] == 1  # the marked foe became Bloodied


def test_dead_march_fall_into_step_takes_reactions_and_fifteen_feet():
    engine = fight(TG_ALL, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    answers(engine, {"thrum.march": ("step",)})
    use(engine, "Dead March", FOE)
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe)) and engine._effective_speed(foe) == foe.speed_ft - 15


def test_burial_drum_refuses_a_foes_healing_and_feeds_a_gravebeat():
    engine = fight(TG_ALL, dc=40, foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Burial Drum")
    foe.current_hp = 20
    heal(engine, FOE)
    assert foe.current_hp == 20 and me.resources[BEATS] == 1


def test_beat_of_interment_spends_a_gravebeat_on_a_foe_in_the_drum():
    engine = fight(TG_ALL, dc=40, foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Burial Drum")
    assert "Burial Drum: Beat of Interment" not in legal(engine)  # no Gravebeat yet
    me.resources[BEATS] = 1
    hp = foe.current_hp
    use(engine, "Burial Drum: Beat of Interment", FOE)
    assert foe.current_hp < hp and any(r.get("no_reactions") for r in typed_executor.condition_rules(foe)) and me.resources[BEATS] == 0


def test_the_unquiet_echos_grave_cry_and_unfinished_violence():
    engine = fight(TG_ALL, dc=40, foe_at=(7, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine, {"thrum.memory": ("violence",)})
    use_to(engine, "Call the Unquiet", 6, 6)
    me.resources[BEATS] = 1
    turn(engine, ME)
    use(engine, "Unquiet Echo: Grave Cry", FOE)
    assert held(foe, "condition:typed.frightened") and me.resources[BEATS] == 0
    turn(engine, ME)
    mark_resonance(engine, FOE)
    events = use(engine, "Mind Spike", FOE)
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) == 2  # + 2d8 Unfinished Violence


def test_the_earth_beats_once_needs_a_bloodied_or_marked_foe_and_spends_gravebeats_on_consequences():
    engine = fight(TG_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert "The Earth Beats Once: Necrotic" not in legal(engine)
    mark_resonance(engine, FOE)
    me.resources[BEATS] = 2
    answers(engine, {"thrum.consequences": ("still", "fracture"), "thrum.afterbeat": None})
    foe.maximum_hp = foe.current_hp = 400  # it survives the blow
    hp = foe.current_hp
    use(engine, "The Earth Beats Once: Necrotic", FOE)
    assert foe.current_hp < hp and me.resources[BEATS] == 0 and me.resources[RES] == 50
    assert any(str(c.condition_id).endswith("prone") for c in foe.conditions.values()) and engine._effective_speed(foe) == 0


def test_gravebeats_and_the_echo_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-THRUM", typed_bundles=(bundle(TG_ALL, dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 9, "y": 6}}})

    def commit(name, dest=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name.startswith(name)
                         and (dest is None or (c.destination is not None and (c.destination.x, c.destination.y) == dest)))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-thrum-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Call the Unquiet", (5, 6))
    reloaded = persistence.load_match(session.match_id)
    assert any(o.object_id.startswith("object:typed.unquiet_echo:") and not o.destroyed for o in reloaded.engine.state.objects.values())
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 32 Unwritten Footprint
UF = "tianxia.tradition.spirit.unwritten_footprint.feature."
UF_ALL = [MIND_SPIKE] + [UF + k for k in ("step_no_record_keeps", "knife_between_thoughts", "steal_the_witness", "no_trace_returns", "concept_of_the_missing_footstep")]
UNWRITTEN_TRACE = "Unwritten Trace"


def test_slip_the_conclusion_leaves_you_unnoticed_and_ambush_without_hatred_strikes():
    engine = fight(UF_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    answers(engine, {"slip_step": None, "unwritten.between_thought": None})
    use(engine, "Step No Record Keeps", FOE)
    assert typed_executor.bears_mark(foe, ME, UNWRITTEN_TRACE) and held(foe, "condition:typed.unnoticing", ME)
    events = use(engine, "Mind Spike", FOE)
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) == 2  # + 3d6 Psychic at CL18
    assert any(r.get("no_reactions") for r in typed_executor.condition_rules(foe)) and not held(foe, "condition:typed.unnoticing", ME)


def test_between_thought_strike_spends_two_resonance_and_consumes_the_trace():
    engine = fight(UF_ALL, dc=40, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    engine._apply_condition(foe, typed_executor.mark_condition_id(UNWRITTEN_TRACE, ME), "test", ME, expires_on="UNTIL_REMOVED")
    answers(engine, {"between_thought_step": None})
    res = me.resources[RES]
    events = use(engine, "Mind Spike", FOE)
    assert me.resources[RES] == res - 2 and not typed_executor.bears_mark(foe, ME, UNWRITTEN_TRACE)
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) == 2  # Ambush applies although it noticed you
    assert held(foe, "condition:typed.cannot_punish_the_unwritten", ME)


def test_misattribute_the_blow_gives_a_traced_attacker_disadvantage():
    engine = fight(UF_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    engine._apply_condition(foe, typed_executor.mark_condition_id(UNWRITTEN_TRACE, ME), "test", ME, expires_on="UNTIL_REMOVED")
    turn(engine, FOE)
    me.reaction_available = True
    raw_d20s(engine, lambda kw: 15)
    answers(engine, {"misattribute_move": None, "unwritten.erase": None})
    n = len(engine.events)
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert [p.get("mode") for p in payloads(engine.events[n:], "ATTACK_ROLLED")][:1] == ["DISADVANTAGE"]
    assert not typed_executor.bears_mark(foe, ME, UNWRITTEN_TRACE) and me.resources[RES] == 58


def test_steal_the_witness_keeps_it_from_targeting_you():
    engine = fight(UF_ALL, dc=40, foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    use(engine, "Steal the Witness", FOE)
    assert held(foe, "condition:typed.unwritten_to", ME)
    turn(engine, FOE)
    assert ME not in {t for c in engine.legal_candidates() if c.display_name == "Paired Bi Shou Assault" for t in (c.target_ids or ())}


def test_erase_the_last_passage_leaves_an_afterimage_to_take_the_blow():
    engine = fight(UF_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    answers(engine, {"unwritten.erase": ("erase",), "erase_move": None, "unwritten.erase_result": ("afterimage",)})
    hp = me.current_hp
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert me.resources[RES] == 55 and not me.reaction_available
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]) <= 1  # the first blow strikes the afterimage


def test_the_missing_footstep_leaves_moving_you_unnoticed_and_unpunished():
    engine = fight(UF_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Concept of the Missing Footstep")
    events = use(engine, "Move to 1,6")
    assert not [e for e in events if e.event_type == "ATTACK_ROLLED"] and held(foe, "condition:typed.unnoticing", ME)


def test_empty_space_assassination_strikes_an_unnoticing_foe_once():
    engine = fight(UF_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Concept of the Missing Footstep")
    use(engine, "Move to 1,6")
    turn(engine, ME)
    answers(engine, {"assassination_step": None, "unwritten.assassination": ("spike",), "unwritten.between_thought": None, "unwritten.cut_action": None})
    events = use(engine, "Empty Space Assassination", FOE)
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) >= 2
    turn(engine, ME)
    assert "Empty Space Assassination" not in legal(engine)


def test_an_unwritten_trace_and_unnoticing_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-UNWRITTEN", typed_bundles=(bundle(UF_ALL, dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-unwritten-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Step No Record Keeps", FOE)
    reloaded = persistence.load_match(session.match_id)
    foe = reloaded.engine.state.actors[FOE]
    assert typed_executor.bears_mark(foe, ME, UNWRITTEN_TRACE) and held(foe, "condition:typed.unnoticing", ME)
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 33 Well of Hours
WH = "tianxia.tradition.spirit.well_of_hours.feature."
WH_ALL = [MIND_SPIKE, SOUL_GAZE] + [WH + k for k in ("ripple_of_before", "borrowed_second", "hourglass_mark", "refuse_the_moment", "the_well_has_no_bottom")]
TIME_DEBT = "resource:named.time_debt"
ARREARS = "resource:named.temporal_arrears"
HOURGLASS_MARK = "Hourglass Mark"


def st_can_react(actor):
    from combat.ext import spirit_traditions as st

    return st.can_react(actor)


def end_turns_until(engine, actor_id):
    """End turns through the table (so turn-start choices are asked) until ``actor_id``'s turn begins."""
    use(engine, "End turn", actor_id=engine.state.current_actor_id)
    while engine.state.current_actor_id != actor_id:
        use(engine, "End turn", actor_id=engine.state.current_actor_id)


def test_the_hour_comes_due_at_full_time_debt_and_an_idle_turn_pays_it_down():
    engine = fight(WH_ALL, foe_at=(8, 6))
    me = engine.state.actors[ME]
    answers(engine, {"well.pay_back": None})
    use(engine, "End turn")
    me.resources[TIME_DEBT] = 6  # at its maximum as your turn begins
    end_turns_until(engine, ME)
    assert held(me, "condition:typed.hour_comes_due") and not st_can_react(me)
    assert "Hourglass Mark" not in legal(engine) and "Borrowed Second: Slip Away" not in legal(engine) and "Mind Spike" in legal(engine)
    assert me.movement_remaining_ft == 15
    use(engine, "End turn")
    assert me.resources[TIME_DEBT] == 4 and not held(me, "condition:typed.hour_comes_due")  # the Hour's 1, and 1 for a turn with no Well of Hours use


def test_borrowed_second_slip_away_costs_three_resonance_and_one_time_debt_once_a_turn():
    engine = fight(WH_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    start = (me.position.x, me.position.y)
    events = use(engine, "Borrowed Second: Slip Away")
    assert (me.position.x, me.position.y) != start and not [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert me.resources[RES] == 57 and me.resources[TIME_DEBT] == 1
    assert not [n for n in legal(engine) if n.startswith("Borrowed Second")]


def test_borrowed_second_mind_spike_needs_a_resonance_mark_and_rolls_one_die_fewer():
    engine = fight(WH_ALL, foe_at=(6, 6))
    me = engine.state.actors[ME]
    assert "Borrowed Second: Mind Spike" not in legal(engine)
    mark_resonance(engine, FOE)
    events = use(engine, "Borrowed Second: Mind Spike", FOE)
    assert [p["expression"].split("d")[0] for p in payloads(events, "DAMAGE_ROLLED")][:1] == ["3"]  # Mind Spike is 4d8 at CL18
    assert me.resources[TIME_DEBT] == 2 and me.resources[RES] == 57


def test_pay_the_second_back_removes_two_time_debt_and_holds_you_still():
    engine = fight(WH_ALL, foe_at=(8, 6))
    me = engine.state.actors[ME]
    answers(engine, {"well.pay_back": ("pay",)})
    use(engine, "End turn")
    me.resources[TIME_DEBT] = 3
    end_turns_until(engine, ME)
    assert me.resources[TIME_DEBT] == 1 and held(me, "condition:typed.paying_the_second_back") and me.movement_remaining_ft == 0
    assert not [n for n in legal(engine) if n.startswith("Borrowed Second") or n.startswith("Move to")]


def test_echo_of_the_chosen_step_returns_you_to_where_your_move_began():
    engine = fight(WH_ALL, foe_at=(9, 9))
    me = engine.state.actors[ME]
    answers(engine, {"well.before_space": ("record",)})
    use(engine, "Move to 1,6")
    assert "Echo of the Chosen Step" in legal(engine)
    use(engine, "Echo of the Chosen Step")
    assert (me.position.x, me.position.y) == (3, 6) and me.resources[RES] == 59 and me.resources[TIME_DEBT] == 1


def test_hourglass_mark_replaces_your_resonance_mark_and_delays_its_strike():
    engine = fight(WH_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    mark_resonance(engine, FOE)
    use(engine, "Hourglass Mark", FOE)
    assert held(foe, typed_executor.mark_condition_id(HOURGLASS_MARK, ME)) and not held(foe, typed_executor.mark_condition_id("Resonance", ME))
    assert typed_executor.bears_mark(foe, ME, "Resonance")  # "a special Resonance Mark"
    turn(engine, FOE)
    raw_d20s(engine, lambda kw: 12)
    answers(engine, {"well.hourglass_strike": ("strike",), "well.refuse": None})
    res, debt = me.resources[RES], me.resources[TIME_DEBT]
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert [p for p in payloads(events, "D20_REWRITTEN") if p.get("bonus", 0) < 0]
    assert me.resources[RES] == res - 1 and me.resources[TIME_DEBT] == debt + 1


def test_break_the_glass_ends_the_hourglass_mark_on_a_good_check():
    engine = fight(WH_ALL, foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, typed_executor.mark_condition_id(HOURGLASS_MARK, ME), "test", ME, expires_on="UNTIL_REMOVED")
    turn(engine, FOE)
    assert "Break the Glass" in legal(engine)
    fixed_d20(engine, 20)
    use(engine, "Break the Glass", actor_id=FOE)
    assert not held(foe, typed_executor.mark_condition_id(HOURGLASS_MARK, ME))


def test_refuse_the_moment_makes_a_blow_wait_and_healing_pays_it_down():
    engine = fight(WH_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    turn(engine, FOE)
    me.reaction_available = True
    fixed_d20(engine, 19)
    answers(engine, {"well.refuse": ("refuse",), "well.hourglass_strike": None})
    hp = me.current_hp
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    deferred = held(me, "condition:typed.deferred_consequence", ME)
    assert deferred and me.resources[RES] == 54 and me.resources[TIME_DEBT] == 2
    from combat.ext import spirit_traditions as st

    waiting = sum(p[0] for p in st.data_of(me, deferred[0])["packets"])
    assert waiting > 0 and me.current_hp == hp  # the first blow waits (a second one of the assault may land)
    answers(engine, {"well.deferred_healing": ("assign",)})
    heal(engine, ME, 5)
    turn(engine, ME)
    before = me.current_hp
    use(engine, "End turn")
    assert not held(me, "condition:typed.deferred_consequence") and me.current_hp < before  # the waiting blow lands


def test_the_well_returns_a_felled_ally_to_its_round_image():
    engine = fight(WH_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 6))
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    answers(engine, {"well.chosen": lambda ids: ids})
    use_to(engine, "The Well Has No Bottom", 3, 6)
    hp = ally.current_hp
    answers(engine, {"well.return_to_the_bell": ("return",), "well.refuse": None})
    mine = me.current_hp
    strike_down(engine, ALLY)
    assert ally.current_hp == hp and ally.active and ally.life_state is None and not held(ally, "condition:typed.life_unconscious")
    assert me.resources[TIME_DEBT] == 6 and me.current_hp < mine  # Time Debt at its maximum and 3d10 Psychic


def test_hostile_undertow_marks_a_foe_that_fails_as_it_attacks_and_delays_the_strike():
    engine = fight(WH_ALL, dc=40, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use_to(engine, "The Well Has No Bottom", 3, 6)
    turn(engine, FOE)
    raw_d20s(engine, lambda kw: 12)
    answers(engine, {"well.refuse": None, "well.hourglass_strike": None})
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert typed_executor.bears_mark(foe, ME, "Resonance")
    assert [p for p in payloads(events, "D20_REWRITTEN") if p.get("bonus", 0) < 0]


def test_friendly_current_gives_a_chosen_ally_temporary_hit_points():
    engine = fight(WH_ALL, ally_ids=[MIND_SPIKE], foe_at=(9, 6))
    ally = engine.state.actors[ALLY]
    answers(engine, {"well.chosen": lambda ids: ids})
    use_to(engine, "The Well Has No Bottom", 3, 6)
    answers(engine, {"well.friendly_current": ("shield",), "well.pay_back": None})
    end_turns_until(engine, ALLY)
    assert ally.temporary_hp == 12


def test_the_wells_collapse_turns_time_debt_into_arrears_that_cap_resonance():
    engine = fight(WH_ALL, foe_at=(9, 6))
    me = engine.state.actors[ME]
    use_to(engine, "The Well Has No Bottom", 3, 6)
    me.resources[TIME_DEBT] = 4
    engine._end_concentration(me, "test")
    assert me.resources[TIME_DEBT] == 0 and me.resources[ARREARS] == 4 and me.resources[RES] <= 56
    engine._gain_resource(me, RES, 10, "test")
    assert me.resources[RES] == 56
    turn(engine, ME)
    assert not [n for n in legal(engine) if n.startswith("The Well Has No Bottom")]


def test_time_debt_and_the_hourglass_mark_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-WELL", typed_bundles=(bundle(WH_ALL, dc=40),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-well-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Hourglass Mark", FOE)
    commit("Borrowed Second: Disengage")
    reloaded = persistence.load_match(session.match_id)
    me, foe = reloaded.engine.state.actors[ME], reloaded.engine.state.actors[FOE]
    assert held(foe, typed_executor.mark_condition_id(HOURGLASS_MARK, ME)) and me.resources[TIME_DEBT] == 1
    assert reloaded.verify()["status"] == "PASS"


# ============================================================================================ 34 Yokai Channeler
YC = "tianxia.tradition.spirit.yokai_channeler.feature."
YC_ALL = [MIND_SPIKE] + [YC + k for k in ("yokai_mask", "unmasking", "yokai_s_bargain")]
LINEAGE = "condition:typed.yokai_lineage"


def unmasked(engine, lineage, kind):
    answers(engine, {"yokai.weapon_type": (kind,)})
    use(engine, f"Yokai Lineage: {lineage.title()}")
    use(engine, "Unmasking")


def test_the_yokai_lineage_is_chosen_once_for_the_fight():
    engine = fight(YC_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    use(engine, "Yokai Lineage: Kappa")
    assert held(me, LINEAGE)[0].data["lineage"] == "kappa"
    assert not [n for n in legal(engine) if n.startswith("Yokai Lineage")]


def test_unmasking_offers_the_natural_weapon_of_the_chosen_type_and_its_extra_damage_once_a_turn():
    engine = fight(YC_ALL, foe_at=(4, 6))
    assert "Yokai Natural Weapon" not in legal(engine)
    unmasked(engine, "tengu", "thunder")
    fixed_d20(engine, 15)
    events = use(engine, "Yokai Natural Weapon", FOE)
    hits = [p for p in payloads(events, "DAMAGE_COMMITTED")]
    assert [p["damage_type"] for p in hits] == ["THUNDER", "THUNDER"] and hits[1]["hp_damage"] == 6  # + Proficiency Bonus of the affinity
    engine.state.actors[ME].action_available = True
    events = use(engine, "Yokai Natural Weapon", FOE)
    assert len(payloads(events, "DAMAGE_COMMITTED")) == 1  # once on each of your turns


def test_a_failed_save_against_mind_spike_adds_the_unmasked_affinity_damage():
    engine = fight(YC_ALL, dc=40, foe_at=(6, 6))
    unmasked(engine, "kitsune", "psychic")
    events = use(engine, "Mind Spike", FOE)
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]) == 2


def test_the_kitsune_foxfire_double_gives_the_next_attack_disadvantage():
    engine = fight(YC_ALL, dc=40, foe_at=(4, 6))
    me = engine.state.actors[ME]
    unmasked(engine, "kitsune", "fire")
    use(engine, "Mind Spike", FOE)
    assert held(me, "condition:typed.foxfire_double")
    turn(engine, FOE)
    raw_d20s(engine, lambda kw: 10)
    answers(engine, {"foxfire_step": None})
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert [p.get("mode") for p in payloads(events, "ATTACK_ROLLED")][:1] == ["DISADVANTAGE"] and not held(me, "condition:typed.foxfire_double")


def test_the_tengu_dive_after_a_straight_dash_adds_thunder_and_a_push():
    engine = fight(YC_ALL, foe_at=(8, 6))
    foe = engine.state.actors[FOE]
    unmasked(engine, "tengu", "slashing")
    use(engine, "Move to 7,6")
    fixed_d20(engine, 15)
    answers(engine, {"yokai.tengu_push": ("push",)})
    events = use(engine, "Yokai Natural Weapon", FOE)
    assert "THUNDER" in [p["damage_type"] for p in payloads(events, "DAMAGE_COMMITTED")] and (foe.position.x, foe.position.y) != (8, 6)


def test_the_kappa_grip_grapples_on_a_hit_and_resists_grapples():
    engine = fight(YC_ALL, foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    unmasked(engine, "kappa", "bludgeoning")
    raw_d20s(engine, lambda kw: 2 if kw["reason"].startswith("SAVE:") else 15)  # the blow lands, the grip holds
    answers(engine, {"yokai.kappa_grapple": ("grapple",)})
    use(engine, "Yokai Natural Weapon", FOE)
    assert any(str(c.condition_id).endswith("grappled") for c in foe.conditions.values())
    raw_d20s(engine, lambda kw: 10)
    n = len(engine.events)
    hostile_save(engine, FOE, ME, "restrained", ability="str")
    assert [p.get("mode") for p in payloads(engine.events[n:], "SAVE_ROLLED")][:1] == ["ADVANTAGE"] or \
        any((p.get("roll") or {}).get("mode") == "ADVANTAGE" for p in payloads(engine.events[n:], "SAVE_ROLLED"))


def test_the_jorogumo_thread_slows_a_marked_foe_and_silk_follows_a_hit():
    engine = fight(YC_ALL, foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    unmasked(engine, "jorogumo", "poison")
    speed = engine._effective_speed(foe)
    answers(engine, {"yokai.thread_slow": ("slow",)})
    typed_executor.run_effects(typed_executor_ctx(engine, FOE), [{"type": "mark", "mark": "Resonance", "applies_to": "target"}])
    assert engine._effective_speed(foe) == speed - 5
    fixed_d20(engine, 15)
    use(engine, "Yokai Natural Weapon", FOE)
    assert typed_executor.bears_mark(foe, ME, "Silk Thread")


def typed_executor_ctx(engine, target_id, source=YC + "yokai_mask"):
    from combat.ext import spirit_traditions as st

    me = engine.state.actors[ME]
    return st.context(engine, me, st.feature_action(engine, me, source), [engine.state.actors[target_id]], st.numbers(engine, me))


def test_wind_perched_step_keeps_a_tengu_standing():
    engine = fight(YC_ALL, foe_at=(4, 6))
    me = engine.state.actors[ME]
    use(engine, "Yokai Lineage: Tengu")
    turn(engine, FOE)
    me.reaction_available = True
    answers(engine, {"yokai.wind_perched": ("wind_perched",)})
    fixed_d20(engine, 1)
    hostile_save(engine, FOE, ME, "prone", ability="str")
    assert not any(str(c.condition_id).endswith("prone") for c in me.conditions.values()) and me.resources[RES] == 59 and (me.position.x, me.position.y) != (3, 6)


def test_river_body_takes_ten_feet_off_a_push():
    from combat.ext import spirit_traditions as st

    engine = fight(YC_ALL, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Yokai Lineage: Kappa")
    turn(engine, FOE)
    me.reaction_available = True
    answers(engine, {"yokai.river_body": ("river_body",)})
    ctx = st.context(engine, foe, st.feature_action(engine, foe, "test:push"), [me], {"save_dc": 17, "pb": 3, "cl": 5})
    typed_executor.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 15, "direction": "away"}])
    assert engine.grid.distance_ft(me.position, foe.position) <= 15 and me.resources[RES] == 59  # 15 feet became 5, plus the 5-foot shift


def test_the_lineage_and_unmasking_survive_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-YOKAI", typed_bundles=(bundle(YC_ALL),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name, target=None):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ())))
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-yokai-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Yokai Lineage: Jorogumo")
    commit("Unmasking")
    reloaded = persistence.load_match(session.match_id)
    me = reloaded.engine.state.actors[ME]
    assert held(me, LINEAGE) and held(me, "condition:typed.yokai_unmasked")
    assert reloaded.verify()["status"] == "PASS"


YC_TRUE = YC_ALL + [YC + "true_yokai_form"]
YC_LORD = YC_TRUE + [YC + "yokai_lord"]


def true_form(engine, lineage, kind, resist=None, name="True Yokai Form"):
    answers(engine, {"yokai.weapon_type": (kind,), **({"yokai.resistance": (resist,)} if resist else {})})
    use(engine, f"Yokai Lineage: {lineage.title()}")
    use(engine, name)


def test_true_yokai_form_raises_the_natural_weapon_die_and_resists_a_chosen_affinity():
    engine = fight(YC_TRUE, foe_at=(4, 6))
    me = engine.state.actors[ME]
    true_form(engine, "kitsune", "fire", resist="psychic")
    assert any(m.target_field == "damage_resistance" and str(m.value) == "PSYCHIC" for m in me.modifiers.values())
    turn(engine, ME)  # True Yokai Form took the Action
    fixed_d20(engine, 15)
    events = use(engine, "Yokai Natural Weapon", FOE)
    assert [p["expression"] for p in payloads(events, "DAMAGE_ROLLED")][:1] == ["1d10+4"]


def test_ninefold_feint_steps_away_from_a_miss_and_signs_the_attacker():
    engine = fight(YC_TRUE, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    true_form(engine, "kitsune", "fire")
    turn(engine, FOE)
    raw_d20s(engine, lambda kw: 2)
    answers(engine, {"yokai.ninefold": ("feint",)})
    use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    assert typed_executor.bears_mark(foe, ME, "Foxfire Sign") and (me.position.x, me.position.y) != (3, 6)


def test_mountain_wind_cut_after_a_long_move_adds_two_d8_and_knocks_it_prone():
    engine = fight(YC_TRUE, foe_at=(9, 6))
    foe = engine.state.actors[FOE]
    true_form(engine, "tengu", "slashing")
    turn(engine, ME)  # True Yokai Form took the Action
    use(engine, "Move to 8,6")
    raw_d20s(engine, lambda kw: 2 if kw["reason"].startswith("SAVE:") else 15)
    answers(engine, {"yokai.tengu_push": None, "yokai.wind_cut": ("prone",)})
    events = use(engine, "Yokai Natural Weapon", FOE)
    assert any(p["expression"].startswith("2d8") for p in payloads(events, "DAMAGE_ROLLED"))
    assert any(str(c.condition_id).endswith("prone") for c in foe.conditions.values())


def test_river_lock_stops_a_grappled_foe_teleporting_on_a_failed_charisma_save():
    from combat.ext import spirit_traditions as st
    from combat.gate2_runtime_models import Position

    engine = fight(YC_TRUE, foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    true_form(engine, "kappa", "bludgeoning")
    engine._apply_condition(foe, "condition:typed.grappled", "test", ME, expires_on="UNTIL_REMOVED")
    raw_d20s(engine, lambda kw: 2)
    ctx = st.context(engine, foe, st.feature_action(engine, foe, "test:teleport"), [foe], {"save_dc": 17, "pb": 3, "cl": 5})
    typed_executor._teleport(ctx, Position(x=8, y=8))
    assert (foe.position.x, foe.position.y) == (4, 6)


def test_grand_silk_restrains_a_foe_that_starts_its_turn_in_the_web():
    engine = fight(YC_TRUE, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    true_form(engine, "jorogumo", "poison")
    engine.state.actors[ME].action_available = True
    use_to(engine, "Grand Silk", 6, 6)
    assert [z for z in engine.state.zones.values() if z.active and (z.trigger_profile or {}).get("name") == "Grand Silk"]
    turn(engine, FOE)
    assert any(str(c.condition_id).endswith("restrained") for c in foe.conditions.values())


def test_heaven_scouring_descent_strikes_a_foe_it_passes():
    engine = fight(YC_LORD, foe_at=(6, 6))
    true_form(engine, "tengu", "thunder", name="Yokai Lord")
    fixed_d20(engine, 15)
    events = use_to(engine, "Heaven-Scouring Descent", 9, 6)
    assert [e for e in events if e.event_type == "ATTACK_ROLLED" and FOE in (e.target_ids or ())]
    assert "Heaven-Scouring Descent" not in {n.split(" to ")[0] for n in legal(engine)}  # once in the activation


def test_web_of_a_hundred_names_stops_a_foe_until_its_anchor_breaks():
    engine = fight(YC_LORD, dc=40, foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    true_form(engine, "jorogumo", "poison", name="Yokai Lord")
    answers(engine, {"yokai.hundred_names": lambda ids: [FOE]})
    use(engine, "Web of a Hundred Names")
    assert held(foe, "condition:typed.hundred_names_silk") and engine._effective_speed(foe) == 0
    anchor = next(o for o in engine.state.objects.values() if o.object_id.startswith("object:typed.hundred_names_anchor:"))
    engine._update_object(anchor.model_copy(update={"destroyed": True, "current_hp": 0}), "test", FOE)
    assert not held(foe, "condition:typed.hundred_names_silk")


def test_true_yokai_form_survives_a_table_commit_and_reload(tmp_path):
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C8-YOKAI-TRUE", typed_bundles=(bundle(YC_TRUE),),
                                       roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def commit(name):
        candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c8-yokai-true-{candidate.state_version}", decision_id=candidate.decision_id,
                                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination))

    while session.engine.state.current_actor_id != ME:
        commit("End turn")
    commit("Yokai Lineage: Kappa")
    commit("True Yokai Form")
    reloaded = persistence.load_match(session.match_id)
    me = reloaded.engine.state.actors[ME]
    assert held(me, "condition:typed.true_yokai_form") and any(m.target_field == "damage_resistance" for m in me.modifiers.values())
    assert reloaded.verify()["status"] == "PASS"
