"""Explicit table/source object profiles, shared by maps, spirit contact and Palm.

A name or cosmetic material never makes an object spiritual. These primitive
facts require a recorded Source Rule and CL when the profile claims one; the
Palm seam's explicit external/internal Anchor flags may stand on their own.
Both vocabularies normalize to one primitive record so an object seeded from a
map (``objects.seed``) and the same object validated at match start agree.
"""

_ALLOWED = {
    # Spirit-contact source facts (this tradition's table/source declarations).
    'source_rule', 'source_cl', 'identity', 'anchor', 'contact_barrier', 'plane',
    # Palm/source-record anchor flags (object_subjects' explicit layout).
    'external_anchor', 'cultivation_asset', 'internal_anchor', 'affectable',
    'saving_throws', 'known_to',
}
ANCHORS = ('none', 'internal', 'external')


def _flag(value, name):
    if type(value) not in (int, bool) or value not in (0, 1):
        raise ValueError(f'Spiritual profile {name} must be 0 or 1')
    return int(value)


def normalize(value):
    if not isinstance(value, dict) or set(value) - _ALLOWED:
        raise ValueError('Spiritual profiles require explicit source facts')
    source_rule, source_cl = value.get('source_rule'), value.get('source_cl')
    if (source_rule is None) != (source_cl is None):
        raise ValueError('Spiritual profiles require both a Source Rule and Source CL')
    if source_rule is not None:
        if not isinstance(source_rule, str) or not source_rule.strip():
            raise ValueError('Spiritual profiles require a Source Rule')
        if type(source_cl) is not int or source_cl < 1:
            raise ValueError('Spiritual profiles require a positive Source CL')
    result = {}
    if source_rule is not None:
        result.update(source_rule=source_rule, source_cl=source_cl)
    identity = _flag(value.get('identity', 0), 'identity')
    contact_barrier = _flag(value.get('contact_barrier', 0), 'contact_barrier')
    anchor = value.get('anchor', 'none')
    if anchor not in ANCHORS:
        raise ValueError('Anchor profile must be internal, external or none')
    plane = value.get('plane', 'material')
    if not isinstance(plane, str) or not plane:
        raise ValueError('Spiritual profiles require a named plane')
    external = _flag(value.get('external_anchor', 0), 'external_anchor')
    internal = _flag(value.get('internal_anchor', 0), 'internal_anchor')
    affectable = _flag(value.get('affectable', 0), 'affectable')
    cultivation = _flag(value.get('cultivation_asset', 0), 'cultivation_asset')
    if anchor == 'internal':
        internal = 1
    elif anchor == 'external' or identity:
        external = 1
    if internal and external:
        raise ValueError('A spiritual profile cannot be both an internal and an external Anchor')
    if identity or external or cultivation:
        affectable = 1  # an explicit Anchor/Cultivation Asset is a contactable target
    if not (source_rule is not None or external or internal or cultivation):
        raise ValueError('Spiritual profiles require explicit source facts')
    result.update(identity=identity, contact_barrier=contact_barrier, anchor=anchor, plane=plane,
                  external_anchor=external, internal_anchor=internal, affectable=affectable,
                  cultivation_asset=cultivation)
    if 'saving_throws' in value:
        saves = value['saving_throws']
        if not isinstance(saves, dict) or any(
                key not in {'STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'} or type(mod) is not int
                for key, mod in saves.items()):
            raise ValueError('Object saving throws require explicit integer modifiers')
        result['saving_throws'] = dict(saves)
    if 'known_to' in value:
        known = value['known_to']
        if not isinstance(known, list) or any(not isinstance(actor, str) for actor in known):
            raise ValueError('Spiritual object knowledge must list actor ids')
        result['known_to'] = list(known)
    return result
