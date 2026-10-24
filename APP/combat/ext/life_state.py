"""Public test documentation omitted."""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any, Callable
from contextlib import contextmanager

from . import effect, hook, note
from .. import typed_executor

DEATH_SAVES_FOR_ALL = False  # True: every creature reduced to 0 Hit Points is Dying (the 2024 rule); False: only those with the abilities below
DC = 10
FAILURES, SUCCESSES = 3, 3
SOUL = "condition:typed.soul_lingering"
DEAD = "condition:typed.death_finalized"
SEAL = "condition:typed.yellow_spring_seal"
MODE = "condition:typed.death_save_mode"
UNCONSCIOUS = "condition:typed.life_unconscious"
RECOVERY = "condition:typed.deathless_recovery"
RECORD = "life_round_record"  # {"ok": n, "bad": n}: "_round_" keeps it through the turn reset, and the runtime snapshot keeps it in a saved fight
HP_BEFORE = "life_round_hp_before"
DOOMED = "life_round_doomed"
HIT_COMPONENT_FLAG = "same_hit_component"
HIT_SCOPE = "_life_hit_component"  # transient engine record: the component scope of the hit in flight
PREVENTED = "life_state:death_prevented"  # key in the in-flight packet's scratch; transient, never saved
BLOCK = "life_state"
ROUND_SLOTS_MINUTE = 10  # a minute is ten rounds


# ------------------------------------------------------------------------------------------------ ownership and state
@hook("compile_block")
def _block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), **{k: v for k, v in spec.items() if k not in ("block", "kind", "why")}}]


def rows(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    """The life-and-death talents this character owns, by kind (combat/rules/feature_blocks.d/auto_h3.json)."""
    found = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    return {str(row.get("kind")): row for row in found if row.get("block") == BLOCK and row.get("kind")}


def soul_of(actor: Any) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == SOUL), None)


def is_dead(actor: Any) -> bool:
    """Dead, its soul not yet gone: a creature only a soul-return talent can reach."""
    return soul_of(actor) is not None


def is_deceased(actor: Any) -> bool:
    """Recorded death, including a departed soul; inactivity alone is nonlethal defeat.

    Post-hit consumers use this query. The older is_dead query deliberately means
    a lingering soul that the soul-return system may still reach.
    """
    return is_dead(actor) or any(c.condition_id == DEAD for c in actor.conditions.values())


def _record(actor: Any) -> dict[str, int]:
    row = actor.turn_flags.get(RECORD) or {}
    return {"ok": int(row.get("ok") or 0), "bad": int(row.get("bad") or 0)}


def _set_record(actor: Any, ok: int, bad: int) -> None:
    actor.turn_flags[RECORD] = {"ok": ok, "bad": bad}


def encounter_death_saves(actor: Any) -> dict[str, int]:
    """Journey continuation's public, integer-only death-save snapshot contract."""
    return _record(actor)


def restore_encounter_death_saves(actor: Any, record: dict[str, int]) -> None:
    """Restore a sealed journey record without healing or changing life state."""
    if set(record) != {"ok", "bad"} or any(type(n) is not int or n < 0 for n in record.values()):
        raise ValueError("Death-save progress must contain nonnegative whole counts.")
    _set_record(actor, record["ok"], record["bad"])


def _modes(actor: Any, engine: Any | None = None) -> list[tuple[str, str | None]]:
    """Every rule that changes this creature's death saves: (mode, the condition instance a "first"/"next" rule is used up with)."""
    found: list[tuple[str, str | None]] = []
    for iid, condition in actor.conditions.items():
        from ..typed_executor import is_active_typed_condition

        if condition.condition_id == "condition:typed.black_star_vessel_active":
            found.append(("DISADVANTAGE", None))
        if not is_active_typed_condition(condition):
            continue
        rule = ((condition.data or {}).get("rule") or {}).get("death_save_mode")
        if rule:
            area = condition.data.get("death_save_area")
            if area and engine is not None:
                continue  # aura membership is queried from its live zone below
            found.append((str(rule.get("mode") or "ADVANTAGE"), iid if rule.get("first") else None))
    if engine is not None:
        for zone in engine.state.zones.values():
            if not zone.active:
                continue
            action = engine.action_catalog.get(zone.source_definition_id)
            typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
            area = typed.get("area") or {}
            caster = engine.state.actors.get(zone.owner_id)
            if caster is None or not caster.active or area.get("shape") != "emanation":
                continue
            if engine._distance_actor_to_actor(caster, actor) > int(area.get("size_ft") or 0):
                continue
            for effect_row in typed.get("effects") or []:
                mode = {"advantage": "ADVANTAGE", "disadvantage": "DISADVANTAGE"}.get(effect_row.get("type"))
                if mode is None or "death sav" not in str(effect_row.get("on") or "").lower():
                    continue
                if mode == "ADVANTAGE" and caster.team_id != actor.team_id:
                    continue
                found.append((mode, None))
        row = rows(engine, actor).get("death_mode")
        if row:
            found.append((str(row.get("mode") or "ADVANTAGE"), None))
        from . import run_strict
        for mode in run_strict("death_save_mode", engine, actor):
            if mode not in ("ADVANTAGE", "DISADVANTAGE"):
                raise ValueError("death_save_mode requires ADVANTAGE or DISADVANTAGE")
            found.append((mode, None))
    return found


def wants_dying(engine: Any, target: Any) -> bool:
    """Fight-wide 2024 dying, or the historical opt-in from an owned life-and-death ability."""
    # Summon records represent combat bodies that the summon lifecycle destroys
    # at zero HP, not ordinary fighters. Absent-rule legacy talent opt-ins retain
    # their prior behavior below; death-save bonuses do not override destruction.
    if DEATH_SAVES_FOR_ALL or engine.state.rules.get("zero_hp") == "dying_2024":
        return target.summon is None
    if any(condition.condition_id in (SEAL, SOUL) for condition in target.conditions.values()):
        return True
    return bool(_modes(target, engine)) or bool({"soul_lamp"} & set(rows(engine, target)))


@hook("zero_hp_default")
def zero_hp(engine: Any, target: Any, source_id: str, intent: Any) -> str | None:
    if not wants_dying(engine, target):
        return None
    _set_record(target, 0, 0)
    engine._apply_condition(target, UNCONSCIOUS, source_id, target.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Unconscious at 0 HP"})
    return "DYING"


def fall_unconscious(engine: Any, target: Any, source_id: str) -> None:
    """End a conscious-at-zero window without discarding accrued damage failures."""
    if not target.active or target.life_state != "CONSCIOUS" or target.current_hp > 0 or is_dead(target):
        return
    if not any(c.condition_id == UNCONSCIOUS for c in target.conditions.values()):
        engine._apply_condition(target, UNCONSCIOUS, source_id, target.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Unconscious at 0 HP", "rule": {"no_actions": True, "no_reactions": True,
                                      "speed_zero": True, "attacked_with": "ADVANTAGE",
                                      "save_mode": {"STR": "AUTO_FAIL", "DEX": "AUTO_FAIL"}}})
    engine._set_life_state(target, "DYING", source_id)
    _settle(engine, target, source_id)


# ------------------------------------------------------------------------------------------------ time
def _slots(engine: Any) -> int:
    return max(1, len(engine.state.initiative_order))


def _now(engine: Any) -> tuple[int, int]:
    return int(engine.state.round_number), int(engine.state.current_slot_index)


def rounds_since(engine: Any, condition: Any) -> float:
    """Rounds since the death (a round is one trip round the initiative order)."""
    round_now, slot_now = _now(engine)
    return (round_now - int(condition.data["round"])) + (slot_now - int(condition.data["slot"])) / _slots(engine)


# ------------------------------------------------------------------------------------------------ death
Handler = Callable[[Any, Any, str, str], bool]
_HANDLERS: list[tuple[int, Handler]] = []


def handler(function: Handler, *, priority: int = 0) -> Handler:
    """Shared death-handler API for life_state and life_riders.

    Lower priority runs first (delay: -100, soul preservation: 0); equal
    priorities keep registration order. Registering the same function twice
    is inert. Returns the function for existing decorator callers; True from
    a handler means it handled death and stops subsequent rules.
    """
    if not any(rule is function for _, rule in _HANDLERS):
        _HANDLERS.append((int(priority), function))
        _HANDLERS.sort(key=lambda row: row[0])
    return function


def _hit_notes(engine: Any) -> dict[str, str]:
    """Which owned death rules have already answered, for the hit whose death is in flight.

    One damaging hit is one death, so a packet tagged HIT_COMPONENT_FLAG reads and writes
    the record of the hit whose ``additional_hit_component`` scope is open: the same hit as
    the packet that came before it, whatever nested damage resolved in between. Any other
    packet in flight is a hit of its own and starts with an empty record, so an unrelated
    nested packet neither inherits the outer hit's answer nor erases it, and the outer hit
    still finds its answer when that packet's resolution returns. The record belongs to the
    hit's own packet (or to the packet that opened the component scope) and is gone with it.
    Outside any damage packet nothing can share an answer, so the record is a throwaway.
    """
    from ..pending_damage import current, packet_scratch
    packet, scratch = current(engine), packet_scratch(engine)
    if scratch is None:
        return {}
    if packet is not None and HIT_COMPONENT_FLAG in packet.source_flags:
        scope = getattr(engine, HIT_SCOPE, None)
        if scope is not None and scope[3] is not None:
            scratch = scope[3]
    return scratch.setdefault(PREVENTED, {})


def _prevented(engine: Any, target: Any, cause: str) -> None:
    """Remember that an owned death rule just answered this death and kept the creature alive.

    Recorded against the hit in flight, never against the creature alone, so one damaging
    hit is one death: a later component of that same hit reuses this answer instead of
    asking the rule a second time, and no other hit, however it resolves, reads it."""
    _hit_notes(engine)[target.entity_id] = str(cause)


def _was_prevented(engine: Any, target: Any) -> str | None:
    """The cause an owned rule already answered for this creature on this hit."""
    return _hit_notes(engine).get(target.entity_id)


def _finalize(engine: Any, target: Any, source_id: str) -> None:
    if not any(c.condition_id == DEAD for c in target.conditions.values()):
        engine._apply_condition(target, DEAD, source_id, target.entity_id,
                                expires_on="UNTIL_REMOVED", data={"label": "Dead: soul has departed"})
    for iid, condition in list(target.conditions.items()):
        if condition.condition_id in (SOUL, SEAL):
            del target.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source_id, actor_id=target.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid})
    if target.active:
        engine._defeat(target, source_id, final=True)
    engine._check_victory()


def die(engine: Any, target: Any, cause: str, source_id: str) -> None:
    """The creature dies (three failed saves, damage of its whole maximum, an instant death): a rule that saves it, delays it, or
    keeps its soul for a soul-return talent gets the first word; else it leaves the map."""
    if not target.active or is_dead(target):
        return
    for _, rule in _HANDLERS:
        if rule(engine, target, cause, source_id):
            _prevented(engine, target, cause)
            return
    _finalize(engine, target, source_id)


def _cp_pool(actor: Any) -> str | None:
    return next((pool for pool in typed_executor.CP_POOLS if pool in actor.resources), None)


def _linger(engine: Any, target: Any, source_id: str, *, window: int, label: str, seal: bool = False, lamp: bool = False) -> None:
    round_now, slot_now = _now(engine)
    engine._apply_condition(target, SOUL, source_id, target.entity_id, expires_on="UNTIL_REMOVED",
                            data={"round": round_now, "slot": slot_now, "window": window, "seal": seal, "lamp": lamp, "label": label})
    note(engine, source_id, target, f"{target.display_name} is dead; {label}")


def _soul_specs(action: Any) -> list[dict[str, Any]]:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return [row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "soul_return"]


def window_of(engine: Any, actor: Any, spec: dict[str, Any]) -> int:
    """How many rounds back a soul-return talent of ``actor`` reaches: its own printed window, a Minute-Gate's minute for
    One-Breath, Unending Loyalty's minute for Recall Spirit."""
    limit = int(spec.get("within_rounds") or 1)
    owned = rows(engine, actor)
    if (spec.get("minute_gate", True) and "minute_gate" in owned) or (spec.get("unending") and "unending_loyalty" in owned):
        limit = max(limit, ROUND_SLOTS_MINUTE)
    return limit


def reach(engine: Any, other: Any) -> int:
    """How many rounds back this creature's soul-return talents reach (0: it has none)."""
    farthest = 0
    for action in engine.action_catalog.values():
        if action.owner_id != other.entity_id:
            continue
        for spec in _soul_specs(action):
            farthest = max(farthest, window_of(engine, other, spec))
    return farthest


def died_since_turn_end(engine: Any, actor: Any, condition: Any) -> bool:
    """"Died since the end of your last turn" (Recall Spirit): after the turn ``actor`` last finished."""
    order = list(engine.state.initiative_order)
    n = _slots(engine)
    mine = order.index(actor.entity_id) if actor.entity_id in order else 0
    round_now, slot_now = _now(engine)
    last_end = round_now * n + mine if slot_now > mine else (round_now - 1) * n + mine
    return int(condition.data["round"]) * n + int(condition.data["slot"]) > last_end


def _spec(action: Any) -> dict[str, Any]:
    return next(iter(_soul_specs(action)), {})


def reachable(engine: Any, actor: Any, dead: Any, action: Any) -> bool:
    """Whether the talent's own window still reaches this dead creature (One-Breath: the last round; Minute-Gate: the last minute;
    Recall Spirit: since the end of the leader's last turn; a Yellow-Spring seal counts the death as within the last round)."""
    condition = soul_of(dead)
    if condition is None:
        return False
    spec = _spec(action)
    if condition.data.get("seal") or condition.data.get("lamp"):
        return True if condition.data.get("seal") else rounds_since(engine, condition) <= window_of(engine, actor, spec)
    if spec.get("since_last_turn") and not (spec.get("unending") and "unending_loyalty" in rows(engine, actor)):
        return died_since_turn_end(engine, actor, condition)
    return rounds_since(engine, condition) <= window_of(engine, actor, spec)


def returners(engine: Any, dead: Any) -> list[Any]:
    """Living creatures on the dead one's side that own a soul-return talent."""
    return [other for other in engine.state.actors.values()
            if other.active and other.team_id == dead.team_id and other.entity_id != dead.entity_id and other.life_state in (None, "CONSCIOUS")
            and not is_dead(other) and reach(engine, other) > 0]


def can_return(engine: Any, dead: Any, condition: Any) -> bool:
    """Whether anyone could still bring this creature back: its own lamp, or a teammate whose talent reaches this far back."""
    data = condition.data
    if data.get("lamp"):
        return True
    elapsed = 0.0 if data.get("seal") else rounds_since(engine, condition)
    if rounds_since(engine, condition) > float(data.get("window") or 1):
        return False
    return any(reach(engine, other) >= elapsed for other in returners(engine, dead))


# The defaults: a creature that dies while a teammate could call it back stays a moment, so that the talent has something to touch.
@handler
def _seal(engine: Any, target: Any, cause: str, source_id: str) -> bool:
    seal = next((c for c in target.conditions.values() if c.condition_id == SEAL), None)
    if seal is None:
        return False
    for iid, held in list(target.conditions.items()):
        if held is seal:
            del target.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source_id, actor_id=target.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": SEAL, "instance_id": iid, "reason": "TRIGGERED"})
    _linger(engine, target, source_id, window=ROUND_SLOTS_MINUTE, seal=True,
            label="its soul does not fully depart for 1 minute (Yellow-Spring Refusal Seal)")
    return True


@handler
def _lamp(engine: Any, target: Any, cause: str, source_id: str) -> bool:
    from . import needle

    pool = _cp_pool(target)
    if "soul_lamp" not in rows(engine, target) or pool is None or target.resources.get(pool, 0) < 1:
        return False
    picked = needle.ask(engine, engine._active_intent, "SOUL_LAMP", target,
                        "choice:life.lamp:" + needle.checkpoint_id(engine, "LAMP", target.entity_id), ["keep_soul"],
                        labels={"keep_soul": "Spend all remaining CP to keep your soul for 1 minute"},
                        prompt="Soul-Lamp Continuity: keep your departing soul?", allow_decline=True, automatic=False)
    if not picked:
        return False
    with activation(engine, target, "reaction:soul_lamp_continuity"):
        engine._spend_resource(target, pool, target.resources[pool], "reaction:soul_lamp_continuity")
        _linger(engine, target, source_id, window=ROUND_SLOTS_MINUTE, lamp=True,
                label="a Soul-Lamp keeps its soul for 1 minute (Soul-Lamp Continuity)")
        return True


@handler
def _teammate(engine: Any, target: Any, cause: str, source_id: str) -> bool:
    farthest = max((reach(engine, other) for other in returners(engine, target)), default=0)
    if farthest <= 0:
        return False
    _linger(engine, target, source_id, window=farthest, label="a soul-return talent may still call it back")
    return True


def _end_of_window(engine: Any, dead: Any, condition: Any) -> None:
    """The window is closed: a lamp gets its Constitution save, everything else is final."""
    if condition.data.get("lamp"):
        for iid, held in list(dead.conditions.items()):
            if held is condition:
                del dead.conditions[iid]
                engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=dead.entity_id, target_ids=(dead.entity_id,),
                                     payload={"condition_id": SOUL, "instance_id": iid, "reason": "LAMP_ENDS"})
        from .d20_rewrite import saving_throw_context

        # Keep the lamp's raw save: ordinary condition auto-failure would apply to its dead body.
        with saving_throw_context(engine, dead, "CON", 20, "soul_lamp", source_name="Soul-Lamp Continuity"):
            roll = engine.roller.d20(modifier=int(dead.saving_throws.get("CON", 0)), actor_id=dead.entity_id, reason="SAVE:soul_lamp:CON",
                                     mode=engine.direct_save_mode(dead, "CON", 20, "soul_lamp"))
        engine._record_roll(roll)
        ok = roll.total >= 20
        engine._append_event("SAVE_ROLLED", "reaction:soul_lamp_continuity", actor_id=dead.entity_id, target_ids=(dead.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": 20, "success": ok, "ability": "CON"})
        if ok:
            if _revive(engine, dead, 1, "reaction:soul_lamp_continuity", exhaustion=1):
                return
        else:
            note(engine, "reaction:soul_lamp_continuity", dead, f"{dead.display_name}'s Soul-Lamp goes out: the Constitution saving throw fails.")
    _finalize(engine, dead, condition.source_definition_id)


def _prune(engine: Any) -> None:
    """Close the windows that are over, and the ones nobody could use: a corpse does not hold a fight open."""
    for dead in list(engine.state.actors.values()):
        condition = soul_of(dead)
        if condition is None or not dead.active:
            continue
        if rounds_since(engine, condition) > float(condition.data.get("window") or 0) or (not condition.data.get("lamp") and not can_return(engine, dead, condition)):
            _end_of_window(engine, dead, condition)


# ------------------------------------------------------------------------------------------------ getting up
def heal_to(engine: Any, target: Any, amount: int, source_id: str, actor_id: str | None = None) -> int:
    """Ordinary healing shared by typed effects and healing plug-ins, including Halo Eater.

    Resolve restrictions, then assignment, before gaining HP; healing cannot reach
    the dead. Actual HP gain triggers healing reactions. Explicit soul return and
    recorded-HP restoration use restore_hp instead.
    """
    if is_dead(target):
        return 0
    amount = typed_executor._reduced_healing(
        engine, target, amount, healer=engine.state.actors.get(actor_id), source=source_id)
    before = target.current_hp
    target.current_hp = min(target.maximum_hp, target.current_hp + amount)
    if target.current_hp > before:
        from .. import typed_reactions

        typed_reactions.on_creature_event(engine, target, "healed")
    restored = _healing_event(engine, target, amount, source_id, actor_id, before)
    if restored == 0:
        note(engine, source_id, target, f"{target.display_name} regains no Hit Points.")
    return restored


def restore_hp(engine: Any, target: Any, amount: int, source_id: str, actor_id: str | None = None) -> None:
    """Explicit HP restoration for soul return, Dream Refuge, Echo Scribe's damage
    rewrite, and Well of Hours' recorded HP reset.

    This sets HP back rather than receiving ordinary healing; it neither contests
    healing restrictions nor pays deferred damage. Keep the existing event shape.
    """
    from ..support_values import healing_offer
    amount = healing_offer(engine, target, source_id, actor_id, amount)
    before = target.current_hp
    target.current_hp = min(target.maximum_hp, target.current_hp + amount)
    _healing_event(engine, target, amount, source_id, actor_id, before)


def _healing_event(engine: Any, target: Any, amount: int, source_id: str, actor_id: str | None, before: int) -> int:
    if target.current_hp > 0:
        engine._remove_condition(target, UNCONSCIOUS, source_id)
        engine._remove_condition(target, RECOVERY, source_id)
    engine._append_event("HEALING_APPLIED", source_id, actor_id=actor_id or target.entity_id, target_ids=(target.entity_id,),
                         payload={"offered": amount, "before": before, "after": target.current_hp})
    return target.current_hp - before


def _revive(engine: Any, target: Any, hp: int, source_id: str, *, exhaustion: int = 0, actor_id: str | None = None) -> bool:
    """Back from the dead: 1 Hit Point (or as told), no soul lingering, the ordeal's Exhaustion."""
    hp = typed_executor.healing_pending(engine, target, hp,
                                        engine.state.actors.get(actor_id or target.entity_id), source_id, "hp")
    if hp <= 0 or target.maximum_hp <= 0:
        note(engine, source_id, target, f"{target.display_name} cannot return to life because no Hit Points can be restored.")
        return False
    for iid, condition in list(target.conditions.items()):
        if condition.condition_id in (SOUL, SEAL):
            del target.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source_id, actor_id=target.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": "REVIVED"})
    restore_hp(engine, target, hp, source_id, actor_id)
    _set_record(target, 0, 0)
    if exhaustion:
        from . import forged_exhaustion

        forged_exhaustion.add(engine, target, exhaustion, source_id)
    return True


def stabilize(engine: Any, target: Any, source_id: str) -> bool:
    """Dying becomes Stable (a dead creature is beyond stabilizing). True when it did."""
    if target.active and target.life_state == "DYING" and not is_dead(target):
        engine._set_life_state(target, "STABLE", source_id)
        _set_record(target, 0, 0)
        stable_recovery(engine, target, source_id)
        return True
    return False


def stable_recovery(engine: Any, target: Any, source_id: str) -> None:
    """Deathless: a Stable creature regains 1 HP after 1d4 minutes.

    Store the deterministic deadline in an evented condition so reloads cannot
    reroll it. Ordinary 1d4-hour recovery remains outside this opt-in feature.
    """
    if "death_mode" not in rows(engine, target) or any(c.condition_id == RECOVERY for c in target.conditions.values()):
        return
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=1, sides=4), actor_id=target.entity_id, reason="DEATHLESS:stable_recovery")
    engine._record_roll(roll)
    engine._apply_condition(target, RECOVERY, source_id, target.entity_id, expires_on="UNTIL_REMOVED",
                            data={"round": engine.state.round_number + roll.total * 10,
                                  "slot": engine.state.current_slot_index, "label": "Deathless stable recovery"})


@hook("turn_decision_required")
def retain_downed_turn_decision(engine: Any, actor: Any) -> bool:
    """The opt-in dying rules retain a downed actor's normal control preference.

    This keeps the reviewed End Turn and recovery decisions available without
    changing the legacy rule that passes a helpless initiative slot automatically.
    AI-controlled actors still choose automatically through their normal policy.
    """
    return bool(engine.state.rules.get("zero_hp") == "dying_2024"
                and actor.active and actor.life_state in ("DYING", "STABLE"))


@hook("turn_boundary_start", priority=1000)
def resolve_stable_opponents(engine: Any, actor: Any) -> None:
    """End new-rule combat without killing helpless, ordinary Stable opponents.

    Query before the next turn, after damage batches and all end-turn
    effects (including native resource riders). Dying fighters, lingering souls,
    scheduled recovery and active
    allied summons keep their side in combat. Never remove or kill the Stable
    body: its HP, position and life state remain available in the saved result.
    """
    if engine.state.rules.get("zero_hp") != "dying_2024" or engine.state.terminal_result is not None:
        return
    from ..relations import ALLY, ENEMY, relation
    from ..gate2_runtime_models import TerminalKind

    primaries = [a for a in engine.state.actors.values() if a.primary_combatant]
    active = [a for a in engine.state.actors.values() if a.active]

    def can_recover(a: Any) -> bool:
        return (a.life_state != "STABLE" or is_dead(a)
                or any(c.condition_id == RECOVERY for c in a.conditions.values())
                or any(not b.primary_combatant and b.life_state not in ("DYING", "STABLE")
                       and relation(engine, a, b) == ALLY for b in active))

    contenders = [a for a in primaries if a.active and can_recover(a)]
    if len(contenders) == sum(a.active for a in primaries):
        return  # Ordinary victory/truce remains the engine's responsibility.
    if any(relation(engine, a, b) == ENEMY for a in contenders for b in contenders):
        return
    fighters = [a for a in contenders if any(relation(engine, a, b) == ENEMY for b in primaries)]
    if fighters:
        if not any(a.life_state == "CONSCIOUS" or (a.life_state is None and a.current_hp > 0) for a in fighters):
            return  # Let the remaining dying/recovering side settle before declaring a winner.
        teams = sorted({a.team_id for a in fighters})
        engine._end_match(TerminalKind.VICTORY, teams[0] if len(teams) == 1 else None,
                          "Opposing fighters are defeated or unconscious and stable; combat ends without killing them.")
    elif not contenders:
        engine._end_match(TerminalKind.DRAW_SIMULTANEOUS, None,
                          "All opposing fighters are defeated or unconscious and stable; neither side can continue combat.")


# ------------------------------------------------------------------------------------------------ death saving throws
def _roll_save(engine: Any, target: Any, source_id: str) -> int:
    """One death saving throw: +1 success, +2 failures on a 1, a 20 stands the creature up. Returns its natural die."""
    modes = _modes(target, engine)
    advantage, disadvantage = any(m == "ADVANTAGE" for m, _ in modes), any(m == "DISADVANTAGE" for m, _ in modes)
    mode = "ADVANTAGE" if advantage and not disadvantage else "DISADVANTAGE" if disadvantage and not advantage else "NORMAL"
    roll = engine.roller.d20(modifier=0, actor_id=target.entity_id, reason="SAVE:death", mode=mode)
    engine._record_roll(roll)
    natural = int(roll.natural_result or 0)
    success = natural == 20 or (natural != 1 and roll.total >= DC)
    engine._append_event("CHECK_ROLLED", source_id, actor_id=target.entity_id, target_ids=(target.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": DC, "success": success, "skill": "Death Saving Throw"})
    for _mode, iid in modes:  # a "first"/"next" rule is used up by the roll
        if iid and iid in target.conditions:
            spent = target.conditions.pop(iid)
            engine._append_event("CONDITION_REMOVED", spent.source_definition_id, actor_id=target.entity_id, target_ids=(target.entity_id,),
                                 payload={"condition_id": MODE, "instance_id": iid, "reason": "CONSUMED"})
    return natural


def death_save(engine: Any, target: Any, source_id: str = "system:death_save") -> None:
    """Make the creature's death saving throw now (the start of its turn, or Quiet Burial's early one)."""
    if not target.active or target.life_state != "DYING" or is_dead(target):
        return
    natural = _roll_save(engine, target, source_id)
    record = _record(target)
    ok, bad = record["ok"], record["bad"]
    if natural == 20:
        heal_to(engine, target, 1, source_id)
        # Healing can be denied, spent on deferred damage, or cause damage/death
        # during its restrictions. Preserve those consequences unless it recovers.
        recovered = target.active and not is_dead(target) and target.current_hp > 0
        if not recovered:
            note(engine, source_id, target, f"{target.display_name} rolls a natural 20 on its death saving throw, but regains no Hit Points because recovery is prevented.")
            return
        # Actual healing already clears the death-save record. Do not recreate
        # an empty persisted record after its HEALING_APPLIED event.
        target.turn_flags.pop(RECORD, None)
        note(engine, source_id, target, f"{target.display_name} rolls a natural 20 on its death saving throw and regains 1 Hit Point.")
        if engine.state.current_actor_id == target.entity_id:  # it is its own turn: it may act
            target.action_available = target.bonus_action_available = target.reaction_available = True
            target.movement_remaining_ft = engine._effective_speed(target)
        return
    if natural != 1 and natural >= DC:
        ok += 1
        if engine.state.rules.get("zero_hp") == "dying_2024":
            _set_record(target, ok, bad)
            note(engine, source_id, target, f"{target.display_name} is dying: death saving throw 1d20 [{natural}] — success ({ok} successes, {bad} failures).")
        else:
            note(engine, source_id, target, f"{target.display_name} succeeds a death saving throw ({ok}/{SUCCESSES}).")
            _set_record(target, ok, bad)
        if ok >= SUCCESSES:
            stabilize(engine, target, source_id)
        return
    from . import iter_strict_all
    for ignored in iter_strict_all("death_save_failure", engine, target, natural, source_id):
        if ignored is not None and type(ignored) is not bool:
            raise ValueError("death_save_failure must return bool or None")
        if ignored is True:
            return
    bad += 2 if natural == 1 else 1
    _set_record(target, ok, bad)
    if engine.state.rules.get("zero_hp") == "dying_2024":
        note(engine, source_id, target, f"{target.display_name} is dying: death saving throw 1d20 [{natural}] — failure ({ok} successes, {min(bad, FAILURES)} failures){'; a natural 1 counts as two failures' if natural == 1 else ''}.")
    else:
        note(engine, source_id, target, f"{target.display_name} fails a death saving throw ({min(bad, FAILURES)}/{FAILURES}).")
    _settle(engine, target, source_id)


def add_failed_death_save(engine: Any, target: Any, source_id: str) -> None:
    """Public lifecycle addition for a printed failure outside a rolled death save.

    Candlemaker's Borrowed Final Breath uses this after a fresh zero-HP episode.
    This preserves successes and lets the ordinary lifecycle settle death.
    """
    if not target.active or (target.life_state not in ("DYING", "CONSCIOUS") and
                             not (target.life_state is None and target.current_hp == 0)) or is_dead(target):
        return
    record = _record(target)
    _set_record(target, record["ok"], record["bad"] + 1)
    _settle(engine, target, source_id)


def _settle(engine: Any, target: Any, source_id: str) -> None:
    if not target.active or target.life_state not in ("DYING", "STABLE", "CONSCIOUS") or is_dead(target):
        return
    doomed = target.turn_flags.pop(DOOMED, None)
    if doomed:
        die(engine, target, str(doomed), source_id)
    elif target.life_state in ("DYING", "CONSCIOUS") and _record(target)["bad"] >= FAILURES:
        die(engine, target, "three failed death saving throws", source_id)


@hook("nominal_slot_boundary")
def nominal_soul_expiry(engine: Any, actor: Any, checkpoint: str) -> None:
    """A departed soul's clock is expiry, never a save or a recovery turn."""
    if checkpoint == "START_OF_TURN":
        _prune(engine)


@hook("turn_start")
def _turn_start(engine: Any, actor: Any) -> None:
    _prune(engine)
    recovery = next((c for c in actor.conditions.values() if c.condition_id == RECOVERY), None)
    if actor.active and actor.life_state == "STABLE" and recovery is not None and _now(engine) >= (recovery.data["round"], recovery.data["slot"]):
        heal_to(engine, actor, 1, recovery.source_definition_id)
        if actor.active and not is_dead(actor) and actor.current_hp > 0:
            actor.action_available = actor.bonus_action_available = actor.reaction_available = True
            actor.movement_remaining_ft = engine._effective_speed(actor)
    if actor.active and actor.life_state == "DYING" and not is_dead(actor):
        death_save(engine, actor, "system:death_save")


# ------------------------------------------------------------------------------------------------ damage at 0 Hit Points
def _was_critical(engine: Any, target_id: str, intent_id: str) -> bool:
    # Native provenance includes widened range and pre-damage cancellation.
    # Keep the inherited close-range Unconscious rule only when no cancellation
    # changed this hit; never reconstruct a cancelled critical from its raw die.
    packet = engine.damage_context()
    if packet is not None and packet.target_id == target_id:
        if packet.critical:
            return True
        if packet.critical_cancelled:
            return False
    for event in reversed(engine.events[-14:]):
        if event.event_type == "ATTACK_ROLLED" and target_id in (event.target_ids or ()) and event.trigger_or_intent_id == intent_id:
            attacker, target = engine.state.actors.get(event.actor_id), engine.state.actors.get(target_id)
            return int((event.payload or {}).get("natural_result") or 0) == 20 or (
                attacker is not None and target is not None and target.life_state in ("DYING", "STABLE")
                and engine._distance_actor_to_actor(attacker, target) <= 5)
    return False


def massive(engine: Any, target: Any) -> int:
    """The damage that kills outright: the creature's Hit Point maximum (Deathless: three times it)."""
    return target.maximum_hp * int((rows(engine, target).get("death_mode") or {}).get("massive_multiplier") or 1)


@contextmanager
def additional_hit_component(engine, target, hp_before, hp_damage):
    """Censure and other typed hit components share the first packet's HP outcome.

    Called during the first packet's DAMAGE_COMMITTED notification, after that
    packet's own zero-HP settlement. Additional defended HP damage contributes to
    that hit's massive-damage excess; it never creates another death-save failure.
    One damaging hit is one death: when the first packet's death was already answered
    by an owned rule that kept the creature alive (Funeral Candle Shelter spends its
    once-per-rest benefit on that hit), the component reuses that answer instead of
    resolving death again. The record of that answer belongs to the hit, not to the
    component: only a tagged component of the enclosing hit inherits its record.
    An independent packet opening its own component scope carries its own scratch,
    even inside another hit's scope, without disturbing that hit's record. Transient, nested-safe
    integers. Callers tag only the additional packet with HIT_COMPONENT_FLAG in
    source_flags; unrelated nested damage retains its ordinary lifecycle, even on this
    target.
    """
    from ..pending_damage import current, packet_scratch
    previous = getattr(engine, HIT_SCOPE, None)
    packet = current(engine)
    belongs_to_enclosing_hit = (previous is not None and packet is not None
                               and previous[0] == packet.target_id == target.entity_id
                               and HIT_COMPONENT_FLAG in packet.source_flags)
    held = previous[3] if belongs_to_enclosing_hit and previous[3] is not None else packet_scratch(engine)
    engine._life_hit_component = (target.entity_id, int(hp_before), int(hp_damage), held)
    try:
        yield
    finally:
        engine._life_hit_component = previous


def _on_damage(engine: Any, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    hp_damage = int(payload.get("hp_damage") or 0)
    damage_taken = hp_damage + int(payload.get("temporary_hp_absorbed") or 0)
    component = getattr(engine, HIT_SCOPE, None)
    from ..pending_damage import current
    packet = current(engine)
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None or not target.active or is_dead(target):
            continue
        is_component = (component is not None and component[0] == target_id and packet is not None
                        and HIT_COMPONENT_FLAG in packet.source_flags)
        if damage_taken <= 0:
            continue
        before = target.turn_flags.pop(HP_BEFORE, None)
        if is_component:
            if wants_dying(engine, target) and target.current_hp == 0 and component[2] + hp_damage - component[1] >= massive(engine, target):
                if _was_prevented(engine, target) is not None:
                    # The first packet of this hit already asked an owned death rule and it kept
                    # the creature alive. Its dice add to the same lethal total, but one hit is one
                    # death: spending the protection is not undone by the rest of the same hit.
                    note(engine, "system:damage", target, f"{target.display_name} would be killed by the rest of "
                         "this hit, but is already saved from it.")
                else:
                    target.turn_flags[DOOMED] = "massive damage"
                    # The first packet already took this hit's single failure and _defeat leaves an
                    # existing life state to this module, so a creature that was already at zero never
                    # gets the fresh LIFE_STATE_CHANGED that consumes DOOMED elsewhere. Settle the
                    # combined hit now. Inert while the target is fresh at zero: it has no life state
                    # yet, so its own settlement keeps the flag.
                    _settle(engine, target, "system:damage")
            continue
        if target.life_state is None:
            # It has just gone to 0: the damage left over decides whether that is an outright death (2024: at least its maximum).
            if target.current_hp == 0 and before is not None and wants_dying(engine, target) and hp_damage - int(before) >= massive(engine, target):
                target.turn_flags[DOOMED] = "massive damage"
            continue
        if damage_taken >= massive(engine, target):
            target.turn_flags[DOOMED] = "massive damage"
        else:
            record = _record(target)
            if target.life_state == "STABLE":
                engine._remove_condition(target, RECOVERY, "system:damage")
                engine._set_life_state(target, "DYING", engine.events[-1].source_definition_id if engine.events else "system:damage")
                record = {"ok": 0, "bad": 0}
            intent_id = engine.events[-1].trigger_or_intent_id if engine.events else ""
            failures = 2 if _was_critical(engine, target_id, intent_id) else 1
            _set_record(target, record["ok"], record["bad"] + failures)
            note(engine, "system:death_save", target, f"{target.display_name} takes damage at 0 Hit Points: "
                 f"{'2 failed death saves (a critical hit)' if failures == 2 else 'a failed death save'} ({min(_record(target)['bad'], FAILURES)}/{FAILURES}).")
        _settle(engine, target, "system:damage")


@hook("event", nested=True)
def _events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    # Legacy life talents already subscribed to nested lifecycle events before
    # the fight-wide dying rule. Recovery and damage settlement must run in
    # both modes; wants_dying still owns the zero-HP opt-in.
    if event_type == "REACTION_WINDOW_OPENED" and (kwargs.get("payload") or {}).get("checkpoint") == "DAMAGE_APPLICATION":
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and target.active:
                target.turn_flags[HP_BEFORE] = int(target.current_hp)
    elif event_type == "DAMAGE_COMMITTED":
        _on_damage(engine, kwargs)
    elif event_type == "LIFE_STATE_CHANGED":
        for target_id in [kwargs.get("actor_id")]:
            target = engine.state.actors.get(target_id or "")
            payload = kwargs.get('payload') or {}
            if target is not None and target.life_state == 'CONSCIOUS' and payload.get('fresh_zero_hp'):
                _set_record(target, 0, 0)
                excess = payload.get('initial_damage_excess')
                if type(excess) is int and excess >= massive(engine, target):
                    target.turn_flags[DOOMED] = 'massive damage'
            if target is not None and target.turn_flags.get(DOOMED):
                _settle(engine, target, "system:damage")
            elif target is not None and target.life_state == "STABLE":
                stable_recovery(engine, target, "system:deathless")
    elif event_type == "HEALING_APPLIED":
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and target.current_hp > 0:
                target.turn_flags.pop(RECORD, None)
                engine._remove_condition(target, UNCONSCIOUS, "system:healing")
                engine._remove_condition(target, RECOVERY, "system:healing")
    if event_type in ("TURN_ENDED", "HEALING_APPLIED", "CONDITION_REMOVED", "ENTITY_DEFEATED") and any(is_dead(a) for a in engine.state.actors.values()):
        _prune(engine)


# ------------------------------------------------------------------------------------------------ nothing reaches the dead but a soul-return talent
def _effect_types(action: Any) -> set[str]:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    return {str(row.get("type")) for row in typed.get("effects") or [] if isinstance(row, dict)}


def _eligible(engine: Any, actor: Any, action: Any) -> list[Any]:
    """The dead creatures this soul-return action could reach now: within its window and, for a Shout, its area."""
    spec = _spec(action)
    area = int(spec.get("area_ft") or 5)
    return [dead for dead in engine.state.actors.values()
            if dead.active and is_dead(dead) and reachable(engine, actor, dead, action)
            and (spec.get("area_ft") is None or engine._distance_actor_to_actor(actor, dead) <= area)]


@hook("candidate_allowed")
def dead_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """A dead creature (its soul lingering) is beyond every action but a soul-return talent's; and a soul-return talent reaches
    only the dead, within the window its talents allow."""
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    targets = [t for t in targets if t is not None]
    returning = "soul_return" in _effect_types(action) if action is not None else False
    if returning:
        if _spec(action).get("shout"):  # a Shout is aimed at nobody: it needs a creature within its area to call back
            return bool(_eligible(engine, actor, action))
        return bool(targets) and all(is_dead(t) and reachable(engine, actor, t, action) for t in targets)
    if any(is_dead(t) for t in targets) and str(getattr(candidate, "kind", "")) not in ("MOVE",):
        return False
    return None


@hook("ai_candidate_allowed")
def dead_ai(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Return allies' souls; in new fights avoid damage aimed only at downed enemies.

    Manual attacks remain legal. Mixed areas can still catch downed creatures
    while attacking conscious foes. Explicit soul-return actions keep their
    printed targeting above; no benefit for executing a dying foe is inferred.
    """
    if action is not None and "soul_return" in _effect_types(action):
        if _spec(action).get("shout"):
            return any(dead.team_id == actor.team_id for dead in _eligible(engine, actor, action))
        return all((t := engine.state.actors.get(i)) is not None and t.team_id == actor.team_id for i in candidate.target_ids or ())
    if engine.state.rules.get("zero_hp") == "dying_2024":
        targets = [engine.state.actors[i] for i in candidate.target_ids or () if i in engine.state.actors]
        damaging = (action is not None and (action.attack_bonus is not None or action.damage is not None)) or int((candidate.metadata or {}).get("expected_damage") or 0) > 0
        from ..relations import relation, ENEMY
        if damaging and targets and all(t.life_state in ("DYING", "STABLE") and relation(engine, actor, t) == ENEMY for t in targets):
            from . import run_strict
            benefits = run_strict("ai_downed_damage_worthwhile", engine, actor, candidate, action, tuple(targets))
            if any(type(answer) is not bool for answer in benefits):
                raise ValueError("ai_downed_damage_worthwhile must return None or bool")
            if True in benefits:
                return None
            return False
    return None


@hook("choice_options")
def _options(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Every life-state choice (id "choice:life.*"): the options and their bounds ride in the trigger context (as needle.py's)."""
    if not str(choice_id).startswith("choice:life.") or not (context or {}).get("needle_options"):
        return None
    spec = {"option_ids": list(context["needle_options"]), "minimum_selections": int(context.get("minimum", 1)),
            "maximum_selections": int(context.get("maximum", 1)), "allow_decline": bool(context.get("allow_decline", False)),
            "automatic_use": bool(context.get("automatic", True))}
    if context.get("preferred"):
        spec["preferred_option_ids"] = list(context["preferred"])
    return spec


def survival_consent(engine: Any, row: dict[str, Any], reactor: Any, checkpoint: str) -> bool:
    """A compiled 0-HP substitution is optional even when it costs no Reaction.

    The table asks its owning fighter; local AI chooses to stay alive. Generic
    reactions retain ownership of affordability, costs and one-use counters.
    """
    from . import needle
    from .choice_prompt import action_context
    from ..decision_text import costs_text

    target_id = (getattr(engine, "_gate4_damaged_target_id", None)
                 or (getattr(engine, "_reaction_trigger", None) or {}).get("target_id")
                 or reactor.entity_id)
    name = row.get('name') or 'Survival ability'
    cost = costs_text(row.get('costs')) or 'No resource cost'
    if not row.get('free') and row.get('reaction', True):
        cost = 'Reaction; ' + cost
    # Reduction reactions can be the most recent events, but the consent is
    # about the damage-producing action. Preserve that action's presentation.
    trigger = getattr(engine, "_reaction_trigger", None) or {}
    source_id = trigger.get("source_definition_id")
    if not source_id:
        source_id = next((event.source_definition_id for event in reversed(engine.events)
                          if event.event_type == "INTENT_ACCEPTED"), "")
    actor_id = trigger.get("actor_id") or getattr(getattr(engine, "_active_intent", None), "actor_id", None)
    target = engine.state.actors.get(target_id) or reactor
    context = {**action_context(engine, engine.state.actors.get(actor_id), source_id, target), 'cost': cost}
    # Manual survival remains an opt-in choice. Only an explicitly AI-owned
    # fighter recommends using the substitution to its automatic controller.
    automatic = (getattr(engine, "typed_control_modes", None) or {}).get(reactor.entity_id) == "LOCAL_AUTO"
    picked = needle.ask(engine, engine._active_intent, checkpoint, reactor,
                        "choice:life.survive:" + needle.checkpoint_id(engine, "SURVIVE", reactor.entity_id, row["feature_id"]),
                        ["use"], labels={"use": f"Use {row.get('name') or row['feature_id']} to prevent reaching 0 HP"},
                        name=name, feature_id=row['feature_id'],
                        prompt=f"{name}: prevent {target.display_name} from reaching 0 HP?",
                        prompt_context=context, allow_decline=True, automatic=automatic, target_id=target_id)
    return bool(picked)


def _hp_returned(ctx: Any, eff: dict[str, Any], unending: bool) -> int:
    """Hit Points a soul-return talent gives back: a number, or from the leader's own (Recall Spirit: CL + key modifier; Unending
    Loyalty: twice CL + key modifier)."""
    formula = eff.get("hp_unending_formula") if unending and eff.get("hp_unending_formula") else eff.get("hp_formula")
    cl, key = int(ctx.numbers.get("cl") or 1), int(ctx.numbers.get("key_mod") or 0)
    if formula == "cl_key":
        return max(1, cl + key)
    if formula == "two_cl_key":
        return max(1, 2 * cl + key)
    return int(eff.get("hp") or 1)


@effect("soul_return")
def soul_return(ctx: Any, eff: dict[str, Any]) -> None:
    """One-Breath Resuscitation and its kin: "The target returns to life with 1 Hit Point ... gains 1 level of Exhaustion"; Recall
    Spirit: one creature within the Shout's area, back with CL + key modifier Hit Points and two levels of Exhaustion (at most 5)."""
    from . import forged_exhaustion, needle

    engine = ctx.engine
    subjects = [s for s in (ctx.targets or ([ctx.target] if ctx.target is not None else [])) if s is not None and is_dead(s)]
    if not subjects and eff.get("shout"):
        pool = _eligible(engine, ctx.actor, ctx.action)
        ordered = sorted(pool, key=lambda d: (d.team_id != ctx.actor.team_id, engine._distance_actor_to_actor(ctx.actor, d), d.entity_id))
        picked = needle.ask(engine, ctx.intent, "SOUL_RETURN", ctx.actor, "choice:life.recall:" + needle.checkpoint_id(engine, "RECALL", ctx.actor.entity_id),
                            [d.entity_id for d in ordered], labels={d.entity_id: f"Call back {d.display_name}" for d in ordered},
                            prompt="Recall Spirit: which fallen creature returns?", preferred=[d.entity_id for d in ordered if d.team_id == ctx.actor.team_id][:1],
                            automatic=True, target_id=ctx.actor.entity_id)
        subjects = [engine.state.actors[i] for i in picked[:1] if i in engine.state.actors]
    for subject in subjects:
        from .choice_prompt import action_context

        willing = needle.ask(engine, ctx.intent, "SOUL_RETURN_CONSENT", subject,
                             "choice:life.return:" + needle.checkpoint_id(engine, "RETURN", subject.entity_id), ["return"],
                             labels={"return": "Let your soul return to life"}, prompt="Return to life?",
                             allow_decline=True, automatic=False, target_id=subject.entity_id,
                             default="first" if subject.team_id == ctx.actor.team_id else "decline",
                             name=ctx.action.display_name, feature_id=ctx.source,
                             prompt_context=action_context(engine, ctx.actor, ctx.source, subject))
        if not willing:
            continue
        condition = soul_of(subject)
        # Minute-Gate: "If the creature has been dead longer than 1 round, increase the cost to 4 CP" (one more than the talent's own).
        if eff.get("minute_gate", True) and "minute_gate" in rows(engine, ctx.actor) and not condition.data.get("seal") and rounds_since(engine, condition) > 1:
            pool = _cp_pool(ctx.actor)
            if pool is not None and ctx.actor.resources.get(pool, 0) >= 1:
                engine._spend_resource(ctx.actor, pool, 1, ctx.source)
        hp = _hp_returned(ctx, eff, bool(eff.get("unending") and "unending_loyalty" in rows(engine, ctx.actor)))
        exhaustion = min(int(eff.get("exhaustion", 1)), max(0, int(eff.get("exhaustion_cap", 6)) - forged_exhaustion.level(subject)))
        if _revive(engine, subject, hp, ctx.source, exhaustion=exhaustion, actor_id=ctx.actor.entity_id):
            hp = subject.current_hp
            ctx.rider(f"{subject.display_name} returns to life with {hp} Hit Point{'s' if hp != 1 else ''}.")


@effect("stabilize")
def stabilize_effect(ctx: Any, eff: dict[str, Any]) -> None:
    """"If the target has 0 Hit Points ... the target becomes stable" (Borrowed Breath, Coagulate, ...): a Dying creature turns Stable."""
    for subject in typed_executor._default_subject(ctx, eff, harmful=False):
        if subject is not None and stabilize(ctx.engine, subject, ctx.source):
            ctx.rider(f"{subject.display_name} is stable.")


@effect("soul_seal")
def soul_seal(ctx: Any, eff: dict[str, Any]) -> None:
    """Yellow-Spring Refusal Seal: "A creature can benefit from only one Yellow-Spring Refusal Seal at a time"; it lasts until the
    target finishes a long rest, so for the fight."""
    for subject in typed_executor._default_subject(ctx, eff, harmful=False):
        if subject is None or not subject.active or is_dead(subject):
            continue
        for iid, held in list(subject.conditions.items()):
            if held.condition_id == SEAL:
                del subject.conditions[iid]
                ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                         payload={"condition_id": SEAL, "instance_id": iid, "reason": "REPLACED"})
        ctx.engine._apply_condition(subject, SEAL, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Yellow-Spring Refusal Seal", "caster": ctx.actor.entity_id})


@effect("death_save_now")
def death_save_now(ctx: Any, eff: dict[str, Any]) -> None:
    """Quiet Burial: "let one dying creature within reach immediately make a death saving throw with Advantage"."""
    for subject in typed_executor._default_subject(ctx, eff, harmful=False):
        if subject is None or subject.life_state != "DYING" or is_dead(subject):
            continue
        ctx.engine._apply_condition(subject, MODE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"rule": {"death_save_mode": {"mode": "ADVANTAGE", "first": True}}, "label": "Advantage on the next death saving throw"})
        death_save(ctx.engine, subject, ctx.source)


def give_death_save_mode(ctx: Any, effect_row: dict[str, Any], mode: str, on: str) -> None:
    """typed_executor.block_advantage's branch for "Advantage/Disadvantage on death saving throws": the subjects hold the rule for
    as long as the ability says ("the first"/"the next" one is used up by the roll it changes)."""
    first = "first" in on or "next" in on
    area = (ctx.typed.get("area") or {}).get("size_ft")
    for subject in typed_executor._default_subject(ctx, effect_row, harmful=mode == "DISADVANTAGE"):
        if subject is None:
            continue
        if mode == "ADVANTAGE" and effect_row.get("applies_to") == "creatures_in_area" and subject.team_id != ctx.actor.team_id:
            continue  # the printed protective death-save auras name allies/chosen willing creatures
        ctx.engine._apply_condition(subject, MODE, ctx.source, ctx.actor.entity_id,
                                    expires_on=typed_executor.effect_expiry(ctx, effect_row, subject, condition=True) or "END_OF_HOLDER_NEXT_TURN",
                                    data={"rule": {"death_save_mode": {"mode": mode, "first": first}},
                                          "death_save_area": area,
                                          "label": f"{mode.title()} on {effect_row.get('on')}"})


def failed_death_saves(actor: Any) -> int:
    """Recorded failures available to an explicit restoration procedure."""
    return _record(actor)["bad"] if actor.active and not is_dead(actor) else 0


def erase_failed_death_save(engine: Any, actor: Any, source: str, owner_id: str) -> bool:
    """Remove one recorded failure without healing, stabilizing or reviving.

    Dedicated procedures may invoke this; ordinary life-state gates remain in
    force. Returns whether a failure was actually removed, with an event receipt.
    """
    if not actor.active or is_dead(actor):
        return False
    record = _record(actor)
    if record["bad"] <= 0:
        return False
    _set_record(actor, record["ok"], record["bad"] - 1)
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=owner_id, target_ids=(actor.entity_id,),
                         payload={"rule": "failed_death_save_erased", "failures_before": record["bad"], "failures_after": record["bad"] - 1,
                                  "successes": record["ok"]})
    return True
