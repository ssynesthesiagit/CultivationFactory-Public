"""Pre-spend dependencies for owned actions and generic reactions.

Compiled typed metadata may supply requires_compiled_actions: exact
action IDs that must exist in this actor's action_ids and the action catalogue.
It may also supply min_cl: a printed "Prerequisite: CL N+" construction gate,
read against the actor's own compiled Cultivation Level (typed numbers.cl,
baked when the character was compiled).
Candidate regeneration and reaction admission check before any payment. A generic
reaction row carries the same gate on row_allowed, the path _can_trigger consults for
every generic row, so a plug-in that admits its own row without _subject_ok reads it too
(Thousand-Grain Grip answering the escape check). This is not a substitute implementation
for a missing action (for example Tumble). Absent metadata leaves older fights and
unrelated characters unchanged.
"""
from . import hook, effect


@hook('compile_passives', priority=1000)
def native_source_profiles(rows, info):
    """Seal source groups at compilation, for later named-system restrictions."""
    from ..typed_numbers import authority_mechanics
    from copy import deepcopy
    mechanics = authority_mechanics()
    result = []
    for original in rows:
        row = deepcopy(original)
        feature = str(row.get('feature_id') or '')
        source = mechanics.get(feature) or {}
        group = source.get('sphere_id') or (feature.split('.feature.')[0] if '.feature.' in feature else '')
        if group:
            row['cultivation_source_group'] = group
        result.append(row)
    return result


def source_suppressed(engine, actor, source, typed=None):
    """Named-source extension of cultivation_suppression; no scope is inert.

    Source consumers supply exact native action/source identities. These records
    never suppress mundane actions or grant knowledge of an unobserved system.
    """
    typed = typed or {}
    identity = typed.get('option_of') or typed.get('source') or source
    for condition in actor.conditions.values():
        if condition.condition_id != 'condition:typed.cultivation_suppression':
            continue
        scopes = condition.data.get('suppressed_sources') or []
        if source in scopes or identity in scopes:
            return True
        if condition.data.get('all_cultivation') == 1 and not typed.get('attack_action'):
            prefixes = ('tianxia.path.', 'tianxia.subpath.', 'tianxia.tradition.', 'tianxia.talent.', 'TAL_',
                        'tianxia.recorded_art.', 'tianxia.forged_technique.', 'tianxia.immortal_art.',
                        'tianxia.method.', 'tianxia.foundation.', 'foundation.', 'tianxia.item.')
            if str(identity or '').startswith(prefixes) or typed.get('sphere') or (typed.get('activation_profile') or {}).get('source_kind'):
                return True
    return False


def effective_cl(actor, printed_cl):
    """Explicit cultivated suppression caps; missing conditions are inert."""
    from ..typed_executor import condition_rules
    caps = [row['effective_cl'] for row in condition_rules(actor)
            if type(row.get('effective_cl')) is int]
    return min([int(printed_cl), *caps])


@effect('cultivation_suppression')
def suppress(ctx, row):
    """A source/GM supplied effective CL, never inferred from injury or Realm names."""
    from ..typed_executor import _default_subject
    if 'suppressed_sources' in row:
        from ..typed_executor import effect_expiry
        sources = row['suppressed_sources']
        whole = row.get('all_cultivation', 0)
        pools = row.get('blocked_pools') or []
        if type(whole) is not int or whole not in (0, 1):
            raise ValueError('Whole-cultivation scope must be the integer 0 or 1.')
        if not isinstance(pools, list) or any(type(p) is not str or not p for p in pools) or len(set(pools)) != len(pools):
            raise ValueError('Blocked pools must be distinct native resource identities.')
        if not isinstance(sources, list) or not (sources or pools or whole) or any(type(s) is not str or not s for s in sources):
            raise ValueError('Named cultivation suppression requires explicit source identities.')
        if not row.get('duration') and not row.get('expires_on'):
            raise ValueError('Named cultivation suppression requires an explicit duration.')
        for target in _default_subject(ctx, row, harmful=True):
            before = set(target.conditions)
            ctx.engine._apply_condition(target, 'condition:typed.cultivation_suppression', ctx.source,
                ctx.actor.entity_id, expires_on=effect_expiry(ctx, row, target, condition=True),
                data={'label': row.get('label') or 'Named cultivation system suppressed',
                      'suppressed_sources': list(dict.fromkeys(sources)),
                      'source_cl': int(ctx.numbers.get('cl') or 1),
                      **({'all_cultivation': 1} if whole else {}),
                      **({'blocked_pools': list(row['blocked_pools'])} if row.get('blocked_pools') else {}),
                      **({'repeat_save': row['repeat_save']} if row.get('repeat_save') else {}),
                      **({'escape_dc': int(row['escape_dc'])} if row.get('escape_dc') else {})})
            marker = next((c for k, c in target.conditions.items() if k not in before
                           and c.condition_id == 'condition:typed.cultivation_suppression'), None)
            if marker is not None:
                capture_source_effects(ctx, target, marker)
        return
    cap = row.get('effective_cl')
    if type(cap) is not int or not 1 <= cap <= 40:
        raise ValueError('Cultivation suppression needs a whole effective Cultivation Level (1–40).')
    for target in _default_subject(ctx, row, harmful=True):
        ctx.engine._apply_condition(target, 'condition:typed.cultivation_suppression', ctx.source,
            ctx.actor.entity_id, expires_on=row.get('expires_on') or 'UNTIL_REMOVED',
            data={'label': f'Cultivation suppressed to level {cap}: higher-level cultivation abilities are unavailable.',
                  'rule': {'effective_cl': cap}})


def min_cl_ready(actor, row):
    """"Prerequisite: CL N+" on its own: False below the printed gate, else None (no opinion)."""
    min_cl = row.get('min_cl')
    numbers = row.get('numbers') or {}
    if min_cl is not None and effective_cl(actor, numbers.get('source_cl', numbers.get('cl') or 1)) < int(min_cl):
        return False  # this character is below the printed gate.
    return None


def dependencies_ready(engine, actor, row):
    """Pure readiness shared by primary and reaction admission."""
    below_gate = min_cl_ready(actor, row)
    if below_gate is False:
        return below_gate
    required = row.get('requires_compiled_actions')
    if required is None:
        return None
    owned = set(engine.actor_templates[actor.entity_id].action_ids)
    if not isinstance(required, list) or not required or any(
            not isinstance(source, str) or source not in owned or source not in engine.action_catalog
            for source in required):
        return False
    return None


@hook('candidate_allowed')
def candidate_ready(engine, actor, candidate, action):
    if source_suppressed(engine, actor, candidate.source_definition_id,
                         (getattr(action, 'parameters', None) or {}).get('typed') or {}):
        return False
    return dependencies_ready(engine, actor, (getattr(action, 'parameters', None) or {}).get('typed') or {})


@hook('reaction_subject_allowed')
@hook('reaction_ally_allowed')
def reaction_ready(engine, actor, subject, row):
    if source_suppressed(engine, actor, row.get('feature_id'), row):
        return False
    return dependencies_ready(engine, actor, row)


@hook('row_allowed')
def generic_row_below_printed_gate(engine, actor, row):
    """The printed CL gate on a generic reaction row, on the admission path every generic row takes.

    ``_can_trigger`` consults row_allowed for every generic row (combat/typed_reactions.py), so a
    plug-in that admits its own row through _can_trigger instead of _subject_ok still reads the
    gate: Thousand-Grain Grip, which offers the burier's compiled "moved" row on its Action
    escape check (combat/ext/sand_burial.py _offer_grip). Absent min_cl, inert.
    """
    return False if source_suppressed(engine, actor, row.get('feature_id'), row) else min_cl_ready(actor, row)


@hook('effect_allowed')
def source_effect_ready(ctx, row):
    return False if source_suppressed(ctx.engine, ctx.actor, ctx.source, ctx.typed) else None


@hook('sense_grant_allowed')
def named_sense_ready(engine, actor, row, seen):
    return False if source_suppressed(engine, actor, row.get('feature_id')) else None


def capture_source_effects(ctx, target, marker):
    """Suspend actual ongoing effects for a named-source restriction.

    Public suppression adapters retain original identities, costs and clocks.
    Innate/passive physical statistics are never reconstructed from a catalog.
    """
    from . import benefit_suppression, area_suppression
    scope = set(marker.data['suppressed_sources'])
    def matched(source):
        action = ctx.engine.action_catalog.get(source)
        typed = (action.parameters or {}).get('typed') or {} if action else {}
        return source in scope or (typed.get('option_of') or typed.get('source')) in scope
    captures = [('condition:' + c.instance_id, c.source_definition_id) for c in list(target.conditions.values())
                if c is not marker and c.condition_id != 'condition:typed.cultivation_suppression'
                and c.source_actor_id == target.entity_id
                and c.expires_on not in (None, '') and (matched(c.source_definition_id) or source_suppressed(ctx.engine, target, c.source_definition_id))]
    captures.extend(('modifier:' + key, m.source_definition_id) for key, m in list(target.modifiers.items())
                    if m.source_actor_id == target.entity_id and m.expires_on not in (None, '', 'UNTIL_REMOVED')
                    and (matched(m.source_definition_id) or source_suppressed(ctx.engine, target, m.source_definition_id)))
    for key, source in captures:
        benefit_suppression.suppress(ctx.engine, ctx.actor, target, key, 'cultivation_source', ctx.source,
                                    label=marker.data['label'])
    areas = []
    for zone in list(ctx.engine.state.zones.values()):
        if zone.active and zone.owner_id == target.entity_id and (matched(zone.source_definition_id) or source_suppressed(ctx.engine, target, zone.source_definition_id)):
            record = area_suppression.suppress(ctx.engine, ctx.actor, zone, marker.expires_on, ctx.source)
            if record:
                areas.append([zone.zone_id, record['key']])
    if areas:
        from .retained_updates import record_instance_update
        marker.data = {**marker.data, 'suppressed_areas': areas}
        record_instance_update(ctx.engine, target, 'condition', marker.instance_id, marker)


@hook('event', nested=True)
def restore_named_sources(engine, event_type, kwargs):
    ended = kwargs.get('ended_effect')
    if event_type != 'CONDITION_REMOVED' or ended is None or ended.get('condition_id') != 'condition:typed.cultivation_suppression':
        return
    from . import benefit_suppression, area_suppression
    for target in engine.state.actors.values():
        for marker in list(target.conditions.values()):
            if marker.condition_id != benefit_suppression.SUPPRESSED or marker.data.get('until') != 'cultivation_source':
                continue
            original = marker.data.get('model') or {}
            if not source_suppressed(engine, target, original.get('source_definition_id')):
                benefit_suppression.release(engine, target, marker)
    for zone_id, key in (ended.get('data') or {}).get('suppressed_areas') or []:
        zone = engine.state.zones.get(zone_id)
        if zone is not None:
            area_suppression.release(engine, zone, key)


def blocked_pools(actor):
    return {pool for c in actor.conditions.values() if c.condition_id == 'condition:typed.cultivation_suppression'
            for pool in c.data.get('blocked_pools') or []}


@hook('resource_spend_allowed')
@hook('resource_gain_allowed')
def scoped_resource_permission(engine, actor, resource_id, amount, source_id):
    return False if amount > 0 and resource_id in blocked_pools(actor) else None


@hook('candidate_allowed')
def scoped_resource_action(engine, actor, candidate, action):
    blocked = blocked_pools(actor)
    return False if blocked and any(pool in blocked and amount > 0 for pool, amount in getattr(action, 'costs', ())) else None


@hook('row_allowed')
def scoped_resource_reaction(engine, actor, row):
    from ..resource_costs import parts
    blocked = blocked_pools(actor)
    return False if blocked and any(pool in blocked and amount > 0 for pool, amount in map(parts, row.get('costs') or [])) else None


@hook('turn_end')
def named_repeat_save(engine, actor):
    from .condition_ownership import remove_instance
    for c in list(actor.conditions.values()):
        rule = c.data.get('repeat_save')
        if c.condition_id != 'condition:typed.cultivation_suppression' or not rule:
            continue
        rolled = engine._roll_save(actor, rule['ability'], int(rule['dc']), c.source_definition_id)
        if rolled is not None and rolled.total >= int(rule['dc']):
            remove_instance(engine, actor, c.instance_id, c.source_definition_id)


def escape_bindings(actor):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.cultivation_suppression'
            and int(c.data.get('escape_dc') or 0) > 0]


ESCAPE_ACTION = 'action:system.escape_cultivation_seal'


@hook('match_start')
def named_escape_action(engine):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    engine.action_catalog[ESCAPE_ACTION] = ActionDefinition(source_definition_id=ESCAPE_ACTION,
        owner_id='*', display_name='Break a cultivation seal', economy=EconomyKind.ACTION,
        resolution_kind='TYPED', target_kind='SELF', parameters={'cultivation_escape': 1,
            'expected_damage': 0, 'typed': {'source': 'system:escape_cultivation_seal', 'numbers': {},
            'effects': [{'type': 'escape_cultivation_seal'}], 'riders': [], 'manual_inline_choice': True}})


@hook('additional_actions')
def named_escape_offered(engine, actor):
    return [ESCAPE_ACTION] if escape_bindings(actor) and ESCAPE_ACTION in engine.action_catalog else []


@hook('candidate_allowed')
def named_escape_ready(engine, actor, candidate, action):
    if (getattr(action, 'parameters', None) or {}).get('cultivation_escape'):
        return bool(escape_bindings(actor))
    return None


@effect('escape_cultivation_seal')
def named_escape(ctx, row):
    from dataclasses import replace
    from .needle import numbers_of
    ctx = replace(ctx, typed={**ctx.typed, 'numbers': numbers_of(ctx.engine, ctx.actor)})
    from .needle import ask, checkpoint_id
    held = escape_bindings(ctx.actor)
    if not held:
        return
    picks = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'escape_cultivation_seal'), ctx.actor,
        'choice:needle.escape_cultivation_seal', [c.instance_id for c in held],
        labels={c.instance_id: c.data['label'] for c in held}, name='Break a cultivation seal',
        prompt=f'{ctx.actor.display_name}: choose one seal with a printed Cultivation Check escape. This costs your Action; success ends only that seal.')
    if not picks:
        return
    seal = next(c for c in held if c.instance_id == picks[0])
    owner = ctx.engine.state.actors.get(seal.source_actor_id)
    if owner is None:
        return
    from ..typed_executor import resolve_opposed_check
    result = resolve_opposed_check(ctx, owner, {'kind': 'cultivation'}, {'kind': 'dc', 'dc': int(seal.data['escape_dc'])})
    if result.success:
        from .condition_ownership import remove_instance
        remove_instance(ctx.engine, ctx.actor, seal.instance_id, seal.source_definition_id)
