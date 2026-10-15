"""Beast-Echo Marrow (v0 2A) combat automation (owner 2026-10-12, A2R03).

The printed combat effects of the foundation's eight features
(authority/typed_mechanics/rules_text.json), resolved through the
documented seams in combat/ext/__init__.py:

* Generate Pack Echo -- the ``generate`` block (combat/pressure.py) for
  a scope hit with an ally or bonded companion near, or a hit on a
  beast-aspected creature; this plug-in generates both receipts in its
  strict ``hit_final`` after paid hit riders (the feature's row claims the trigger through
  ``trigger_owner``, so the compiled generic reaction is left out).
* Pack-Marrow Strike -- a prior-Echo ``hit_snapshot`` and paid ``hit_final``, including the
  Refined Pack Marrow rider's same-target +PB and the state's
  once-per-round another +PB.
* Beast-Sense Witness -- ``d20_rewrite`` rules (combat/ext/d20_rewrite.py):
  the fighter's own roll, and -- with Companion Echo -- a bonded
  companion's roll for another PB, plus the companion's failed-save
  psychic-damage reroll.
* Marrow Pack Guard -- the compiled generic ``ally_damaged`` reaction
  from its typed record (the PB reduction), plus the cultivation
  ability modifier, Companion Echo's another PB and the bonded-companion
  move rider here (``damage_reduction_bonus``), and the printed
  trigger's source taxonomy and prior-damage link
  (``reaction_geometry_allowed``, the pre-consent veto that receives
  the triggering attacker).
* Companion Echo -- the riders above.
* Predator Answer -- the rider on generating Pack Echo from a
  beast-aspected hit: temporary HP or a 5-foot move (the player
  chooses; the AI takes the temporary HP).
* Beast-Echo Marrow State -- the bonus action below and its mode hooks.

The printed "Fixed Beast-Echo Scope" is the foundation's own scope:
Beastmastery, Spirit Companions, Blood, Hunger, Athletics, Warleader,
Brute, Berserker or Wrestling techniques and natural weapons (the
families Beast-Echo Marrow State itself names as compatible). The
engine tracks no separate "predator-aspected" label, so a predator is
read through its beast label (combat/ext/creature_kinds.py).
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, needle, note
from . import creature_kinds
from .d20_rewrite import Rule, register
from .. import pressure, summons
from ..ability_checks import key_modifier
from ..gate2_runtime_models import ActionDefinition, EconomyKind
from ..typed_executor import Context, clock_expiry, run_effects

FEATURE = "foundation.beast_echo_marrow_v0_2A"
ECHO = "resource:foundation.pack_echo"
BLOCK = "beast_echo"
CP_POOLS = frozenset({"resource:core.qi", "resource:core.stamina", "resource:core.resonance"})

GENERATE = FEATURE + ".generate_pack_echo"
STRIKE = FEATURE + ".pack_marrow_strike"
WITNESS = FEATURE + ".beast_sense_witness"
GUARD = FEATURE + ".marrow_pack_guard"
COMPANION = FEATURE + ".companion_echo"
MARROW = FEATURE + ".pack_marrow"
PREDATOR = FEATURE + ".predator_answer"
STATE = FEATURE + ".beast_echo_marrow_state"

STATE_CONDITION = "condition:typed.beast_echo_marrow_state"
STATE_ACTION = "action:typed.beast_echo_marrow_state"
STATE_USED = "typed_round_once:beast_echo_marrow_state"
PAIR_BUDGET = "typed_round_once:beast_echo_pair"

# The Fixed Beast-Echo Scope's technique families and natural weapons.
SCOPE_PREFIXES = (
    "tianxia.talent.beastmastery.",
    "TAL_BEASTMASTERY_",
    "tianxia.talent.spirit_companions.",
    "TAL_SPIRIT_COMPANIONS_",
    "tianxia.talent.blood.",
    "tianxia.talent.hunger.",
    "tianxia.talent.warleader.",
    "tianxia.talent.brute.",
    "TAL_BRUTE_",
    "tianxia.talent.berserker.",
    "TAL_BERSERKER_",
    "TAL_WRESTLING_",
    "TAL_ATHLETICS_",
)
# The printed beast kinds (a "demon beast" answers either label).
BEAST_KINDS = ("beast", "monstrosity", "spirit beast", "demon")

# Beast-Sense Witness's printed scope words, as roll hazards and skills.
SCOPE_HAZARDS = frozenset({
    "frightened", "charmed", "dominated", "fear", "intimidation",
    "forced_movement", "prone", "grappled", "restrained",
})
SCOPE_SKILLS = frozenset({
    "animal handling", "nature", "survival", "perception", "insight",
})

# Beast-Echo Marrow State's Advantage list: fear, intimidation,
# domination, predator aura and forced movement.
FEAR_PRESSURE = frozenset({
    "frightened", "charmed", "dominated", "fear", "intimidation",
    "domination", "forced_movement",
})


def hostile(a: Any, b: Any) -> bool:
    return a is not None and b is not None and a.team_id != b.team_id


def owns(engine: Any, actor: Any, feature_id: str) -> bool:
    """Whether the fighter owns the feature: a compiled row of the
    character's carries its mechanic id."""
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    reactions = (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
    return any(row.get("feature_id") == feature_id for row in (*rows, *reactions))


def echo_held(actor: Any) -> bool:
    return int((actor.resources or {}).get(ECHO, 0)) >= 1


def companions(engine: Any, owner: Any) -> list[Any]:
    """The owner's bonded companions: its own summoned creatures."""
    return [creature for creature in summons.owned_by(engine, owner.entity_id)
            if creature.active and creature.team_id == owner.team_id]


def beast_kinded(actor: Any) -> bool:
    return actor is not None and creature_kinds.matches(actor, BEAST_KINDS)


def in_scope(source_id: str | None) -> bool:
    """Whether an attack or technique is a Fixed Beast-Echo Scope
    expression: one of the scope families, or a natural weapon."""
    if not source_id:
        return False
    lowered = str(source_id).strip().lower()
    return _scope_family_source(lowered) \
        or "unarmed" in lowered or "natural" in lowered


def _scope_family_source(source_id: str) -> bool:
    """Match a canonical family ID or its compiler-sealed typed action ID."""
    prefixes = tuple(prefix.lower() for prefix in SCOPE_PREFIXES)
    if source_id.startswith(prefixes):
        return True
    if source_id.startswith("action:typed."):
        # factory_compiler uses action:typed.<character>.<mechanic_id>.
        mechanic_id = source_id[len("action:typed."):].partition(".")[2]
        return bool(mechanic_id) and mechanic_id.startswith(prefixes)
    return False


def _hazards(named: Any) -> frozenset[str]:
    return frozenset(str(hazard).lower() for hazard in (named or ()))


def _ally_near(engine: Any, actor: Any, target: Any, ft: int) -> bool:
    """An ally or bonded companion within ``ft`` of the fighter or
    the target."""
    for creature in engine.state.actors.values():
        if not creature.active or creature.entity_id == actor.entity_id:
            continue
        if creature.team_id != actor.team_id and creature not in companions(engine, actor):
            continue
        if engine._distance_actor_to_actor(creature, actor) <= ft \
                or engine._distance_actor_to_actor(creature, target) <= ft:
            return True
    return False


def _pair_near(engine: Any, owner: Any, creature: Any, ft: int) -> bool:
    """The creature is the owner itself, a bonded companion, or an
    ally within ``ft`` of the owner."""
    if creature.entity_id == owner.entity_id:
        return True
    if creature in companions(engine, owner):
        return True
    return creature.team_id == owner.team_id and engine._distance_actor_to_actor(owner, creature) <= ft


def _refined_pack_marrow_qualifies(engine: Any, owner: Any, hitter: Any,
                                   target: Any) -> bool:
    """Whether this Strike earns Refined Pack Marrow's extra PB.

    Unlike the base Strike, the refined rider's printed 30-foot range also
    applies to a bonded companion, whose ordinary pair eligibility is not
    range-limited by ``_pair_near``.
    """
    return (hitter.entity_id != owner.entity_id
            and owns(engine, owner, MARROW)
            and _pressed_by_owner(engine, owner, target)
            and engine._distance_actor_to_actor(owner, hitter) <= 30)


def _damaged_since_last_turn(engine: Any, owner: Any, attacker: Any, friends: list[str]) -> bool:
    """Whether the owner's side damaged the attacker since the start
    of the owner's last turn: damage events after the start of the
    owner's previous turn on their turn, or most recent turn off-turn, up to now."""
    turns = 0
    for event in reversed(getattr(engine, "events", []) or []):
        if event.event_type == "TURN_STARTED" and event.actor_id == owner.entity_id:
            turns += 1
            if turns >= (2 if engine.state.current_actor_id == owner.entity_id else 1):
                return False  # the applicable printed start boundary
            continue
        if event.event_type == "DAMAGE_COMMITTED" and attacker.entity_id in (event.target_ids or ()):
            if event.actor_id in friends:
                return True
    return False


def _scope_source(engine: Any, attacker: Any) -> bool:
    """A beast/predator/natural-weapon/blood/fear/pack-aura source."""
    if beast_kinded(attacker):
        return True
    action_id = str(getattr(engine, "_active_action_source_id", None) or "")
    if not action_id:
        return False
    lowered = action_id.lower()
    return ("unarmed" in lowered or "natural" in lowered
            or _scope_family_source(lowered)
            or "fear" in lowered or "aura" in lowered)


def _hit_damage_type(engine: Any, actor: Any, target: Any) -> str:
    dealt = next((event for event in reversed(engine.events[-30:])
                  if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id
                  and target.entity_id in (event.target_ids or ())), None)
    return str(((dealt.payload or {}) if dealt is not None else {}).get("damage_type") or "")


def _active_action(engine: Any) -> Any:
    """The action the engine is resolving, for a movement effect's
    context."""
    return engine.action_catalog.get(getattr(engine, "_active_action_source_id", None) or "")


@hook("hit_snapshot")
def echo_before_hit(engine: Any, actor: Any, target: Any, attack_context: Any,
                    intent: Any) -> dict[str, Any] | None:
    """Only Echo held before this hit can pay any owner's hit rider."""
    held = {owner.entity_id: int(owner.resources.get(ECHO, 0))
            for owner in engine.state.actors.values() if owns(engine, owner, STRIKE)}
    return {"beast_echo_strike": held} if held else None


@hook("hit_final", priority=10)
def pack_echo_generation(ctx: Any, target: Any, kind: str) -> None:
    """Generate Pack Echo: a Fixed Beast-Echo Scope hit while an ally
    or bonded companion is within 30 ft of the fighter or the target,
    or a hit on a beast-aspected creature (which also answers
    Predator Answer)."""
    engine, actor = ctx.engine, ctx.actor
    if not owns(engine, actor, GENERATE) or not target.active or not hostile(actor, target):
        return
    if beast_kinded(target):
        if pressure.generate(engine, actor, "echo_beast_hit"):
            predator_answer(engine, actor, target, ctx)
        return
    if in_scope(ctx.typed.get("source")) and _ally_near(engine, actor, target, 30):
        pressure.generate(engine, actor, "echo_scope_hit")


def predator_answer(engine: Any, actor: Any, target: Any, ctx: Any) -> None:
    """Predator Answer: generating Pack Echo from a beast-aspected hit
    grants temporary HP equal to PB, or a 5-foot move that does not
    provoke the target's opportunity attacks (the player chooses; the
    AI takes the temporary HP)."""
    if not owns(engine, actor, PREDATOR):
        return
    intent = ctx.intent
    choice = needle.ask(engine, intent,
                        needle.checkpoint_id(engine, "BEAST_ECHO_PREDATOR", actor.entity_id),
                        actor, "choice:needle.predator_answer", ["temp_hp", "move"],
                        labels={"temp_hp": f"Gain {int(actor.proficiency_bonus or 2)} temporary Hit Points",
                                "move": "Move 5 feet without provoking an opportunity attack from it"},
                        prompt=("Predator Answer: you generated Pack Echo from hitting a "
                                "beast-aspected creature. Gain temporary Hit Points equal to "
                                "your Proficiency Bonus, or move 5 feet without provoking "
                                "opportunity attacks from it?"),
                        name="Predator Answer", minimum=0, maximum=1, allow_decline=True,
                        preferred=["temp_hp"])
    picked = choice[0] if choice else None
    if picked == "temp_hp":
        engine._grant_temp_hp(actor, int(actor.proficiency_bonus or 2), f"passive:{PREDATOR}", actor.entity_id)
        note(engine, PREDATOR, actor,
             f"{actor.display_name} gains {int(actor.proficiency_bonus or 2)} temporary Hit Points (Predator Answer).")
    elif picked == "move":
        from .granted_moves import choose
        choose(engine, actor, 5, PREDATOR, "Predator Answer", intent=intent,
               ignore_oa_from=(target.entity_id,))


@hook("hit_final")
def pack_marrow_strike(ctx: Any, target: Any, kind: str) -> None:
    """Pack-Marrow Strike: after the fighter, a bonded companion, or an
    ally within 30 ft hits a creature a Fixed Beast-Echo Scope attack
    or technique (or a beast-aspected creature) qualifies, spend 1 Pack
    Echo to add PB damage of the hit's type -- another PB from Refined
    Pack Marrow when the fighter already damaged that target, and
    another PB from Beast-Echo Marrow State once a round for the
    chosen pair."""
    engine = ctx.engine
    hitter = ctx.actor
    if not target.active or not hostile(hitter, target):
        return
    if not (in_scope(ctx.typed.get("source")) or beast_kinded(target)):
        return
    damage_type = _hit_damage_type(engine, hitter, target)
    for owner in engine.state.actors.values():
        if not owner.active or owner.team_id != hitter.team_id:
            continue
        if not owns(engine, owner, STRIKE) or not echo_held(owner):
            continue
        if not ((ctx.hit_snapshots or {}).get("beast_echo_strike") or {}).get(owner.entity_id):
            continue
        if not _pair_near(engine, owner, hitter, 30):
            continue
        intent = ctx.intent if owner.entity_id == hitter.entity_id else getattr(engine, "_active_intent", None)
        bonus = int(owner.proficiency_bonus or 2)
        if _refined_pack_marrow_qualifies(engine, owner, hitter, target):
            bonus += int(owner.proficiency_bonus or 2)
        bonus += _pair_bonus(engine, owner, consume=False)
        choice = needle.ask(engine, intent,
                            needle.checkpoint_id(engine, "BEAST_ECHO_STRIKE", owner.entity_id),
                            owner, "choice:needle.pack_marrow_strike", ["strike"],
                            labels={"strike": "Spend 1 Pack Echo to add damage to the hit"},
                            prompt=("Pack-Marrow Strike: spend 1 Pack Echo to add "
                                    f"{bonus} damage to {hitter.display_name}'s {ctx.action.display_name} hit on {target.display_name}"
                                    + (f" ({damage_type.lower()})" if damage_type and damage_type != "UNTYPED" else "")
                                    + "?"),
                            name="Pack-Marrow Strike", minimum=0, maximum=1, allow_decline=True,
                            preferred=["strike"])
        if not choice:
            continue
        engine._spend_resource(owner, ECHO, 1, f"passive:{STRIKE}")
        bonus = int(owner.proficiency_bonus or 2)
        if _refined_pack_marrow_qualifies(engine, owner, hitter, target):
            bonus += int(owner.proficiency_bonus or 2)
        bonus += _pair_bonus(engine, owner)
        sub = Context(engine, owner, ctx.action, intent, ctx.typed, [target], target, {})
        engine._append_event("PASSIVE_TRIGGERED", f"passive:{STRIKE}", actor_id=owner.entity_id,
                             target_ids=(target.entity_id,), payload={"trigger": "Pack-Marrow Strike"})
        run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": bonus,
                           **({"damage_types": [damage_type.lower()]} if damage_type and damage_type != "UNTYPED" else {}),
                           "evidence": "Pack-Marrow Strike: add damage equal to your Proficiency Bonus."}])
        note(engine, STRIKE, owner, f"{owner.display_name}'s Pack-Marrow Strike adds {bonus} damage to the hit.")


def _pressed_by_owner(engine: Any, owner: Any, target: Any) -> bool:
    """Pack Marrow: the fighter damaged the same target since the start
    of the fighter's last turn."""
    return _damaged_since_last_turn(engine, owner, target, [owner.entity_id])


# Beast-Sense Witness: a d20_rewrite rule for the fighter's own roll,
# and -- with Companion Echo -- a bonded companion's roll.
def _witness_scope(engine: Any, rc: Any) -> bool:
    """Whether a roll is in the Fixed Beast-Echo Scope: its named
    hazards (fear, forced movement, holds), a beast-aspected source, a
    beast-sense skill, or a scope attack or technique."""
    if _hazards(rc.named) & SCOPE_HAZARDS:
        return True
    frame = engine.d20_context() or {}
    source = engine.state.actors.get(frame.get("source_actor_id"))
    if beast_kinded(source):
        return True
    if str(frame.get("skill") or "").strip().lower() in SCOPE_SKILLS:
        return True
    return in_scope(frame.get("source_id"))


def _witness_bonus(engine: Any, holder: Any, rc: Any) -> int:
    """PB, plus the state's another PB when the roll belongs to the
    chosen pair."""
    bonus = int((holder.numbers or {}).get("pb") or 2)
    return bonus + _witness_pair_bonus(engine, holder, rc)


def _witness_pair_bonus(engine: Any, holder: Any, rc: Any) -> int:
    """Pure quote, or the bonus reserved by acceptance for this exact roll."""
    flags = holder.actor.turn_flags
    if flags.get("beast_echo_witness_roll") == str(rc.roll.roll_id):
        return int(flags.get("beast_echo_witness_extra") or 0)
    return _pair_bonus(engine, rc.roller, consume=False)


def _witness_used(engine: Any, holder: Any, rc: Any) -> None:
    """Spend the pair's round bonus only after accepting the Witness."""
    holder.actor.turn_flags["beast_echo_witness_roll"] = str(rc.roll.roll_id)
    holder.actor.turn_flags["beast_echo_witness_extra"] = _pair_bonus(engine, rc.roller)


def _witness_say(engine: Any, holder: Any, rc: Any, roll: Any) -> str:
    companion = rc.roller.entity_id != holder.actor.entity_id
    bonus = (_witness_companion_bonus if companion else _witness_bonus)(engine, holder, rc)
    kind = {"check": "check", "save": "saving throw"}[rc.kind]
    return (f"Beast-Sense Witness{' (Companion Echo)' if companion else ''}: spend 1 Pack Echo "
            f"to add {bonus} to {rc.roller.display_name}'s {kind}.")


def _witness_ai(engine: Any, holder: Any, rc: Any) -> bool:
    return True


register(Rule(
    "beast_sense_witness", "Beast-Sense Witness",
    feature=WITNESS,
    rolls=("check",), who="self", when="any",
    op="bonus", costs=((("pack_echo", 1),),), reaction=False,
    guard=lambda engine, holder, rc: owns(engine, holder.actor, WITNESS) and _witness_scope(engine, rc),
    bonus=_witness_bonus, on_use=_witness_used, say=_witness_say, ai=_witness_ai,
))

register(Rule(
    "beast_sense_witness_save", "Beast-Sense Witness",
    feature=WITNESS, rolls=("save",), who="self", when="any",
    op="choose", costs=((("pack_echo", 1),),), reaction=False,
    guard=lambda engine, holder, rc: owns(engine, holder.actor, WITNESS) and _witness_scope(engine, rc),
    additive_save_bonus=_witness_bonus, on_use=_witness_used, say=_witness_say, ai=_witness_ai,
))


def _witness_companion_guard(engine: Any, holder: Any, rc: Any) -> bool:
    """Companion Echo: the witness spends on a bonded companion's save
    or check in the Fixed Beast-Echo Scope."""
    if not owns(engine, holder.actor, COMPANION) or not _witness_scope(engine, rc):
        return False
    return any(companion.entity_id == rc.roller.entity_id for companion in companions(engine, holder.actor))


def _witness_companion_bonus(engine: Any, holder: Any, rc: Any) -> int:
    """The base PB plus Companion Echo's another PB, plus the state's
    another PB for the chosen pair."""
    return 2 * int((holder.numbers or {}).get("pb") or 2) + _witness_pair_bonus(engine, holder, rc)


def _witness_companion_used(engine: Any, holder: Any, rc: Any) -> None:
    """Mark the companion's save, so Companion Echo's psychic-damage
    reroll can answer it."""
    _witness_used(engine, holder, rc)
    if rc.kind == "save":
        holder.actor.turn_flags[f"beast_echo_witnessed:{rc.roller.entity_id}"] = str(rc.roll.roll_id)


register(Rule(
    "beast_sense_witness_companion", "Beast-Sense Witness (Companion Bond)",
    feature=COMPANION,
    rolls=("check",), who="team", range_ft=30, when="any",
    op="bonus", costs=((("pack_echo", 1),),), reaction=False,
    guard=_witness_companion_guard, bonus=_witness_companion_bonus,
    on_use=_witness_companion_used, say=_witness_say, ai=_witness_ai,
))

register(Rule(
    "beast_sense_witness_companion_save", "Beast-Sense Witness (Companion Bond)",
    feature=COMPANION, rolls=("save",), who="team", range_ft=30, when="any",
    op="choose", costs=((("pack_echo", 1),),), reaction=False,
    guard=_witness_companion_guard, additive_save_bonus=_witness_companion_bonus,
    on_use=_witness_companion_used, say=_witness_say, ai=_witness_ai,
))


def _psychic_reroll_guard(engine: Any, holder: Any, rc: Any) -> bool:
    """Companion Echo: the protected companion's save still failed after
    Beast-Sense Witness, so the fighter may reroll it for psychic damage
    equal to the fighter's cultivation level."""
    if rc.kind != "save":
        return False
    if holder.actor.turn_flags.get(f"beast_echo_witnessed:{rc.roller.entity_id}") != str(rc.roll.roll_id):
        return False
    return bool(rc.dc is not None and rc.total < rc.dc)


def _psychic_reroll_after(engine: Any, holder: Any, rc: Any, roll: Any) -> None:
    """The reroll's cost: psychic damage equal to the fighter's
    cultivation level, which this Foundation cannot reduce."""
    level = int((holder.numbers or {}).get("cl") or 1)
    holder.actor.turn_flags.pop(f"beast_echo_witnessed:{rc.roller.entity_id}", None)
    # A native save need not have a catalog action. Commit the printed self
    # damage through the shared packet seam with this ability's provenance.
    engine._commit_damage(holder.actor, level, "PSYCHIC", COMPANION,
                          holder.actor.entity_id, getattr(engine, "_active_intent", None),
                          reaction_depth=0)
    note(engine, COMPANION, holder.actor,
         f"{holder.actor.display_name} takes {level} psychic damage (Companion Echo) to reroll {rc.roller.display_name}'s save.")


register(Rule(
    "companion_echo_reroll", "Companion Echo (Share the Fall)",
    feature=COMPANION,
    rolls=("save",), who="team", range_ft=30, when="failed",
    op="reroll", costs=(), reaction=False,
    guard=_psychic_reroll_guard, bonus=lambda engine, holder, rc: 0,
    after=_psychic_reroll_after,
    say=lambda engine, holder, rc, roll: ("Companion Echo: take psychic damage equal to your "
                                          "cultivation level to let the companion reroll the failed save."),
    ai=lambda engine, holder, rc: True,
))


@hook("reaction_geometry_allowed")
def marrow_pack_guard_trigger(engine: Any, reactor: Any, source: Any, subject: Any,
                              row: dict[str, Any]) -> bool | None:
    """Marrow Pack Guard's printed trigger: the damage comes from a
    creature the fighter's side damaged since the start of the
    fighter's last turn, or from a beast/predator/natural-weapon/
    blood/fear/pack-aura source."""
    if row.get("feature_id") != GUARD or not owns(engine, reactor, GUARD) or source is None:
        return None
    friends = [reactor.entity_id, *(companion.entity_id for companion in companions(engine, reactor))]
    friends += [creature.entity_id for creature in engine.state.actors.values()
                if creature.active and creature.team_id == reactor.team_id
                and creature.entity_id != reactor.entity_id
                and engine._distance_actor_to_actor(reactor, creature) <= 30]
    if _damaged_since_last_turn(engine, reactor, source, friends) or _scope_source(engine, source):
        return None
    return False


@hook("damage_reduction_bonus")
def marrow_pack_guard_bonus(engine: Any, owner: Any, protected: Any, attacker: Any,
                            reaction_row: dict[str, Any]) -> int | None:
    """Marrow Pack Guard: the reduction is PB + the fighter's
    cultivation ability modifier (the compiled reaction carries the PB;
    this adds the modifier). Companion Echo adds another PB for a bonded
    companion, Beast-Echo Marrow State another once a round for the
    chosen pair, and the bonded companion may move 5 feet without
    provoking the beast-aspected source after the damage resolves."""
    if not reaction_row or str(reaction_row.get("feature_id") or "") != GUARD or protected is None:
        return None
    bonus = key_modifier(engine, owner)
    if owns(engine, owner, COMPANION) and protected in companions(engine, owner):
        bonus += int(owner.proficiency_bonus or 2)
    pair_bonus = _pair_bonus(engine, protected)
    if not pair_bonus:
        pair_bonus = _pair_bonus(engine, owner)
    bonus += pair_bonus
    if protected in companions(engine, owner) and beast_kinded(attacker):
        protected.turn_flags["beast_echo_guard_move"] = attacker.entity_id
    return bonus


@hook("event")
def marrow_pack_guard_move(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Marrow Pack Guard's bonded-companion rider, after the damage
    resolves: the companion may move 5 feet without provoking the
    beast-aspected source's opportunity attacks."""
    if event_type != "DAMAGE_COMMITTED":
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None:
            continue
        source_id = target.turn_flags.pop("beast_echo_guard_move", None)
        if source_id is None:
            continue
        intent = getattr(engine, "_active_intent", None)
        choice = needle.ask(engine, intent,
                            needle.checkpoint_id(engine, "BEAST_ECHO_GUARD_MOVE", target.entity_id),
                            target, "choice:needle.marrow_pack_guard", ["move"],
                            labels={"move": "Move 5 feet without provoking an opportunity attack from the source"},
                            prompt=("Marrow Pack Guard: the damage is from a beast-aspected source. "
                                    "Move 5 feet without provoking an opportunity attack from it?"),
                            name="Marrow Pack Guard", minimum=0, maximum=1, allow_decline=True,
                            preferred=["move"])
        if not choice:
            continue
        from .granted_moves import choose
        choose(engine, target, 5, GUARD, "Marrow Pack Guard", intent=intent,
               ignore_oa_from=(source_id,))


# Beast-Echo Marrow State: the bonus action and its state.
@hook("compile_block")
def compile_beast_echo(block: str, spec: dict[str, Any], row: dict[str, Any],
                       numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Compile this foundation's own ``beast_echo`` rows, so the
    plug-in can find what a fighter owns."""
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "cl": int(numbers.get("cl") or 1),
             "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0),
             **({"keeps_compiling": True} if spec.get("keeps_compiling") else {})}]


@hook("compile_actions")
def compile_state_action(info: dict[str, Any]) -> list[Any] | None:
    """Beast-Echo Marrow State: Bonus Action, 1 Pack Echo + 2 CP, once
    per combat or major scene (once per fight: the engine keeps no rest
    inside a fight; the candidate_allowed gate below names it)."""
    if STATE not in info.get("owned_ids", ()):
        return None
    # A generic CP cost names the character's own CP pool (Core Rules Reference
    # v0_2C, "CP means the character's current Path resource"); the compiler
    # resolves it the same way for its own augment costs, so the same pool id
    # is recorded here rather than the bare "cp" key the engine cannot pay.
    from ..factory_compiler import RESOURCE_IDS
    return [ActionDefinition(
        source_definition_id=STATE_ACTION,
        display_name="Beast-Echo Marrow State",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED",
        target_kind="SELF", costs=((ECHO, 1), (RESOURCE_IDS[info["primary"]], 2)),
        parameters={"typed": {
            "source": STATE,
            "numbers": dict(info.get("numbers") or {}),
            "action_subtype": "technique",
            "effects": [{"type": "beast_echo_marrow_state", "applies_to": "self",
                         "evidence": "Beast-Echo Marrow State"}],
        }, "description": "Spend 1 Pack Echo and 2 CP (your Path resource) as a Bonus Action, once per combat. Choose an ally or bonded companion within 60 feet to share Beast-Echo Marrow State for 1 minute: resist beast fear and forced movement, improve the pair's Echo effects once per round, and move after compatible CP techniques."},
    )]


@hook("candidate_allowed")
def state_once_per_fight(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The state's printed "once per combat or major scene": once per
    fight, named before any payment."""
    if getattr(action, "source_definition_id", None) != STATE_ACTION:
        return None
    if actor.turn_flags.get(STATE_USED):
        return False
    return None


@effect("beast_echo_marrow_state")
def beast_echo_marrow_state(ctx: Any, eff: dict[str, Any]) -> None:
    """Enter the state: the fighter and one bonded companion or ally
    within 60 ft are the chosen pair for 1 minute."""
    engine, actor = ctx.engine, ctx.actor
    numbers = ctx.numbers or {}
    intent = ctx.intent
    options = [companion.entity_id for companion in companions(engine, actor)
               if engine._distance_actor_to_actor(actor, companion) <= 60]
    options += [creature.entity_id for creature in engine.state.actors.values()
                if creature.active and creature.team_id == actor.team_id
                and creature.entity_id != actor.entity_id
                and creature.entity_id not in options
                and engine._distance_actor_to_actor(actor, creature) <= 60]
    if not options:
        ctx.rider("Beast-Echo Marrow State: no bonded companion or ally within 60 ft to choose.")
        return
    labels = {entity_id: engine.state.actors[entity_id].display_name for entity_id in options}
    choice = needle.ask(engine, intent,
                        needle.checkpoint_id(engine, "BEAST_ECHO_STATE_PAIR", actor.entity_id),
                        actor, "choice:needle.beast_echo_marrow_state", options,
                        labels=labels,
                        prompt=("Beast-Echo Marrow State: choose one bonded companion or ally "
                                "within 60 feet to share the state with you."),
                        name="Beast-Echo Marrow State", minimum=1, maximum=1,
                        preferred=[min(options, key=lambda entity_id: engine._distance_actor_to_actor(
                            actor, engine.state.actors[entity_id]))])
    if not choice:
        return
    member = engine.state.actors[choice[0]]
    for creature in (actor, member):
        engine._apply_condition(creature, STATE_CONDITION, f"passive:{STATE}", actor.entity_id,
                                expires_on=clock_expiry(engine, "minutes", 1),
                                data={"holder": actor.entity_id,
                                      "member": member.entity_id,
                                      "cl": int(numbers.get("cl") or 1),
                                      "label": "Beast-Echo Marrow State"})
    actor.turn_flags[STATE_USED] = 1
    note(engine, STATE, actor,
         f"{actor.display_name} enters Beast-Echo Marrow State with {member.display_name} for 1 minute: "
         f"Advantage on saves against fear, intimidation, domination, predator aura and forced movement "
         f"from beast-aspected sources, another +Proficiency Bonus once a round on Pack-Marrow Strike, "
         f"Marrow Pack Guard or Beast-Sense Witness used by or for the pair, a 5-foot move after the "
         f"pair spends CP on a compatible technique, and temporary Hit Points equal to the cultivation "
         f"level for reducing a beast-aspected creature to 0 Hit Points.")


def _pair(engine: Any, creature: Any) -> tuple[str, str] | None:
    """The chosen pair (holder, member) a creature belongs to, while
    its state is active."""
    for instance in (creature.conditions or {}).values():
        if instance.condition_id != STATE_CONDITION:
            continue
        data = instance.data or {}
        holder = engine.state.actors.get(data.get("holder") or "")
        member = engine.state.actors.get(data.get("member") or "")
        if holder is not None and holder.active and member is not None and member.active:
            return holder.entity_id, member.entity_id
    return None


def _state_level(engine: Any, creature: Any) -> int:
    for instance in (creature.conditions or {}).values():
        if instance.condition_id == STATE_CONDITION:
            return int((instance.data or {}).get("cl") or 1)
    return 1


@hook("save_mode")
def state_save_mode(engine: Any, subject: Any, ability: str, dc: Any, source_id: str, rc: Any) -> str | None:
    """The state's Advantage on saves against fear, intimidation,
    domination, predator aura and forced movement from beast-aspected
    sources."""
    if _pair(engine, subject) is None:
        return None
    if _hazards((rc or {}).get("named")) & FEAR_PRESSURE:
        source = engine.state.actors.get((rc or {}).get("source_actor_id"))
        if beast_kinded(source):
            return "ADVANTAGE"
    return None


@hook("ability_check_hazards")
def state_check_mode(engine: Any, actor: Any, ability: str, skill: Any, hazards: Any) -> str | None:
    """The state's Advantage on the matching ability checks."""
    if _pair(engine, actor) is None:
        return None
    if _hazards(hazards) & FEAR_PRESSURE:
        frame = engine.d20_context() or {}
        source = engine.state.actors.get(frame.get("source_actor_id"))
        if beast_kinded(source):
            return "ADVANTAGE"
    return None


def _pair_bonus(engine: Any, creature: Any, *, consume: bool = True) -> int:
    """The state's once-per-round another +PB, spent by or for the
    chosen pair: the Proficiency Bonus while the pair's round budget is
    unspent, then 0 and the budget spent (the flag holds the round, so
    a new round spends it again)."""
    pair = _pair(engine, creature)
    if pair is None:
        return 0
    holder = engine.state.actors.get(pair[0])
    if holder is None or holder.turn_flags.get(PAIR_BUDGET) == engine.state.round_number:
        return 0
    if consume:
        holder.turn_flags[PAIR_BUDGET] = engine.state.round_number
    return int((holder.proficiency_bonus if holder is not None else 0) or 2)


@hook("technique_used")
def state_technique_move(ctx: Any) -> None:
    """The state's once-per-turn move: after either chosen creature
    spends CP on a compatible technique, one chosen creature may move
    5 feet without provoking opportunity attacks."""
    engine, actor = ctx.engine, ctx.actor
    if _pair(engine, actor) is None:
        return
    if not any(str(cost[0]) in CP_POOLS and int(cost[1]) > 0
               for cost in (getattr(ctx.action, "costs", ()) or ())):
        return
    if not in_scope(ctx.typed.get("source")):
        return
    if actor.turn_flags.get("beast_echo_state_move"):
        return
    pair = _pair(engine, actor)
    holder = engine.state.actors.get(pair[0])
    member = engine.state.actors.get(pair[1])
    intent = getattr(engine, "_active_intent", None)
    options = [creature.entity_id for creature in (holder, member) if creature is not None and creature.active]
    labels = {entity_id: engine.state.actors[entity_id].display_name for entity_id in options}
    choice = needle.ask(engine, intent,
                        needle.checkpoint_id(engine, "BEAST_ECHO_STATE_MOVE", actor.entity_id),
                        actor, "choice:needle.beast_echo_state_move", options,
                        labels=labels,
                        prompt=("Beast-Echo Marrow State: the chosen creature spent CP on a "
                                "compatible technique. Which chosen creature moves 5 feet "
                                "without provoking opportunity attacks?"),
                        name="Beast-Echo Marrow State", minimum=0, maximum=1, allow_decline=True,
                        preferred=[actor.entity_id])
    actor.turn_flags["beast_echo_state_move"] = 1
    if not choice:
        return
    mover = engine.state.actors.get(choice[0])
    if mover is None or not mover.active:
        return
    from .granted_moves import choose
    choose(engine, mover, 5, STATE, "Beast-Echo Marrow State", intent=intent, provokes=False)


@hook("fresh_zero_hp")
def state_beast_defeated(engine: Any, defeated: Any, attacker_id: str, source_id: str) -> None:
    """The state's beast-kill benefit: a chosen creature reducing a
    hostile beast-aspected creature to 0 Hit Points grants the fighter
    temporary Hit Points equal to the cultivation level (the printed
    alternative, removing one Beast-Echo Surge progress, is a
    Foundation-scene escalation no engine state represents)."""
    if defeated is None or not beast_kinded(defeated):
        return
    reducer = engine.state.actors.get(attacker_id)
    for creature in (reducer,) if reducer is not None else ():
        if not creature.active or not hostile(creature, defeated):
            continue
        if _pair(engine, creature) is None:
            continue
        level = _state_level(engine, creature)
        engine._grant_temp_hp(creature, level, f"passive:{STATE}", creature.entity_id)
        note(engine, STATE, creature,
             f"{creature.display_name} reduced {defeated.display_name} to 0 Hit Points: Beast-Echo "
             f"Marrow State grants {level} temporary Hit Points.")
        return
