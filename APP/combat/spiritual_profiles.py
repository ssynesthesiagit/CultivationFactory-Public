"""Explicit table/source object profiles, shared by maps and spirit contact.

A name or cosmetic material never makes an object spiritual. These primitive
facts require a recorded Source Rule and CL and survive the native map seal.
"""


def normalize(value):
    allowed = {'source_rule', 'source_cl', 'identity', 'anchor', 'contact_barrier', 'plane'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('Spiritual profiles require explicit source facts')
    if not isinstance(value.get('source_rule'), str) or not value['source_rule'].strip():
        raise ValueError('Spiritual profiles require a Source Rule')
    if type(value.get('source_cl')) is not int or value['source_cl'] < 1:
        raise ValueError('Spiritual profiles require a positive Source CL')
    result = {'source_rule': value['source_rule'], 'source_cl': value['source_cl']}
    for key in ('identity', 'contact_barrier'):
        flag = value.get(key, 0)
        if type(flag) not in (int, bool) or flag not in (0, 1):
            raise ValueError('Spiritual profile flags must be 0 or 1')
        result[key] = int(flag)
    anchor = value.get('anchor', 'none')
    if anchor not in ('none', 'internal', 'external'):
        raise ValueError('Anchor profile must be internal, external or none')
    result['anchor'] = anchor
    plane = value.get('plane', 'material')
    if not isinstance(plane, str) or not plane:
        raise ValueError('Spiritual profiles require a named plane')
    result['plane'] = plane
    return result
