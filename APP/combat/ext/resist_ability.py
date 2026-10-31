"""A creature that resists ONE ability of one creature for a time after it saved against it (rider lane 3, 2026-09-29).

  resist_ability  {"applies_to": "target", "mode": "advantage" | "immune", "duration": {"kind": "minutes", "amount": 10}}

"A creature that succeeds on this saving throw has Advantage on saving throws against your Catch the Eye for 10 minutes" (Catch the Eye); "A creature that
succeeds on its initial saving throw is immune to your Beauty Beyond Form for 24 hours" (Beauty Beyond Form); "Once a creature succeeds on a saving throw
against this talent, it is immune to your Beauty That Ends War for 24 hours"; "On a successful save, it is immune to this aura until the start of your next
turn" (Lotus Court Aura).  Both belong to the ability the row sits in and to the creature that used it: the condition
``condition:typed.resist_ability`` on the saver remembers the ability and who used it (the condition's source).

advantage   the saver's saving throws against that ability from that creature have Advantage (the ``save`` hook, typed_executor.block_save).
immune      the ability does nothing to it: its saving throw is not rolled and none of the effects hang from it (the ``save_gate`` hook); a single-target
            use aimed at it is not offered (``candidate_allowed``).
A night (24 hours) is the rest of the fight; ten minutes is the rounds it stands for on the round clock.
The shared public resists helper also filters extra_targets before its target menu;
source_ability is shared with charm_rules' repeated-save immunity.
"""
from typing import Any

from . import effect, hook

CONDITION = "condition:typed.resist_ability"


def ability_id(ctx: Any) -> str:
    """One printed ability across its compiled augment variants."""
    return str(ctx.typed.get("source") or ctx.source)


def source_ability(engine: Any, source: str) -> str:
    action = engine.action_catalog.get(source)
    return str((((action.parameters or {}).get("typed") or {}).get("source") if action is not None else None) or source)


@effect("resist_ability")
def resist_ability(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    mode = str(row.get("mode") or "advantage").lower()
    for subject in _default_subject(ctx, row, harmful=False):
        if subject.active:
            ctx.engine._apply_condition(
                subject, CONDITION, ctx.source, ctx.actor.entity_id,
                expires_on=effect_expiry(ctx, row, subject, condition=True) or "UNTIL_REMOVED",
                data={"ability": ability_id(ctx), "mode": mode,
                      "label": ("Immune to" if mode == "immune" else "Advantage on saves against") + f" {ctx.actor.display_name}'s {row.get('name') or 'ability'}"})


def resists(ctx_actor_id: str, subject: Any, source: str, mode: str) -> bool:
    """Whether this subject resists this ability from this particular caster."""
    return any(c.condition_id == CONDITION and c.source_actor_id == ctx_actor_id and (c.data or {}).get("ability") == source
               and (c.data or {}).get("mode") == mode for c in subject.conditions.values())


@hook("save")
def save_mode(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if resists(ctx.actor.entity_id, subject, ability_id(ctx), "advantage"):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("save_gate")
def unaffected(ctx: Any, subject: Any) -> bool | None:
    return False if resists(ctx.actor.entity_id, subject, ability_id(ctx), "immune") else None


@hook("candidate_allowed")
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    aimed = [engine.state.actors.get(target_id) for target_id in candidate.target_ids or ()]
    if len(aimed) == 1 and aimed[0] is not None and resists(actor.entity_id, aimed[0], source_ability(engine, candidate.source_definition_id), "immune"):
        return False
    return None
