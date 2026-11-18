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
    from .choice_prompt import action_context
    from .needle import CHOICE, ask

    best = choose_damage_type(ctx, list(kinds), list(targets))
    name = str(effect.get("source_name") or "Feature")
    target = targets[0] if targets else None
    slug = re.sub(r"[^a-z0-9_]+", "_", str(effect.get("source_feature") or name).lower())
    # The prompt names the feature, the action it rides on and the creature hit, as every owner prompt does (rule 9).
    hit_on = target.display_name if target is not None else "a creature"
    picked = ask(ctx.engine, ctx.intent, "TECHNIQUE_USE", ctx.actor, CHOICE + "owner_damage_type." + slug,
                 list(kinds), labels={kind: f"{kind.title()} damage" for kind in kinds}, preferred=[best],
                 target_id=target.entity_id if target is not None else None, name=name,
                 feature_id=str(effect.get("source_feature") or ""),
                 prompt=f"{name}: your {ctx.action.display_name} hits {hit_on}. Choose the damage type of this hit: "
                        f"{' or '.join(kind.title() for kind in kinds)}. The additional damage is part of the hit.",
                 prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, target) if target is not None else None)
    return picked[0] if picked else best
