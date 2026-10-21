"""Pressure Points sphere: Precision Contact, Touch the Point, and the Point/Seal talents it carries
(owner 2026-09-28, "automate every aspect before another playtest"). Shi Xunyun.

Precision Contact and Touch the Point are base sphere abilities (granted by Pressure Points Training) that
never made it into the typed mechanics authority: their headers ("### Precision Contact", "### Touch the
Point" in 09_RULES/Source_Text/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md, lines 62224 and 62258) sit
before the sphere's own "## BASE SPHERE ABILITIES" section the authority builder keys its id prefix on, so
PRESSURE_POINTS_BASE_TOUCH_THE_POINT etc. were never extracted -- confirmed by grepping the source text and
the built authority. Reviewed_final.d cannot add a brand-new id (tools/build_typed_mechanics_authority.py
skips a reviewed entry whose id it does not already know), and fixing the shared extractor's heading rule is
out of scope for a single character's pass, so this module implements the loop directly instead:

  Precision Contact -- "Replace one attack when you take the Attack action... [with] the Damage option of an
  Unarmed Strike; a light or finesse melee weapon...; or an approved pressure tool... Hit: deal the attack's
  normal damage. You may then use Touch the Point." It adds no damage of its own, so no new action is added:
  any of the character's own melee hits (after_hit's ``kind`` "unarmed" or "weapon", range 5 ft) already is
  one. This is a small simplification -- a heavy, non-finesse two-handed weapon would not truly qualify --
  noted here since Shi Xunyun's own weapons are the Dual Wielding sphere's light/paired pair and always do.

  Touch the Point -- "Once per turn, when you hit a creature with Precision Contact... choose one: Apply a
  Point... Close a Seal (if the target already bears one of your Pressure Points)... [or] Read the Body."
  Read the Body (Reading Touch) has no fight-state effect (it only reveals information a GM answers) and is
  not offered as an automated choice. Apply/Close are: mark the target ("a Pressure Point lasts until the
  end of your next turn") and run the picked Point talent's own typed effects, or -- if the target already
  bears the mark -- remove it and run the picked Seal talent's own typed effects. Each Point/Seal talent's
  own effects come straight from the typed mechanics authority (read once there, at fight time, via
  _mechanics() below) so its printed text is never re-typed or duplicated in this file.

  The player's pick (which Point, which Seal) is a sticky toggle, the same convention as
  combat/typed_executor.py's EXPLOIT_PICK/OPEN_THE_GATE: a free (EconomyKind.NONE, player_only) action sets a
  condition holding the choice; the built-in AI's default is the first option in each list below.

Shared helper module (consumers: combat/ext/pressure_points.py): ``apply_point(ctx, target)`` applies the picked Point.

combat/rules/feature_blocks.d/shi.json (and riders_c2.json) marks each Point/Seal talent the character knows with a "shi_pp_point"
/ "shi_pp_point_options" (Numbing Point's four) / "shi_pp_seal" block, so this only runs for a character who
actually knows the talent in question."""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

POINT_PICK = "condition:typed.shi_pp_point_pick"
MODE_PICK = "condition:typed.shi_pp_mode_pick"
SEAL_PICK = "condition:typed.shi_pp_seal_pick"
PRESSURE_POINT_MARK = "Pressure Point"

_MECHANICS_CACHE: dict[str, Any] | None = None


def _mechanics() -> dict[str, Any]:
    """The typed mechanics authority's own ``mechanics`` dict, read once per process (it does not change
    while a fight runs) so Point/Seal talents' printed effects are read from their one authored place."""
    global _MECHANICS_CACHE
    if _MECHANICS_CACHE is None:
        import json

        from .. import factory_compiler as fc

        _MECHANICS_CACHE = json.loads(fc.TYPED_AUTHORITY.read_bytes())["mechanics"]
    return _MECHANICS_CACHE


def _slug(text: str | None) -> str:
    return "_".join(str(text or "").lower().split())


@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block == "shi_pp_point_options":
        mechanic = _mechanics().get(row["feature_id"]) or {}
        options = ((mechanic.get("modifier") or {}).get("options")) or []
        return [{**row, "option_index": index, "key": _slug(option.get("label")), "label": f"Numbing Point ({option.get('label')})"}
                for index, option in enumerate(options)]
    if block in ("shi_pp_point", "shi_pp_seal"):
        mechanic = _mechanics().get(row["feature_id"]) or {}
        name = str(mechanic.get("name") or row["feature_id"])
        return [{**row, "label": name, "key": _slug(name),
                 **({"point_effects": copy.deepcopy(spec["point_effects"])} if "point_effects" in spec else {})}]
    return None


def _leaf_effects(leaf: dict[str, Any]) -> list[dict[str, Any]]:
    # New reviewed Point declarations can freeze their delivery effects in the
    # sealed passive row. Legacy saved rows retain the authority-backed path.
    if "point_effects" in leaf:
        return list(leaf["point_effects"])
    mechanic = _mechanics().get(leaf["feature_id"]) or {}
    if "option_index" in leaf:
        options = ((mechanic.get("modifier") or {}).get("options")) or []
        index = leaf["option_index"]
        return list(options[index].get("effects") or []) if index < len(options) else []
    return list(mechanic.get("effects") or [])


def _rows(engine: Any, actor: Any, block: str) -> list[dict[str, Any]]:
    from .. import typed_reactions

    return typed_reactions._rows(engine, actor.entity_id, block)


def _picked_leaf(actor: Any, condition_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    picked = next((str((condition.data or {}).get("key")) for condition in actor.conditions.values() if condition.condition_id == condition_id), None)
    return next((row for row in rows if row.get("key") == picked), rows[0])


@hook("choice_reactors")
def seal_choice_targets(engine: Any) -> tuple[str, ...]:
    """Seals resolve authority rows at hit time, including in existing saved bundles.

    Tell the general AI-step probe that a seal can ask its defender, even when
    that defender owns no Ask-me reaction. No target-choice seal = inert.
    """
    from .save_choices import has_target_choice

    if any(has_target_choice(_leaf_effects(row)) for actor in engine.state.actors.values()
           for row in _rows(engine, actor, "shi_pp_seal")):
        return tuple(engine.state.actors)
    return ()


@hook("compile_actions")
def _compile_actions(info: dict[str, Any]) -> list[Any]:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    point_rows = [row for row in info["passives"] if row.get("block") in ("shi_pp_point", "shi_pp_point_options")]
    seal_rows = [row for row in info["passives"] if row.get("block") == "shi_pp_seal"]
    if not point_rows and not seal_rows:
        return []
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    actions = []
    for which, rows in (("point", point_rows), ("seal", seal_rows)):
        for row in rows:
            actions.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.touch_the_point.{which}.{row['key']}",
                display_name=f"Touch the Point: {row['label']}", owner_id=actor_id, economy=EconomyKind.NONE,
                resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "typed": {"effects": [{"type": f"shi_pp_pick_{which}", "key": row["key"]}], "numbers": numbers,
                                      "duration": {"kind": "instant"}, "riders": []},
                            "expected_damage": 0, "player_only": True}))
    if any(any(e.get("type") == "pp_stolen_step" for e in row.get("point_effects") or []) for row in point_rows):
        for mode, label in (("point", "Apply a Point even to a marked creature"), ("auto", "Close a Seal on a marked creature")):
            actions.append(ActionDefinition(
                source_definition_id=f"action:typed.{short}.touch_the_point.mode.{mode}",
                display_name=f"Touch the Point: {label}", owner_id=actor_id, economy=EconomyKind.NONE,
                resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "player_only": True, "expected_damage": 0,
                    "typed": {"effects": [{"type": "shi_pp_pick_mode", "key": mode}], "numbers": numbers,
                              "duration": {"kind": "instant"}, "riders": []}}))
    return actions


def _set_pick(ctx: Any, condition_id: str, key: str) -> None:
    for instance_id, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == condition_id:
            del ctx.actor.conditions[instance_id]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": instance_id})
    ctx.engine._apply_condition(ctx.actor, condition_id, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data={"key": key})


@effect("shi_pp_pick_point")
def _pick_point(ctx: Any, effect_row: dict[str, Any]) -> None:
    _set_pick(ctx, POINT_PICK, str(effect_row.get("key") or ""))


@effect("shi_pp_pick_seal")
def _pick_seal(ctx: Any, effect_row: dict[str, Any]) -> None:
    _set_pick(ctx, SEAL_PICK, str(effect_row.get("key") or ""))


@effect("shi_pp_pick_mode")
def _pick_mode(ctx, row):
    _set_pick(ctx, MODE_PICK, str(row.get("key") or "auto"))


def _second_pass_points(engine, actor):
    return any(any(e.get("type") == "pp_stolen_step" for e in r.get("point_effects") or [])
               for r in _rows(engine, actor, "shi_pp_point"))


@hook("after_hit")
def _touch_the_point(ctx: Any, target: Any, kind: str) -> None:
    if not _second_pass_points(ctx.engine, ctx.actor):
        _deliver_touch(ctx, target, kind)


@hook("hit_final")
def _second_pass_touch(ctx, target, kind):
    if _second_pass_points(ctx.engine, ctx.actor):
        _deliver_touch(ctx, target, kind)


def _deliver_touch(ctx: Any, target: Any, kind: str) -> None:
    # A reaction's explicit Point rider delivers that one Point itself. It does
    # not also receive the ordinary once-per-turn Touch-the-Point follow-up.
    if ctx.typed.get("reaction_attack") and any(
        e.get("type") == "pp_apply_point" for r in ctx.typed.get("effects") or []
        for e in r.get("on_hit") or []):
        return
    if kind not in ("unarmed", "weapon"):
        return  # Precision Contact is a melee method only
    range_ft = ctx.typed.get("range_ft")
    if range_ft is not None and int(range_ft) > 5:
        return
    actor = ctx.actor
    if actor.turn_flags.get("shi_touch_the_point_used"):
        return  # "Once per turn"
    # Numbing Point (Pressure Points Training's own always-known Point talent) sorts first, so it is the
    # built-in AI's default pick, ahead of any other Point talent the character separately learned.
    point_rows = _rows(ctx.engine, actor, "shi_pp_point_options") + _rows(ctx.engine, actor, "shi_pp_point")
    seal_rows = _rows(ctx.engine, actor, "shi_pp_seal")
    if not point_rows and not seal_rows:
        return  # doesn't have Pressure Points Training

    from .. import typed_executor

    actor.turn_flags["shi_touch_the_point_used"] = True
    already_marked = typed_executor.bears_mark(target, actor.entity_id, PRESSURE_POINT_MARK)
    mode = next((c.data.get("key") for c in actor.conditions.values() if c.condition_id == MODE_PICK), "auto")
    if already_marked and seal_rows and mode != "point":
        leaf = _picked_leaf(actor, SEAL_PICK, seal_rows)
        ctx.rider(f"Touch the Point: Close a Seal ({leaf['label']})")
        ctx.engine._remove_condition(target, typed_executor.mark_condition_id(PRESSURE_POINT_MARK, actor.entity_id), ctx.source)
        # Presentation identity belongs to the seal, while the source action/intent
        # remains the delivery attack for payment, replay and activation tracking.
        inner = typed_executor.Context(ctx.engine, actor, ctx.action, ctx.intent,
                                       {**ctx.typed, "effect_name": leaf["label"]}, [target], target, ctx.damage_cache)
        typed_executor.run_effects(inner, copy.deepcopy(_leaf_effects(leaf)))
    elif point_rows:
        apply_point(ctx, target)
    else:
        actor.turn_flags["shi_touch_the_point_used"] = False  # nothing this character knows could fire; leave the turn free


def apply_point(ctx: Any, target: Any) -> bool:
    """Apply the actor's picked Point talent to ``target``: its Pressure Point mark ("until the end of your next turn") and the talent's own
    typed effects.  Shared helper (consumers: this module's Touch the Point, and combat/ext/pressure_points.py for "apply one Point talent
    you know" -- Retaliatory Nerve, Intercepting Tap, Needle Meets Blade).  False when the actor knows no Point talent."""
    from .. import typed_executor

    actor = ctx.actor
    point_rows = _rows(ctx.engine, actor, "shi_pp_point_options") + _rows(ctx.engine, actor, "shi_pp_point")
    if not point_rows or target is None or not target.active:
        return False
    leaf = _picked_leaf(actor, POINT_PICK, point_rows)
    return deliver_point(ctx, target, leaf)


def deliver_point(ctx: Any, target: Any, leaf: dict[str, Any]) -> bool:
    """Shared Point delivery for Touch the Point and Cascade: mark plus owned effects.

    Callers choose an owned leaf first; the delivery never reselects Cascade or
    spends the once-per-turn Touch the Point allowance for the second creature.
    """
    from .. import typed_executor

    actor = ctx.actor
    snapshot = (ctx.hit_snapshots or {}).get("pp_preexisting_point") or {}
    before = (snapshot.get("marked") if (snapshot.get("owner"), snapshot.get("target")) == (actor.entity_id, target.entity_id)
              else typed_executor.bears_mark(target, actor.entity_id, PRESSURE_POINT_MARK))
    ctx.damage_cache["pp_preexisting_mark:" + target.entity_id] = bool(before)
    ctx.rider(f"Touch the Point: Apply a Point ({leaf['label']})")
    typed_executor.block_mark(typed_executor.Context(ctx.engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target),
                              {"mark": PRESSURE_POINT_MARK, "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}})
    inner = typed_executor.Context(ctx.engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
    typed_executor.run_effects(inner, copy.deepcopy(_leaf_effects(leaf)))
    return True


@hook("choice_reactors")
def cascade_choice_owners(engine: Any) -> tuple[str, ...]:
    """New sealed Cascade deliveries can ask their manual owner on any turn.

    Old bundles lack the opt-in effect, so their choices and replay stay unchanged.
    """
    def contains(value: Any) -> bool:
        if isinstance(value, dict):
            return value.get("type") == "shi_pp_apply_numbing" or any(contains(v) for v in value.values())
        return isinstance(value, list) and any(contains(v) for v in value)

    return tuple(actor.entity_id for actor in engine.state.actors.values()
                 if any(contains(row.get("point_effects")) for row in _rows(engine, actor, "shi_pp_point")))


@effect("shi_pp_apply_numbing")
def apply_numbing(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Cascade's failed secondary save delivers one known Numbing option.

    Reuses the owned Numbing leaves and ordinary Point mark deadline. No owned
    Numbing row means no effect; legacy sealed Cascade tags are not reinterpreted.
    """
    from . import needle

    rows = _rows(ctx.engine, ctx.actor, "shi_pp_point_options")
    if not rows:
        return
    for target in ctx.targets or ([ctx.target] if ctx.target else []):
        if target is None or not target.active:
            continue
        labels = {row["key"]: row["label"] + ": " + "; ".join(
            str(e.get("evidence") or "") for e in _leaf_effects(row)) + "; until the start of your next turn"
                  for row in rows}
        chosen = needle.ask(ctx.engine, ctx.intent,
                            needle.checkpoint_id(ctx.engine, "PP_NUMBING", ctx.source, target.entity_id),
                            ctx.actor, "choice:needle.pp_numbing", list(labels), labels=labels,
                            name="Nine-Needle Cascade: Numbing Point", target_id=target.entity_id,
                            prompt=f"Nine-Needle Cascade after {ctx.action.display_name}: choose Numbing Point for "
                                   f"{target.display_name} until the start of your next turn. No additional cost.")
        leaf = next((row for row in rows if row["key"] in chosen), None)
        if leaf is not None:
            deliver_point(ctx, target, leaf)
