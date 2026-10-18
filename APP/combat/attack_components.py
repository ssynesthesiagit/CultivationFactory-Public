"""Mixed-type additions to one confirmed hit, shared by paid-hit providers.

Components retain type defenses and Resistance permissions. Flat defenses are
allocated once across their eligible portions; reactions and HP settle once.
Only resolution-local dictionaries are used, never serialized fight state.
"""
import json
from contextlib import contextmanager
from contextvars import ContextVar


_CURRENT = ContextVar('attack_components', default=None)


def rolled_component(amount, kind, roll=None, *, critical=False, **permissions):
    """Retain the actual dice provenance, without consulting unrelated events."""
    dice = list(getattr(roll, 'dice', ()) or ())
    return dict(amount=amount, damage_type=kind, **permissions,
                roll_id=getattr(roll, 'roll_id', None),
                critical_extra=sum(dice[len(dice)//2:]) if critical and dice else 0)


@contextmanager
def scope(engine, target, parts):
    """Recipient-bound, resolution-local portions for defense/share providers.

    Used by typed_reactions, lane4_crit, retribution_riders and damage_sharing.
    Nested defenses (including an ordinary single-type share) mask the parent.
    """
    token = _CURRENT.set((engine, target.entity_id, parts))
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current(engine, target):
    frame = _CURRENT.get()
    return frame[2] if frame and frame[0] is engine and frame[1] == target.entity_id else ()


def eligible_amount(engine, target, fallback, kinds):
    parts = current(engine, target)
    return sum(p['amount'] for p in parts if p['damage_type'].upper() in kinds) if parts else fallback


def reduce_eligible(engine, target, amount, *, kinds=None, critical=False):
    """Allocate a callback's reduction only to its qualifying portions.

    Return the scalar reduction too, for the unchanged single-packet contract.
    callbacks() reconciles explicit allocations so they are never applied twice.
    """
    parts = current(engine, target)
    left = amount
    for part in parts:
        if kinds is not None and part['damage_type'].upper() not in kinds:
            continue
        used = min(left, part['amount'], part.get('critical_extra', 0) if critical else left)
        part['amount'] -= used
        part['critical_extra'] = max(0, part.get('critical_extra', 0) - used)
        left -= used
    return amount


def callbacks(point, engine, target, amount, kind, source, actor, parts):
    """Run existing scalar callbacks once; preserve explicit type allocations."""
    from . import ext
    _adjust_total(parts, amount)
    # Scalar subscribers remain applicable when a component-aware subscriber
    # exists. Run them once first, then let component providers make their
    # type-specific allocations against the residual packet.
    component_handlers = ext.callbacks(point + '_components')
    component_modules = {handler.__module__ for handler in component_handlers}
    scalar_handlers = [handler for handler in ext.callbacks(point)
                       if handler.__module__ not in component_modules]
    removed = sum(int(value or 0) for handler in scalar_handlers
                  for value in (ext.invoke(point, handler, engine, target, amount, kind, source, actor),))
    remaining = max(0, amount - removed)
    _adjust_total(parts, remaining)
    for handler in component_handlers:
        handler(engine, target, parts, source, actor)
    return sum(max(0, int(part['amount'])) for part in parts)


def _adjust_total(parts, amount):
    if parts:
        # Providers that know their eligibility already changed the portions.
        # Only the residual scalar adjustment follows the legacy primary-first rule.
        difference = amount - sum(p['amount'] for p in parts)
        if difference >= 0:
            parts[0]['amount'] += difference
        else:
            left = -difference
            for part in parts:
                used = min(left, part['amount'])
                part['amount'] -= used
                part['critical_extra'] = min(part.get('critical_extra', 0), part['amount'])
                left -= used


def take_share(engine, target, amount, *, kinds=None):
    """Split a share proportionally by type/permission, preserving exact total.

    Integer cumulative allocation rounds only once over the whole instance;
    neither a primary-type label nor a new attack is invented for the share.
    """
    parts = [p for p in current(engine, target) if kinds is None or p['damage_type'].upper() in kinds]
    total = sum(p['amount'] for p in parts)
    if not parts or not total:
        return ()
    result, cumulative, allocated = [], 0, 0
    for part in parts:
        cumulative += part['amount']
        through = cumulative * amount // total
        portion = through - allocated
        allocated = through
        extra = min(portion, part.get('critical_extra', 0) * amount // total)
        result.append({**part, 'amount':portion, 'critical_extra':extra})
        part['amount'] -= portion
        part['critical_extra'] = max(0, part.get('critical_extra', 0) - extra)
    return result


def needs_component_settlement(parts):
    """Whether portions need independent defenses rather than the legacy scalar pipeline.

    Uniform, ordinarily defended damage keeps the historical scalar path. Component
    settlement is reserved for mixed types or an explicit per-component permission.
    This makes an empty/default component extension behaviorally inert.
    """
    if len(parts) < 2:
        return False
    kinds = {str(part.get('damage_type') or '').upper() for part in parts}
    if len(kinds) > 1:
        return True
    permission_keys = {'ignore_resistance', 'ignore_threshold', 'multiplier', 'resistance_types'}
    return any(any(part.get(key) for key in permission_keys) for part in parts)


def collect(primary, kind, components, *, primary_roll=None, critical=False):
    parts = [rolled_component(primary, kind, primary_roll, critical=critical), *components]
    for part in parts:
        if (type(part.get('amount')) is not int
                or not isinstance(part.get('damage_type'), str)):
            raise ValueError('Attack components require integer damage and a type')
    # Native damage rolls can be below zero after penalties. Match ordinary
    # damage settlement without turning a negative portion into healing.
    return [{**part,'amount':max(0,part['amount'])} for part in parts]


def defenses(engine, target, parts, source, actor, primary, *, native=False):
    from .typed_reactions import _defenses, _typed
    from . import ext
    founds = []
    for index, part in enumerate(parts):
        found = dict(primary) if index == 0 else _defenses(
            engine, target, part['damage_type'], source, actor, native=native)
        if part.get('ignore_resistance'):
            found['resist'] = False
            found['resistance_suppressed'] = True
        founds.append(found)
    combined = dict(primary)
    combined['immune'] = all(f['immune'] for p,f in zip(parts,founds) if p['amount'] > 0)
    for key in ('once', 'resistance_next', 'per_round'):
        combined[key] = list(dict.fromkeys(v for p,f in zip(parts,founds) if p['amount'] > 0 for v in f[key]))
    # A defense row applicable to multiple portions still reduces one attack.
    reductions = {}
    for index, found in enumerate(founds):
        if found['immune'] or parts[index]['amount'] <= 0:
            continue
        for row in found['reduction_rows']:
            # Dynamic providers often narrow damage_types to the queried type.
            # That projection does not create a second use of the same defense.
            key = json.dumps({k:v for k,v in row.items() if k!='damage_types'}, sort_keys=True)
            entry = reductions.setdefault(key, [row, []])
            entry[1].append(index)
    # Numeric reducers are independent providers, not one competing total.
    # The same provider applies once across its eligible types; different
    # providers add. Keep its callback transient for exact applied receipts.
    if engine is not None:
        typed = _typed(engine, source)
        for index, (part, found) in enumerate(zip(parts, founds)):
            if found['immune'] or part['amount'] <= 0:
                continue
            kind = part['damage_type'].upper()
            for handler, value in ext.run('damage_reduction',engine,target,kind,typed,actor,_with_handlers=True):
                if not value:
                    continue
                key = ('handler',handler)
                row, indices = reductions.setdefault(key,[{'kind':'reduction','amount':0,
                    'handler':handler,'contexts':{},'caps':{}},[]])
                row['amount'] = max(row['amount'],int(value))
                row['contexts'][index] = (kind,typed)
                row['caps'][index] = max(0,int(value))
                indices.append(index)
    combined['reduction'] = sum(int(row.get('amount') or 0) for row, _ in reductions.values()
                                if row.get('kind') == 'reduction')
    combined['ext_reduction'] = 0  # every reduction is allocated in apply()
    return combined, (parts, founds, reductions)


def apply(amount, prepared, *, receipt=None):
    parts, founds, reductions = prepared
    values = [p['amount'] for p in parts]
    # Earlier packet-wide additions/reductions affect the primary portion first.
    difference = amount - sum(values)
    if difference >= 0:
        values[0] += difference
    else:
        left = -difference
        for i in range(len(values)):
            used = min(left, values[i]); values[i] -= used; left -= used
    for row, indices in reductions.values():
        if row.get('kind') != 'reduction_before_resistance':
            continue
        left = int(row.get('amount') or 0)
        before = left
        for i in indices:
            used = min(left, values[i]); values[i] -= used; left -= used
        if receipt is not None and left < before:
            receipt.append(row)
    # Same-type, same-permission portions share rounding. Immunity is never bypassed.
    groups = {}
    for part, value, found in zip(parts, values, founds):
        if found['immune']:
            continue
        key = (part['damage_type'].upper(), found['resist'], found['vulnerable'])
        groups[key] = groups.get(key, 0) + value
    defended = [0] * len(parts)
    for key, total in groups.items():
        _, resist, vulnerable = key
        left = (total // 2 if resist else total) * (2 if vulnerable else 1)
        indices = [i for i, (p, f) in enumerate(zip(parts, founds)) if not f['immune']
                   and (p['damage_type'].upper(), f['resist'], f['vulnerable']) == key]
        for i in indices[:-1]:
            defended[i] = (values[i] // 2 if resist else values[i]) * (2 if vulnerable else 1)
            left -= defended[i]
        defended[indices[-1]] = left
    for row, indices in reductions.values():
        if row.get('kind') != 'reduction':
            continue
        left = int(row.get('amount') or 0)
        before = left
        first_applied = None
        for i in indices:
            used = min(left, defended[i], row.get('caps',{}).get(i,left)); defended[i] -= used; left -= used
            if used and first_applied is None:
                first_applied = i
        if receipt is not None and left < before:
            receipt.append({**row,'applied_index':first_applied})
    return max(0, sum(defended))
