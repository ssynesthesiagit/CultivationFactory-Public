"""Read the Sky's Battle Reading of the caster's own live Weather Signs.

The native Mantle/Shroud conditions and Gather fields are the fact producers;
no ambient weather, forecast, hidden opponent effect or sign ownership is
inferred. Immediate/Careful Reading and ambient signs still need an authoritative
table weather input. This is intentionally partial coverage of the base row.

Uses the existing technique_final hook: after a resolved Weather cast, an owner
of Read the Sky may identify one sign, without another action or payment. The
choice uses only information already established by that owner's own effects.
No new state, hook, acquisition rule or duplicate Weather implementation.
"""
from __future__ import annotations

from . import hook, note
from .needle import CHOICE, ask, checkpoint_id

BASE = "WEATHER_BASE_READ_THE_SKY"
CHOICE_ID = CHOICE + "weather_battle_reading"


def placed_signs(engine, actor):
    """Return all live signs placed by this caster in the current combat scene.

    Public reader for Weather information consumers. Uses the public producer
    APIs, not another plug-in's private state. Own placements are positive
    evidence only: an empty result says nothing about natural or hidden weather.
    """
    from . import weather_fields, weather_mantle, weather_shroud, weather_signs

    found = set()
    for holder in engine.state.actors.values():
        if not holder.active:
            continue
        for mantle in weather_mantle.all_mantles(holder):
            if mantle.source_actor_id == actor.entity_id:
                found.add(weather_mantle.sign_of(mantle))
        for shroud in weather_shroud.shrouds(holder, actor.entity_id):
            found.add(weather_shroud.sign_of(shroud))
    for field in weather_fields.fields(engine, actor):
        found.update(sign for sign, severity in weather_fields.signs(field).items()
                     if int(severity) >= 1)
    return [sign for sign in weather_signs.names() if sign in found]


@hook("technique_final")
def battle_reading(ctx):
    """Default-inert aftermath: only an owned Read the Sky and Weather cast qualify."""
    from ..alternative_payments import owned
    from . import weather_signs

    if ctx.typed.get("sphere") != weather_signs.SPHERE or not owned(ctx.engine, ctx.actor, BASE):
        return
    # Read the Sky itself is a reading, rather than a cast that places weather.
    if ctx.typed.get("source") == BASE:
        return
    options = placed_signs(ctx.engine, ctx.actor)
    if not options:
        return
    selected = ask(
        ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "WEATHER_BATTLE_READING"),
        ctx.actor, CHOICE_ID, options, allow_decline=True,
        labels={sign: weather_signs.sign(sign)["name"] for sign in options},
        name="Read the Sky — Battle Reading", feature_id=BASE,
        prompt=(f"Read the Sky — Battle Reading: after casting {ctx.action.display_name}, "
                f"{ctx.actor.display_name} may identify one active Weather Sign placed by their "
                "own Mantle, Shroud, or Gather Weather in this scene. This uses no additional "
                "action or Cultivation Points. Other weather remains unknown."),
        prompt_context={"cost": "No additional action or Cultivation Points"})
    if not selected:
        return
    sign = selected[0]
    note(ctx.engine, BASE, ctx.actor,
         f"Read the Sky — Battle Reading: {ctx.actor.display_name} identifies "
         f"{weather_signs.sign(sign)['name']} as active in this scene. "
         "No additional action or Cultivation Points are spent.",
         reading="battle", sign=sign, triggering_source=ctx.source)
