"""Shared helpers for the pool a printed "CP" belongs to, at build time and in a live fight.

Shared helper module: ``talismans`` (Qi Storage Talisman spend, regen and wall costs) and
``yang_recovery`` (Yang's Furnace Backlash 1-CP payment) both resolve a printed "CP" through
``of``/``restore_pool`` instead of assuming Qi, so one fighter's Path pool is resolved the same
way wherever a printed rule says "CP".

Many printed rules name no pool at all -- "regain CP equal to the amount stored, up to its normal
maximum" (Qi Storage Talisman), "Cost: 1 CP per talisman used" (Talisman Wall), "cannot spend that
Path's resource" (Dao-Sealing Talisman).  "CP" is this game's Path pool, and it is not always
``resource:core.qi``: a Body Refining fighter's Path pool is Stamina and a Spirit Awakening fighter's
is Resonance (``typed_executor.CP_POOLS``).  Assuming Qi leaves those fighters trying to spend or
regain a pool they do not have -- ``gate2_engine._gain_resource``/``_spend_resource`` raise
``ValueError("unknown resource")`` and the button the table offered them takes the table down.

Two questions, two answers:

* **In a fight** ask the fighter.  ``of(actor)`` is their real Path pool, read from the pools they
  actually hold, so it is right for Qi, Stamina and Resonance fighters alike, and ``None`` when they
  have no Path pool at all (a caller must then decline cleanly, never fall back to a guess).
  ``restore_pool(actor, recorded)`` honours a pool an older saved catalog recorded *only when the
  fighter really has it*, so a saved fight keeps paying into the pool it was compiled for.
* **While compiling** there is no fighter yet, only the character sheet, and the ``compile_action``
  hook is not even given the ``primary`` name (``factory_compiler`` supplies ``pools`` to
  ``compile_actions`` only).  ``build_pool(info)`` therefore returns ``None`` rather than guessing,
  and the effect resolves the real pool at use time.

Tie-break, when a fighter holds more than one Path pool: the fixed ``CP_POOLS`` order (Qi, Stamina,
Resonance), so the same fighter always resolves the same way in the same fight and replays stay
byte-identical.  A fighter with one Path pool -- the normal case -- has no tie to break.

Used by ``combat/ext/talismans.py`` (Qi Storage Talisman restore, Talisman Wall payment,
Dao-Sealing Talisman), ``combat/ext/healing_interception.py`` (Stillness Has Teeth payment),
and ``combat/ext/water_defenses.py`` (Water Whip and Water Shield payment).
Any other plug-in that needs a fighter's real Path pool should use this
module rather than repeating the four-key ``RESOURCE_IDS`` lookup.
"""

from __future__ import annotations

from typing import Any

QI = "resource:core.qi"
STAMINA = "resource:core.stamina"
RESONANCE = "resource:core.resonance"


def path_pool_ids() -> tuple[str, ...]:
    """The pools a printed "CP" may mean, in the fixed tie-break order (the engine's own list)."""
    from ..typed_executor import CP_POOLS

    return tuple(CP_POOLS)


def all_of(actor: Any) -> tuple[str, ...]:
    """Every Path pool this fighter really holds, in the fixed tie-break order."""
    pools = path_pool_ids()
    held = getattr(actor, "resources", None) or {}
    return tuple(pool for pool in pools if pool in held or held.get(pool, 0) > 0)


def of(actor: Any, *, at_least: int = 0) -> str | None:
    """This fighter's Path pool, or None when they have none (or none with ``at_least`` to spend).

    ``at_least`` asks for a pool that can actually cover a payment; a gain should pass 0, because a
    full pool is still a legal place to restore into (the engine caps the gain at the maximum).
    """
    held = getattr(actor, "resources", None) or {}
    if at_least > 0:
        return next((pool for pool in all_of(actor) if int(held.get(pool, 0)) >= int(at_least)), None)
    return all_of(actor)[0] if all_of(actor) else None


def restore_pool(actor: Any, recorded: Any) -> str | None:
    """Where a "regain CP" gain belongs: a saved catalog's recorded pool when the fighter has it,
    else the fighter's own Path pool, else None (the caller declines; it must not invent a pool)."""
    pool = str(recorded or "")
    if pool and (pool in (getattr(actor, "resources", None) or {}) or pool in (getattr(actor, "resource_maximums", None) or {})):
        return pool
    return of(actor)


def build_pool(info: dict[str, Any] | None) -> str | None:
    """A Path pool the character sheet declares, or None.

    ``info`` is a ``compile_actions`` info dict, whose ``pools`` maps Path pool *names* to their
    printed maximum.  Returns None rather than defaulting to Qi, so a compiler that cannot see the
    fighter's pools leaves the decision to use time (see the module docstring).
    """
    from ..factory_compiler import RESOURCE_IDS

    pools = (info or {}).get("pools") or {}
    for name, resource_id in RESOURCE_IDS.items():
        if name in pools and resource_id in path_pool_ids():
            return resource_id
    return None
