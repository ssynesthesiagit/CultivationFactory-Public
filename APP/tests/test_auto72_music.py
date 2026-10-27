"""AUTO72f1 (Music automation review fixes): the corrected Soul-Stirring Refrain, Immortal Funeral
Bell and Silence-Breaking Note, at the level each printed line broke.

Findings fixed here (AUTO72.review.md):

  1. Fury's Proficiency Bonus now goes onto the weapon's own damage roll (combat/typed_executor
     ``attack_damage_bonus``), so it keeps the weapon's damage type -- its Resistance/Immunity answer
     it -- and the bearer stays the attacker. It used to be a second, untyped packet dealt by the
     singer.
  2. "Choose one creature that can hear you ... A willing target may choose to fail" is asked again:
     both a willing ally/self and an unwilling enemy can be chosen, a willing target is asked and its
     emotion lands with no save, and the repeat save belongs to an unwilling target only.
  3. Immortal Funeral Bell's "enemies inside ... cannot regain HP more than once per round" follows
     the bell's printed aura as it moves, not the creatures that were inside when it was rung.
  4. "one weapon damage roll each turn" is the shared per-turn clock, so an Opportunity Attack on
     another creature's turn has its own roll, and two creatures at the same distance are both
     nearest (neither is penalised).
  5. Silence-Breaking Note's outcome is the GM's again ("chosen by the GM according to the effect's
     strength"), with the honest rider, and no "Keep it silenced" button.

Harness: the Music sphere's own engine-level helpers (tests/test_riders_lane10.py and
tests/test_auto_lane1.py both build a real compiled character and run it through the engine), plus
the real table (tests/test_hunt27_table.py) for the consent question and for commit + reload.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
M = "tianxia.talent.music."

_spec = importlib.util.spec_from_file_location("auto72_support", ROOT / "tests/test_riders_lane10.py")
_L10 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_L10)
SWF = _L10.SWF
L4 = _L10.L4

_spec1 = importlib.util.spec_from_file_location("auto72_lane1", ROOT / "tests/test_auto_lane1.py")
L1 = importlib.util.module_from_spec(_spec1)
_spec1.loader.exec_module(L1)

AUTH = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))["mechanics"]


def _music(key, *, extras=(), dc=50):
    """A real Music character with one talent, as every other Music regression builds it."""
    return SWF.fight("MUSIC_BASE_KEEP_THE_MEASURE", dc=dc, extras=(*extras, key))


def _label(actor, condition_id):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _gm_lines(mechanic_id):
    from combat.factory_compiler import _gm_lines

    row = AUTH[mechanic_id]
    return _gm_lines(row.get("riders") or [], row, row.get("effects") or []) + [
        line for option in row.get("options") or []
        for line in _gm_lines(option.get("riders") or [], row, option.get("effects") or [], option.get("label"))]


def _committed(engine, victim):
    """The damage packets this attacker landed on that creature, oldest first."""
    return [(ev.source_definition_id, int((ev.payload or {}).get("hp_damage") or 0),
             str((ev.payload or {}).get("damage_type") or ""))
            for ev in engine.events if ev.event_type == "DAMAGE_COMMITTED" and ev.actor_id == victim.entity_id
            and victim.entity_id in (ev.target_ids or ())]


# =========================================================== the retired GM lines are gone from the fight log
RETIRED = {
    "tianxia.talent.music.soul_sundering_note": ("Disadvantage on this saving throw",),
    "tianxia.talent.music.soul_stirring_refrain": ("Fury on an unwilling target",),
    "tianxia.talent.music.immortal_funeral_bell": ("cannot regain HP more than once per round",
                                                  "does not kill creatures automatically"),
    "tianxia.talent.music.healing_hymn": ("does not regrow limbs",),
    "tianxia.talent.music.shared_measure": ("must be visible as rhythm",),
    "tianxia.talent.music.echoing_step": ("Leave a faint audible",),
}
# Silence-Breaking Note keeps its Game Master reminder on purpose: the printed outcome is
# "chosen by the GM according to the effect's strength", so the table must not decide it.


def test_the_retired_music_lines_no_longer_reach_the_fight_log():
    """Checklist 13: what the table now does must not still be printed as the GM's work."""
    printed = {key: "\n".join(_gm_lines(key)) for key in RETIRED}
    found = [f"{key}: {phrase!r} is still a GM line" for key, phrases in RETIRED.items()
             for phrase in phrases if any(phrase in line for line in printed[key].splitlines())]
    assert not found, "\n".join(found)


def test_the_moving_music_mechanics_are_typed_all_the_way():
    for key in ("tianxia.talent.music.soul_sundering_note", "tianxia.talent.music.immortal_funeral_bell",
                "tianxia.talent.music.healing_hymn", "tianxia.talent.music.shared_measure"):
        assert AUTH[key]["coverage"] == "FULL", (key, AUTH[key]["coverage"], AUTH[key]["riders"])


# =========================================================== Soul-Sundering Note: Disadvantage on the save
def test_soul_sundering_note_gives_a_spirit_disadvantage_on_its_save():
    """"A spirit, ghost, possessing entity, or incorporeal creature has Disadvantage on this saving throw."

    The save is the printed one either way; only the die changes, so the roll's record is the proof.
    """
    from combat.ext import creature_kinds

    def rolled(kind):
        _, engine, me, foe = _music(M + "soul_sundering_note")
        foe.creature_types = [kind]
        SWF.cast(engine, "Soul-Sundering Note", target=SWF.AN)
        mode = next(ev for ev in engine.events if ev.event_type == "SAVE_ROLLED").payload["mode"]
        return mode, creature_kinds.matches(foe, ["spirit", "ghost", "possession entity", "incorporeal"])

    for kind in ("Spirit", "Ghost", "Possession Entity", "Incorporeal"):
        mode, matched = rolled(kind)
        assert matched, f"{kind} carries no printed label, so the rule cannot read it"
        assert mode == "DISADVANTAGE", kind
    assert rolled("Humanoid") == ("NORMAL", False)  # an ordinary creature is unaffected


def test_soul_sundering_note_still_damages_and_stuns_on_a_failure():
    _, engine, me, foe = _music(M + "soul_sundering_note")
    foe.current_hp = 500
    SWF.cast(engine, "Soul-Sundering Note", target=SWF.AN)
    assert foe.current_hp < 500
    assert _label(foe, "condition:typed.stunned")


# =========================================================== Soul-Stirring Refrain: who may be chosen
def _refrain_candidates(engine):
    return sorted((c.display_name, c.target_ids[0]) for c in engine.legal_candidates() if "Refrain" in c.display_name)


def test_soul_stirring_refrain_offers_every_emotion_to_a_willing_ally_and_to_an_enemy():
    """"Choose one creature that can hear ... If the target is unwilling, it makes a Wisdom saving
    throw. A willing target may choose to fail."  Both kinds of creature are legal choices, and the
    emotion reaches an enemy only through the printed save."""
    from combat.ext import music

    _, engine, me, foe = _music(M + "soul_stirring_refrain")
    ally = SWF.ally(engine, me)
    offered = _refrain_candidates(engine)
    labels = {"Fear", "Sorrow", "Courage", "Fury", "Calm"}
    for label in labels:
        assert (f"Soul-Stirring Refrain: {label}", ally.entity_id) in offered, label
        assert (f"Soul-Stirring Refrain: {label} (any creature)", SWF.AN) in offered, label
        assert (f"Soul-Stirring Refrain: {label}", me.entity_id) in offered, "you may Refrain yourself"

    L4._script(engine, [1])  # the enemy refuses (an AI declines a hostile singer) and fails the Wisdom save
    SWF.cast(engine, "Soul-Stirring Refrain: Fury (any creature)", target=SWF.AN)
    saves = [ev for ev in engine.events if ev.event_type == "SAVE_ROLLED" and ev.actor_id == SWF.AN]
    assert [ev.payload["dc"] for ev in saves] == [50], "an unwilling target makes the printed Wisdom save at the caster's Save DC"
    assert _label(foe, "condition:typed.music_fury"), "a failed save leaves the emotion"

    me.action_available = True
    SWF.cast(engine, "Soul-Stirring Refrain: Fury", target=ally.entity_id)
    assert _label(ally, "condition:typed.music_fury"), "a willing ally takes the emotion without a save"
    assert not [c for c in ally.conditions.values() if (c.data or {}).get("repeat_save")], \
        "a willing target was never made to save, so it has no save to repeat"


def test_soul_stirring_refrain_fury_repeats_the_save_only_for_a_target_that_failed_one():
    """"At the end of each of its turns, an unwilling target repeats the saving throw, ending the
    effect on itself on a success."  A success therefore removes the mark; a failure keeps it."""
    _, engine, me, foe = _music(M + "soul_stirring_refrain", dc=10)
    L4._script(engine, [1])  # fails the printed Wisdom save, so the emotion lands with its repeat save
    SWF.cast(engine, "Soul-Stirring Refrain: Fury (any creature)", target=SWF.AN)
    (mark,) = _label(foe, "condition:typed.music_fury")
    assert mark.data["repeat_save"]["ability"] == "WIS"

    def ends_its_turn_with(natural):
        before = len(engine.events)
        engine.state.current_actor_id = SWF.AN  # the bearer's own turn ends: it repeats the save
        L4._script(engine, [natural])
        engine.end_turn()
        return [ev for ev in engine.events[before:] if ev.event_type == "SAVE_ROLLED"]

    assert ends_its_turn_with(20), "the bearer never repeated the Wisdom save at the end of its turn"
    assert not _label(foe, "condition:typed.music_fury"), "a success ends the effect on the target itself"

    L4._new_turn(engine, SWF.ME)  # the emotion returns
    L4._script(engine, [1])
    _act_as(engine, SWF.ME, "Soul-Stirring Refrain: Fury (any creature)", SWF.AN)
    assert _label(foe, "condition:typed.music_fury")
    assert ends_its_turn_with(2), "the repeated save is rolled again"
    assert _label(foe, "condition:typed.music_fury"), "a failure keeps the effect"


# =========================================================== Soul-Stirring Refrain: the cure reaches the chosen creature
def _feeling(engine, creature, name):
    """Put an ordinary printed condition on a creature, as the table's own condition API does."""
    engine._apply_condition(creature, f"condition:typed.{name}", "auto72:test", SWF.ME, expires_on="UNTIL_REMOVED")


def _answers(answer):
    """Answer the consent question with ``answer`` for any creature, and leave every other answer alone."""
    from combat.gate2_runtime_models import ReactionDecision

    def provider(row):
        if row["reaction_source_id"] == "choice:willing.consent":
            return ReactionDecision(checkpoint=row["checkpoint"], reactor_id=row["reactor_id"],
                                    reaction_source_id=row["reaction_source_id"], selection="USE",
                                    option_ids=(answer,)), None
        return None
    return provider


@pytest.mark.parametrize("emotion,feelings", [("Calm", ("charmed", "frightened")), ("Courage", ("frightened",))])
@pytest.mark.parametrize("willing", [True, False])
def test_a_refrain_cure_reaches_the_chosen_creature_and_no_other(emotion, feelings, willing):
    """"End [the emotion] on the target": the cure belongs to the creature the singer chose.

    An enemy either accepts (willing) or refuses and fails the printed Wisdom save; either way the
    chosen enemy is cured, and an unrelated ally carrying the same conditions keeps them.
    """
    _, engine, me, foe = _music(M + "soul_stirring_refrain", dc=10)
    ally = SWF.ally(engine, me)
    for feeling in feelings:
        _feeling(engine, foe, feeling)
        _feeling(engine, ally, feeling)
    if willing:  # an enemy that accepts takes the cure with no save; the AI alone would decline
        engine.set_reaction_provider(_answers("accept"))
    else:
        L4._script(engine, [1])  # it refuses (the AI declines a hostile singer) and fails the save
    SWF.cast(engine, f"Soul-Stirring Refrain: {emotion} (any creature)", target=SWF.AN)

    for feeling in feelings:
        assert not _label(foe, f"condition:typed.{feeling}"), \
            f"the printed cure of {feeling} did not reach the creature the singer chose"
        assert _label(ally, f"condition:typed.{feeling}"), \
            f"{feeling} was cured on an unrelated ally instead of on the chosen creature"


def test_an_ordinary_consent_keeps_a_repeat_save_that_row_carries_itself():
    """Only a row behind the printed refusal gate loses its repeat save in the willing branch.

    ``combat/ext/willing_targets.py`` deletes every ``repeat_save`` from the effects it runs for an
    accepting target. That is right for Soul-Stirring Refrain, whose print says the repeat save belongs
    to an unwilling target -- but a plain consent row may carry a condition with its own recurring save,
    and the shared helper used to delete that escape mechanism for every ability.
    """
    from combat.gate2_runtime_models import ActionIntent
    from combat.typed_executor import Context, run_effects

    _, engine, me, _ = _music(M + "soul_stirring_refrain")
    ally = SWF.ally(engine, me)
    row = {"type": "choose_willing", "applies_to": "target", "range_ft": 60, "target_only": True,
           "effects": [{"type": "music_ally_rule", "applies_to": "target", "mark": "music_courage",
                        "rule": {"music_ac": 1}, "evidence": "A consented benefit with its own recurring save.",
                        "repeat_save": {"ability": "WIS", "timing": "END_OF_TURN"}}]}
    action = next(iter(engine.action_catalog.values()))
    intent = ActionIntent(intent_id="auto72-consent", decision_id="d", candidate_id="c", state_version=0,
                          actor_id=me.entity_id, target_ids=(ally.entity_id,))
    run_effects(Context(engine, me, action, intent, {"numbers": {"save_dc": 50}}, [ally], ally, {}), [row])

    (mark,) = _label(ally, "condition:typed.music_courage")
    assert mark.data.get("repeat_save"), "a row without unwilling_save lost its own printed repeat save"


# =========================================================== Soul-Stirring Refrain: Fury's damage bonus
def _act_as(engine, actor_id, name, target=None):
    """Use the action named ``name`` as ``actor_id`` (SWF.cast always acts as the singer)."""
    from combat.gate2_runtime_models import ActionIntent

    engine.state.actors[actor_id].action_available = True
    found = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id
             and (target is None or target in (c.target_ids or ()))]
    assert found, f"{name!r} is not legal for {actor_id}"
    candidate = found[0]
    engine.execute_intent(ActionIntent(intent_id=f"auto72-{name}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids, destination=candidate.destination))


def _ally_of(engine, actor, *, entity_id="review:ally", at=None):
    """An ally of ``actor`` that can also take its own turn (an added square, never a shared one)."""
    ally = SWF.ally(engine, actor)
    engine.state.actors.pop(ally.entity_id, None)  # the helper's own placeholder key
    ally.entity_id = entity_id
    ally.position = ally.position.model_copy(update=at or {"y": 7})
    engine.state.actors[entity_id] = ally
    engine.state.initiative_order.append(entity_id)
    return ally


def _fury_on_a_willing_ally(engine):
    """The bearer a willing ally accepts Fury on (an AI ally accepts an allied singer)."""
    bearer = _ally_of(engine, engine.state.actors[SWF.ME])
    SWF.cast(engine, "Soul-Stirring Refrain: Fury", target=bearer.entity_id)
    assert _label(bearer, "condition:typed.music_fury")
    return bearer


def test_soul_stirring_refrain_fury_adds_the_proficiency_bonus_to_the_bearers_own_weapon_roll():
    """"The target adds your Proficiency Bonus to one weapon damage roll each turn."

    The extra points join the roll the attack is already making, so there is exactly one damage
    packet, it is the bearer's, and it carries the weapon's own damage type.
    """
    _, engine, me, foe = _music(M + "soul_stirring_refrain")
    bearer = _fury_on_a_willing_ally(engine)

    plain = _one_weapon_hit(engine, bearer, fury=False)
    rolled = _one_weapon_hit(engine, bearer)
    assert len(rolled) == 1, f"one hit, one damage packet: {rolled}"
    (plain_source, plain_hp, plain_type), (source, hp, kind) = plain[0], rolled[0]
    assert source == plain_source, "the bearer is the attacker of record, not the singer"
    assert source.startswith(f"action:typed.") and M not in source
    assert hp == plain_hp + me.proficiency_bonus, (plain, rolled)
    assert kind == plain_type and kind != "UNTYPED", (plain_type, kind)


def test_soul_stirring_refrain_fury_rides_the_bearers_own_weapon_type_against_resistance_and_immunity():
    """The points join the roll the weapon is already making, so the defender's Resistance still halves
    them and its Immunity still refuses the hit -- a different bearer and a different singer than the
    one that placed the mark."""
    _, engine, me, foe = _music(M + "soul_stirring_refrain")
    bearer = _fury_on_a_willing_ally(engine)  # an ally of the singer, not the singer itself
    weapon = (engine.action_catalog[_weapon_action(engine, bearer)].parameters or {})["typed"]["weapon"]
    kinds = [str(kind).upper() for kind in weapon["damage_types"]]

    def defence(field):
        for kind in kinds:  # both of a Versatile weapon's types, so the wielder's choice cannot dodge it
            engine._add_modifier(foe, f"test:fury_{field}:{kind}", field, "set", kind, "damage_types",
                                 expires_on="UNTIL_REMOVED")

    plain = _one_weapon_hit(engine, bearer, fury=False)
    defence("damage_resistance")
    plain_resisted = _one_weapon_hit(engine, bearer, fury=False)
    resisted = _one_weapon_hit(engine, bearer)
    assert plain[0][1] > plain_resisted[0][1], "the defender's Resistance really bites"
    assert resisted[0][1] == plain_resisted[0][1] + me.proficiency_bonus // 2, (plain, plain_resisted, resisted)
    assert resisted[0][2] in kinds, "the bonus is still the weapon's own damage type"

    for mid, modifier in list(foe.modifiers.items()):
        if modifier.source_definition_id.startswith("test:fury_damage_resistance"):
            foe.modifiers[mid] = modifier.model_copy(update={"target_field": "damage_immunity"})
    assert [hp for _, hp, _ in _one_weapon_hit(engine, bearer)] == [0], \
        "a weapon the defender is immune to lands nothing at all, Fury's points included"
    assert not [ev for ev in engine.events[-6:] if ev.event_type == "DAMAGE_COMMITTED"
                and ev.source_definition_id != _weapon_action(engine, bearer)], "no second packet from the singer"


def test_soul_stirring_refrain_fury_charges_one_roll_each_turn_not_one_each_of_the_bearers_own_turns():
    """"one weapon damage roll each turn": the clock is the table's shared per-turn clock, so the
    bearer's Opportunity Attack on someone else's turn has its own roll, and a second roll on the
    same turn does not repeat it.

    The singer Refrains itself here ("Choose one creature that can hear ... you"), so the bearer is a
    fully compiled fighter with a real Opportunity Attack reaction to measure.
    """
    from combat.ext import music

    _, engine, me, foe = _music(M + "soul_stirring_refrain")
    SWF.cast(engine, "Soul-Stirring Refrain: Fury", target=SWF.ME)
    assert _label(me, "condition:typed.music_fury")
    assert music.FURY_DAMAGE.startswith("typed_once_turn:"), "the shared per-turn clock, not an owner-turn flag"

    own_turn = _swing(engine, me, SWF.AN)
    assert own_turn["modifier"] == _plain_modifier(engine, me) + me.proficiency_bonus, own_turn
    assert me.turn_flags.get(music.FURY_DAMAGE), "the roll that was made is charged"

    engine.state.actors[SWF.ME].action_available = True  # a second swing on the same turn
    L4._script(engine, [15, 7])
    before = len(engine.events)
    _act_as(engine, SWF.ME, SWING, SWF.AN)
    repeat = next(ev.payload for ev in engine.events[before:] if ev.event_type == "DAMAGE_ROLLED")
    assert repeat["modifier"] == _plain_modifier(engine, me), "a second roll on the same turn does not add it again"

    L4._new_turn(engine, SWF.AN)          # another creature's turn begins
    assert not me.turn_flags.get(music.FURY_DAMAGE), "the clock resets at the start of any creature's turn"
    opportunity = _opportunity_attack(engine, me, foe)
    assert opportunity["modifier"] == _plain_modifier(engine, me) + me.proficiency_bonus, opportunity
    assert me.turn_flags.get(music.FURY_DAMAGE), "the off-turn roll is charged too"


def _plain_modifier(engine, actor):
    """The weapon roll's own modifier, without Fury's Proficiency Bonus."""
    weapon = (engine.action_catalog[_weapon_action(engine, actor)].parameters or {})["typed"]["weapon"]["damage"]
    return int(weapon.get("modifier") or 0)


def _swing(engine, actor, target_id):
    """One weapon swing by ``actor`` at ``target_id``, returning the damage roll it recorded."""
    L4._new_turn(engine, actor.entity_id)
    L4._script(engine, [15, 7])
    before = len(engine.events)
    _act_as(engine, actor.entity_id, SWING, target_id)
    return next(ev.payload for ev in engine.events[before:] if ev.event_type == "DAMAGE_ROLLED")


def _opportunity_attack(engine, actor, foe):
    """The bearer's Opportunity Attack as ``foe`` walks out of its reach on its own turn."""
    from combat.gate2_runtime_models import ActionIntent

    moves = [c for c in engine.legal_candidates() if c.actor_id == foe.entity_id and c.display_name.startswith("Move")
             and c.destination and abs(c.destination.x - foe.position.x) + abs(c.destination.y - foe.position.y) >= 4]
    assert moves, "the departing creature cannot walk out of reach"
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="auto72-leave", decision_id=moves[0].decision_id,
                                       candidate_id=moves[0].candidate_id, state_version=moves[0].state_version,
                                       actor_id=foe.entity_id, target_ids=moves[0].target_ids,
                                       destination=moves[0].destination))
    rolls = [ev.payload for ev in engine.events[before:] if ev.event_type == "DAMAGE_ROLLED"
             and ev.actor_id == actor.entity_id]
    assert rolls, "the bearer never made its Opportunity Attack"
    return rolls[0]


def test_soul_stirring_refrain_fury_gives_a_missed_weapon_roll_back():
    """"one weapon damage roll each turn": a swing that never rolled damage was not a damage roll."""
    from combat.ext import music

    _, engine, me, foe = _music(M + "soul_stirring_refrain")
    bearer = _fury_on_a_willing_ally(engine)
    assert _one_weapon_hit(engine, bearer, natural=2, ac=500) == [], "the attack missed"
    assert not bearer.turn_flags.get(music.FURY_DAMAGE), "a miss hands the roll back"
    assert _one_weapon_hit(engine, bearer, ac=-50)[0][1], "the next swing that lands has the bonus"


def _enemy_of(engine, foe, *, entity_id, at):
    """A second enemy of the same kind, on its own square (an equal rival for the nearest-creature rule)."""
    twin = foe.model_copy(deep=True)
    twin.entity_id = entity_id
    twin.position = at
    twin.action_available = twin.bonus_action_available = twin.reaction_available = True
    engine.state.actors[entity_id] = twin
    engine.state.initiative_order.append(entity_id)
    return twin


def test_soul_stirring_refrain_fury_penalises_only_targets_beyond_the_nearest_creature():
    """"has Disadvantage on attack rolls against targets other than the nearest creature": two
    creatures at the same distance are both nearest, so neither of them is penalised."""
    _, engine, me, foe = _music(M + "soul_stirring_refrain")
    bearer = _fury_on_a_willing_ally(engine)
    me.position = me.position.model_copy(update={"y": 12})  # the singer is far away, so it is not "the nearest creature"
    foe.position = foe.position.model_copy(update={"y": 8})  # 5 feet from the bearer
    twin = _enemy_of(engine, foe, entity_id="review:twin", at=me.position.model_copy(update={"x": 2, "y": 8}))

    def mode_of(target_id):
        L4._new_turn(engine, bearer.entity_id)
        L4._script(engine, [20, 5])  # a natural 20 still records the mode the roll was made with
        before = len(engine.events)
        _act_as(engine, bearer.entity_id, SWING, target_id)
        return next(ev.payload["mode"] for ev in engine.events[before:] if ev.event_type == "ATTACK_ROLLED")

    assert mode_of(foe.entity_id) == "NORMAL"
    assert mode_of(twin.entity_id) == "NORMAL", \
        "a tied nearest creature is not penalised, whichever way its name sorts"
    # The same reading one target further away, through the same Context the executor builds. A melee
    # reach of 5 feet cannot reach past the nearest creature on this grid, so the far target is a
    # ranged attack: the rule is about the distance, not about the weapon.
    twin.position = me.position.model_copy(update={"x": 2, "y": 12})
    assert _fury_mode(engine, bearer, twin) == "DISADVANTAGE"
    assert _fury_mode(engine, bearer, foe) is None, "the nearest creature itself is never penalised"


def _fury_mode(engine, bearer, target):
    """What the Fury attack_mode rule answers for one target, through a real Context."""
    from combat.typed_executor import Context

    from combat.ext import music
    action = engine.action_catalog[_weapon_action(engine, bearer)]
    ctx = Context(engine, bearer, action, None, dict((action.parameters or {}).get("typed") or {}), [target], target)
    return music.fury_away_from_the_nearest(ctx, target)


SWING = "Jian (Straight Sword) attack"  # the compiled weapon swing these tests measure


def _weapon_action(engine, bearer):
    """The swing's own action, so its compiled weapon (and damage types) are the ones under test."""
    return next(action_id for action_id in bearer.action_ids
                if engine.action_catalog[action_id].display_name == SWING)


def _mark_fury(engine, bearer, present):
    """Put the printed Fury mark on the bearer (or take it off) through the engine's own condition API."""
    from combat.ext import music

    held = music._fury(bearer)
    if present and held is None:
        engine._apply_condition(bearer, "condition:typed.music_fury", M + "soul_stirring_refrain", SWF.ME,
                                expires_on="CONCENTRATION_END", data={"label": "Fury", "rule": {"music_fury": True}})
    elif not present and held is not None:
        del bearer.conditions[held.instance_id]


def _one_weapon_hit(engine, bearer, *, fury=True, off_turn=False, natural=15, ac=None):
    """One weapon hit by ``bearer`` at the first foe, returning that foe's damage packets."""
    _mark_fury(engine, bearer, fury)
    foe = engine.state.actors[SWF.AN]
    if ac is not None:
        foe.armor_class = ac
    if off_turn:
        L4._new_turn(engine, SWF.AN)        # someone else's turn: the bearer's Opportunity Attack
        engine.state.actors[bearer.entity_id].reaction_available = True
    else:
        L4._new_turn(engine, bearer.entity_id)
    L4._script(engine, [natural, 7])
    before = len(engine.events)
    _act_as(engine, bearer.entity_id, SWING, SWF.AN)
    return [(ev.source_definition_id, int((ev.payload or {}).get("hp_damage") or 0), str((ev.payload or {}).get("damage_type") or ""))
            for ev in engine.events[before:] if ev.event_type == "DAMAGE_COMMITTED" and foe.entity_id in (ev.target_ids or ())]


# =========================================================== Immortal Funeral Bell: one healing a round, inside the aura
def test_immortal_funeral_bell_lets_an_enemy_inside_regain_hit_points_only_once_a_round():
    """"Enemies inside ... cannot regain HP more than once per round"."""
    from combat.ext import music

    _, engine, me, foe = _music(M + "immortal_funeral_bell")
    ally = SWF.ally(engine, me)
    foe.current_hp = ally.current_hp = 500
    SWF.cast(engine, "Immortal Funeral Bell")
    assert music._covered_by_the_bell(engine, foe) and not music._covered_by_the_bell(engine, ally)
    engine._heal(foe, 30, "action:test.bandage", me.entity_id)
    assert foe.current_hp == 530
    engine._heal(foe, 30, "action:test.bandage", me.entity_id)
    assert foe.current_hp == 530, "a second healing in the same round is refused"
    engine._heal(ally, 30, "action:test.bandage", me.entity_id)
    assert ally.current_hp == 530, "an ally inside the bell is untouched"
    engine.state.round_number += 1
    engine._heal(foe, 30, "action:test.bandage", me.entity_id)
    assert foe.current_hp == 560, "the next round brings one more healing"


def test_immortal_funeral_bell_follows_its_printed_aura_as_creatures_move():
    """The aura is "a 60-foot-radius aura centered on you", so membership is read now: an enemy that
    walks out from under the bell is free again, and an enemy that walks in is covered."""
    from combat.ext import music

    _, engine, me, foe = _music(M + "immortal_funeral_bell")
    latecomer = SWF.ally(engine, me)
    engine.state.actors.pop(latecomer.entity_id, None)
    latecomer.entity_id, latecomer.team_id = "review:latecomer", foe.team_id
    latecomer.position = me.position.model_copy(update={"x": me.position.x + 14})  # 70 feet: outside the 60-foot aura
    engine.state.actors[latecomer.entity_id] = latecomer
    foe.current_hp = latecomer.current_hp = 500
    SWF.cast(engine, "Immortal Funeral Bell")

    def walk(creature, feet_x, feet_y):
        creature.position = me.position.model_copy(update={"x": feet_x, "y": feet_y})

    def heals_outside(creature):
        before = creature.current_hp
        engine._heal(creature, 30, "action:test.bandage", me.entity_id)
        engine._heal(creature, 30, "action:test.bandage", me.entity_id)
        return creature.current_hp - before == 60

    assert not music._covered_by_the_bell(engine, latecomer), "an enemy outside the bell is not covered"
    assert heals_outside(latecomer)

    assert latecomer.current_hp == 560
    walk(latecomer, me.position.x + 2, me.position.y)  # it walks into the bell
    assert music._covered_by_the_bell(engine, latecomer)
    engine._heal(latecomer, 30, "action:test.bandage", me.entity_id)
    engine._heal(latecomer, 30, "action:test.bandage", me.entity_id)
    assert latecomer.current_hp == 590, "inside the bell it heals once a round, even though it arrived late"

    walk(latecomer, me.position.x + 14, me.position.y)  # and back out again
    assert not music._covered_by_the_bell(engine, latecomer)
    assert heals_outside(latecomer), "outside the bell it heals freely again"
    assert latecomer.current_hp == 650

    walk(latecomer, me.position.x + 2, me.position.y)
    engine.state.round_number += 1
    engine._heal(latecomer, 30, "action:test.bandage", me.entity_id)
    assert latecomer.current_hp == 680, "a new round brings one more healing inside the bell"
    walk(me, me.position.x + 15, me.position.y)  # the singer walks on: the aura travels with it
    assert not music._covered_by_the_bell(engine, latecomer), "the aura moved with its singer"


# =========================================================== Bell of Warning: one attack, once a round
def test_bell_of_warning_gives_two_armour_class_against_the_triggering_attack_only():
    """"gain +2 AC against the triggering attack" -- the printed deadline is that one attack."""
    from combat.ext.music import BELL

    _, engine, me, foe = _music(M + "bell_of_warning")
    row = next(r for r in engine.typed_reaction_rows[me.entity_id] if r.get("feature_id") == BELL)
    assert [effect["type"] for effect in row["effects"]] == ["ac_bonus"], row["effects"]
    assert row["effects"][0]["amount"] == 2
    from combat.ext.effect_durations import kind_of
    assert kind_of(row["effects"][0]["duration"]) == "triggering_attack", \
        'the printed deadline is that one attack: combat/ext/attack_defenses.grant installs it around the ' \
        'triggering attack alone (and it is the shape combat/typed_reactions._offer_ally_attacked hands the ' \
        'protected creature to, which next_attack_ac never received)' 


def test_bell_of_warning_is_rung_once_in_a_round():
    """"Use Bell of Warning once per round" -- a Reaction is otherwise one per turn, so the singer could
    ring it on someone else's turn and again on their own."""
    from combat.ext import music

    _, engine, me, foe = _music(M + "bell_of_warning")
    row = next(r for r in engine.typed_reaction_rows[me.entity_id] if r.get("feature_id") == music.BELL)
    assert any(ev.event_type == "REACTION_RESOLVED" and ev.source_definition_id == music.BELL
               for ev in engine.events), "the setup answered the bell's own initiative trigger"
    assert music.bell_once_per_round(engine, me, row) is False, "a second bell this round is not offered"
    engine.state.round_number += 1
    assert music.bell_once_per_round(engine, me, row) is None, "the next round may ring it again"
    assert music.bell_once_per_round(engine, foe, row) is None, "another creature's bell is its own"


# =========================================================== Silence-Breaking Note: the GM's outcome
def test_silence_breaking_note_offers_one_printed_note_and_leaves_the_outcome_to_the_game_master():
    """"Success: End the effect or suppress it until the start of your next turn, chosen by the GM
    according to the effect's strength."  The table may end the silence on a success; which of the
    two printed outcomes applies is the GM's call, so it is one action with an honest reminder
    rather than two buttons the player or the AI picks from."""
    engine = L1._engine(L1._bundle(M + "silence_breaking_note"), allies=(L1._ally_bundle(),))
    ally = engine.state.actors[L1.ALLY]
    L1._put(engine, L1.ALLY, "silenced", L1.FOE, "action:test.foe_silence")
    names = {name for name in L1._legal(engine) if "Silence-Breaking Note" in name}
    assert names == {"Silence-Breaking Note"}, names
    events = L1._use(engine, "Silence-Breaking Note", L1.ALLY)
    assert L1._payloads(events, "CHECK_ROLLED")[0]["success"] is True
    assert not _label(ally, "condition:typed.silenced")
    assert not _label(ally, "condition:typed.suppressed.silenced"), \
        "the temporary suppression is not a button: the Game Master decides which outcome applies"
    reminders = "\n".join(_gm_lines("tianxia.talent.music.silence_breaking_note"))
    assert "chosen by the GM according to the effect" in reminders


def test_silence_breaking_note_leaves_the_silence_alone_on_a_failed_check():
    engine = L1._engine(L1._bundle(M + "silence_breaking_note", dc=50), allies=(L1._ally_bundle(),))
    ally = engine.state.actors[L1.ALLY]
    L1._put(engine, L1.ALLY, "silenced", L1.FOE, L1._own_action(engine, "Silence-Breaking Note"))  # a DC 50 silence
    events = L1._use(engine, "Silence-Breaking Note", L1.ALLY)
    assert L1._payloads(events, "CHECK_ROLLED")[0]["success"] is False
    assert _label(ally, "condition:typed.silenced"), "a failed check leaves the silence"

# =========================================================== the real table: consent, reaction, commit + reload
# A real table, not an engine: CombatService + TabletopService, a fresh saved-fight load per commit (so
# every commit proves commit + reload + replay), and the prompts the player or the AI actually answers.
TABLE_ME, TABLE_ALLY, TABLE_FOE, TABLE_FOE2 = ["actor:factory.h27" + n for n in ("probe", "ally", "foe", "foe2")]


def table_arena(tmp_path, talents, topic, *, ac=None, ask_actors=(TABLE_ME,),
                maximum_rounds=4, bundle_transform=None):
    """The hunt-27 table with two extra levers: a chosen Armour Class for any fighter, and a
    scenario's own typed actions.

    ``ac`` picks the defender's Armour Class so a scenario can put the attacker's roll exactly on it --
    a hit without the bell and a miss with it, on the same seeded dice.

    ``bundle_transform(bundles)`` may give a creature a plain typed action (a fixture lever, the way
    tests/test_c15_healing_choices.py prepares a wound and a fixed heal), so a scenario spends and
    refuses a printed effect through real table transactions instead of by poking saved state.
    """
    import json
    import zipfile

    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet
    from tests.test_carry import KIT

    ids = [TABLE_ME, TABLE_ALLY, TABLE_FOE, TABLE_FOE2]
    docs = [sheet(talents, cl=20, dc=22, kit={"starting_kit": KIT})] + [sheet([], cl=20, kit={"starting_kit": KIT}) for _ in range(3)]
    for aid, doc, name in zip(ids, docs, ("You", "Ally", "East foe", "West foe")):
        doc["identity"]["display_name"] = name
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid in ask_actors else None)
               for aid, doc in zip(ids, docs)]
    if bundle_transform is not None:
        bundle_transform(bundles)
    for aid, bundle in zip(ids, bundles):
        value = (ac or {}).get(aid)
        if value is not None:
            bundle["actor_template"]["armor_class"] = value
    mid = combat._finish_factory_match(
        bundles, ids,
        {TABLE_ME: "team:factory", TABLE_ALLY: "team:factory", TABLE_FOE: "team:opponents", TABLE_FOE2: "team:opponents"},
        {TABLE_ME: {"x": 3, "y": 6}, TABLE_ALLY: {"x": 3, "y": 7}, TABLE_FOE: {"x": 4, "y": 6}, TABLE_FOE2: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [TABLE_ME, TABLE_ALLY], [TABLE_FOE, TABLE_FOE2],
        control_modes={TABLE_ME: "MANUAL", **{aid: "MANUAL" for aid in ask_actors}},
        match_seed=f"AUTO72-{topic}-0", maximum_rounds=maximum_rounds, display_name="AUTO72f1 regression")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def table_commit(combat, table, mid, tmp_path, cid=None, choose=None):
    """The hunt-27 commit: a real transaction, then a fresh load that must match and replay PASS."""
    from tests.test_hunt27_table import commit
    return commit(combat, table, mid, tmp_path, cid, choose=choose)


def table_next(combat, table, mid, tmp_path, choose=None):
    """Let whoever's turn it is end, until a foe with a live attack at the ally is the actor."""
    engine = combat._load_session(mid).engine
    candidates = engine.legal_candidates()
    cid = next((c.candidate_id for c in candidates if c.kind.value == "END_TURN"), candidates[0].candidate_id)
    table_commit(combat, table, mid, tmp_path, cid, choose=choose)


def _bell_answer(armed):
    """The bell prompt is answered only once ``armed`` is true.

    Bell of Warning is a once-per-round Reaction, and the fight's own Initiative is its first trigger,
    so a scenario that wants it against an attack has to let the Initiative one go (a Decline spends
    nothing). ``armed`` is that switch.
    """
    def choose(prompt):
        if "bell_of_warning" not in str(prompt["context"].get("reaction_source_id")):
            return None
        if not armed.get("rung"):
            return None  # decline: the Reaction is not spent
        options = (prompt.get("choice") or {}).get("options") or []
        return [options[0]["id"]] if options else "USE"
    return choose


def _unused_strike_the_ally(combat, table, mid, tmp_path, armed):
    """A foe attacks the ally; returns (attack roll payload, damage dealt, prompts answered).

    The bell answers an attack only "before [the creature] has acted in combat", so the scenario needs
    the singer to act before the ally and a foe in between (see BELL_TOPIC).
    """
    choose = _bell_answer(armed)
    for _ in range(24):
        engine = combat._load_session(mid).engine
        if engine.state.current_actor_id in (TABLE_FOE, TABLE_FOE2) and int(engine.state.round_number) == 1:
            attack = next((c for c in engine.legal_candidates()
                           if c.kind.value == "ACTION" and TABLE_ALLY in (c.target_ids or ())
                           and "attack" in c.display_name), None)
            if attack is not None:
                before = len(engine.events)
                armed["rung"] = True  # this attack is the one the bell answers
                answers = table_commit(combat, table, mid, tmp_path, attack.candidate_id, choose=choose)
                engine = combat._load_session(mid).engine
                rolled = next(ev.payload for ev in engine.events[before:] if ev.event_type == "ATTACK_ROLLED")
                dealt = [int((ev.payload or {}).get("hp_damage") or 0) for ev in engine.events[before:]
                         if ev.event_type == "DAMAGE_COMMITTED" and TABLE_ALLY in (ev.target_ids or ())]
                return rolled, dealt, answers
        table_next(combat, table, mid, tmp_path, choose=choose)
        armed["rung"] = False
    raise AssertionError("no foe ever got to attack the ally")


SINGER, RIVAL = "actor:factory.auto72singer", "actor:factory.auto72rival"


def _two_music_fighters(key):
    """Two compiled Music fighters on opposite sides: one rings the bell, the other swings a real
    (typed) weapon attack at it -- the attack path that opens the ATTACK_DECLARED window."""
    from combat.factory_compiler import compile_character
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.hunt24_support import finish_direct_setup
    from tests.test_zones import SHEET

    def sheet():
        return {**SHEET,
                "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "quantity": 1}]}}],
                "identity": {**SHEET["identity"], "cultivation_level": 20},
                "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"],
                                                  "technique_save_dc": 20, "technique_attack_bonus": 40,
                                                  "primary_resource": {"name": "Qi", "maximum": 100}},
                "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.music"],
                                        "learned_talent_record_ids": ["MUSIC_BASE_KEEP_THE_MEASURE", key]}}

    bundles = (compile_character(sheet(), actor_id=SINGER), compile_character(sheet(), actor_id=RIVAL))
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO72", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [SINGER, RIVAL],
                                                 "team_by_actor": {SINGER: "team:a", RIVAL: "team:b"},
                                                 "starting_positions": {SINGER: {"x": 3, "y": 6}, RIVAL: {"x": 4, "y": 6}}})
    finish_direct_setup(engine)
    singer, rival = engine.state.actors[SINGER], engine.state.actors[RIVAL]
    singer.maximum_hp = singer.current_hp = rival.maximum_hp = rival.current_hp = 500
    return engine, singer, rival


def test_bell_of_warning_raises_the_armour_class_of_the_attack_it_answers():
    """"gain +2 AC against the triggering attack", through the real Reaction path and a real attack.

    The attacker's roll is put exactly on the singer's Armour Class, so the same seeded attack hits
    without the bell and misses with it -- and nothing else about that attack changes.
    """
    engine, singer, rival = _two_music_fighters(M + "bell_of_warning")
    assert not [e for e in engine.events if e.actor_id == SINGER and e.event_type in ("TURN_ENDED", "INTENT_ACCEPTED")
                and (e.payload or {}).get("kind") in ("ACTION", "BONUS_ACTION", "MOVE", "HOLD_POSITION", "END_TURN")], \
        "the singer has not acted yet, which is the bell's printed window"
    def strike(natural):
        L4._new_turn(engine, RIVAL)
        engine.state.actors[RIVAL].action_available = True
        L4._script(engine, [natural, 7])
        before = len(engine.events)
        _act_as(engine, RIVAL, SWING, SINGER)
        rolled = next(ev.payload for ev in engine.events[before:] if ev.event_type == "ATTACK_ROLLED"
                      and SINGER in (ev.target_ids or ()))
        dealt = [int((ev.payload or {}).get("hp_damage") or 0) for ev in engine.events[before:]
                 if ev.event_type == "DAMAGE_COMMITTED" and SINGER in (ev.target_ids or ())]
        return rolled, dealt

    plain_ac = singer.armor_class
    # Round one: the fight's own Initiative already spent the bell's one use, so this is the control --
    # the attacker's roll lands exactly on the printed Armour Class and hits.
    rolled, dealt = strike(plain_ac - 2)
    assert rolled["target_ac"] == plain_ac and rolled["provisional_hit"] and sum(dealt) > 0, (rolled, dealt)
    # Round two: the bell is available again, and the singer takes no action, so it may still answer.
    engine.state.round_number = 2
    L4._new_turn(engine, SINGER)
    rolled, dealt = strike(plain_ac - 2)
    assert rolled["target_ac"] == plain_ac + 2, "the bell's +2 answers the very attack that triggered it"
    assert rolled["modified_total"] == plain_ac and rolled["provisional_hit"] is False and not dealt, (rolled, dealt)
    assert not [m for m in singer.modifiers.values() if m.target_field == "armor_class"], \
        "the bonus belonged to that one attack"
    assert singer.resources["resource:core.qi"] < 100, "the bell cost its printed 1 Qi"


def test_bell_of_warning_at_the_table_costs_one_reaction_once_a_round(tmp_path):
    """Bell of Warning at the real table: the printed Reaction, its printed cost, its once-per-round
    use, and a plain-language reminder instead of an unexplained one.

    Every commit here is a fresh load of the committed fight that must match and replay PASS, so the
    singer's recorded use of the bell is proven to survive a save. (The +2 AC answering the attack that
    triggered the bell is proven in the reaction test above: a bell rung on the Initiative rolls has no
    attack to answer, which is what the reminder says.)
    """
    root = tmp_path / "bell"
    root.mkdir()
    combat, table, mid = table_arena(root, [M + "bell_of_warning"], "bell-table")
    qi = combat._load_session(mid).engine.state.actors[TABLE_ME].resources["resource:core.qi"]

    def choose(prompt):
        if "bell_of_warning" in str(prompt["context"].get("reaction_source_id")):
            options = (prompt.get("choice") or {}).get("options") or []
            return [options[0]["id"]] if options else "USE"
        return None

    engine = combat._load_session(mid).engine
    candidates = engine.legal_candidates()
    cid = next((c.candidate_id for c in candidates if c.kind.value == "END_TURN"), candidates[0].candidate_id)
    answers = table_commit(combat, table, mid, root, cid, choose=choose)
    assert any("bell_of_warning" in str(a.get("reaction_source_id")) for a in answers), "the bell was never rung"

    engine = combat._load_session(mid).engine  # a fresh load of the committed fight
    singer = engine.state.actors[TABLE_ME]
    assert singer.resources["resource:core.qi"] == qi - 1, "the bell cost its printed 1 Qi"
    assert int(singer.turn_flags["_round_music_bell_of_warning"]) == engine.state.round_number, \
        "'Use Bell of Warning once per round' is recorded on the singer and survives the reload"
    assert not [m for a in engine.state.actors.values() for m in a.modifiers.values()
                if m.target_field == "armor_class"], "the bell left no standing Armour Class bonus behind"
    said = "\n".join(str((ev.payload or {}).get("rider") or (ev.payload or {}).get("log") or "")
                     for ev in engine.events if ev.event_type in ("GM_RIDER", "PASSIVE_TRIGGERED"))
    assert "no attack for its +2 Armour Class to answer" in said, said


@pytest.mark.parametrize("answer", ["accept", "refuse"])
@pytest.mark.parametrize("manual", [True, False])
def test_soul_stirring_refrain_asks_the_target_before_it_saves(tmp_path, manual, answer):
    """"A willing target may choose to fail": the choice is asked at the table, of the target, on the
    singer's turn -- and the AI answers it on its own turns (an ally accepts, an enemy refuses)."""
    root = tmp_path / f"{manual}-{answer}"
    root.mkdir()
    combat, table, mid = table_arena(root, [M + "soul_stirring_refrain"], f"refrain-{manual}-{answer}",
                                     ask_actors=(TABLE_ME, TABLE_ALLY))
    name = "Soul-Stirring Refrain: Fury"   # the ally is the chosen creature; the consent answer is the variable
    if not manual:
        combat.set_controller_mode(mid, actor_id=TABLE_ME, controller_mode="LOCAL_AUTO")

    def offering():
        return next((c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.display_name == name and TABLE_ALLY in (c.target_ids or ())), None)

    while offering() is None:  # let the table reach the singer's turn with the Refrain available
        table_next(combat, table, mid, root, choose=_refrain_answer(answer))

    seen = []

    def choose(prompt):
        seen.append(prompt)
        return _refrain_answer(answer)(prompt)

    engine = combat._load_session(mid).engine
    before = len(engine.events)
    table_commit(combat, table, mid, root, offering().candidate_id, choose=choose)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[TABLE_ALLY]
    consent = [p for p in seen if p["context"].get("reaction_source_id") == "choice:willing.consent"]
    assert consent, f"the target was never asked; prompts: {[p['context'].get('reaction_source_id') for p in seen]}"
    assert consent[0]["context"]["reactor_id"] == TABLE_ALLY
    assert "Soul-Stirring Refrain" in consent[0]["moment"] and "Ally" in consent[0]["moment"], consent[0]["moment"]
    assert "willing" in consent[0]["moment"].lower(), "the question explains what accepting means"
    mark = [c for c in ally.conditions.values() if c.condition_id == "condition:typed.music_fury"]
    if answer == "accept":
        assert mark, "a willing target takes the emotion"
        assert not [ev for ev in engine.events[before:] if ev.event_type == "SAVE_ROLLED"
                    and ev.actor_id == TABLE_ALLY], "a willing target makes no save"
        assert not (mark[0].data or {}).get("repeat_save"), "and has no printed save to repeat"
    else:
        saves = [ev for ev in engine.events[before:] if ev.event_type == "SAVE_ROLLED" and ev.actor_id == TABLE_ALLY]
        assert saves, "an unwilling target makes the printed Wisdom save"
        failed = not bool(saves[0].payload.get("success"))
        assert bool(mark) == failed, "a refused target keeps the emotion only if it fails that save"
        assert bool((mark[0].data or {}).get("repeat_save")) == failed, \
            "the printed repeat save belongs to the target that was made to save"


def _refrain_answer(answer):
    def choose(prompt):
        if prompt["context"].get("reaction_source_id") == "choice:willing.consent":
            return [answer]
        return None
    return choose


def _act_when(combat, table, mid, root, wanted, *, choose=None, limit=48):
    """Advance the table until ``wanted(engine, candidate)`` names a live action, then commit it.

    Every commit is a real transaction followed by a fresh load that must match and replay PASS
    (tests/test_hunt27_table.py), so anything this helper observes afterwards is read back off disk.
    """
    for _ in range(limit):
        engine = combat._load_session(mid).engine
        found = next((c for c in engine.legal_candidates() if wanted(engine, c)), None)
        if found is not None:
            return table_commit(combat, table, mid, root, found.candidate_id, choose=choose)
        table_next(combat, table, mid, root, choose=choose)
    raise AssertionError("the table never offered that action")


def test_furys_charged_damage_roll_survives_a_save_and_the_next_turn_restores_it(tmp_path):
    """Fury's "one weapon damage roll each turn" is saved on the bearer, not rebuilt on load.

    The bearer charges the roll with a real attack at the real table; the fight is committed and read
    back from disk, and the charged turn is still charged -- a second weapon roll on that same turn
    still adds no Proficiency Bonus.  The next turn's clock (the shared per-turn one) restores it.
    """
    from combat.ext import music

    root = tmp_path / "fury-saved"
    root.mkdir()
    combat, table, mid = table_arena(root, [M + "soul_stirring_refrain"], "fury-saved",
                                     ac={TABLE_FOE: 1}, ask_actors=(TABLE_ME, TABLE_ALLY))
    _act_when(combat, table, mid, root,
              lambda engine, c: (c.kind.value == "ACTION" and c.actor_id == TABLE_ME
                                 and c.display_name == "Soul-Stirring Refrain: Fury"
                                 and TABLE_ALLY in (c.target_ids or ())),
              choose=_refrain_answer("accept"))
    engine = combat._load_session(mid).engine  # a fresh load of the committed fight
    bearer = engine.state.actors[TABLE_ALLY]
    assert _label(bearer, "condition:typed.music_fury"), "the ally took the emotion with the singer's consent"

    # the bearer's own weapon attack: Armour Class -50 on the foe makes the hit certain, so the roll is charged
    _act_when(combat, table, mid, root,
              lambda engine, c: (c.kind.value == "ACTION" and c.actor_id == TABLE_ALLY
                                 and TABLE_FOE in (c.target_ids or ()) and "attack" in c.display_name))
    engine = combat._load_session(mid).engine  # a fresh load of the committed fight
    bearer = engine.state.actors[TABLE_ALLY]
    singer = engine.state.actors[TABLE_ME]
    assert bearer.turn_flags.get(music.FURY_DAMAGE), "'one damage roll each turn' is saved on the bearer"
    assert music._fury_bonus(engine, bearer) is None, \
        "the saved charge still refuses a second weapon damage roll on that same turn"

    table_next(combat, table, mid, root)  # the next creature's turn begins: the shared clock resets
    engine = combat._load_session(mid).engine
    bearer, singer = engine.state.actors[TABLE_ALLY], engine.state.actors[TABLE_ME]
    assert not bearer.turn_flags.get(music.FURY_DAMAGE), "the per-turn clock reset after the reload"
    assert music._fury_bonus(engine, bearer) == singer.proficiency_bonus, \
        "the next turn's weapon damage roll adds the Proficiency Bonus again"


def test_funeral_bells_one_healing_a_round_for_a_covered_enemy_is_saved_with_the_fight(tmp_path):
    """Immortal Funeral Bell's "enemies inside ... cannot regain HP more than once per round".

    The bell is rung at the real table and the fight is committed, so the ringing bell itself is read
    back from disk.  The enemy the bell covers then regains Hit Points, which spends its one healing
    for the round: the fight state is written out and read back the way a save and a reload do it, and
    that spent healing is still spent -- the enemy cannot regain Hit Points again this round, and the
    next round brings one more.
    """
    import json

    from combat.ext import music

    root = tmp_path / "bell-heal"
    root.mkdir()
    combat, table, mid = table_arena(root, [M + "immortal_funeral_bell"], "bell-heal")
    _act_when(combat, table, mid, root,
              lambda engine, c: (c.kind.value == "ACTION" and c.actor_id == TABLE_ME
                                 and c.display_name == "Immortal Funeral Bell"))
    engine = combat._load_session(mid).engine  # a fresh load of the committed fight
    covered = engine.state.actors[TABLE_FOE]
    assert music._covered_by_the_bell(engine, covered), "the committed bell is ringing over an enemy of its singer"

    covered.current_hp -= 60  # wound it, so a refused or an allowed healing below cannot pass vacuously
    engine._heal(covered, 30, "action:auto72.probe", TABLE_ME)
    assert covered.current_hp == 170, "the enemy's one healing of the round was spent"
    spent = covered.turn_flags.get(music.FUNERAL_HEALED)

    # what a save writes and a load reads: the fight state as JSON, validated back into the model
    written = json.dumps(engine.state.model_dump(mode="json", by_alias=True))
    reloaded_state = type(engine.state).model_validate(json.loads(written))
    reloaded = combat.persistence._engine_from_loaded(reloaded_state, engine.events, engine.rolls,
                                                      commanded_cui_this_turn=False)
    covered = reloaded.state.actors[TABLE_FOE]
    assert covered.turn_flags.get(music.FUNERAL_HEALED) == spent == int(reloaded.state.round_number), \
        "the one healing a round is recorded on the covered enemy, as a whole number a save can carry"
    assert music._covered_by_the_bell(reloaded, covered), "the bell still covers it after the reload"

    covered.current_hp -= 30  # wound it again, so the probe below cannot pass vacuously
    reloaded._heal(covered, 30, "action:auto72.probe", TABLE_ME)
    assert covered.current_hp == 140, \
        "a covered enemy still cannot regain Hit Points again in the round it spent"

    reloaded.state.round_number += 1  # the next round's clock
    reloaded._heal(covered, 30, "action:auto72.probe", TABLE_ME)
    assert covered.current_hp == 170, "the next round brings one more healing"


# =========================================================== the bell's one healing, through the real table
def _add_test_action(bundle, *, name, source_id, target_kind, range_ft, effects, economy="ACTION"):
    """Give one creature in this fixture a plain typed action.

    The lever belongs to the scenario, not to the engine: the healing and the wound below are real
    compiled actions that the table offers, commits and writes out, which is what lets a scenario
    spend and then refuse the bell's one healing a round without patching anything to manufacture a
    transaction.  It follows tests/test_c15_healing_choices.py, which prepares its Mend the same way.
    """
    from combat.canonical import canonical_sha256

    template = next(a for a in bundle["action_catalog"]
                    if a["resolution_kind"] == "TYPED" and a["target_kind"] == "SELF"
                    and not a.get("costs") and not a.get("concentration"))
    typed = copy.deepcopy(template["parameters"]["typed"])
    action = copy.deepcopy(template)
    action["source_definition_id"] = source_id
    action["display_name"] = name
    action["economy"] = economy
    action["target_kind"] = target_kind
    action["range_ft"] = range_ft
    action["attack_bonus"] = action["damage"] = action["damage_type"] = action["save"] = None
    # Only the typed block and its effects survive: whatever the borrowed action was printed to do
    # (carry a blossom, need a stance) is not part of this plain lever, and would gate it away.
    action["parameters"] = {"expected_damage": 0,
                            "typed": {**typed, "effects": effects, "riders": [], "range_ft": range_ft,
                                      "duration": {"kind": "instant"}}}
    bundle["action_catalog"].append(action)
    bundle["actor_template"]["action_ids"].append(source_id)
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def _bell_healing_actions():
    """A wound for the ally, and one healing plus a second healing for the covered enemy.

    The enemy's second healing is a Bonus Action so both of its healings belong to the same turn,
    which is what "cannot regain HP more than once per round" is about: an Action and a Bonus Action
    healing in one round is the ordinary way a creature tries to heal twice, and each is its own
    table transaction.
    """
    def prepare(bundles):
        for bundle in bundles:
            if bundle["actor_id"] == TABLE_ALLY:
                _add_test_action(bundle, name="Test Wound", source_id="action:test.auto72_wound",
                                 target_kind="HOSTILE_ENTITY", range_ft=30, economy="ACTION",
                                 effects=[{"type": "damage", "flat": 60, "damage_type": "UNTYPED",
                                           "applies_to": "target"}])
            elif bundle["actor_id"] == TABLE_FOE:
                _add_test_action(bundle, name="Test Mend", source_id="action:test.auto72_mend",
                                 target_kind="SELF", range_ft=None, economy="ACTION",
                                 effects=[{"type": "healing", "flat": 20, "applies_to": "self"}])
                _add_test_action(bundle, name="Test Second Wind", source_id="action:test.auto72_second_wind",
                                 target_kind="SELF", range_ft=None, economy="BONUS_ACTION",
                                 effects=[{"type": "healing", "flat": 20, "applies_to": "self"}])
    return prepare


def test_the_bells_spent_healing_is_still_spent_after_a_real_commit_and_reload(tmp_path):
    """Immortal Funeral Bell's "enemies inside ... cannot regain HP more than once per round".

    This is the level the printed line lives at.  The bell is rung at the real table, the covered
    enemy is wounded by a real action and then tries to heal twice in that same round, with an
    Action and a Bonus Action: every step is a transaction followed by a fresh load that must match
    and replay PASS, so the flag that refuses the second healing is one that went through the journal
    and came back off disk.  Only one of the two healings lands.  After a real round transition the
    enemy is healed again, which is the half the earlier probe could not show.
    """
    from combat.ext import music

    root = tmp_path / "bell-heal-table"
    root.mkdir()
    # Every creature with a lever in this scenario is answered by hand, so the only healings that
    # happen are the two the scenario asks for.
    combat, table, mid = table_arena(root, [M + "immortal_funeral_bell"], "bell-heal-table",
                                     ask_actors=(TABLE_ME, TABLE_ALLY, TABLE_FOE, TABLE_FOE2),
                                     maximum_rounds=6, bundle_transform=_bell_healing_actions())

    def wound_the_enemy():
        _act_when(combat, table, mid, root,
                  lambda engine, c: (c.kind.value == "ACTION" and c.actor_id == TABLE_ALLY
                                     and c.display_name == "Test Wound" and TABLE_FOE in (c.target_ids or ())))

    def heal(kind, name):
        _act_when(combat, table, mid, root,
                  lambda engine, c: (c.kind.value == kind and c.actor_id == TABLE_FOE
                                     and c.display_name == name and TABLE_FOE in (c.target_ids or ())))

    def enemy_hp():
        return combat._load_session(mid).engine.state.actors[TABLE_FOE].current_hp

    _act_when(combat, table, mid, root,
              lambda engine, c: (c.kind.value == "ACTION" and c.actor_id == TABLE_ME
                                 and c.display_name == "Immortal Funeral Bell"))
    engine = combat._load_session(mid).engine
    assert music._covered_by_the_bell(engine, engine.state.actors[TABLE_FOE]), \
        "the committed bell is ringing over an enemy of its singer"

    wound_the_enemy()
    assert enemy_hp() == 140, "the enemy is wounded by a real committed action, ready for a real heal"
    round_spent = combat._load_session(mid).engine.state.round_number

    heal("ACTION", "Test Mend")  # the enemy's one healing of the round, committed and written out
    assert enemy_hp() == 160, "the first real committed healing of the round lands"
    heal("BONUS_ACTION", "Test Second Wind")  # same creature, same turn, same round
    assert enemy_hp() == 160, \
        f"a covered enemy cannot regain Hit Points twice in the round it already spent: {enemy_hp()}"

    engine = combat._load_session(mid).engine  # a fresh load of the committed fight
    covered = engine.state.actors[TABLE_FOE]
    assert covered.turn_flags.get(music.FUNERAL_HEALED) == round_spent == engine.state.round_number, \
        "the one healing a round that the second healing was refused by is the one read back off disk"
    assert covered.current_hp == 160, "the refused healing never reached the saved fight"

    # the next round really begins, and the enemy is healed again
    wound_the_enemy()
    assert enemy_hp() == 100, "wounding the enemy again spends nothing and heals nothing"
    heal("ACTION", "Test Mend")
    engine = combat._load_session(mid).engine
    assert engine.state.round_number > round_spent, \
        f"the enemy healed again only after a real round transition: {engine.state.round_number}"
    assert engine.state.actors[TABLE_FOE].current_hp == 120, "the next round brings one more healing"
