"""A printed hit whose type the owner of the feature chooses, one choice per hit ("chosen for that hit").

A passive on-hit damage row that lists more than one type and carries `owner_chooses_type` (feature_blocks.d) asks its
owner -- through the shared needle choice, so a player-controlled owner answers on their own turn and an AI owner resolves
automatically -- which listed type this hit deals. The automatic answer is the type that lands hardest on the targets
(typed_executor.choose_damage_type), the same pick the table made before the choice existed. Nothing here knows a
feature: the compiled row names the choice and its source. Inert for every other damage row.
"""

from __future__ import annotations

import re
from typing import Any

from . import hook


@hook("owner_damage_type_choice")
def owner_damage_type(ctx: Any, effect: dict[str, Any], kinds: list[str], targets: list[Any]) -> str | None:
    if not effect.get("owner_chooses_type") or len(kinds) < 2:
        return None
    from ..typed_executor import choose_damage_type
    from .needle import CHOICE, ask

    best = choose_damage_type(ctx, list(kinds), list(targets))
    name = str(effect.get("source_name") or "Feature")
    slug = re.sub(r"[^a-z0-9_]+", "_", str(effect.get("source_feature") or name).lower())
    picked = ask(ctx.engine, ctx.intent, "TECHNIQUE_USE", ctx.actor, CHOICE + "owner_damage_type." + slug,
                 list(kinds), labels={kind: f"{kind.title()} damage" for kind in kinds}, preferred=[best],
                 name=name, feature_id=str(effect.get("source_feature") or ""),
                 prompt=f"{name}: choose the damage type of this hit: {' or '.join(kind.title() for kind in kinds)}. "
                        "The additional damage is part of the hit.")
    return picked[0] if picked else best
