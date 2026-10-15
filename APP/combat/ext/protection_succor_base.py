"""Base Succor procedure; pure, default-inert compilation of owned reactions."""
from . import hook

@hook('compile_bundle')
def succor(bundle, info):
    if 'tianxia.sphere.protection' not in (info.get('owner_sheet', {}).get('spheres_and_talents', {}).get('sphere_record_ids') or ()):
        return None
    for row in bundle.get('typed_reactions', ()):
        effects = row.get('effects') or []
        sacrifice = [r for r in effects if r.get('type') in ('spend_mark', 'mark_consume')
                     and r.get('mark') == 'Persistent Aegis']
        if not sacrifice:
            continue
        row['range_ft'] = min(int(row.get('range_ft') or 300), 300)
        row['range_reference'] = 'subject'
        row['effects'] = sacrifice + [r for r in effects if r not in sacrifice]
    return bundle
