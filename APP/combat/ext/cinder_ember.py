"""Revealing Ember (Cinder Heart Cultivator, docs/specs/LIGHTING_SPEC.md §8.2).

A FIRE hit from a Cinder Touch attack that deals HP damage marks the target with the typed condition
"condition:fire.revealing_ember" until the start of the marking creature's next turn. The mark also sheds the Cinder
Touch row's printed Dim Light (combat/rules/light_sources.json) on that same clock, through
combat/ext/printed_light.py::shed.

Core names no ability here: the character adapter only reports the committed attack through the generic
"attack_damage_committed" seam, and this plug-in decides what that damage means for Revealing Ember.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .printed_light import shed

#: The passive that carries Revealing Ember on its owner.
EMBER = "passive:cinder.revealing_ember"
#: The condition the mark is filed as on the target.
MARK = "condition:fire.revealing_ember"
#: The Cinder Touch row whose curated light the mark sheds.
CINDER_TOUCH = "tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch"
#: The mark lasts until the marking creature's next turn starts.
EXPIRES_ON = "START_OF_SELF_NEXT_TURN"


@hook("attack_damage_committed")
def revealing_ember(engine: Any, target: Any, actor: Any, damage_type: str, hp_damage: int, source_id: str) -> None:
    """A Revealing Ember owner's FIRE attack that deals HP damage marks the living target and sheds its light."""
    if hp_damage <= 0 or damage_type != "FIRE" or EMBER not in actor.passive_ids or not target.active:
        return
    engine._apply_condition(target, MARK, EMBER, actor.entity_id, expires_on=EXPIRES_ON,
                            data={"revealed_to": actor.entity_id, "range_ft": 60})
    shed(engine, target, CINDER_TOUCH, EMBER, actor.entity_id, EXPIRES_ON)
    engine._append_event("PASSIVE_TRIGGERED", EMBER, actor_id=actor.entity_id, target_ids=(target.entity_id,))
