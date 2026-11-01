"""Automation lane H3, part 2: Dying, Stable and death, on the lock round's ``zero_hp`` hook (combat/ext/life_state.py).

The table's default is unchanged (a creature at 0 Hit Points leaves the map); a creature carrying an ability of the life-and-death
rules goes down Dying, rolls death saving throws, can be stabilized, and -- when a soul-return talent could reach it -- lingers dead
for the talent's window.
"""

import pytest

from combat import ext
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from combat.gate4_engine import Gate4ControllerEngine
from combat.ext import life_state
from tests.test_auto_lane2 import ALLY, ME, ROOT, _legal, _payloads, _sheet, _use
from tests.test_lock_choices import install

SOUL = "typed.soul_lingering"
SEAL = "typed.yellow_spring_seal"
MODE = "typed.death_save_mode"
DEATHLESS = "TAL_BERSERKER_DEATHLESS"
ONE_BREATH = "tianxia.talent.life.one_breath_resuscitation"
MINUTE_GATE = "tianxia.talent.life.minute_gate_resuscitation"
SOUL_LAMP = "tianxia.talent.life.soul_lamp_continuity"
YELLOW = "tianxia.talent.life.yellow_spring_refusal_seal"


def _bundle(actor, sphere=None, talents=(), **kw):
    return compile_character(_sheet(sphere, list(talents), **kw), actor_id=actor)


def _fight(me, ally=None, *, foe_at=(4, 6), third=None):
    bundles, teams, places, roster = (me,), {ME: "team:a", AN: "team:b"}, {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}, [ME, AN]
    for actor, bundle, at, team in ((ALLY, ally, (2, 6), "team:a"), ("actor:factory.third", third, (2, 7), "team:a")):
        if bundle is not None:
            bundles += (bundle,)
            roster.append(actor)
            teams[actor], places[actor] = team, {"x": at[0], "y": at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed="H3LIFE", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": roster, "team_by_actor": teams, "starting_positions": places})
    _turn(engine, ME)
    engine.state.actors[AN].armor_class = -50
    return engine


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    return engine.state.actors[actor_id]


def _use_on(engine, name, target):
    """Use the ability on this creature (an ability that can be aimed at several has a button for each)."""
    matches = [c for c in engine.legal_candidates() if c.display_name == name and target in (c.target_ids or ())]
    assert matches, f"{name!r} cannot be aimed at {target}; legal: {sorted({c.display_name for c in engine.legal_candidates() if c.kind.value != 'MOVE'})}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine.events[before:]


def _hit(engine, target, amount=None, *, kind="SLASHING"):
    amount = target.current_hp + 3 if amount is None else amount
    return engine._commit_damage(target, amount, kind, "test:blow", AN, None, reaction_depth=0)


def _rolls(monkeypatch, *naturals):
    """The next d20s come up as these (every d20 the fight rolls is one of them, in order)."""
    queue = list(naturals)
    install(monkeypatch, "d20_result", lambda engine, roll, intent: {"source_id": "test:die", "operation": "replace", "natural_result": queue.pop(0)})
    return queue


def _saves(engine):
    return [e.payload for e in engine.events if e.event_type == "CHECK_ROLLED" and e.payload.get("skill") == "Death Saving Throw"]


def _conditions(actor):
    return {c.condition_id.removeprefix("condition:") for c in actor.conditions.values()}


def _deathless_ally(**kw):
    return _bundle(ALLY, "tianxia.sphere.berserker", [DEATHLESS], **kw)


@pytest.fixture()
def dying():
    engine = _fight(_bundle(ME), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    assert ally.life_state == "DYING"
    return engine, ally


# ------------------------------------------------------------------------------------------------------ the default
def test_a_creature_without_these_abilities_still_leaves_the_map_at_zero():
    engine = _fight(_bundle(ME), _bundle(ALLY))
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    assert not ally.active and ally.life_state is None and ally.current_hp == 0
    assert not any(e.event_type == "LIFE_STATE_CHANGED" for e in engine.events) and not life_state.is_dead(ally)


def test_the_switch_makes_every_creature_dying_at_zero(monkeypatch):
    monkeypatch.setattr(life_state, "DEATH_SAVES_FOR_ALL", True)
    engine = _fight(_bundle(ME), _bundle(ALLY))
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    assert ally.active and ally.life_state == "DYING"


def test_a_deathless_body_goes_down_dying_and_keeps_its_place():
    """"Advantage on death saving throws" is meaningless for a creature that leaves the map at 0: the owner now goes down Dying."""
    engine = _fight(_bundle(ME), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    assert ally.active and ally.life_state == "DYING" and ally.current_hp == 0
    assert (ally.position.x, ally.position.y) in engine._occupied_cells_except(ME)
    assert not (ally.action_available or ally.bonus_action_available or ally.reaction_available) and ally.movement_remaining_ft == 0


# ------------------------------------------------------------------------------------------------------ death saving throws
def test_a_dying_creature_rolls_a_death_save_at_the_start_of_its_turn_with_advantage_from_deathless(dying, monkeypatch):
    engine, ally = dying
    _rolls(monkeypatch, 14)
    _turn(engine, ALLY)
    saves = _saves(engine)
    assert len(saves) == 1 and saves[0]["dc"] == 10 and saves[0]["success"] is True
    assert saves[0]["actor"]["mode"] == "ADVANTAGE" and saves[0]["actor"]["natural_result"] == 14  # Deathless
    assert life_state._record(ally) == {"ok": 1, "bad": 0}


def test_three_successes_make_it_stable_and_three_failures_kill_it(dying, monkeypatch):
    engine, ally = dying
    _rolls(monkeypatch, 12, 15, 18)
    for _ in range(3):
        _turn(engine, ALLY)
    assert ally.life_state == "STABLE" and ally.active and life_state._record(ally) == {"ok": 0, "bad": 0}
    before = len(_saves(engine))
    _turn(engine, ALLY)
    assert len(_saves(engine)) == before  # a stable creature makes no saves

    engine, ally = _dying_again()
    _rolls(monkeypatch, 3, 4, 5, 3, 4, 5)  # Advantage takes the higher of two dice each time; both dice are these
    for _ in range(3):
        _turn(engine, ALLY)
    assert not ally.active and ally.life_state is None
    assert any(e.event_type == "ENTITY_DEFEATED" for e in engine.events)


def _dying_again():
    engine = _fight(_bundle(ME), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    return engine, ally


def test_a_natural_one_is_two_failures_and_a_natural_twenty_stands_it_up(monkeypatch):
    engine, ally = _dying_again()
    _rolls(monkeypatch, 1)
    _turn(engine, ALLY)
    assert life_state._record(ally) == {"ok": 0, "bad": 2} and ally.life_state == "DYING"
    engine, ally = _dying_again()
    _rolls(monkeypatch, 20)
    _turn(engine, ALLY)
    assert ally.current_hp == 1 and ally.life_state is None and ally.active
    assert ally.action_available and ally.movement_remaining_ft > 0  # its own turn: it acts


def test_damage_at_zero_is_a_failure_two_from_a_critical_hit_and_a_stable_creature_falls_again(dying):
    engine, ally = dying
    _hit(engine, ally, 4)
    assert life_state._record(ally) == {"ok": 0, "bad": 1} and ally.life_state == "DYING"
    engine._append_event("ATTACK_ROLLED", "test:atk", actor_id=AN, target_ids=(ALLY,), payload={"natural_result": 20})
    _hit(engine, ally, 4)  # ... a critical hit: two more, three in all
    assert not ally.active  # dead: nobody on its side can call it back

    engine, ally = _dying_again()
    life_state.stabilize(engine, ally, "test:stabilize")
    assert ally.life_state == "STABLE"
    _hit(engine, ally, 2)
    assert ally.life_state == "DYING" and life_state._record(ally) == {"ok": 0, "bad": 1}


def test_damage_of_the_whole_maximum_kills_outright_and_deathless_treats_it_as_three_times(dying, monkeypatch):
    engine, ally = dying
    _hit(engine, ally, ally.maximum_hp * 2)  # Deathless: massive damage is three times the maximum
    assert ally.active and ally.life_state == "DYING"
    _hit(engine, ally, ally.maximum_hp * 3)
    assert not ally.active

    ordinary = _fight(_bundle(ME), _bundle(ALLY))
    monkeypatch.setattr(life_state, "DEATH_SAVES_FOR_ALL", True)
    ally = ordinary.state.actors[ALLY]
    ally.current_hp, ally.maximum_hp = 10, 10
    _hit(ordinary, ally, 25)  # 10 to reach 0, 15 left over: at least its maximum
    assert not ally.active and not life_state.is_dead(ally)


def test_healing_ends_the_state_and_the_creature_is_up_at_the_healed_amount(dying):
    engine, ally = dying
    life_state.heal_to(engine, ally, 4, "test:heal")
    assert ally.current_hp == 4 and ally.life_state is None and ally.active


def test_the_state_replays_from_the_events_alone(monkeypatch):
    engine = _fight(_bundle(ME), _deathless_ally())
    before, n = engine.state.model_copy(deep=True), len(engine.events)
    ally = engine.state.actors[ALLY]
    with engine._transaction("test:blow", "test:intent", ME):
        _hit(engine, ally)
    replayed = Gate3EventReducer().apply_events(before, enrich_committed_events(engine.events[n:], post_engine=engine))
    assert replayed.actors[ALLY].model_dump() == ally.model_dump()
    assert replayed.actors[ALLY].life_state == "DYING"


# ------------------------------------------------------------------------------------------------------ abilities that give or change the saves
def test_death_save_modes_cancel_and_a_first_or_next_rule_is_used_up_by_the_roll(dying, monkeypatch):
    engine, ally = dying
    engine._apply_condition(ally, "condition:" + MODE, "test:bane", AN, expires_on="UNTIL_REMOVED",
                            data={"rule": {"death_save_mode": {"mode": "DISADVANTAGE", "first": True}}, "label": "Disadvantage on the first one"})
    _rolls(monkeypatch, 13, 9, 15)
    _turn(engine, ALLY)  # Advantage (Deathless) and Disadvantage cancel: one die
    assert _saves(engine)[-1]["actor"]["mode"] == "NORMAL"
    assert MODE not in _conditions(ally)  # "the first death saving throw it makes"
    _turn(engine, ALLY)
    assert _saves(engine)[-1]["actor"]["mode"] == "ADVANTAGE"


def test_an_aura_that_gives_advantage_on_death_saves_puts_the_state_on_its_allies():
    """Purity Edict ("You and allies inside the aura have Advantage on Wisdom saving throws and Death Saving Throws") was a GM line:
    the ally it covers now goes down Dying and rolls with Advantage."""
    edict = _bundle(ME, "tianxia.sphere.fate", ["TAL_FATE_PURITY_EDICT"])
    engine = _fight(edict, _bundle(ALLY))
    _use(engine, "Purity Edict", target=None)
    ally = engine.state.actors[ALLY]
    assert MODE in _conditions(ally)
    _hit(engine, ally)
    assert ally.active and ally.life_state == "DYING"
    assert life_state._modes(ally) and life_state._modes(ally)[0][0] == "ADVANTAGE"
    assert not life_state._modes(engine.state.actors[AN], engine)


def test_death_save_aura_checks_current_membership_including_late_entry_and_exit():
    engine = _fight(_bundle(ME, "tianxia.sphere.fate", ["TAL_FATE_PURITY_EDICT"]), _bundle(ALLY))
    ally = engine.state.actors[ALLY]
    ally.position = Position(x=9, y=6)
    _use(engine, "Purity Edict", target=None)
    assert not life_state._modes(ally, engine)
    ally.position = Position(x=2, y=6)
    assert life_state._modes(ally, engine) == [("ADVANTAGE", None)]
    ally.position = Position(x=9, y=6)
    assert not life_state._modes(ally, engine)


def test_dying_is_unconscious_and_healing_clears_only_its_lifecycle_condition(dying):
    from combat import typed_executor

    engine, ally = dying
    assert any(c.condition_id == life_state.UNCONSCIOUS for c in ally.conditions.values())
    attacker = engine.state.actors[AN]
    assert engine._distance_actor_to_actor(attacker, ally) > 5
    assert engine._attack_mode(attacker, ally) == "NORMAL"  # Unconscious Advantage cancels Prone's distant Disadvantage
    assert any(r.get("save_mode", {}).get("DEX") == "AUTO_FAIL" for r in typed_executor.condition_rules(ally))
    life_state.heal_to(engine, ally, 1, "test:heal")
    assert ally.life_state is None and not any(c.condition_id == life_state.UNCONSCIOUS for c in ally.conditions.values())
    assert any(c.condition_id == "condition:typed.prone" for c in ally.conditions.values())
    assert engine._attack_mode(attacker, ally) == "DISADVANTAGE"  # waking leaves Prone


def test_active_black_star_vessel_gives_disadvantage_on_death_saves(monkeypatch):
    from combat import unmaking

    engine = _fight(_bundle(ME), _bundle(ALLY, "tianxia.sphere.unmaking", ["TAL_UNMAKING_BLACK_STAR_VESSEL"]))
    ally = engine.state.actors[ALLY]
    assert not life_state.wants_dying(engine, ally)
    engine._apply_condition(ally, unmaking.BLACK_STAR_ACTIVE, "TAL_UNMAKING_BLACK_STAR_VESSEL", ALLY,
                            expires_on="END_OF_HOLDER_NEXT_TURN", data={"label": "Black Star Vessel"})
    _hit(engine, ally)
    assert ally.life_state == "DYING"
    _rolls(monkeypatch, 10)
    _turn(engine, ALLY)
    assert _saves(engine)[-1]["actor"]["mode"] == "DISADVANTAGE"


def test_deathless_stable_recovery_uses_one_saved_1d4_minute_deadline(dying):
    engine, ally = dying
    life_state.stabilize(engine, ally, "test:stabilize")
    held = next(c for c in ally.conditions.values() if c.condition_id == life_state.RECOVERY)
    deadline = dict(held.data)
    rolls = [r for r in engine.rolls if r.reason == "DEATHLESS:stable_recovery"]
    assert len(rolls) == 1 and 10 <= deadline["round"] - engine.state.round_number <= 40
    life_state.stable_recovery(engine, ally, "test:again")
    assert len([r for r in engine.rolls if r.reason == "DEATHLESS:stable_recovery"]) == 1
    engine.state.round_number = deadline["round"] - 1
    _turn(engine, ALLY)
    assert ally.life_state == "STABLE" and ally.current_hp == 0
    engine.state.round_number = deadline["round"] + 1
    _turn(engine, ALLY)
    assert ally.current_hp == 1 and ally.life_state is None and ally.action_available
    assert not any(c.condition_id == life_state.RECOVERY for c in ally.conditions.values())


# ------------------------------------------------------------------------------------------------------ stabilizing
def test_borrowed_breath_stabilizes_a_dying_creature_before_the_temporary_hp():
    """"If the target has 0 Hit Points and is living, the target becomes stable before receiving these Temporary HP."""
    healer = _bundle(ME, "tianxia.sphere.life", [])
    engine = _fight(healer, _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    assert "Borrowed Breath" in _legal(engine)
    _use_on(engine, "Borrowed Breath", ALLY)
    assert ally.life_state == "STABLE" and ally.temporary_hp > 0 and ally.current_hp == 0


def test_coagulate_stabilizes_a_dying_creature():
    blood = _bundle(ME, "tianxia.sphere.blood", [])
    engine = _fight(blood, _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    engine._apply_condition(ally, "condition:typed.mark.blood_thread." + ME, "test:thread", ME, expires_on="UNTIL_REMOVED")
    _use_on(engine, "Coagulate: Stabilize", ALLY)  # "Choose one" (rider lane C5)
    assert ally.life_state == "STABLE"


def test_quiet_burial_makes_a_dying_creature_roll_its_death_save_now_with_advantage(monkeypatch):
    death = _bundle(ME, "tianxia.sphere.death", ["TAL_DEATH_QUIET_BURIAL"])
    engine = _fight(death, _bundle(ALLY, "tianxia.sphere.berserker", []))
    ally = engine.state.actors[ALLY]
    monkeypatch.setattr(life_state, "DEATH_SAVES_FOR_ALL", True)
    _hit(engine, ally)
    _rolls(monkeypatch, 16)
    assert "Quiet Burial" in _legal(engine)
    _use_on(engine, "Quiet Burial", ALLY)
    assert _saves(engine)[-1]["actor"]["mode"] == "ADVANTAGE" and life_state._record(ally)["ok"] == 1


# ------------------------------------------------------------------------------------------------------ Stone Womb
def test_stone_womb_shells_a_dying_ally_and_makes_it_stable():
    """"touch a willing creature at 0 Hit Points ... the target ... is stable if it was dying": a creature at 0 had left the map."""
    womb = _bundle(ME, "tianxia.sphere.source", ["tianxia.talent.source.stone_womb_preservation"])
    engine = _fight(womb, _deathless_ally())
    ally = engine.state.actors[ALLY]
    assert "Stone Womb Preservation" not in _legal(engine)  # nothing at 0 Hit Points to touch yet
    _hit(engine, ally)
    assert ally.life_state == "DYING"
    _use_on(engine, "Stone Womb Preservation", ALLY)
    assert ally.life_state == "STABLE" and "typed.stone_shell" in _conditions(ally)
    assert engine._effective_speed(ally) == 0


# ------------------------------------------------------------------------------------------------------ Yellow-Spring, One-Breath, the lamp
def _healers(*, minute_gate=False, lamp=False):
    talents = [ONE_BREATH, YELLOW, *([MINUTE_GATE] if minute_gate else [])]
    return _bundle(ME, "tianxia.sphere.life", talents, cl=15)


def _die(engine, ally):
    """Three failed saves in a row, as the fight would have them."""
    life_state._set_record(ally, 0, 2)
    _hit(engine, ally, 1)


def test_a_yellow_spring_seal_keeps_the_soul_of_a_creature_that_dies_and_is_used_up():
    engine = _fight(_healers(), _deathless_ally())
    ally = engine.state.actors[ALLY]
    assert "Yellow-Spring Refusal Seal" not in _legal(engine)  # "a creature bearing your Pulse Seal": Read the Pulse first
    _use_on(engine, "Read the Pulse", ALLY)
    engine.state.actors[ME].action_available = True
    _use_on(engine, "Yellow-Spring Refusal Seal", ALLY)
    assert SEAL in _conditions(ally)
    _hit(engine, ally)
    _die(engine, ally)
    assert ally.active and life_state.is_dead(ally) and SEAL not in _conditions(ally)
    assert life_state.soul_of(ally).data["seal"] is True


def test_one_breath_brings_back_a_creature_that_died_within_the_round_with_one_hit_point_and_exhaustion():
    engine = _fight(_healers(), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    _die(engine, ally)
    assert ally.active and life_state.is_dead(ally)  # someone on its side owns the talent: the soul lingers
    pool = next(key for key in engine.state.actors[ME].resources if key.endswith("core.stamina") or key.endswith("core.qi"))
    cp = engine.state.actors[ME].resources[pool]
    assert "One-Breath Resuscitation" in _legal(engine)
    _use_on(engine, "One-Breath Resuscitation", ALLY)
    assert ally.current_hp == 1 and ally.life_state is None and not life_state.is_dead(ally) and ally.active
    assert engine.state.actors[ME].resources[pool] == cp - 3  # "Cost: 3 CP"
    from combat.ext import forged_exhaustion
    assert forged_exhaustion.level(ally) == 1  # "gains 1 level of Exhaustion"


def test_nothing_but_a_soul_return_talent_reaches_the_dead():
    engine = _fight(_healers(), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    _die(engine, ally)
    names = {c.display_name for c in engine.legal_candidates() if ALLY in (c.target_ids or ())}
    assert names == {"One-Breath Resuscitation"}
    engine.state.current_actor_id = AN  # and nobody else may strike it either
    engine.state.actors[AN].action_available = True
    assert not [c for c in engine.legal_candidates() if ALLY in (c.target_ids or ())]


def test_one_breath_does_not_reach_past_the_round_and_minute_gate_reaches_the_minute():
    engine = _fight(_healers(), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    _die(engine, ally)
    engine.state.round_number += 2  # more than a round on
    _turn(engine, AN)
    assert not ally.active  # nobody could call it back any more: its soul is gone

    engine = _fight(_healers(minute_gate=True), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    _die(engine, ally)
    engine.state.round_number += 3
    _turn(engine, ME)
    assert ally.active and life_state.is_dead(ally)  # "died within the last minute"
    pool = next(key for key in engine.state.actors[ME].resources if key.endswith("core.stamina") or key.endswith("core.qi"))
    cp = engine.state.actors[ME].resources[pool]
    _use_on(engine, "One-Breath Resuscitation", ALLY)
    assert ally.current_hp == 1 and engine.state.actors[ME].resources[pool] == cp - 4  # "increase the cost to 4 CP"
    engine.state.round_number += 20


def test_a_yellow_spring_seal_makes_the_talent_count_the_death_as_within_the_last_round():
    engine = _fight(_healers(), _deathless_ally())
    ally = engine.state.actors[ALLY]
    engine._apply_condition(ally, "condition:" + SEAL, "test:seal", ME, expires_on="UNTIL_REMOVED", data={"label": "seal"})
    _hit(engine, ally)
    _die(engine, ally)
    engine.state.round_number += 6  # well past a round: only the seal keeps it in reach
    _turn(engine, ME)
    assert ally.active and life_state.is_dead(ally)
    assert "One-Breath Resuscitation" in _legal(engine)
    _use_on(engine, "One-Breath Resuscitation", ALLY)
    assert ally.current_hp == 1 and not life_state.is_dead(ally)


def test_a_dead_creature_that_nobody_can_bring_back_leaves_at_once_and_the_fight_ends():
    engine = _fight(_bundle(ME), _deathless_ally())
    ally = engine.state.actors[ALLY]
    engine.state.actors[ME].current_hp = 0  # the only other member of its side is down too
    _hit(engine, ally)
    _die(engine, ally)
    assert not ally.active and not life_state.is_dead(ally)


def test_the_soul_lamp_keeps_the_owner_and_a_constitution_save_brings_it_back(monkeypatch):
    lamp = _bundle(ALLY, "tianxia.sphere.life", [SOUL_LAMP])
    engine = _fight(_bundle(ME), lamp)
    ally = engine.state.actors[ALLY]
    monkeypatch.setattr(life_state, "DEATH_SAVES_FOR_ALL", True)
    pool = next(key for key in ally.resources if key.endswith("core.stamina") or key.endswith("core.qi") or key.endswith("core.resonance"))
    _hit(engine, ally)
    _die(engine, ally)
    assert ally.active and life_state.is_dead(ally) and life_state.soul_of(ally).data["lamp"] is True
    assert ally.resources[pool] == 0  # "spend all remaining CP"
    engine.state.round_number += 11
    _rolls(monkeypatch, 20)  # a natural 20 is 20 + the save: it makes DC 20
    _turn(engine, AN)
    assert ally.current_hp == 1 and not life_state.is_dead(ally) and ally.active  # "return to life with 1 Hit Point and 1 level of Exhaustion"
    from combat.ext import forged_exhaustion
    assert forged_exhaustion.level(ally) == 1


def test_a_failed_lamp_save_is_death(monkeypatch):
    lamp = _bundle(ALLY, "tianxia.sphere.life", [SOUL_LAMP])
    engine = _fight(_bundle(ME), lamp)
    ally = engine.state.actors[ALLY]
    monkeypatch.setattr(life_state, "DEATH_SAVES_FOR_ALL", True)
    _hit(engine, ally)
    _die(engine, ally)
    engine.state.round_number += 11
    _rolls(monkeypatch, 2)
    _turn(engine, AN)
    assert not ally.active and not life_state.is_dead(ally)


# ------------------------------------------------------------------------------------------------------ Recall Spirit, Unending Loyalty
RECALL = "tianxia.talent.warleader.recall_spirit"
UNENDING = "tianxia.talent.warleader.unending_loyalty"
FOCUS = "resource:core.martial_focus"


def _leader(*talents):
    return _bundle(ME, "tianxia.sphere.warleader", [RECALL, *talents], cl=15)


def test_recall_spirit_calls_back_a_creature_that_died_since_the_end_of_the_leaders_last_turn():
    """"Choose one creature within your Shout area that died since the end of your last turn. The creature returns to life with Hit
    Points equal to your CL + Warleader key ability modifier. The creature's Exhaustion level increases by 2 ...": the whole
    talent was a GM line (a creature that died could not be brought back)."""
    engine = _fight(_leader(), _deathless_ally())
    ally, me = engine.state.actors[ALLY], engine.state.actors[ME]
    _hit(engine, ally)
    _die(engine, ally)
    assert ally.active and life_state.is_dead(ally)  # the leader's own talent reaches it
    me.resources[FOCUS] = 1
    assert "Recall Spirit" in _legal(engine)
    numbers = next(a for a in engine.action_catalog.values() if a.display_name == "Recall Spirit").parameters["typed"]["numbers"]
    events = _use(engine, "Recall Spirit", target=None)
    assert ally.current_hp == int(numbers["cl"]) + int(numbers["key_mod"]) and not life_state.is_dead(ally) and ally.life_state is None
    from combat.ext import forged_exhaustion
    assert forged_exhaustion.level(ally) == 2  # "increases by 2"
    assert me.resources[FOCUS] == 0  # "Cost: Expend Martial Focus"
    assert events


def test_recall_spirit_does_not_reach_one_that_died_before_the_leaders_last_turn_unless_unending_loyalty():
    engine = _fight(_leader(), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    _die(engine, ally)
    _turn(engine, ME)  # the leader takes a turn ...
    engine.state.round_number += 1
    _turn(engine, AN)
    assert not ally.active or not [c for c in engine.legal_candidates() if c.display_name == "Recall Spirit"]

    engine = _fight(_leader(UNENDING), _deathless_ally())
    ally, me = engine.state.actors[ALLY], engine.state.actors[ME]
    _hit(engine, ally)
    _die(engine, ally)
    engine.state.round_number += 4  # "died within the last minute instead of since the end of your last turn"
    _turn(engine, ME)
    me.resources[FOCUS] = 1
    assert ally.active and life_state.is_dead(ally) and "Recall Spirit" in _legal(engine)
    numbers = next(a for a in engine.action_catalog.values() if a.display_name == "Recall Spirit").parameters["typed"]["numbers"]
    _use(engine, "Recall Spirit", target=None)
    assert ally.current_hp == 2 * int(numbers["cl"]) + int(numbers["key_mod"])  # "2 x your CL + Warleader key ability modifier"


def test_return_the_broken_pulse_revives_without_exhaustion():
    engine = _fight(_bundle(ME, "tianxia.sphere.pressure_points", ["tianxia.talent.pressure_points.return_the_broken_pulse"]),
                    _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    _die(engine, ally)
    _use_on(engine, "Return the Broken Pulse", ALLY)
    from combat.ext import forged_exhaustion

    assert ally.current_hp == 1 and ally.life_state is None and not life_state.is_dead(ally)
    assert forged_exhaustion.level(ally) == 0


def test_soul_lamp_table_pause_unwinds_damage_and_decline_spends_nothing():
    from combat.gate5_service import _ReactionRequired
    from combat.gate2_runtime_models import ReactionDecision

    engine = _fight(_bundle(ME), _bundle(ALLY, "tianxia.sphere.life", [SOUL_LAMP]))
    _hit(engine, engine.state.actors[ALLY])
    life_state._set_record(engine.state.actors[ALLY], 0, 2)
    engine._active_intent = ActionIntent(intent_id="lamp:damage", decision_id="test", candidate_id="test",
                                        state_version=engine.state.state_version, actor_id=AN, target_ids=(ALLY,))
    calls = []

    def pause(request):
        calls.append(request)
        raise _ReactionRequired(None, None)

    engine.set_reaction_provider(pause)
    before = engine.state.model_dump(mode="json")
    with pytest.raises(_ReactionRequired):
        with engine._transaction("test:damage", "lamp:damage", AN):
            _hit(engine, engine.state.actors[ALLY], 1)
    assert engine.state.model_dump(mode="json") == before
    assert calls[-1]["reactor_id"] == ALLY and calls[-1]["extension_choice"]["automatic_use"] is False

    def decline(request):
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None

    engine.set_reaction_provider(decline)
    ally = engine.state.actors[ALLY]
    resources = dict(ally.resources)
    with engine._transaction("test:damage", "lamp:damage", AN):
        _hit(engine, ally, 1)
    assert ally.resources == resources and not ally.active and not life_state.is_dead(ally)


def test_soul_return_asks_the_dead_fighter_and_decline_leaves_the_soul():
    from combat.gate5_service import _ReactionRequired
    from combat.gate2_runtime_models import ReactionDecision

    engine = _fight(_healers(), _deathless_ally())
    ally = engine.state.actors[ALLY]
    _hit(engine, ally)
    _die(engine, ally)
    calls = []

    def pause(request):
        calls.append(request)
        raise _ReactionRequired(None, None)

    engine.set_reaction_provider(pause)
    before = engine.state.model_dump(mode="json")
    with pytest.raises(_ReactionRequired):
        _use_on(engine, "One-Breath Resuscitation", ALLY)
    assert engine.state.model_dump(mode="json") == before
    assert calls[-1]["reactor_id"] == ALLY

    def decline(request):
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None

    engine.set_reaction_provider(decline)
    _use_on(engine, "One-Breath Resuscitation", ALLY)
    assert engine.state.actors[ALLY].current_hp == 0 and life_state.is_dead(engine.state.actors[ALLY])


@pytest.mark.parametrize("ability,sphere", [
    ("TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS", "tianxia.sphere.shield"),
    ("tianxia.path.body_refining.feature.blood_pump", None),
])
def test_printed_no_action_survival_keeps_one_hp_without_a_reaction_once_per_fight(ability, sphere):
    engine = _fight(_bundle(ME), _bundle(ALLY, sphere, [ability], cl=20))
    ally = engine.state.actors[ALLY]
    ally.reaction_available = False
    intent = ActionIntent(intent_id="test:drop", decision_id="test", candidate_id="test", actor_id=AN,
                          state_version=engine.state.state_version, target_ids=(ALLY,))
    engine._commit_damage(ally, ally.current_hp + 3, "SLASHING", "test:blow", AN, intent, reaction_depth=0)
    assert ally.current_hp == 1 and ally.active and ally.life_state is None and not ally.reaction_available
    engine._commit_damage(ally, ally.current_hp + 3, "SLASHING", "test:blow", AN, intent, reaction_depth=0)
    assert ally.current_hp == 0 and not ally.active


def test_no_action_survival_table_pause_rolls_back_and_decline_really_falls():
    from combat.gate5_service import _ReactionRequired
    from combat.gate2_runtime_models import ReactionDecision

    ability = "TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS"
    engine = _fight(_bundle(ME), _bundle(ALLY, "tianxia.sphere.shield", [ability], cl=20))
    engine._active_intent = ActionIntent(intent_id="survive:damage", decision_id="test", candidate_id="test",
                                        state_version=engine.state.state_version, actor_id=AN, target_ids=(ALLY,))
    calls = []

    def pause(request):
        calls.append(request)
        raise _ReactionRequired(None, None)

    engine.set_reaction_provider(pause)
    before = engine.state.model_dump(mode="json")
    with pytest.raises(_ReactionRequired):
        with engine._transaction("test:damage", "survive:damage", AN):
            ally = engine.state.actors[ALLY]
            engine._commit_damage(ally, ally.current_hp + 3, "SLASHING", "test:blow", AN, engine._active_intent, reaction_depth=0)
    assert engine.state.model_dump(mode="json") == before
    assert calls[-1]["reactor_id"] == ALLY and not calls[-1]["extension_choice"]["automatic_use"]

    def decline(request):
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None

    engine.set_reaction_provider(decline)
    resources = dict(engine.state.actors[ALLY].resources)
    with engine._transaction("test:damage", "survive:damage", AN):
        ally = engine.state.actors[ALLY]
        engine._commit_damage(ally, ally.current_hp + 3, "SLASHING", "test:blow", AN, engine._active_intent, reaction_depth=0)
    assert not engine.state.actors[ALLY].active and engine.state.actors[ALLY].resources == resources
