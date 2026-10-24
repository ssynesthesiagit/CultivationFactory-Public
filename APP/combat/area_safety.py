"""Pure per-effect risk shared by placement labels, scoring and AI retaliation restraint.

Use executor geometry/scopes and compiler dice averages without rolling. New
fight previews run on the caster's knowledge projection; actual resolution
keeps its real recipients. Mutually
exclusive save/attack outcomes use their larger risk. Explicit self harm is an
activation cost, separate from collateral harm caused by the chosen placement.
"""
from dataclasses import replace
from .effect_harm import rows, classify_effect
from .read_queries import pure


def harmful_effect(ctx, row, *, saving_throw=False):
    """Pure leaf classification shared by area placement and controller risk.

Extensions may classify their own effect via area_effect_risk. Unknown save
outcomes conservatively retain the historical warning; known beneficial rows
are excluded. Classification never widens the executor's recipient set.
"""
    from . import ext
    replies = set(ext.run_strict('area_effect_risk', ctx, row)) - {None}
    if not replies <= {'harmful', 'harmless'} or len(replies) > 1:
        raise ValueError('area effect risk must be one consistent harmful/harmless answer')
    if replies:
        return 'harmful' in replies
    return builtin_harmful_effect(row, saving_throw=saving_throw)


def builtin_harmful_effect(row, *, saving_throw=False):
    """Compatibility facade for the shared pure harm contract (leaf risk)."""
    return classify_effect(row, saving_throw=saving_throw, recursive=False) is True


def _risk(ctx, effects, *, self_only=False, saving_throw=False):
    from .factory_compiler import _expected_damage
    from .typed_executor import effect_subjects, save_subjects
    from .area_recipients import harmful_effect_scope
    # Preserve self-cost provenance even if another area effect hits its user.
    result = {}
    def add(values):
        for key, amount in values.items():
            result[key] = result.get(key, 0) + amount
    for row in effects or ():
        if not isinstance(row, dict) or row.get('deferred'):
            continue
        cl = int(ctx.numbers.get('cl') or 1)
        if cl < int(row.get('min_cl') or 0) or (row.get('max_cl') is not None and cl > int(row['max_cl'])):
            continue
        kind = row.get('type')
        own = self_only or row.get('applies_to') == 'self'
        # Match execution's transient parent permission without mutating the
        # caller or leaking an inclusive container's scope into its siblings.
        inherited = getattr(ctx, 'area_harmful_scope', None)
        scope = harmful_effect_scope(ctx.typed.get('area') or {}, row, inherited=inherited)
        row_ctx = replace(ctx, area_harmful_scope=scope) if scope != inherited else ctx
        if kind in {'save', 'attack'}:
            subjects = save_subjects(row_ctx, row) if kind == 'save' else effect_subjects(row_ctx, row, harmful=True)
            keys = ('on_fail', 'on_success') if kind == 'save' else ('on_hit', 'on_miss')
            for subject in subjects:
                inner = replace(row_ctx, targets=[subject], target=subject,
                                explicit_self_recipient=own or getattr(ctx, 'explicit_self_recipient', False))
                branches = [_risk(inner, row.get(key), self_only=own,
                                  saving_throw=saving_throw or kind == 'save') for key in keys]
                add({key: max(branch.get(key, 0) for branch in branches)
                     for branch in branches for key in branch})
            continue
        if harmful_effect(row_ctx, row, saving_throw=saving_throw):
            leaf = {key: value for key, value in row.items()
                    if key not in {'effects', 'on_fail', 'on_success', 'on_hit', 'on_miss'}}
            amount = max(0, _expected_damage([leaf], ctx.numbers))
            for subject in effect_subjects(row_ctx, row, harmful=True):
                add({(subject.entity_id, own and subject.entity_id == ctx.actor.entity_id): amount})
        add(_risk(row_ctx, row.get('effects'), self_only=own, saving_throw=saving_throw))
    return result


@pure
def preview(engine, actor, action, destination, *, actors=None):
    """Placement estimate; an explicit roster projects knowledge without changing execution.

    hostile_damage_by_id carries per-recipient immediate damage estimates for
    AI focus/finishing comparisons. It excludes later zone exposure and explicit
    self costs, and grants no targeting or execution authority.
    """
    from .area_knowledge import preview_engine
    typed = action.parameters.get('typed') or {}
    area = typed.get('area') or {}
    if action.resolution_kind != 'TYPED' or not area.get('size_ft'):
        return None
    engine = preview_engine(engine, actor)
    return _preview(engine, actor, action, destination, actors=actors)


@pure
def _preview(engine, actor, action, destination, *, actors=None):
    """Scope all membership/risk queries to the actual knowledge projection.

    A copied engine has a different identity from the caller's read frame.
    Bind a fresh frame on that copy so area targets and nested save/effect/zone
    branches share pure geometry derivations. It lasts only this placement;
    exceptions restore the enclosing frame and later placements compute anew.
    No hook replies or recipient decisions are reused across projections.
    """
    from .typed_executor import Context, _area_targets, cant_hear
    from .relations import relation, ALLY, ENEMY
    typed = action.parameters.get('typed') or {}
    area = typed.get('area') or {}
    by_id = engine.state.actors if actors is None else {other.entity_id: other for other in actors}
    roster = by_id.values()
    targets = _area_targets(engine, actor, destination, area, typed=typed, actors=roster)
    if typed.get('requires_hearing'):
        from .speech import can_hear_from
        targets = [target for target in targets if can_hear_from(engine, actor, target, action.source_definition_id)]
    ctx = Context(engine, actor, action, None, typed, targets, targets[0] if len(targets) == 1 else None)
    risk = _risk(ctx, typed.get('effects'))
    direct_risk = dict(risk)
    spec = typed.get('zone_spec')
    if spec:
        from . import zones
        from .action_geometry import point
        from .spatial_areas import zone_contains
        # Runtime pays activation costs before it chooses affordable shaping.
        funded = actor.model_copy(update={'resources': dict(actor.resources)})
        for resource, cost in action.costs:
            funded.resources[resource] = funded.resources.get(resource, 0) - int(cost)
        spec, _ = zones.shaped_spec(engine, funded, spec)
        zone = zones.prospective_zone(ctx, spec, point(engine, actor) if spec.get('centered_on_self') else destination)
        for subject in roster:
            if not subject.active or not zone_contains(engine, subject, zone):
                continue
            from .area_recipients import delayed_area_context
            groups = [_risk(replace(ctx, typed={**typed, 'area': None,
                           **delayed_area_context(engine, zone, effects)}, targets=[subject], target=subject), effects)
                      for effects in zones.prospective_effects(engine, zone, subject)]
            # One possible exposure, not a sum of enter/start/future turns.
            for key in {key for group in groups for key in group}:
                risk[key] = risk.get(key, 0) + max(group.get(key, 0) for group in groups)
    choice = next((row for row in rows(typed.get('effects')) if row.get('type') == 'rider_choose_area_recipients'), None)
    allies = sorted((by_id[who] for who, own in risk
                     if not own and who in by_id and relation(engine, actor, by_id[who]) == ALLY), key=lambda a: a.entity_id)
    if choice and choice.get('hostile_only'):
        allies = []
    automatic_spares = choice is not None and not choice.get('automatic_friendly')
    metadata = {'hostile_damage_by_id': {
        who: amount for (who, own), amount in direct_risk.items()
        if not own and amount > 0 and who in by_id and relation(engine, actor, by_id[who]) == ENEMY}}
    if (actor.entity_id, True) in risk:
        metadata.update(self_harm=1, self_expected_damage=risk[(actor.entity_id, True)])
    if allies:
        metadata.update({'allies_in_area': len(allies),
                    'ally_expected_damage': 0 if automatic_spares else
                        sum(risk[(a.entity_id, False)] for a in allies),
                    'unavoidable_allies_in_area': 0 if automatic_spares else len(allies)})
    label = ('Allies you can choose: ' if choice else 'Hits allies too: ') + ', '.join(a.display_name for a in allies) if allies else ''
    return sum(relation(engine, actor, target) == ENEMY for target in targets), metadata, label


def harmful_recipients(ctx, effects):
    """Pure harmful recipient IDs shared by placement and AI reaction restraint.

    Damage of zero can still carry harmful conditions. Explicit self-costs are
    excluded; branches and scopes use the same executor rules as area previews.
    """
    return {who for who, own in _risk(ctx, effects) if not own}
