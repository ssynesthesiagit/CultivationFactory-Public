"""Water's Cleansing Basin (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). Printed (Sphere Compendium, Water, Shape Current): "Cleansing Basin. The first time each round you or an ally
enters the area or starts its turn there, it may end the Soaked state on itself, extinguish ordinary flames on itself, or gain Advantage
on the next saving throw before the start of its next turn against Poisoned, a disease, smoke, heat, or mundane contamination."

``water_cleansing`` is the Basin's enter/start trigger (once per creature per round: the zone trigger's ``per_round``); the creature
itself chooses (its player is asked; the built-in AI ends Burning first, then Soaked, else takes the Advantage): end every Soaked mark on
it, end its Burning (the table's ordinary flames), or Advantage on its next save against Poisoned or a disease until the start of its
next turn. Shape Current's other forms are typed zone rows (authority/typed_mechanics/reviewed_final.d/elements.json); moving a Basin
is combat/ext/zone_mover.py. The compile_action hook also replaces Flowing
Current's ordinary initial push in newly compiled Wave Burst variants; their
reviewed effect uses the shared chosen-area recipient selector. Saved catalogs
are unchanged. Cleansing is inert outside a Cleansing Basin.

Owned Cleansing Water annotates this same trigger, grants the actual beneficiary
PB Temporary HP and records one improved cleansing per Basin per round. The
separate wash choice handles recorded mundane surface residue; it never cures
Poisoned, disease or curses. Source ownership is checked during compilation and
all runtime washing requires an active owned upgraded Basin. The improved
removal can benefit any creature; original benefits and Temporary HP remain
allied benefits. Recorded magical or contested residue is left unchanged.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note, ai_controlled

SOAKED_PREFIX = "condition:typed.mark.soaked."
BURNING = "condition:typed.burning"
CLEANSING = 'TAL_WATER_CLEANSING_WATER'
WASH = 'action:water.cleansing_residue'
RESIDUE = {'mundane_poison_residue', 'acid_residue', 'dust', 'ash', 'filth', 'mundane_contamination', 'covered_in_smoke'}
WASH_RESIDUE = {'mundane_poison_residue', 'acid_residue', 'dust', 'ash', 'filth'}


def residue_conditions(creature: Any, *, wash_only: bool = False) -> dict[str, Any]:
    """Read eligible recorded condition instances from a creature, without removal.

    ``cleansing`` uses the full smoke/contamination set. ``wash_targets`` and
    ``wash_residue`` pass ``wash_only=True`` for the five printed surface types.
    The result maps instance IDs to existing conditions; no eligible state gives
    an empty dict. Magical/contested instances and unsupported ailments stay out.
    """
    return {iid: c for iid, c in creature.conditions.items()
            if c.condition_id.removeprefix('condition:typed.') in (WASH_RESIDUE if wash_only else RESIDUE)
            and c.data.get('magical') is not True and c.data.get('contested') is not True}


@hook('compile_action')
def cleansing_beneficiary(action: Any, info: dict[str, Any]) -> Any:
    """Move mandatory owned benefits from casting to the actual Basin trigger."""
    import copy
    typed = (action.parameters or {}).get('typed') or {}
    if CLEANSING not in info['owned_ids'] or typed.get('source') != 'WATER_BASE_SHAPE_CURRENT':
        return None
    found = False

    def shape(value):
        nonlocal found
        if isinstance(value, list):
            return [shape(row) for row in value
                    if not isinstance(row, dict) or row.get('source_modifier') != CLEANSING]
        if isinstance(value, dict):
            row = {k: shape(v) for k, v in value.items()}
            if any(e.get('type') == 'water_cleansing' for e in row.get('effects') or []):
                row['who'] = 'any'
            if row.get('type') == 'water_cleansing':
                row['cleansing_water'] = 1
                found = True
            return row
        return value

    updated = shape(copy.deepcopy(typed))
    if not found:
        return None
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': updated}})


@hook('zone_trigger_context')
def cleansing_zone(ctx: Any, zone: Any, creature: Any, moment: str) -> None:
    """Bind the retained Basin identity for its shared one-creature-round budget."""
    if any(e.get('type') == 'water_cleansing' and e.get('cleansing_water') for e in ctx.typed.get('effects') or []):
        ctx.typed['_cleansing_zone_id'] = zone.zone_id


def cleansing_areas(engine: Any, owner: Any) -> list[Any]:
    """Read active upgraded Basins belonging to ``owner``; never spend a use.

    ``wash_targets`` consumes this list to bound the wash action to its creator's
    geometry. With no owned upgraded zone the result is empty. The query returns
    existing zone objects without changing source, counters or concentration.
    """
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == owner.entity_id
            and any(e.get('type') == 'water_cleansing' and e.get('cleansing_water')
                    for trigger in z.trigger_profile.get('triggers') or [] for e in trigger.get('effects') or [])]


def wash_targets(engine: Any, owner: Any) -> dict[str, Any]:
    """Read washable creature/object IDs in this creator's active upgraded Basins.

    ``wash_allowed`` consumes emptiness for legal candidates; ``wash_residue``
    presents the complete returned mapping to the creator's choice transport.
    The query spends nothing and returns {} with no eligible in-area residue.
    Automatic creators retain the native creature/object perception filters.
    """
    from ..senses import perceives, perceives_object
    automatic = ai_controlled(engine, owner)
    cells = tuple(p for z in cleansing_areas(engine, owner) for p in z.affected_cells)
    targets = {a.entity_id: a for a in engine.state.actors.values() if a.active
               and residue_conditions(a, wash_only=True) and (not automatic or a is owner or perceives(engine, owner, a))
               and engine._footprint_intersects(a, cells)}
    targets.update({oid: obj for oid, obj in engine.state.objects.items() if not obj.destroyed
                    and (obj.component or {}).get('mundane_residue') in WASH_RESIDUE
                    and (obj.component or {}).get('magical') is not True
                    and (obj.component or {}).get('contested') is not True
                    and (not automatic or perceives_object(engine, owner, obj)) and obj.position in cells})
    return targets


@hook('compile_actions')
def cleansing_wash_action(info: dict[str, Any]) -> list[Any] | None:
    if CLEANSING not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f'{WASH}.{info["actor_id"]}', display_name='Cleansing Water: Wash Residue',
                             owner_id=info['actor_id'], economy='NONE', resolution_kind='TYPED', target_kind='SELF',
                             parameters={'typed': {'source': CLEANSING, 'numbers': dict(info['numbers']),
                                                   'effects': [{'type': 'water_wash_residue'}], 'riders': []},
                                         'description': 'Wash mundane poison or acid residue, dust, ash or filth from one '
                                                        'creature or object in your Cleansing Basin; allies gain your Proficiency Bonus in Temporary HP. No action or Cultivation Point cost; '
                                                        'this does not cure Poisoned, disease or curses. '
                                                        'Smoke removal uses the Basin benefit, limited to one creature per round.'})]


@hook('candidate_allowed')
def wash_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.source_definition_id.startswith(WASH + '.'):
        return bool(wash_targets(engine, actor))
    return None


@effect('water_wash_residue')
def wash_residue(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .condition_ownership import remove_instance
    targets = wash_targets(ctx.engine, ctx.actor)
    names = {key: (target.display_name if hasattr(target, 'entity_id') else
                   f'{(target.component or {}).get("name") or target.object_kind} at square ({target.position.x}, {target.position.y})')
             for key, target in targets.items()}
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'WATER_WASH', ctx.actor.entity_id), ctx.actor,
                   'choice:needle.water_wash_residue', list(targets), allow_decline=True,
                   labels={key: f'Wash mundane residue from {name}' for key, name in names.items()},
                   name='Cleansing Water', feature_id=CLEANSING,
                   prompt='Cleansing Water: choose one creature or object in your Cleansing Basin to wash. '
                          'Remove mundane surface poison, acid residue, dust, ash or filth; no action or Cultivation Point cost. '
                          'This does not cure Poisoned, magical disease or curses.')
    if not selected:
        return
    target = targets[selected[0]]
    if hasattr(target, 'entity_id'):
        for iid in residue_conditions(target, wash_only=True):
            remove_instance(ctx.engine, target, iid, ctx.source)
        if target.team_id == ctx.actor.team_id:
            from dataclasses import replace
            from ..typed_executor import run_effects
            run_effects(replace(ctx, targets=[target], target=target),
                        [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb'}])
    else:
        target.component.pop('mundane_residue', None)
        ctx.engine._update_object(target, ctx.source, actor_id=ctx.actor.entity_id)
    note(ctx.engine, ctx.source, ctx.actor, f'Cleansing Water washes mundane residue from {names[selected[0]]}.')


@hook("compile_action")
def wave_burst_replaces_current_save(action: Any, info: dict[str, Any]) -> Any:
    """The burst replaces the current's initial one-creature push, not two pushes."""
    typed = (action.parameters or {}).get("typed") or {}
    if (typed.get("modifier") or {}).get("id") != "TAL_WATER_WAVE_BURST":
        return None
    effects = [e for e in typed.get("effects") or []
               if not (e.get("type") == "save" and e.get("cast_only") and not e.get("source_modifier"))]
    return action.model_copy(update={"parameters": {**action.parameters, "typed": {**typed, "effects": effects}}})


@effect("water_cleansing")
def cleansing(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .condition_ownership import remove_instance
    from .rider_choices import pick, trigger_name

    engine, owner, creature = ctx.engine, ctx.actor, ctx.target
    if creature is None or not creature.active:
        return
    ally = creature.team_id == owner.team_id
    if not ally and not eff.get('cleansing_water'):
        return
    soaked = [iid for iid, row in creature.conditions.items() if row.condition_id.startswith(SOAKED_PREFIX)]
    burning = [iid for iid, row in creature.conditions.items() if row.condition_id == BURNING]
    upgraded = bool(eff.get('cleansing_water'))
    zone = engine.state.zones.get(ctx.typed.get('_cleansing_zone_id')) if upgraded else None
    cleanable = {**residue_conditions(creature), **{iid: creature.conditions[iid] for iid in burning}}
    can_clean = bool(zone and zone.per_turn_triggered.get('cleansing_water_round') != engine.state.round_number and cleanable)
    labels = {"save": "Advantage on its next saving throw against Poisoned or a disease before the start of its next turn"} if ally else {}
    if ally and soaked:
        labels = {"soaked": "End the Soaked state on itself", **labels}
    if ally and burning:
        labels = {"flames": "Put out the flames on itself (end Burning)", **labels}
    if can_clean:
        labels = {'cleanse': 'Cleansing Water: end Burning, covered-in-smoke or mundane contamination on yourself '
                             '(one creature per Basin per round)', **labels}
    if not labels:
        return
    options = list(labels)
    name = 'Cleansing Water (Cleansing Basin)' if upgraded else 'Cleansing Basin'
    chosen = pick(engine, creature, "water_cleansing", name, options, subject=creature, labels=labels, preferred=[options[0]],
                  trigger=f"{trigger_name(engine)}: {creature.display_name} is in {owner.display_name}'s Cleansing Basin",
                  choose=(f'Choose a free benefit; Cleansing Water also grants {int(ctx.numbers.get("pb") or 0)} Temporary HP.'
                          if upgraded and ally else 'Choose an option.'))
    if not chosen:
        return
    if chosen[0] == 'cleanse':
        from .retained_updates import record_zone_update
        for iid in cleanable:
            remove_instance(engine, creature, iid, ctx.source)
        zone.per_turn_triggered['cleansing_water_round'] = engine.state.round_number
        record_zone_update(engine, zone)
    elif chosen[0] == "flames":
        for iid in burning:
            remove_instance(engine, creature, iid, ctx.source)
    elif chosen[0] == "soaked":
        for iid in soaked:
            remove_instance(engine, creature, iid, ctx.source)
    else:
        run_effects(ctx, [{"type": "advantage", "applies_to": "target", "on": "the next saving throw against Poisoned or a disease",
                           "duration": "until_start_of_next_turn",
                           "evidence": "gain Advantage on the next saving throw before the start of its next turn against Poisoned, a disease, smoke, heat, or mundane contamination"}])
    if upgraded and ally:
        run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb',
                           'evidence': 'an ally that benefits from the Basin gains Temporary HP equal to your Proficiency Bonus'}])
    extra = f' Cleansing Water grants {int(ctx.numbers.get("pb") or 0)} Temporary HP (use the higher Temporary HP total).' if upgraded and ally else ''
    note(engine, ctx.source, owner, f"Cleansing Basin: {creature.display_name} -- {labels[chosen[0]].lower()}.{extra}", (creature,))
