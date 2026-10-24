"""Shared readied Qualifying Pair eligibility, queried without changing saved state.

qualifying_pair serves martial_dual_wielding's Focusing Defense and critical_hits.
qualifying_pairs serves zz_dual_wielding's Cyclone, Asynchronous and High-Low.
Return physical weapon identities only; ordinary dice/types belong to consumers.
"""
from __future__ import annotations

import itertools
import re
from typing import Any


def qualifying_pairs(engine: Any, actor: Any) -> list[tuple[str, str]]:
    """Enumerate allowed readied melee Lead weapons, including a Paired weapon itself."""
    from .hand_occupancy import weapon_grips, weapon_allowed
    singles = []
    pairs = []
    for identity, hands in weapon_grips(engine, actor).items():
        action = engine.action_catalog.get(identity)
        if action is None or weapon_allowed(engine, actor, action) is False:
            continue
        typed = action.parameters.get('typed') or {}
        properties = str((typed.get('weapon') or {}).get('properties') or '')
        if (typed.get('pair_role') != 'lead' or typed.get('range_ft')
                or re.search(r'\bTwo-Handed\b', properties, re.I)):
            continue
        if re.search(r'\bPaired\b(?! Method)', properties, re.I):
            pairs.append((identity, identity))
        elif hands == 1:
            singles.append(identity)
    return pairs + list(itertools.combinations(singles, 2))


def qualifying_pair(engine: Any, actor: Any) -> bool:
    """Whether any readied Qualifying Pair exists, using the same enumeration."""
    return bool(qualifying_pairs(engine, actor))
