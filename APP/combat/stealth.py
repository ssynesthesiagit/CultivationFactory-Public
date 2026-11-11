"""Hiding and finding in a fight (owner 2026-09-27: "i dont see a way to do a stealth check").

The 2024 Hide action: a DC 15 Dexterity (Stealth) check while no enemy can see you -- heavily obscured (darkness, a thick
cloud), behind a wall of smoke or darkness, or out of its line of sight. On a success you are Hidden (the Invisible
condition: your attacks have Advantage, attacks against you Disadvantage), and the check's total is the DC to find you.
It ends when you make an attack roll or an enemy finds you: its Search action, a Wisdom (Perception) check against that
total -- with Disadvantage where sound is dimmed (Pure Darkness) -- or, a table ruling, when you end a move in plain view
of an enemy. Senses change who sees whom (combat/senses.py): Darkvision, Blindsight and Truesight within their range, and
a Search finds with no roll a hidden creature its senses reach.
"""

from __future__ import annotations

from typing import Any

from .gate2_runtime_models import ActorState

HIDDEN = "condition:typed.hidden"
HIDE_DC = 15


def hidden(actor: ActorState) -> str | None:
    """The instance of its Hidden condition, if it is hidden."""
    return next((iid for iid, condition in actor.conditions.items() if condition.condition_id == HIDDEN), None)


def sees(engine: Any, viewer: ActorState, target: ActorState) -> bool:
    """Whether the shared perception rules let ``viewer`` see ``target``."""
    from . import senses

    return senses.perceives(engine, viewer, target)


def foes(engine: Any, actor: ActorState) -> list[ActorState]:
    return [other for other in engine.state.actors.values() if other.active and other.team_id != actor.team_id]


def in_own_area(engine: Any, actor: ActorState, name: str | None) -> bool:
    """Whether it stands inside an area of its own of that kind (Hide in Darkness: "inside an area of your Darkness")."""
    from . import senses, zones

    if name and not senses.meld_active(engine, actor, "TAL_DARK_HIDE_IN_DARKNESS"):
        return False  # Hide in Darkness is a Meld: only while this fighter has Hide in Darkness's own Meld active. Several Melds may
                      # be active at once (owner 2026-09-29 struck the one-Meld rule); this asks only about this one (combat/senses.py).
    return bool(name) and any(zone.owner_id == actor.entity_id and str(zone.trigger_profile.get("name") or "").lower() == str(name).lower()
                              and zones._inside(engine, actor, zone) for zone in zones.typed_zones(engine))


def concealment_permission(engine: Any, actor: ActorState, inside: str | None = None) -> bool:
    """Live, ability-defined permission to Hide in lesser concealment.

    The same permission prevents movement from revealing an already hidden creature
    while the qualifying concealment remains. It does not bypass Search or senses.
    """
    from . import ext

    return in_own_area(engine, actor, inside) or any(ext.run_strict("hide_concealment_allowed", engine, actor))


def can_hide(engine: Any, actor: ActorState, inside: str | None = None) -> bool:
    """No enemy can see it -- or, with Hide in Darkness, it stands in its own Darkness ("even while clearly visible") --
    and it is not hidden already."""
    if not actor.active or hidden(actor) is not None:
        return False
    return concealment_permission(engine, actor, inside) or not any(sees(engine, foe, actor) for foe in foes(engine, actor))


def can_search(engine: Any, actor: ActorState) -> bool:
    return actor.active and any(hidden(foe) for foe in foes(engine, actor))


def reveal(engine: Any, actor: ActorState, source: str, why: str) -> None:
    iid = hidden(actor)
    if iid is None:
        return
    condition = actor.conditions.pop(iid)
    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": condition.condition_id, "instance_id": iid, "reason": why})


def after_move(engine: Any, mover: ActorState) -> None:
    """A hidden creature that ends a move where an enemy can see it is found (table ruling) -- not while it stays in the
    area it hid in with Hide in Darkness."""
    iid = hidden(mover)
    if iid is None or concealment_permission(engine, mover, (mover.conditions[iid].data or {}).get("inside")):
        return
    if any(sees(engine, foe, mover) for foe in foes(engine, mover)):
        reveal(engine, mover, "move", "seen")


def _check(engine: Any, actor: ActorState, bonus: int, mode: str, source: str, skill: str, dc: int | None = None):
    from . import ext  # a d20 floor on skill checks (Complete Mandala Auspice, combat/ext/d20_floor.py)

    roll = engine.roller.d20(modifier=bonus, actor_id=actor.entity_id, reason=f"CHECK:{source}:{skill}", mode=mode)
    engine._record_roll(roll)
    return ext.floored(engine, actor, roll, dc)


def hiding_denied(actor: ActorState, basis: tuple[str, ...]) -> bool:
    """Whether held rules deny every sense supporting this hiding attempt.

    Independent visual concealment survives a sound-only denial. Producers of
    exclusively auditory hiding must declare that basis explicitly.
    """
    from .typed_executor import condition_rules

    denied = {sense for row in condition_rules(actor) for sense in row.get("hiding_denied", [])}
    return bool(basis) and set(basis) <= denied


def hide(engine: Any, actor: ActorState, bonus: int, source: str, mode: str = "NORMAL", inside: str | None = None,
         *, basis: tuple[str, ...] = ("visual_concealment", "sound_reliance")) -> bool:
    """The Hide action: a Dexterity (Stealth) check against DC 15."""
    from .typed_executor import check_modes

    if not can_hide(engine, actor, inside) or hiding_denied(actor, basis):
        return False
    from . import ext  # Cooperative Stealth (eye 2026-09-28): an ally may use the leader's recorded check total instead

    override = next((value for value in ext.run("hide_check_override", engine, actor) if value is not None), None)
    if override is not None:
        total, success = int(override), int(override) >= HIDE_DC
        engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"dc": HIDE_DC, "success": success, "check": "Stealth", "shared_total": total})
    else:
        from . import motion

        # The one combat Stealth check is made to avoid being found, which this
        # engine models by sight and sound: its detection counterpart (the Search
        # check below) is hearing-sensitive, since muffled sound gives it
        # Disadvantage. Carrying both hazards lets a scoped check mode name
        # either sense (combat/ability_checks.SOUND_RELIANCE) without changing
        # what an unscoped one reaches.
        modes = check_modes(actor, "DEX", "Stealth", engine=engine, hazards=basis)
        # Denial removes an auditory hiding benefit, not an unrelated Stealth
        # bonus. Keep disadvantages and independently supported Advantage.
        denied_basis = tuple(sense for sense in basis if hiding_denied(actor, (sense,)))
        if denied_basis and "ADVANTAGE" in modes:
            independent = check_modes(actor, "DEX", "Stealth", engine=engine,
                                      hazards=tuple(sense for sense in basis if sense not in denied_basis))
            if "ADVANTAGE" not in independent:
                modes.discard("ADVANTAGE")
        modes.update(m for m in (mode, motion.hide_mode(engine, actor))
                     if m in ("ADVANTAGE", "DISADVANTAGE"))
        roll = _check(engine, actor, bonus, "NORMAL" if len(modes) != 1 else modes.pop(), source, "Stealth", HIDE_DC)
        total, success = roll.total, roll.total >= HIDE_DC
        engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": HIDE_DC, "success": success, "check": "Stealth"})
    if success:
        data = {"stealth_total": total,
                **({"hiding_basis": ",".join(basis)} if basis != ("visual_concealment", "sound_reliance") else {}),
                **({"inside": inside} if in_own_area(engine, actor, inside) else {})}
        engine._apply_condition(actor, HIDDEN, source, actor.entity_id, expires_on="UNTIL_REMOVED", data=data)
    return success


def search_modes(engine: Any, actor: ActorState, target: ActorState | None = None) -> set[str]:
    """Shared by ordinary Search and single-check Sweep; resolve only after all sources."""
    from . import ext, zones
    from .ability_checks import SOUND_RELIANCE
    from .typed_executor import check_modes

    # The engine's Perception check is made by sight and hearing: muffled
    # sound (Pure Darkness) already gives it Disadvantage, so it carries the
    # sound hazard and a scoped check mode may name hearing
    # (combat/ability_checks.SOUND_RELIANCE).
    modes = check_modes(actor, "WIS", "Perception", engine=engine, hazards=(SOUND_RELIANCE,))
    modes.update(m for m in ext.run("search_mode", engine, actor) if m in ("ADVANTAGE", "DISADVANTAGE"))
    if zones.muffled(engine, actor) or (target is not None and zones.muffled(engine, target)):
        modes.add("DISADVANTAGE")
    if target is not None:
        modes.update(m for m in ext.run("stealth_search_mode", engine, actor, target)
                     if m in ("ADVANTAGE", "DISADVANTAGE"))
    return modes


def resolved_search_mode(engine: Any, actor: ActorState, target: ActorState | None = None) -> str:
    """Cancel opposing modes once, including target-qualified protections."""
    modes = search_modes(engine, actor, target)
    return next(iter(modes)) if len(modes) == 1 else "NORMAL"


def pending_search_modes(engine: Any, actor: ActorState, target: ActorState, source: str) -> set[str]:
    """Resolve optional target reactions only for a check that will actually roll.

    Pure Search previews continue to use search_modes. Pending callbacks may
    pause/spend; their modes join ordinary contributions before cancellation.
    """
    from . import ext

    modes = search_modes(engine, actor, target)
    for reply in ext.run_strict("stealth_search_before_roll", engine, actor, target, source):
        if reply not in ("ADVANTAGE", "DISADVANTAGE"):
            raise ValueError("stealth_search_before_roll requires an attack-style roll mode")
        modes.add(reply)
    return modes


def search_roll_view(roll: Any, mode: str) -> Any:
    """Single-check Search consumers reuse dice, never reroll for a different target.

    A normal view uses the first die; Advantage/Disadvantage uses the max/min.
    Preserve any total adjustment made by the shared d20 rewrite callback.
    Consumers apply skill floors after selecting their view.
    """
    if mode == roll.mode:
        return roll
    natural = roll.dice[0] if mode == "NORMAL" else (max(roll.dice) if mode == "ADVANTAGE" else min(roll.dice))
    original = roll.dice[0] if roll.mode == "NORMAL" else (max(roll.dice) if roll.mode == "ADVANTAGE" else min(roll.dice))
    if roll.natural_result != original:
        natural = int(roll.natural_result)  # a shared rewrite replaces the check, not just one target's view
    delta = roll.total - int(roll.natural_result or 0) - roll.modifier
    discarded = () if mode == "NORMAL" else (min(roll.dice) if mode == "ADVANTAGE" else max(roll.dice),)
    return roll.model_copy(update={"mode": mode, "natural_result": natural,
                                  "total": natural + roll.modifier + delta, "discarded": discarded})


def search(engine: Any, actor: ActorState, bonus: int, source: str) -> list[str]:
    """The Search action: a Wisdom (Perception) check against each hidden enemy's Stealth total; the ones it beats are
    found. Where sound is dimmed around either of them (Pure Darkness) the check has Disadvantage."""
    found = []
    for foe in foes(engine, actor):
        iid = hidden(foe)
        if iid is None:
            continue
        dc = int((foe.conditions[iid].data or {}).get("stealth_total") or HIDE_DC)
        from . import senses

        if senses.finds(engine, actor, foe):
            # Blindsight or Truesight sees it, Tremorsense pinpoints it (proposed ruling, combat/rules/senses.json): found.
            engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(foe.entity_id,),
                                 payload={"dc": dc, "success": True, "check": "Perception", "by_sense": senses.summary(engine, actor)})
            reveal(engine, foe, source, "found")
            found.append(foe.entity_id)
            continue
        modes = pending_search_modes(engine, actor, foe, source)
        roll = _check(engine, actor, bonus, next(iter(modes)) if len(modes) == 1 else "NORMAL", source, "Perception", dc)
        success = roll.total >= dc
        engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(foe.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "check": "Perception"})
        if success:
            reveal(engine, foe, source, "found")
            found.append(foe.entity_id)
    return found
