"""Shield lines that were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Sphere Compendium, Shield
(owner's text: authority/typed_mechanics/rules_text.json; the Deflect rules: "choose one Deflect talent after determining whether the
triggering attack hits or misses; apply no more than one Deflect talent to one use of Active Defense").  Active Defense itself is the
compiled reaction (+2 AC against the attack, SHIELD_BASE_ACTIVE_DEFENSE; Cover Ally's is its ally form); combat/ext/redirect_reactions.py
plays Redirecting Shield.  Rows: feature block "lane9_shield" (combat/rules/feature_blocks.d/riders_lane9.json).

  Smashing Counter        (Deflect) a missed attack Active Defense answered, attacker adjacent: the 2024 Shove (Strength or Dexterity
                          save against 8 + STR + PB; push 5 feet or Prone).  Heaven-Rebuking Bash then adds one: 15 more feet of push (30
                          at CL 17), 2d8 + STR Bludgeoning (4d8 at CL 17), Prone after the push, or a 15-foot step without Opportunity
                          Attacks staying adjacent.
  Rain-on-the-Lotus       (Deflect) a ranged weapon attack Active Defense made miss: send the projectile back -- d20 + DEX + PB against
                          the attacker's AC, the projectile's damage dice + DEX (catching it or letting it fall changes nothing here).
  Punch Block             Active Defense answering a hit: an Unarmed Strike attack roll replaces your AC for that attack, even if lower.
  Sacrificial Shield      (Deflect) a critical hit Active Defense answered becomes a normal hit (its extra dice come off); the Shield breaks:
                          -2 AC (its Shield Bonus) for the rest of the fight.
  Greater Deflect         Martial Focus lets a second, different Deflect apply to the same Active Defense.
  Blockade                Active Defense against a Dexterity save for half damage: + Shield Bonus (2) to the save, and a success takes no
                          damage (the Reaction is spent; the player is asked).
  Reactive Defense        after the Dodge action with a Shield, one melee attack as a Reaction against a creature that misses you before
                          the start of your next turn, once per Dodge.
  Extensive Defense       a free action (Martial Focus): until the start of your next turn every attack against you (and, with Cover Ally,
                          allies within 5 feet) meets Active Defense's +2 AC without a Reaction.
  Shield of the Second    when Active Defense makes an attack miss, the next attack against that creature before the start of your next
  Answer                  turn meets the +2 AC without a Reaction (once a round).
  Mountain-Rooted Rim     a creature Active Defense (or Blockade) protected: forced movement on it is 10 feet shorter until the start of your
                          next turn (hook "forced_distance", typed_reactions.on_forced_movement), and it has Advantage on a save against Prone
                          from the triggering attack or effect.

Shared helpers other Shield plug-ins read (never an underscore-prefixed name):
``defender_of(engine, attacker, target)`` -- who answered this attack roll with Active Defense, the fighter itself or a
Cover Ally shield-bearer, which is how combat/ext/shield_incarnation.py knows the Incarnation's own reduction and Focus
recovery apply; ``caused_miss(engine, attacker, target)`` -- whether Active Defense is what turned the attack aside, the
same consumer's "regain Martial Focus whenever a hostile attack misses because of your Active Defense".
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "lane9_shield"
AD = "SHIELD_BASE_ACTIVE_DEFENSE"
COVER = "TAL_SHIELD_COVER_ALLY"
FOCUS = "resource:core.martial_focus"
BROKEN = "condition:typed.shield_broken"
EXTENSIVE = "condition:typed.extensive_defense"
ECHO = "condition:typed.second_answer"
RIM = "condition:typed.rooted_rim"
DODGED = "shield_reactive_dodge"


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
             "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _mods(engine: Any, actor: Any) -> dict[str, int]:
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == actor.entity_id:
            for row in bundle.get("typed_reactions") or []:
                if isinstance(row.get("ability_mods"), dict):
                    return {k: int(v) for k, v in row["ability_mods"].items()}
    return {}


def defender_of(engine: Any, attacker: Any, target: Any) -> Any:
    """Who answered this attack with Active Defense (the target or its Cover Ally), including non-reaction forms."""
    from ..attack_outcomes import attempt_end

    roll = _last_roll(engine, attacker, target)
    if roll is not None:
        start = roll.sequence - 1
        end = attempt_end(engine, attacker.entity_id, start)
        # Post-roll Active Defense is attributable only to this roll. A prior
        # swing's window is before this interval and cannot defend this attack.
        if any(event.event_type == "REACTION_WINDOW_OPENED" and event.source_definition_id == AD
               and event.actor_id == target.entity_id and attacker.entity_id in (event.target_ids or ())
               for event in engine.events[start:end]):
            return target

        # Cover Ally is declared before the roll, so retain its pre-roll window
        # while bounding it by the attacker's previous roll/intent.
        for event in reversed(engine.events[:start]):
            if event.event_type == "ATTACK_ROLLED" and event.actor_id == attacker.entity_id:
                break
            if event.event_type == "INTENT_ACCEPTED" and event.actor_id == attacker.entity_id:
                break
            if (event.event_type == "REACTION_WINDOW_OPENED" and event.source_definition_id == COVER
                    and attacker.entity_id in (event.target_ids or ())
                    and target.entity_id in (event.target_ids or ())):
                return engine.state.actors.get(event.actor_id or "")
    held = {c.condition_id: c for c in target.conditions.values()}
    if EXTENSIVE in held:
        return target
    if ECHO in held:
        return engine.state.actors.get(held[ECHO].source_actor_id) or target
    return _extensive_cover(engine, target)


def _extensive_cover(engine: Any, target: Any) -> Any:
    """An ally with Extensive Defense and Cover Ally within 5 feet: "apply this benefit to yourself and allies within your natural reach"."""
    return next((ally for ally in engine.state.actors.values() if ally.active and ally is not target and ally.team_id == target.team_id
                 and any(c.condition_id == EXTENSIVE for c in ally.conditions.values()) and rows(engine, ally, "cover_ally")
                 and engine._distance_actor_to_actor(ally, target) <= 5), None)


def caused_miss(engine: Any, attacker: Any, target: Any) -> bool:
    """Shared: whether "When Active Defense causes an attack to miss" is true for this roll.

    combat/ext/shield_incarnation.py asks the same question for the Incarnation's "regain Martial Focus whenever a
    hostile attack misses because of your Active Defense, once per round".

    The roll hit before an answer turned it (Punch Block), or it would have hit without
    Active Defense's +2.
    """
    roll = _last_roll(engine, attacker, target)
    if roll is None:
        return False
    payload = roll.payload or {}
    # A forced miss (before_attack answer) misses whatever the roll and AC were: Active Defense did not turn it aside.
    # The optional after-roll window stays legal; only its numerical causality (and the benefits keyed to it) is withheld.
    from ..attack_outcomes import attempt_end
    index = roll.sequence - 1
    if any(e.event_type == 'ATTACK_FORCED_MISS' and (e.payload or {}).get('roll_id') == payload.get('roll_id')
           for e in engine.events[index + 1:attempt_end(engine, attacker.entity_id, index)]):
        return False
    # Late window: Active Defense answered after the roll. Scan from the roll to the present, however long the log has
    # grown since, and take the bonus from the AC the roll was really measured against (the recorded outcome), not a constant.
    late = any(e.event_type == 'REACTION_WINDOW_OPENED' and e.source_definition_id == AD
               and e.actor_id == target.entity_id and attacker.entity_id in e.target_ids
               for e in engine.events[roll.sequence:])
    if late:
        from ..attack_outcomes import attack_outcome
        # Event sequence n sits at index n-1 (engine.events invariant), so the roll's own index is sequence - 1.
        receipt = attack_outcome(engine, attacker.entity_id, roll.sequence - 1)
        if receipt is None:
            return False  # no defence raised the AC for this roll
        natural = int(payload.get('natural_result') or 0)
        total = int(payload.get('modified_total', payload.get('total', 0)))
        baseline = int(payload.get('target_ac') or 0)
        bonus = int(receipt['armor_class']) - baseline
        return bonus > 0 and natural not in (1, 20) and baseline <= total < baseline + bonus
    if payload.get("provisional_hit"):
        return True
    natural = int(payload.get("natural_result") or 0)
    return natural != 1 and int(payload.get("modified_total") or 0) >= int(payload.get("target_ac") or 0) - 2


def _deflect_ok(engine: Any, defender: Any, attacker: Any, name: str) -> bool:
    """One Deflect a use of Active Defense; Greater Deflect's Martial Focus lets a second, different one apply (counted per attack roll)."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_shield_deflects")
    # The attack's own roll, however long ago it was: no fixed tail, or a long fight shares one stamp (0) across attacks.
    stamp = next((e.sequence for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker.entity_id), 0)
    used = engine.__dict__.setdefault("_shield_deflects", {})
    names = used.get((defender.entity_id, stamp), [])
    if not names:
        used[(defender.entity_id, stamp)] = [name]
        return True
    if name in names or len(names) >= 2 or not rows(engine, defender, "greater_deflect") or defender.resources.get(FOCUS, 0) < 1:
        return False
    engine._spend_resource(defender, FOCUS, 1, "TAL_SHIELD_GREATER_DEFLECT")
    used[(defender.entity_id, stamp)] = [*names, name]
    return True


def _last_roll(engine: Any, attacker: Any, target: Any) -> Any:
    return next((e for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker.entity_id
                 and target.entity_id in (e.target_ids or ())), None)


def _ctx(engine: Any, actor: Any, other: Any, feature: str, name: str) -> Any:
    from .. import typed_reactions

    return typed_reactions._generic_context(engine, actor, other, {"feature_id": feature, "name": name, "effects": [], "numbers": {}})


# ------------------------------------------------------------------------------------------------ after a miss
@hook("after_miss")
def deflect_on_miss(ctx: Any, target: Any) -> None:
    engine, attacker = ctx.engine, ctx.actor
    defender = defender_of(engine, attacker, target)
    if defender is None or not defender.active:
        return
    _rim(engine, defender, target, attacker)
    if caused_miss(engine, attacker, target):
        _second_answer(engine, defender, target)
    if rows(engine, defender, "smashing_counter") and engine._distance_actor_to_actor(defender, attacker) <= 5 and _deflect_ok(engine, defender, attacker, "smashing"):
        _smashing_counter(ctx, defender, attacker)
    ranged = ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5 and ctx.typed.get("weapon") is not None
    if ranged and rows(engine, defender, "rain_lotus") and _deflect_ok(engine, defender, attacker, "rain"):
        _rain_back(ctx, defender, attacker)


def _smashing_counter(ctx: Any, defender: Any, attacker: Any) -> None:
    from ..typed_executor import run_effects

    engine = ctx.engine
    mods = _mods(engine, defender)
    pb = int(rows(engine, defender, "smashing_counter")[0]["pb"])
    dc = 8 + mods.get("STR", 0) + pb
    options = {"prone": "Smashing Counter: shove it Prone", "push": "Smashing Counter: shove it 5 feet away"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "SMASHING_COUNTER", defender.entity_id, attacker.entity_id), defender, CHOICE + "smashing_counter",
                 list(options), labels=options, preferred=["prone"], allow_decline=True, target_id=attacker.entity_id,
                 prompt=f"{attacker.display_name}'s attack misses: Smashing Counter?")
    if not picked:
        return
    ability = max(("STR", "DEX"), key=lambda name: int(attacker.saving_throws.get(name, 0)))
    roll = engine._roll_save(attacker, ability, dc, "tianxia.talent.shield.smashing_counter")
    if roll is None or int(roll.total) >= dc:
        note(engine, "tianxia.talent.shield.smashing_counter", defender, f"Smashing Counter: {attacker.display_name} keeps its footing.")
        return
    sub = _ctx(engine, defender, attacker, "tianxia.talent.shield.smashing_counter", "Smashing Counter")
    run_effects(sub, [{"type": "condition", "condition": "prone", "applies_to": "target"}] if picked[0] == "prone"
                else [{"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target"}])
    if rows(engine, defender, "heaven_rebuking"):
        _heaven_rebuking(ctx, defender, attacker, mods, picked[0])


def _heaven_rebuking(ctx: Any, defender: Any, attacker: Any, mods: dict[str, int], shove: str) -> None:
    from ..typed_executor import run_effects

    engine = ctx.engine
    cl = int(rows(engine, defender, "heaven_rebuking")[0]["cl"])
    push, dice = (30, 4) if cl >= 17 else (15, 2)
    options = {"push": f"Heaven-Rebuking Bash: push it {push} more feet", "damage": f"Heaven-Rebuking Bash: {dice}d8 + Strength Bludgeoning",
               "step": "Heaven-Rebuking Bash: move up to 15 feet (no Opportunity Attacks) staying beside it"}
    if shove == "push":
        options["prone"] = "Heaven-Rebuking Bash: it falls Prone after the push"
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "HEAVEN_REBUKING", defender.entity_id, attacker.entity_id), defender, CHOICE + "heaven_rebuking",
                 list(options), labels=options, preferred=["damage"], target_id=attacker.entity_id, prompt="Heaven-Rebuking Bash: one more effect")
    choice = picked[0] if picked else "damage"
    sub = _ctx(engine, defender, attacker, "TAL_SHIELD_HEAVEN_REBUKING_BASH", "Heaven-Rebuking Bash")
    if choice == "push":
        run_effects(sub, [{"type": "forced_movement", "distance_ft": push, "direction": "away", "applies_to": "target"}])
    elif choice == "damage":
        run_effects(sub, [{"type": "damage", "dice": {"count": dice, "sides": 8}, "flat": mods.get("STR", 0), "formula": "none", "damage_types": ["bludgeoning"],
                           "applies_to": "target", "evidence": f"{dice}d8 + your Strength modifier"}])
    elif choice == "prone":
        run_effects(sub, [{"type": "condition", "condition": "prone", "applies_to": "target"}])
    else:
        run_effects(sub, [{"type": "reaction_move", "direction": "toward", "distance_ft": 15, "no_opportunity_attacks": True}])


def _rain_back(ctx: Any, defender: Any, attacker: Any) -> None:
    from ..gate2_runtime_models import DiceSpec

    engine = ctx.engine
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "RAIN_LOTUS", defender.entity_id, attacker.entity_id), defender, CHOICE + "rain_lotus", ["back"],
                 labels={"back": "Rain-on-the-Lotus Deflection: send the projectile back"}, allow_decline=True, target_id=attacker.entity_id,
                 prompt="Rain-on-the-Lotus Deflection: send the missed projectile back?")
    if not picked:
        return
    mods = _mods(engine, defender)
    pb = int(rows(engine, defender, "rain_lotus")[0]["pb"])
    roll = engine.roller.d20(
        modifier=mods.get('DEX', 0) + pb,
        actor_id=defender.entity_id,
        reason='ATTACK:TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION',
        mode=engine.direct_attack_mode(defender, attacker),
    )
    engine._record_roll(roll)
    ac = attacker.armor_class + engine._ac_modifier(attacker)
    natural = int(roll.natural_result or 0)
    hit = natural != 1 and (natural == 20 or int(roll.total) >= ac)
    engine._append_event("ATTACK_ROLLED", "TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION", actor_id=defender.entity_id, target_ids=(attacker.entity_id,),
                         payload={**roll.model_dump(mode="json"), "modified_total": int(roll.total), "target_ac": ac, "cover_bonus": 0, "provisional_hit": hit})
    if not hit:
        return
    damage = (ctx.typed.get("weapon") or {}).get("damage") or {}
    kind = str((ctx.typed.get("weapon") or {}).get("damage_type") or "PIERCING").upper()
    rolled = engine.roller.roll(DiceSpec(count=int(damage.get("count") or 1), sides=int(damage.get("sides") or 4), modifier=mods.get("DEX", 0)),
                                actor_id=defender.entity_id, reason="DAMAGE:TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION", critical=natural == 20)
    engine._record_roll(rolled)
    engine._commit_damage(attacker, max(0, int(rolled.total)), kind, "TAL_SHIELD_RAIN_ON_THE_LOTUS_DEFLECTION", defender.entity_id, None, reaction_depth=1)


# ------------------------------------------------------------------------------------------------ answering a hit
@hook("hit_response")
def deflect_on_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> Any:
    defender = defender_of(engine, attacker, target)
    if defender is None or not defender.active:
        return None
    _rim(engine, defender, target, attacker)
    if defender is target and rows(engine, defender, "punch_block") and not engine.__dict__.get("_shield_punch_done"):
        picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "PUNCH_BLOCK", defender.entity_id, attacker.entity_id), defender,
                     CHOICE + "punch_block", ["punch"], labels={"punch": "Punch Block: an Unarmed Strike roll replaces your AC for this attack"},
                     allow_decline=True, target_id=attacker.entity_id, prompt=f"{attacker.display_name}'s attack ({total}) hits: Punch Block?", default="decline")
        if picked:
            mods = _mods(engine, defender)
            roll = engine.roller.d20(
                modifier=mods.get('STR', 0) + int(rows(engine, defender, 'punch_block')[0]['pb']),
                actor_id=defender.entity_id,
                reason='ATTACK:TAL_SHIELD_PUNCH_BLOCK',
                mode=engine.direct_attack_mode(defender, attacker),
            )
            engine._record_roll(roll)
            new_ac = int(roll.total)
            note(engine, "TAL_SHIELD_PUNCH_BLOCK", defender, f"Punch Block: {defender.display_name}'s Unarmed Strike roll ({new_ac}) is its AC against {total}.")
            if natural != 20 and total < new_ac:
                return new_ac, False
    return None


@hook("incoming_damage")
def sacrificial_shield(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    from .lane4_crit import critical_extra

    attacker = engine.state.actors.get(source_actor_id or "")
    if attacker is None or amount <= 0 or not rows(engine, target, "sacrificial") or any(c.condition_id == BROKEN for c in target.conditions.values()):
        return None
    if defender_of(engine, attacker, target) is not target:
        return None
    extra = min(critical_extra(engine, target.entity_id, source_actor_id), int(amount))
    if extra <= 0 or not _deflect_ok(engine, target, attacker, "sacrificial"):
        return None
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "SACRIFICIAL", target.entity_id, attacker.entity_id), target,
                 CHOICE + "sacrificial_shield", ["break"], labels={"break": "Sacrificial Shield: break your Shield; the Critical Hit becomes a normal hit"},
                 allow_decline=True, target_id=target.entity_id, prompt="A Critical Hit: break your Shield to make it a normal hit?")
    if not picked:
        return None
    from .shield_uncbroken import owning
    from .shield_incarnation import available

    if owning(engine, target) is not None or available(engine, target):
        from ..typed_reactions import triggered_context
        from ..typed_executor import run_effects

        ctx = triggered_context(engine, target, target, rows(engine, target, 'sacrificial')[0],
                                getattr(engine, '_active_intent', None))
        run_effects(ctx, [{'type': 'condition', 'condition': 'shield_broken',
                          'applies_to': 'self', 'duration': 'until_removed'}])
        result = 'the Shield breaks' if any(c.condition_id == BROKEN for c in target.conditions.values()) else 'a rescue keeps the Shield'
    else:
        # Keep the original event bytes for saved fighters without these rescue rows.
        engine._apply_condition(target, BROKEN, "tianxia.talent.shield.sacrificial_shield", target.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Shield broken: no Shield Bonus (-2 AC)"})
        result = 'the Shield breaks'
    note(engine, "tianxia.talent.shield.sacrificial_shield", target, f"Sacrificial Shield: {result}; {extra} critical damage is not taken.")
    return extra


@hook("ac")
def shield_ac(engine: Any, target: Any) -> int | None:
    # Inventory-marked shields lose their bonus through shield_possession;
    # legacy/unmarked fighters retain this rider's historical -2 penalty.
    held = {c.condition_id for c in target.conditions.values()}
    total = 0
    if BROKEN in held:
        from .. import armour

        # Marked shields are handled by shield_possession. Historical and
        # hand-built fighters keep the original broken-shield subtraction.
        if armour.shield_item_key(engine, target) is None:
            total -= 2
    if EXTENSIVE in held or ECHO in held:
        total += 2
    elif any(EXTENSIVE in {c.condition_id for c in ally.conditions.values()} and ally.team_id == target.team_id and ally is not target
             and rows(engine, ally, "cover_ally") and engine._distance_actor_to_actor(ally, target) <= 5 for ally in engine.state.actors.values() if ally.active):
        total += 2  # Extensive Defense with Cover Ally: "apply this benefit to ... allies within your natural reach"
    return total or None


# ------------------------------------------------------------------------------------------------ Blockade
@hook("save")
def blockade_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    from .. import typed_reactions

    if str(ability).upper()[:3] != "DEX" or not rows(ctx.engine, subject, "blockade") or subject is ctx.actor:
        return None
    halves = any(isinstance(row, dict) and row.get("type") == "half_damage" for row in _walk(ctx.typed.get("effects")))
    if not halves or not typed_reactions._can_react(ctx.engine, subject):
        return None
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "BLOCKADE", subject.entity_id), subject, CHOICE + "blockade", ["use"],
                 labels={"use": "Blockade (Reaction): + Shield Bonus to the save; a success takes no damage"}, allow_decline=True,
                 target_id=subject.entity_id, prompt=f"{ctx.action.display_name}: a Dexterity save for half damage. Blockade?")
    if not picked:
        return None
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(ctx.engine, subject, "TAL_SHIELD_BLOCKADE", independent=True):
        subject.reaction_available = False
        ctx.engine._append_event("REACTION_WINDOW_OPENED", "TAL_SHIELD_BLOCKADE", actor_id=subject.entity_id, target_ids=(ctx.actor.entity_id,),
                                 payload={"checkpoint": "DEX_SAVE"})
        ctx.damage_cache[f"blockade:{subject.entity_id}"] = "pending"
        _rim(ctx.engine, subject, subject, ctx.actor)
        return {"bonus": 2}


def _walk(effects: Any):
    from ..typed_executor import _walk_rows

    return _walk_rows(effects)


@hook("after_save")
def blockade_result(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_shield_blockade")
    key = f"blockade:{subject.entity_id}"
    if ctx.damage_cache.get(key) == "pending":
        ctx.damage_cache[key] = "failed" if failed else "success"
        if not failed:
            ctx.engine.__dict__.setdefault("_shield_blockade", set()).add((ctx.source, subject.entity_id))


@hook("damage_pending")
def blockade_damage(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    blocked = engine.__dict__.get("_shield_blockade") or set()
    if (source_definition_id, target.entity_id) in blocked:
        return 0  # "a successful saving throw causes you to take no damage from the effect"
    return None


@hook("technique_used")
def blockade_done(ctx: Any) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_shield_blockade")
    blocked = ctx.engine.__dict__.get("_shield_blockade")
    if blocked:
        ctx.engine.__dict__["_shield_blockade"] = {pair for pair in blocked if pair[0] != ctx.source}


# ------------------------------------------------------------------------------------------------ Reactive Defense, Second Answer, Rim
@hook("event")
def reactive_dodge(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Taking the Dodge action (the engine's own Dodge condition lands on the fighter) arms Reactive Defense until it is used."""
    if event_type != "CONDITION_APPLIED" or str((kwargs.get("payload") or {}).get("condition_id") or "") != "condition:core.dodge":
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is not None and rows(engine, actor, "reactive_defense"):
            actor.turn_flags[f"{DODGED}_round_armed"] = True


@hook("after_miss")
def reactive_counter(ctx: Any, target: Any) -> None:
    from .. import typed_reactions
    from ..typed_executor import run_effects

    engine, attacker = ctx.engine, ctx.actor
    marker = target.turn_flags.get(f"{DODGED}_round_armed")
    dodging = any(c.condition_id == "condition:core.dodge" for c in target.conditions.values())
    if not marker or not dodging or not rows(engine, target, "reactive_defense") or not typed_reactions._can_react(engine, target):
        return
    if engine._distance_actor_to_actor(target, attacker) > 5:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "REACTIVE_DEFENSE", target.entity_id, attacker.entity_id), target, CHOICE + "reactive_defense",
                 ["strike"], labels={"strike": f"Reactive Defense: strike back at {attacker.display_name}"}, allow_decline=True,
                 target_id=attacker.entity_id, prompt=f"{attacker.display_name} misses you: Reactive Defense?")
    if not picked:
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, target, "TAL_SHIELD_REACTIVE_DEFENSE", independent=True):
        target.turn_flags.pop(f"{DODGED}_round_armed", None)  # "only once per use of Dodge"
        target.reaction_available = False
        row = {"feature_id": "TAL_SHIELD_REACTIVE_DEFENSE", "name": "Reactive Defense", "numbers": {},
               "effects": [{"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": []}]}
        run_effects(typed_reactions._generic_context(engine, target, attacker, row), row["effects"])


@hook("row_allowed")
def quiet_rows(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    feature = str(row.get("feature_id") or "")
    if feature == "TAL_SHIELD_REACTIVE_DEFENSE" and rows(engine, actor, "reactive_defense"):
        return False  # the compiled row attacked as the Dodge was taken; the counter above answers a miss
    if feature == AD and any(c.condition_id in (EXTENSIVE, ECHO) for c in actor.conditions.values()):
        return False  # Extensive Defense (or the echo) already gives the attack the +2
    return None


@effect("shield_extensive")
def shield_extensive(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._apply_condition(ctx.actor, EXTENSIVE, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Extensive Defense: Active Defense against every attack without a Reaction"})
    ctx.rider("Extensive Defense: until the start of your next turn every attack against you meets Active Defense's +2 AC.")


def _second_answer(engine: Any, defender: Any, protected: Any) -> None:
    if not rows(engine, defender, "second_answer") or defender.turn_flags.get("shield_round_second") == engine.state.round_number:
        return
    defender.turn_flags["shield_round_second"] = engine.state.round_number
    engine._apply_condition(protected, ECHO, "TAL_SHIELD_SHIELD_OF_THE_SECOND_ANSWER", defender.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": "Shield of the Second Answer: the next attack meets Active Defense's +2 AC"})


@hook("after_hit")
def echo_spent_hit(ctx: Any, target: Any, kind: str) -> None:
    _spend_echo(ctx.engine, target)


@hook("after_miss")
def echo_spent_miss(ctx: Any, target: Any) -> None:
    if not _echoed_by_this_attack(ctx.engine, ctx.actor, target):
        _spend_echo(ctx.engine, target)


def _echoed_by_this_attack(engine: Any, attacker: Any, target: Any) -> bool:
    """The echo was left by this very miss (deflect_on_miss runs first), not by an earlier attack: it is not spent on the attack that made it."""
    from .retained_updates import is_retained_update

    for event in reversed(engine.events[-40:]):
        if is_retained_update(event.event_type, event.payload or {}):
            continue
        if event.event_type == "ATTACK_ROLLED" and event.actor_id == attacker.entity_id:
            return False
        if event.event_type == "CONDITION_APPLIED" and (event.payload or {}).get("condition_id") == ECHO and target.entity_id in (event.target_ids or ()):
            return True
    return False


def _spend_echo(engine: Any, target: Any) -> None:
    if any(c.condition_id == ECHO for c in target.conditions.values()):
        engine._remove_condition(target, ECHO, "TAL_SHIELD_SHIELD_OF_THE_SECOND_ANSWER")


def _intent_seq(engine: Any, actor: Any) -> int:
    return next((e.sequence for e in reversed(engine.events[-200:]) if e.event_type == "INTENT_ACCEPTED" and e.actor_id == actor.entity_id), -1)


def _rim(engine: Any, defender: Any, protected: Any, attacker: Any) -> None:
    """Mountain-Rooted Rim: forced movement on the protected creature is 10 feet shorter until the start of your next turn (rim_cut), and it has
    Advantage on a save against Prone from the triggering attack or effect (the attacker's same action: rim_save)."""
    if not rows(engine, defender, "mountain_rim"):
        return
    if any(c.condition_id == RIM for c in protected.conditions.values()):
        engine._remove_condition(protected, RIM, "TAL_SHIELD_MOUNTAIN_ROOTED_RIM")
    engine._apply_condition(protected, RIM, "TAL_SHIELD_MOUNTAIN_ROOTED_RIM", defender.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": "Mountain-Rooted Rim: forced movement 10 feet shorter", "attacker": attacker.entity_id,
                                  "intent": _intent_seq(engine, attacker)})


@hook("save")
def rim_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if "prone" not in {str(name).lower() for name in named or ()}:
        return None
    for held in subject.conditions.values():
        if held.condition_id == RIM and held.data.get("attacker") == ctx.actor.entity_id and held.data.get("intent") == _intent_seq(ctx.engine, ctx.actor):
            return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("forced_distance")
def rim_cut(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    return 10 if any(c.condition_id == RIM for c in mover.conditions.values()) else None


@hook("compile_actions")
def extensive_action(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if "TAL_SHIELD_EXTENSIVE_DEFENSE" not in (info.get("owned_ids") or []):
        return None
    typed = {"effects": [{"type": "shield_extensive", "evidence": "Until the start of your next turn, apply Active Defense against every valid triggering attack without spending a Reaction."}],
             "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "source": "TAL_SHIELD_EXTENSIVE_DEFENSE", "coverage": "FULL"}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.shield.extensive", display_name="Extensive Defense (Martial Focus)",
                             owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0, "player_only": True})]
