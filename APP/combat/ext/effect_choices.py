"""Shared post-resolution choices for Listening Sutra checks and Nail saves.

``choose_effects`` selects exactly ``count`` distinct labeled effect bundles.
The existing Needle checkpoint carries the owned actor's decision and pauses
transactional previews; AI owners select automatically. Absent an owned typed
source or target, the effect is inert (a generic reaction row's own feature id
counts as its source). No persistent choice state is introduced.
``preference_menu`` supplies standing menu picks as AI/default preferences only;
player owners still choose at resolution. ``result`` names the resolved outcome
in the prompt (default: succeeded), without changing any mechanics. Optional ``display_label`` explains each option while
its ``label`` remains the stable selection key for saved choices.

Active zone triggers may opt into the existing AI-step probe with
``choice_owner: "source"`` (the zone owner) or ``"recipient"`` (potential
recipients). This pure query enrolls controllers only; the actual trigger still
checks its recipient, timing and available choices. Recipient enrollment uses
the roster rather than hidden positions, and does not choose for the AI.
Unmarked saved triggers retain their prior enrollment behavior.
"""
from typing import Any

from . import effect, hook


@effect("choose_effects")
def choose_effects(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .needle import CHOICE, ask, checkpoint_id
    from .menus import picks

    # A generic reaction's context (typed_reactions.triggered_context) has no typed source: its own feature id stands in
    # (rider lane C14: Smothering Mandate on Smother the Breath, Flaw Within the Golden Technique).
    if not (ctx.typed.get("source") or (ctx.typed.get("reaction_attack") and ctx.source)) or ctx.target is None:
        return
    options = {str(row["label"]): row for row in eff.get("options") or []}
    if not options:
        return
    count = min(len(options), max(1, int(eff.get("count") or 1)))
    name = str(eff.get("name") or ctx.action.display_name)
    preferred = picks(ctx.engine, ctx.actor, str(eff["preference_menu"])) if eff.get("preference_menu") else None
    # The question names the ability, the creature it landed on and what the printed moment was. A
    # Reaction's own name is not repeated as its own trigger, and "one" reads as one choice rather
    # than a count of options.
    against = ctx.target.display_name
    moment = str(eff.get("result") or "succeeded")
    heading = f"{name}: " if ctx.action.display_name == name else f"{name} ({ctx.action.display_name}): "
    pick = "Choose one:" if count == 1 else f"Choose {count} of them:"
    picked = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, "effect_choices", ctx.actor.entity_id, ctx.source, ctx.target.entity_id),
        ctx.actor, CHOICE + "effect_choices", list(options), minimum=count, maximum=count,
        name=name, target_id=ctx.target.entity_id, preferred=preferred,
        labels={label: str(row["display_label"]) for label, row in options.items() if row.get("display_label")},
        prompt=f"{heading}{against} {moment}. {pick}")
    for label in picked:
        run_effects(ctx, [dict(row) for row in options[label].get("effects") or []])


@hook("choice_reactors")
def zone_choice_owners(engine: Any) -> tuple[str, ...]:
    """Potential owners of explicit, persisted zone-trigger choices.

    No ability IDs or prose inference. The service filters this result by each
    actor's recorded control mode before probing an AI action for player input.
    """
    owners = set()
    for zone in engine.state.zones.values():
        if not zone.active:
            continue
        for trigger in (zone.trigger_profile or {}).get("triggers") or []:
            if not isinstance(trigger, dict):
                continue
            owner = trigger.get("choice_owner")
            if owner == "source" and zone.owner_id in engine.state.actors:
                owners.add(zone.owner_id)
            elif owner == "recipient":
                owners.update(engine.state.actors)
    return tuple(sorted(owners))
