"""Radiant Rivalry: choose a Beauty-Marked creature, hold one Rivalry Mark, optionally spend it before a Beauty save.

Owner rules_text.json, tianxia.talent.beauty.radiant_rivalry. The free self action asks the existing bounded choice
transport for one marked creature; evented conditions remember the chosen creature and the single Rivalry Mark.
Typed active saves use save/after_save hooks. Generic reactions have a separate save interpreter and remain a rider,
as do social checks and the GM's classification of a 'Beauty-related' attack roll. No numbers or ranges are inferred.
"""
from typing import Any

from . import effect, hook

WATCH = "condition:typed.rivalry_watch"
MARK = "condition:typed.rivalry_mark"
ID = "tianxia.talent.beauty.radiant_rivalry"


@hook("compile_actions")
def actions(info: dict[str, Any]) -> list[Any] | None:
    row = info["mechanics"].get(ID) or {}
    if ID not in info["owned_ids"] or not any(e.get("type") == "rivalry_watch" for e in row.get("effects") or []):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.radiant_rivalry", display_name="Radiant Rivalry",
                             owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             parameters={"typed":{"source":ID,"effects":row["effects"],"riders":row.get("riders") or [],
                                                  "numbers":info["numbers"],"duration":{"kind":"instant"}},
                                         "player_only":True,"expected_damage":0})]


def _held(actor: Any, name: str):
    return next(((iid, held) for iid, held in actor.conditions.items() if held.condition_id == name), None)


def _remove(engine: Any, actor: Any, iid: str, held: Any) -> None:
    del actor.conditions[iid]
    engine._append_event("CONDITION_REMOVED", held.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"instance_id": iid, "condition_id": held.condition_id})


def _put(engine: Any, actor: Any, name: str, source: str, target_id: str) -> None:
    old = _held(actor, name)
    if old:
        _remove(engine, actor, *old)
    engine._apply_condition(actor, name, source, actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"target_id": target_id, "label": "Radiant Rivalry: " + engine.state.actors[target_id].display_name})


@effect("rivalry_watch")
def choose(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from ..typed_executor import bears_mark

    options = sorted(other.entity_id for other in ctx.engine.state.actors.values() if other.active and bears_mark(other, ctx.actor.entity_id, "Beauty Mark"))
    ids = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "RIVALRY_WATCH", ctx.source), ctx.actor,
                     "choice:needle.rivalry_watch", options,
                     labels={key: ctx.engine.state.actors[key].display_name for key in options},
                     prompt=f"Radiant Rivalry: {ctx.action.display_name} — choose a creature bearing your Beauty Mark", maximum=1,
                     name="Radiant Rivalry", allow_decline=True)
    if ids:
        _put(ctx.engine, ctx.actor, WATCH, ctx.source, ids[0])


def _beauty(ctx: Any) -> bool:
    source = str(ctx.typed.get("source") or "")
    return source.startswith("BEAUTY_BASE_") or source.startswith("tianxia.talent.beauty.")


@hook("after_save_resolved")
def earn(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    watch = _held(ctx.actor, WATCH)
    if not failed and _beauty(ctx) and watch and watch[1].data.get("target_id") == subject.entity_id:
        _put(ctx.engine, ctx.actor, MARK, watch[1].source_definition_id, subject.entity_id)


@hook("save")
def spend(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    mark = _held(ctx.actor, MARK)
    if not _beauty(ctx) or not mark or mark[1].data.get("target_id") != subject.entity_id:
        return None
    from . import needle

    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "RIVALRY_SAVE", ctx.source, subject.entity_id), ctx.actor,
                        "choice:needle.rivalry_spend", ["SAVE_DC_PLUS_2"], labels={"SAVE_DC_PLUS_2": "Increase save DC by 2"},
                        prompt=f"Radiant Rivalry: {ctx.action.display_name} — spend the mark against {subject.display_name} for +2 save DC?",
                        name="Radiant Rivalry", target_id=subject.entity_id, maximum=1, allow_decline=True)
    if not chosen:
        return None
    _remove(ctx.engine, ctx.actor, *mark)
    return {"bonus": -2, "modes": []}  # block_save subtracts the target's bonus from the DC
