"""Shared helper module (consumers: daemonic_riders.py, river_riders.py). Source-bound rider adapters, declared on the owning compiled ability only.

``rider_defeats`` wraps effects and pays ``per_defeat`` for each distinct creature
reduced from positive HP to zero by this activation's own damage. ``threshold``
and ``threshold_effects`` pay once when that many creatures fell. Rewards still
settle when the last enemy falls; no extra attack is allowed after combat ends.
``rider_targets`` chooses up to ``count`` (integer or pb) visible creatures in
range, or a subset of the ability's existing area targets (``area_only``).
Optional ``prompt`` supplies source-specific choice instructions; absent text
preserves the historical prompt. Destruction's distinct Multi-Ray uses it.
``rider_save`` runs a save with Disadvantage for any declared predicate: below
half HP, a condition, or a caster-owned mark. It changes that save only.
``rider_menu`` chooses distinct effects at resolution, with a larger printed
count when the target already bears a named mark (from any source).
``rider_after_failed_save`` resolves its effects, then chooses exactly one
creature that failed this source's save for the declared ``after`` effects.

Sources: Daemonic Cultivation's Hunger-Refining Breath, Thousand-Mouth Devouring
Art and World-Devouring Maw in authority/typed_mechanics/rules_text.json.
"""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any

from . import effect, hook


@hook("unresolved_roll_mode_text")
def describe_untyped_roll_mode(ctx: Any, row: dict[str, Any], mode: str) -> str | None:
    """Missing roll descriptors remain GM text, using printed evidence rather than 'on None'.

    This applies to any incomplete generated roll-mode row; it grants no mode
    and changes nothing for a row with a real roll descriptor.
    """
    if row.get("type") not in ("advantage", "disadvantage") or str(row.get("on") or "").strip():
        return None
    evidence = str(row.get("evidence") or "").strip()
    return evidence or "The rule does not identify the roll affected; the GM must identify it before applying this benefit or penalty."


@hook("compile_action")
def chosen_area_scale(action: Any, info: dict[str, Any]) -> Any:
    """Seal a selected area's CL size before menus and recipient queries.

    A size_ft_by_cl-only shape otherwise looks like a single-target action.
    Only explicit recipient selectors opt in; sealed old actions are untouched.
    """
    typed = (action.parameters or {}).get("typed") or {}
    area = typed.get("area") or {}
    if area.get("size_ft") or not area.get("size_ft_by_cl") or not any(
            row.get("type") == "rider_choose_area_recipients" for row in typed.get("effects") or []):
        return None
    level = int((typed.get("numbers") or {}).get("cl") or 1)
    size = next((int(feet) for low, high, feet in area["size_ft_by_cl"] if low <= level <= high), None)
    if size is None:
        return None
    shaped = {**area, "size_ft": size}
    kind = "SELF" if area.get("centered_on_self") else "CELL"
    reach = size if area.get("shape") in {"line", "cone"} and not area.get("placed") else action.range_ft
    return action.model_copy(update={"target_kind": kind, "range_ft": reach,
        "parameters": {**action.parameters, "typed": {**typed, "area": shaped}}})


@hook("compile_action")
def weapon_roster_action(action: Any, info: dict[str, Any]) -> Any:
    """An explicit weapon-range selector owns its roster at resolution."""
    typed = (action.parameters or {}).get("typed") or {}
    if any(row.get("type") == "rider_targets" and row.get("range_from_weapon")
           for row in typed.get("effects") or []):
        return action.model_copy(update={"target_kind": "SELF", "range_ft": None})
    return None


@hook("before_target_reactions")
def choose_area_recipients_before_reactions(ctx: Any) -> None:
    """Run opted-in area recipient choices before target-specific reactions."""
    def visit(rows: Any) -> dict[str, Any] | None:
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("type") == "rider_choose_area_recipients":
                return row
            for key in ("effects", "on_hit", "on_miss", "on_fail", "on_success"):
                found = visit(row.get(key))
                if found:
                    return found
        return None

    choice = visit(ctx.typed.get("effects") or [])
    if choice and not choice.get("after_arrival"):
        choose_area_recipients(ctx, choice)


def settle(ctx: Any, rows: list[dict[str, Any]]) -> None:
    """Resolve completed-hit rewards for defeat riders and Black-Claw, even after combat ends."""
    from .. import typed_executor as te

    if ctx.engine.state.terminal_result is None:
        te.run_effects(ctx, rows)
        return
    # These are consequences of the completed damage, not another activation.
    # Keep the ordinary resource/healing reducers and their restrictions.
    for row in rows:
        if row.get("type") in {"gain_resource", "healing", "temp_hp"}:
            te.BLOCKS[row["type"]](ctx, row)


@effect("rider_defeats")
def defeats(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import typed_executor as te

    before = {key: actor.current_hp for key, actor in ctx.engine.state.actors.items()}
    start = len(ctx.engine.events)
    te.run_effects(ctx, spec.get("effects") or [])
    damaged = {who for event in ctx.engine.events[start:]
               if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == ctx.actor.entity_id
               and event.source_definition_id == ctx.source and int((event.payload or {}).get("hp_damage") or 0) > 0
               for who in event.target_ids or ()}
    fallen = sorted(who for who in damaged if before.get(who, 0) > 0
                    and ctx.engine.state.actors[who].current_hp <= 0)
    for _ in fallen:
        settle(ctx, spec.get("per_defeat") or [])
    if spec.get("threshold") and len(fallen) >= int(spec["threshold"]):
        settle(ctx, spec.get("threshold_effects") or [])


@effect("rider_targets")
def targets(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import stealth, typed_executor as te
    from . import needle

    if spec.get("range_from_weapon"):
        # The binding is selected before the roster, so a longer stowed weapon
        # cannot lend its reach to an attack delivered by the held short one.
        from ..attack_reach import maximum
        from ..weapon_delivery import ready_weapons
        from ..targeting import line_of_effect
        weapon = ready_weapons(ctx.engine, ctx.actor).get(ctx.typed.get("weapon_source_id"))
        if weapon is None:
            return
        reach = maximum(ctx.engine, ctx.actor, weapon, base=int(weapon.reach_ft or weapon.range_ft or 5))
        action = ctx.action.model_copy(update={"range_ft": reach, "reach_ft": reach})
        weapon_typed = weapon.parameters.get("typed") or {}
        numbers = {**ctx.numbers, "attack_bonus": (weapon_typed.get("numbers") or {}).get("attack_bonus", 0)}
        typed = {**ctx.typed, "numbers": numbers,
                 **{key: weapon_typed[key] for key in ("mundane", "proficient", "magic_bonus") if key in weapon_typed}}
        ctx = replace(ctx, action=action, typed=typed)
        spec = {**spec, "range_ft": reach}
    pool = ctx.targets if spec.get("area_only") else list(ctx.engine.state.actors.values())
    # The validated area roster can include its user. Visibility to oneself
    # is not a perception query; do not drop a printed or chosen self recipient.
    candidates = sorted((row for row in pool if row.active and (spec.get("requires_visibility") is False
                         or ((spec.get("area_only") or spec.get("range_from_weapon")) and row.entity_id == ctx.actor.entity_id)
                         or stealth.sees(ctx.engine, ctx.actor, row))
                         and (not spec.get("hostile_only") or row.team_id != ctx.actor.team_id)
                         and (not spec.get("condition") or any(c.condition_id == te.CONDITION_PREFIX + spec["condition"]
                                                                 for c in row.conditions.values()))
                         and (not spec.get("range_from_weapon") or line_of_effect(ctx.engine, ctx.actor, target=row))
                         and (spec.get("area_only") or ctx.engine._distance_actor_to_actor(ctx.actor, row) <= int(spec["range_ft"]))),
                        key=lambda row: (row is not ctx.target, ctx.engine._distance_actor_to_actor(ctx.actor, row), row.entity_id))
    # Full printed legality remains the player's choice. An explicitly opted-in
    # harmful selector gives automatic controllers only perceived enemies,
    # rather than relying on preferences that the controller fills to maximum.
    if spec.get("automatic_hostile_only"):
        from ..zones import uses_default_shape
        if uses_default_shape(ctx.engine, ctx.actor):
            candidates = [row for row in candidates if row.team_id != ctx.actor.team_id]
    side = spec.get("automatic_side")
    if side and not needle.answerable(ctx.engine, ctx.actor):
        if side not in {"enemies", "allies", "allies_and_self"}:
            raise ValueError("invalid automatic recipient side")
        candidates = [row for row in candidates if (
            row.team_id != ctx.actor.team_id if side == "enemies" else
            row.team_id == ctx.actor.team_id and (side == "allies_and_self" or row.entity_id != ctx.actor.entity_id))]
    count = int(ctx.numbers.get("pb") or 0) if spec.get("count") == "pb" else int(spec.get("count") or len(candidates))
    maximum = min(count, len(candidates), 64)
    if not maximum:
        return
    # Reuse an unrestricted area choice answered before target reactions.
    # Keep this wrapper's visibility/condition eligibility, but do not ask a
    # second time or replace deliberately selected allies with AI preferences.
    if spec.get("area_only") and not spec.get("count") and ctx.typed.get("_area_recipients_preselected"):
        te.run_effects(replace(ctx, targets=candidates, target=None), spec.get("effects") or [])
        return
    preferred = [row.entity_id for row in candidates if row.team_id != ctx.actor.team_id][:maximum]
    if spec.get("minimum") and not preferred:
        preferred = [row.entity_id for row in candidates[:maximum]]
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "rider_targets", ctx.source), ctx.actor,
                        needle.CHOICE + "rider_targets", [row.entity_id for row in candidates],
                        labels={row.entity_id: row.display_name for row in candidates}, preferred=preferred,
                        minimum=min(int(spec.get("minimum") or 0), maximum), maximum=maximum,
                        allow_decline=not bool(spec.get("minimum")), default_count=len(preferred),
                        default="first" if preferred else "decline", prompt=spec.get("prompt") or f"{ctx.action.display_name}: choose creatures")
    selected = [row for row in candidates if row.entity_id in chosen]
    te.run_effects(replace(ctx, targets=selected, target=selected[0] if len(selected) == 1 else None), spec.get("effects") or [])


@effect("rider_zone_targets")
def zone_targets(ctx: Any, spec: dict[str, Any]) -> None:
    """Select creatures inside this caster/source's actual active zone cells."""
    cells = {(cell.x, cell.y) for zone in ctx.engine.state.zones.values()
             if zone.active and zone.owner_id == ctx.actor.entity_id and zone.source_definition_id == ctx.source
             for cell in zone.affected_cells}
    pool = [actor for actor in ctx.engine.state.actors.values()
            if any(cell in cells for cell in ctx.engine._actor_cells(actor))]
    targets(replace(ctx, targets=pool, target=None), {"requires_visibility": False, **spec, "area_only": True})


@effect("rider_after_failed_save")
def failed_save_choice(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from . import needle

    start = len(ctx.engine.events)
    te.run_effects(ctx, spec.get("effects") or [])
    ids = list(dict.fromkeys(event.actor_id for event in ctx.engine.events[start:]
                            if event.event_type == "SAVE_ROLLED" and event.source_definition_id == ctx.source
                            and event.payload.get("success") is False))
    if not ids:
        return
    selected = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "failed_save", ctx.source), ctx.actor,
                          needle.CHOICE + "rider_failed_save", ids, minimum=1, maximum=1,
                          labels={key: ctx.engine.state.actors[key].display_name for key in ids},
                          prompt=str(spec.get("prompt") or f"{ctx.action.display_name}: choose a creature that failed its save"),
                          name=str(spec.get("name") or ""), feature_id=str(spec.get("feature_id") or ""))
    for who in selected:
        subject = ctx.engine.state.actors[who]
        te.run_effects(replace(ctx, targets=[subject], target=subject), spec.get("after") or [])


@effect("rider_save")
def save(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import typed_executor as te

    te.run_effects(replace(ctx, typed={**ctx.typed, "_rider_save_traits": spec.get("disadvantage_if") or {}}), spec.get("effects") or [])


@hook("save")
def save_traits(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    from .. import typed_executor as te

    traits = ctx.typed.get("_rider_save_traits") or {}
    qualifies = (traits.get("below_half_hp") and subject.current_hp * 2 < subject.maximum_hp) or \
        any(c.condition_id == te.CONDITION_PREFIX + name for name in traits.get("conditions") or [] for c in subject.conditions.values()) or \
        any(te.bears_mark(subject, ctx.actor.entity_id, name) for name in traits.get("marks") or [])
    return {"modes": ["DISADVANTAGE"]} if qualifies else None


@effect("rider_menu")
def menu(ctx: Any, spec: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from . import needle
    from .choice_prompt import action_context

    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        options = spec.get("options") or []
        ids = [str(row["id"]) for row in options]
        count = int(spec.get("count") or 1)
        larger = spec.get("count_if_marked") or {}
        prefix = te.MARK_PREFIX + te._mark_slug(str(larger.get("mark") or "")) + "."
        if larger and any(c.condition_id.startswith(prefix) for c in subject.conditions.values()):
            count = int(larger["count"])
        chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "rider_menu", subject.entity_id), ctx.actor,
                            needle.CHOICE + str(spec["id"]), ids, labels={row["id"]: _menu_label(row) for row in options},
                            minimum=count, maximum=count, allow_decline=bool(spec.get("optional")), default_count=count,
                            preferred=ids[:count],
                            prompt=f"{ctx.action.display_name}: {spec.get('label') or 'choose effects'} for {subject.display_name}. "
                                   f"Choose {count} effect{'s' if count != 1 else ''}. No extra cost.",
                            target_id=subject.entity_id, name=str(spec.get("label") or ctx.action.display_name),
                            feature_id=ctx.source, prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, subject))
        for row in options:
            if row["id"] in chosen:
                te.run_effects(replace(ctx, target=subject, targets=[subject]), row.get("effects") or [])


def _menu_label(option: dict[str, Any]) -> str:
    """Display a common stated turn expiry beside a rider's effect, without changing it."""
    endings = {
        "START_OF_TARGET_NEXT_TURN": "until their next turn starts",
        "START_OF_SOURCE_NEXT_TURN": "until your next turn starts",
        "END_OF_HOLDER_NEXT_TURN": "until their next turn ends",
        "END_OF_CURRENT_TURN": "until this turn ends",
    }
    rows = option.get("effects") or []
    durations = {row.get("expires_on") for row in rows}
    label = str(option.get("label") or option["id"])
    if len(durations) == 1 and next(iter(durations)) in endings:
        label += " — " + endings[next(iter(durations))]
    return label


@effect("rider_replacing")
def replacing(ctx: Any, spec: dict[str, Any]) -> None:
    """Replace this named rider's previous effects from this caster, preserving all others.

    The ledger stores only newly created condition/modifier instance IDs. Used
    by Heat Pressure's 'only one effect from you at a time' rule.
    """
    from .. import typed_executor as te

    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        ledger_id = te.mark_condition_id(str(spec["name"]), ctx.actor.entity_id)
        old = next((c for c in subject.conditions.values() if c.condition_id == ledger_id), None)
        if old:
            for iid in (old.data or {}).get("conditions") or []:
                condition = subject.conditions.pop(iid, None)
                if condition:
                    ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                             payload={"condition_id": condition.condition_id, "instance_id": iid})
            for mid in (old.data or {}).get("modifiers") or []:
                if subject.modifiers.pop(mid, None):
                    ctx.engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=subject.entity_id, target_ids=(subject.entity_id,),
                                             payload={"modifier_id": mid})
            ctx.engine._remove_condition(subject, ledger_id, ctx.source)
        before_c, before_m = set(subject.conditions), set(subject.modifiers)
        te.run_effects(replace(ctx, target=subject, targets=[subject]), spec.get("effects") or [])
        ctx.engine._apply_condition(subject, ledger_id, ctx.source, ctx.actor.entity_id,
                                    expires_on=te.effect_expiry(ctx, spec, subject, condition=True),
                                    data={"conditions": sorted(set(subject.conditions) - before_c),
                                          "modifiers": sorted(set(subject.modifiers) - before_m), "label": spec["name"]})


@effect("rider_choose_area_recipients")
def choose_area_recipients(ctx: Any, spec: dict[str, Any]) -> None:
    """Restrict a printed area effect to recipients selected from the full area roster.

    Typed rows opt in only when their printed rule says creatures are chosen by the user.
    Ordinary area targeting includes every creature permitted by the printed text. AI receives the
    preferred hostile roster automatically; player-owned and Ask-me actors use the normal
    transactional choice checkpoint before any save or effect is resolved.
    """
    if ctx.typed.get("_area_recipients_preselected"):
        return
    from . import needle

    area = ctx.typed.get("area") or {}
    if not area.get("size_ft"):
        return
    # typed_executor has already applied geometry, recipient and hearing
    # rules. Selection may narrow that roster, never widen it.
    candidates = list(ctx.targets)
    from ..effect_harm import classify_effect
    from ..area_recipients import harmful_area_subject_allowed

    payloads = [row for row in ctx.typed.get("effects") or ()
                if isinstance(row, dict) and row.get("type") != "rider_choose_area_recipients" and row.get("applies_to") != "self"
                and not (row.get("type") == "zone" and not ctx.typed.get("zone_spec"))]
    harmful = [row for row in payloads if classify_effect(row, ignore_self=True) is True]
    # The selector is bookkeeping, not a benefit that admits friendly targets.
    # A zone row without the native zone_spec also resolves only as a GM note.
    # Mixed/opaque benefits still keep their legal friendly choices. Pure harm
    # offers only creatures eligible for at least one actual harmful payload.
    # Save consequences stay bound to the save's recipients: half damage on
    # success is not an independent benefit permitting friendly save targets.
    helpful = any(classify_effect(row, ignore_self=True) is not True for row in payloads)
    if harmful and not helpful:
        candidates = [subject for subject in candidates
                      if any(harmful_area_subject_allowed(ctx.actor, subject, area, row) for row in harmful)]
    # Manual owners may select every creature the printed area permits. An
    # automatic caster uses only hostile recipients for harmful area effects;
    # individual typed rows can opt in to friendly recipients when their effect
    # benefits them.
    from .. import zones
    automatic = zones.uses_default_shape(ctx.engine, ctx.actor)
    if automatic:
        from ..target_knowledge import located

        # A chosen area is a creature decision, not an indiscriminate blast.
        # The world roster supplies geometry, never the automatic chooser's
        # knowledge. Current perception includes pinpointing senses.
        candidates = [row for row in candidates if located(ctx.engine, ctx.actor, row)]
    if automatic and spec.get("automatic_side"):
        from ..relations import relation
        side = spec["automatic_side"]
        if side not in {"ALLY", "ENEMY"}:
            raise ValueError("automatic area side must be ALLY or ENEMY")
        candidates = [row for row in candidates if relation(ctx.engine, ctx.actor, row) == side]
        if spec.get("automatic_perceived_only"):
            from ..target_knowledge import knowledge
            candidates = [row for row in candidates if (known := knowledge(ctx.engine, ctx.actor, row)) is not None
                          and known.mode == 'DIRECT']
    elif automatic and not spec.get("automatic_friendly"):
        candidates = [row for row in candidates if row.team_id != ctx.actor.team_id]
    if automatic and spec.get("perceived_only_for_automatic"):
        from ..target_knowledge import can_see
        candidates = [row for row in candidates if can_see(ctx.engine, ctx.actor, row)]
    if spec.get("hostile_only"):
        candidates = [row for row in candidates if row.team_id != ctx.actor.team_id]
    ids = [row.entity_id for row in candidates]
    labels = {row.entity_id: row.display_name for row in candidates}
    cap = int(ctx.numbers.get("pb") or 0) if spec.get("count") == "pb" else int(spec.get("count") or len(ids))
    maximum = min(max(0, cap), len(ids))
    roster = ", ".join(labels[key] for key in ids) or "no creatures"
    allies = ", ".join(row.display_name for row in candidates
                        if row.team_id == ctx.actor.team_id and row.entity_id != ctx.actor.entity_id)
    friendly_fire = f"Allies in the area: {allies}. " if allies else ""
    consequences = _area_choice_consequences(ctx)
    instruction = (f"choose up to {maximum} creatures in the area to affect" if spec.get("count")
                   else "choose which creatures in the area are affected")
    selected = needle.ask(
        ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, "area_recipients", ctx.source),
        ctx.actor, "choice:needle.area_recipients", ids, labels=labels,
        minimum=0, maximum=maximum, default="all", preferred=ids[:maximum],
        prompt=f"{ctx.action.display_name}: {instruction}. {friendly_fire}{consequences} Creatures here: {roster}.",
        name=ctx.action.display_name, feature_id=ctx.source,
    )
    by_id = {row.entity_id: row for row in candidates}
    ctx.targets[:] = [by_id[key] for key in selected if key in by_id]
    ctx.target = None
    ctx.typed["_area_recipients_preselected"] = True


def _area_choice_consequences(ctx: Any) -> str:
    """Describe all printed consequences before choosing recipients.

    Reviewed selectors carry their source-backed summary, including alternatives,
    movement, marks, benefits, durations and payment. Older saved action trees
    without it use each outcome's evidence rather than omitting unfamiliar rows.
    """
    typed = ctx.typed
    ability_names = {"str": "Strength", "dex": "Dexterity", "con": "Constitution",
                     "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
    durations = {"until_end_of_turn": "until the end of this turn",
                 "until_end_of_your_next_turn": "until the end of your next turn",
                 "until_start_of_next_turn": "until the start of their next turn",
                 "until_start_of_your_next_turn": "until the start of your next turn"}
    outcomes: list[str] = []
    summaries: list[str] = []
    glossary: list[str] = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "rider_choose_area_recipients" and value.get("summary"):
                summaries.append(str(value["summary"]))
                glossary.extend(str(entry) for entry in value.get("glossary") or [])
            if value.get("type") == "save":
                save_name = ability_names.get(str(value.get("ability") or "").lower())
                if save_name:
                    outcomes.append(f"Each selected creature makes a {save_name} saving throw")
                for key, lead in (("on_fail", "On a failure"), ("on_success", "On a success")):
                    for effect_row in value.get(key) or []:
                        if not isinstance(effect_row, dict):
                            continue
                        condition = str(effect_row.get("condition") or "").replace("_", " ")
                        duration_value = effect_row.get("duration") or ""
                        if isinstance(duration_value, dict):
                            duration_value = duration_value.get("kind") or ""
                        duration = durations.get(str(duration_value))
                        evidence = str(effect_row.get("evidence") or "").strip()
                        if evidence:
                            consequence = evidence
                        elif effect_row.get("type") == "half_damage":
                            consequence = "creatures take half damage"
                        elif effect_row.get("type") == "damage":
                            dice = effect_row.get("dice") or {}
                            amount = (f"{dice.get('count')}d{dice.get('sides')}" if dice.get("count") and dice.get("sides")
                                      else str(effect_row.get("flat") or effect_row.get("formula") or "the stated"))
                            kinds = " or ".join(str(kind).title() for kind in effect_row.get("damage_types") or [])
                            consequence = f"creatures take {amount} {kinds} damage"
                        elif effect_row.get("type") == "forced_movement":
                            consequence = f"creatures move {effect_row.get('distance_ft', 0)} feet " + str(effect_row.get("on") or "")
                        elif condition and condition != "none":
                            consequence = f"creatures are {condition}" + (f" {duration}" if duration else "")
                        elif effect_row.get("type") == "reaction_denied":
                            consequence = "creatures cannot take Reactions" + (f" {duration}" if duration else "")
                        else:
                            consequence = str(effect_row.get("label") or "")
                            if not consequence:
                                continue
                        if duration and duration not in consequence:
                            consequence += f" ({duration})"
                        outcomes.append(f"{lead}, {consequence}")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(typed.get("effects") or [])
    if summaries:
        reading = " ".join(dict.fromkeys(summaries))
        if "CP" in reading:
            glossary.append("CP means Cultivation Points, your technique resource.")
        if "Stamina" in reading:
            glossary.append("Stamina is the resource you spend on martial techniques.")
        # A small printed progression table reads as sentences inside a prompt.
        reading = re.sub(r"\| Cultivation Level \| Damage \| \| --- \| --- \| \| 1-10 \| 2d6 \| \| 11-16 \| 3d6 \| \| 17-20 \| 4d6 \|",
                         "Damage: 2d6 at Cultivation Levels 1–10, 3d6 at 11–16, and 4d6 at 17–20.", reading)
        return reading + " " + " ".join(dict.fromkeys(glossary))
    # Each node may be reached through multiple typed wrappers; retain the
    # order while removing duplicate summaries.
    outcomes = list(dict.fromkeys(outcomes))
    resource_names = {"resource:core.qi": "Cultivation Points", "resource:core.stamina": "Stamina",
                      "resource:core.resonance": "Resonance"}
    costs = [f"{int(amount)} {resource_names.get(resource, resource.rsplit('.', 1)[-1].replace('_', ' ').title())}"
             for resource, amount in getattr(ctx.action, "costs", ()) if int(amount)]
    parts = ["; ".join(outcomes)] if outcomes else []
    if costs:
        parts.append("Cost: " + " and ".join(costs) + ".")
    return ". ".join(parts) + ("." if parts and not parts[-1].endswith(".") else "")
