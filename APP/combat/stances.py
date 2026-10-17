"""Forms and stances (owner 2026-09-28: "we need to automate every aspect before another playtest"): a technique that says
"for the duration: once per turn, when you hit with ..., add ..." -- the Unmaking Ruin Forms first. Using it applies a
stance on its user for its duration; while it lasts, each hit that fits a rider runs that rider (once a turn where the text
says so), and a rider "at the end of each of your turns in which you damaged a creature with this form" runs then.

A typed stance effect: {"type": "stance", "name", "rounds", "hit_riders": [{"attack_kinds": ["unarmed"|"weapon"|"any"],
"once_per_turn": bool, "effects": [...]}], "end_of_turn_if_damaged": [...], "ruin_channel_bonus": "pb"}.
Optional (rider lane C5, Fourth Ruin Form): a hit rider's "melee_only": true skips ranged attacks and its "surge_effects" replace
its effects once the stance's data carries "surge" (combat/ext/unmaking_forms.surge re-applies the stance with it after a Ruin
Backlash); "end_of_turn": [...] rows run at the end of each of the user's turns whether or not it damaged anyone; "on_end": [...]
rows run on the user when the stance's duration runs out, and "unarmed_ruin": true lets its Unarmed Strikes deal Ruin (Force)
damage ("melee_ruin": its melee weapon attacks too; both combat/ext/unmaking_forms.py). A hit rider's "weapon_words" limits it to
weapons whose name has one of the words ("saber", "dao") or to the "or_sphere" sphere's own techniques, its "if_target" ({"marks", "conditions", "bloodied"}) to a target in one
of those states, checked before the once-per-turn use is spent (Execution Platform Presence); "kill_ends_frightened_ft" is read by
combat/ext/sabers_riders.py.
"""

from __future__ import annotations

import json
import re
from typing import Any

PREFIX = "condition:typed.stance."


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_") or "stance"


def slug(name: str) -> str:
    """The stance condition's id suffix for a form's printed name (public: combat/ext/unmaking_forms.py)."""
    return _slug(name)


def active(actor: Any) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id.startswith(PREFIX)]


def start(ctx: Any, effect: dict[str, Any]) -> None:
    name = str(effect.get("name") or ctx.action.display_name)
    condition_id = PREFIX + _slug(name)
    ctx.engine._remove_condition(ctx.actor, condition_id, ctx.source)
    rounds = int(effect.get("rounds") or 10)
    ctx.engine._apply_condition(ctx.actor, condition_id, ctx.source, ctx.actor.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + rounds}",
                                data={"label": name, "name": name, "hit_riders": effect.get("hit_riders") or [],
                                      "end_of_turn_if_damaged": effect.get("end_of_turn_if_damaged") or [],
                                      **{key: effect[key] for key in ("end_of_turn", "on_end", "unarmed_ruin", "melee_ruin", "kill_ends_frightened_ft") if effect.get(key)},
                                      "ruin_channel_bonus": effect.get("ruin_channel_bonus"), "source": ctx.source})


def _fits(rider: dict[str, Any], kind: str) -> bool:
    kinds = rider.get("attack_kinds") or ["any"]
    return "any" in kinds or kind in kinds


def after_hit(ctx: Any, target: Any, *, kind: str) -> None:
    """``kind``: "unarmed" (an Unarmed Strike or natural weapon), "weapon" or "other"."""
    from .typed_executor import Context, run_effects

    for condition in active(ctx.actor):
        data = condition.data or {}
        for index, rider in enumerate(data.get("hit_riders") or []):
            if not target.active or not _fits(rider, kind):
                continue
            if rider.get("melee_only"):
                from .typed_executor import ranged_attack_now

                if ranged_attack_now(ctx):
                    continue
            words = rider.get("weapon_words")
            if words and not any(word in str(ctx.action.display_name).lower() for word in words) \
                    and not (rider.get("or_sphere") and ctx.typed.get("sphere") == rider["or_sphere"]):
                continue
            if rider.get("if_target") and not _target_state(ctx, target, rider["if_target"]):
                continue
            flag = f"stance_hit:{condition.condition_id}:{index}"
            if rider.get("once_per_turn") and ctx.actor.turn_flags.get(flag):
                continue
            ctx.actor.turn_flags[flag] = True
            ctx.actor.turn_flags[f"stance_damaged:{condition.condition_id}"] = True
            ctx.engine._append_event("PASSIVE_TRIGGERED", condition.source_definition_id,
                actor_id=ctx.actor.entity_id, target_ids=(target.entity_id,),
                payload={"text": f"{ctx.actor.display_name}'s {data.get('name')} adds {rider.get('label') or 'its hit effect'} to the hit on {target.display_name}."})
            run_effects(ctx.on_hit_context(target, typed={**ctx.typed, "source": data.get("source")}).with_source(condition.source_definition_id),
                        json.loads(json.dumps((data.get("surge") and rider.get("surge_effects")) or rider.get("effects") or [])))


def _target_state(ctx: Any, target: Any, want: dict[str, Any]) -> bool:
    """A rider's "if_target": the target bears one of the user's named marks, one of the typed conditions, or is Bloodied."""
    from .typed_executor import mark_condition_id

    ids = {f"condition:typed.{name}" for name in want.get("conditions") or []} | {mark_condition_id(name, ctx.actor.entity_id) for name in want.get("marks") or []}
    return (bool(want.get("bloodied")) and target.current_hp * 2 <= target.maximum_hp) or any(c.condition_id in ids for c in target.conditions.values())


def on_turn_ended(engine: Any, actor: Any) -> None:
    """"At the end of each of your turns in which you damaged a creature with this form" (Second Ruin Form: 1 Strain)."""
    for condition in active(actor):
        data = condition.data or {}
        for effect in data.get("end_of_turn") or []:
            if effect.get("type") == "gain_resource" and effect.get("resource_id") in actor.resources:
                engine._gain_resource(actor, effect["resource_id"], int(effect.get("flat") or 1), condition.source_definition_id)
        if data.get("end_of_turn_if_damaged") and actor.turn_flags.get(f"stance_damaged:{condition.condition_id}"):
            for effect in data["end_of_turn_if_damaged"]:
                if effect.get("type") == "gain_resource" and effect.get("resource_id") in actor.resources:
                    engine._gain_resource(actor, effect["resource_id"], int(effect.get("flat") or 1), condition.source_definition_id)


def ruin_channel_bonus(actor: Any, pb: int) -> int:
    return sum(pb for c in active(actor) if (c.data or {}).get("ruin_channel_bonus") == "pb")
