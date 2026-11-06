"""Pure useful recovery queries for controller scoring, sharing execution rules.

Only immediate executable effects count. Query-local preparation is reused for
an action's target variants; no cache or mutation is stored on the fight.
"""
from .effect_eligibility import eligible
from .temp_hp_terms import fold_temp_hp
from .typed_amounts import average_amount


def prepare(engine, actor, action):
    from .typed_executor import Context, rules
    typed = action.parameters.get('typed') or {}
    effects = [row for row in typed.get('effects') or () if isinstance(row, dict)
               and row.get('type') in {'healing', 'temp_hp'} and not row.get('deferred')]
    if not effects:
        return None
    ctx = Context(engine, actor, action, None, typed, [])
    ready, folded = [], set()
    for effect in effects:
        if id(effect) in folded or not eligible(ctx, effect):
            continue
        if effect['type'] == 'temp_hp':
            effect = fold_temp_hp(effects, effect, folded, eligible=lambda row: eligible(ctx, row))
        parts = (effect.get('parts') or [effect]) if effect['type'] == 'temp_hp' else [effect]
        amount = sum(average_amount(part, ctx.numbers,
            trigger_damage=getattr(engine, '_typed_trigger_damage', 0),
            unknown=rules()['defaults'].get('unknown_formula_value', 0))
            for part in parts)
        ready.append((effect, amount))
    return ready


def recovery(engine, actor, candidate, action, *, cache=None):
    """Useful integer HP by recipient; None for actions without recovery rows.

    Existing Temporary HP is replaced, not added. Its increase is capped at
    missing HP as a conservative AI priority. Optional cache belongs to ONE
    context build only. No effect execution, spending, random roll or prompt.
    """
    if cache is not None:
        key = action.source_definition_id
        if key not in cache:
            cache[key] = prepare(engine, actor, action)
        effects = cache[key]
    else:
        effects = prepare(engine, actor, action)
    if effects is None:
        return None
    from .typed_executor import Context, _default_subject, _area_targets, stored_healing_reductions, condition_rules
    from .ext.life_state import is_dead
    typed = action.parameters.get('typed') or {}
    targets = [engine.state.actors[aid] for aid in candidate.target_ids if aid in engine.state.actors]
    if candidate.destination and typed.get('area'):
        targets = _area_targets(engine, actor, candidate.destination, typed['area'], typed=typed)
    target = targets[0] if len(targets) == 1 else None
    ctx = Context(engine, actor, action, None, typed, targets, target)
    remaining, temps, values = {}, {}, {}
    for effect, amount in effects:
        for subject in _default_subject(ctx, effect, harmful=False):
            if not subject.active or subject.team_id != actor.team_id or is_dead(subject):
                continue
            aid = subject.entity_id
            missing = remaining.setdefault(aid, max(0, subject.maximum_hp - subject.current_hp))
            row = values.setdefault(aid, {'target_id': aid, 'healing_hp': 0, 'temporary_hp': 0})
            if effect['type'] == 'healing':
                useful = min(missing, stored_healing_reductions(engine, subject, amount, consume=False))
                remaining[aid] -= useful
                row['healing_hp'] += useful
            elif not any(rule.get('temp_hp_denied') for rule in condition_rules(subject)):
                current = temps.setdefault(aid, subject.temporary_hp)
                grant = min(amount, missing) if effect.get('cap_at_missing_hp') else amount
                row['temporary_hp'] += min(max(0, missing - row['temporary_hp']), max(0, grant - current))
                temps[aid] = max(current, grant)
    return [values[aid] for aid in sorted(values)]
