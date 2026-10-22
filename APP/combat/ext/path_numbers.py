"""Owning-Path numbers for explicitly multi-Path portable sheets.

Used by Poison Touch; reusable by Path/Subpath plug-ins. An explicit Path row
uses its effective_cl and key ability instead of another Path's overall CL.
Single-Path sheets without rows retain their ordinary compiled numbers.
"""
def numbers_for(info, path_id):
    numbers = dict(info['numbers'])
    rows = (info['owner_sheet'].get('path_and_subpath') or {}).get('paths') or []
    row = next((r for r in rows if isinstance(r, dict) and r.get('path_id') == path_id), None)
    if row is not None:
        numbers['cl'] = int(row.get('effective_cl', row.get('attainment', 0)))
        if row.get('key_ability'):
            key = str(row['key_ability']).upper()[:3]
            numbers['key_mod'] = int(info['mods'].get(key, 0))
            numbers['attack_bonus'] = numbers['pb'] + numbers['key_mod']
            numbers['save_dc'] = 8 + numbers['attack_bonus']
    return numbers
