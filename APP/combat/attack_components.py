"""Mixed-type additions to one confirmed hit, shared by paid-hit providers.

Components retain type defenses and Resistance permissions. Flat defenses are
allocated once across their eligible portions; reactions and HP settle once.
Only resolution-local dictionaries are used, never serialized fight state.
"""
import json


def collect(primary, kind, components):
    parts = [{'amount': primary, 'damage_type': kind}, *components]
    for part in parts:
        if (type(part.get('amount')) is not int or part['amount'] < 0
                or not isinstance(part.get('damage_type'), str)):
            raise ValueError('Attack components require nonnegative integer damage and a type')
    return parts


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
    combined['immune'] = all(f['immune'] for f in founds)
    for key in ('once', 'resistance_next', 'per_round'):
        combined[key] = list(dict.fromkeys(v for p,f in zip(parts,founds) if p['amount'] > 0 for v in f[key]))
    # A defense row applicable to multiple portions still reduces one attack.
    reductions = {}
    for index, found in enumerate(founds):
        if found['immune']:
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
            if found['immune']:
                continue
            kind = part['damage_type'].upper()
            for handler, value in ext.run('damage_reduction',engine,target,kind,typed,actor,_with_handlers=True):
                if not value:
                    continue
                key = ('handler',handler)
                row, indices = reductions.setdefault(key,[{'kind':'reduction','amount':0,
                    'handler':handler,'contexts':{}},[]])
                row['amount'] = max(row['amount'],int(value))
                row['contexts'][index] = (kind,typed)
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
            used = min(left, defended[i]); defended[i] -= used; left -= used
            if used and first_applied is None:
                first_applied = i
        if receipt is not None and left < before:
            receipt.append({**row,'applied_index':first_applied})
    return max(0, sum(defended))
