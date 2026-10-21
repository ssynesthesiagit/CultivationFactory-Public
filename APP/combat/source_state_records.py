"""Owner/table declarations of ongoing source facts, never inferred diagnoses.

Used by map normalization and source_state's native effect/genesis producers.
The source's declared lifetime bounds the facts; no extra penalty is granted.
"""
CATEGORIES = ('ordinary_possession', 'curse', 'heart_demon', 'spiritual_contamination',
              'external_controlling_link', 'disguised_spirit_body_relation')
FACT_KEYS = {'categories', 'plane', 'perfect_spiritual_concealment', 'spiritual_contact_denied',
             'level_limit_path', 'level_limit_cl'}


def normalize_facts(row):
    categories = row.get('categories') or {}
    if not isinstance(categories, dict) or any(k not in CATEGORIES or v not in ('present', 'absent') for k, v in categories.items()):
        raise ValueError('Source states require explicit known categories')
    data = {'category:' + k: v for k, v in categories.items()}
    for key in FACT_KEYS - {'categories'}:
        if key not in row:
            continue
        value = row[key]
        if type(value) not in (str, int, bool):
            raise ValueError('Source-state facts must be primitive')
        if key in ('plane', 'level_limit_path') and (not isinstance(value, str) or not value):
            raise ValueError('Source-state plane/path must be explicit names')
        if key in ('perfect_spiritual_concealment', 'spiritual_contact_denied') and (type(value) not in (int, bool) or value not in (0, 1)):
            raise ValueError('Source-state contact flags must be 0 or 1')
        data[key] = int(value) if type(value) is bool else value
    if ('level_limit_path' in data or 'level_limit_cl' in data) and (
            'level_limit_path' not in data or type(data.get('level_limit_cl')) is not int or data['level_limit_cl'] < 0):
        raise ValueError('Source states require a nonnegative effective CL and its Path')
    return data


def normalize_record(row):
    allowed = {'target_id', 'source_rule', 'source_cl', 'source_actor_id', 'duration_rounds', 'facts', 'label'}
    if not isinstance(row, dict) or set(row) - allowed:
        raise ValueError('Ongoing source states require an explicit table record')
    for key in ('target_id', 'source_rule'):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise ValueError('Ongoing source states require a creature and Source Rule')
    for key in ('source_cl', 'duration_rounds'):
        if type(row.get(key)) is not int or row[key] < 1:
            raise ValueError('Source CL and lifetime in rounds must be positive whole numbers')
    if not isinstance(row.get('facts'), dict) or set(row['facts']) - FACT_KEYS:
        raise ValueError('Ongoing source states require explicit source facts')
    normalize_facts(row['facts'])
    if not isinstance(row.get('source_actor_id', ''), str):
        raise ValueError('Source creature must be a recorded identifier or unknown')
    if not isinstance(row.get('label', 'Ongoing source effect'), str):
        raise ValueError('Source effect label must be text')
    return {**row, 'facts': dict(row['facts'])}
