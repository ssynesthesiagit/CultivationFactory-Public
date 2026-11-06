"""Pure geometry for mounted, finite thresholds; no ability ownership or state writes."""
from fractions import Fraction


def thresholds(engine):
    return [obj for obj in engine.state.objects.values()
            if not obj.destroyed and obj.object_kind.lower() in {'door', 'gate', 'threshold', 'arch'}
            and obj.component.get('mount_axis') in {'h', 'v'}
            and type(obj.component.get('mount_line')) is int]


def side(obj, position):
    axis = obj.component['mount_axis']
    return (position.y if axis == 'h' else position.x) * 100 + 50 - obj.component['mount_line']


def crosses(obj, start, end):
    """Intersect the mounted one-cell aperture, rather than its infinite wall line."""
    if start.z != obj.position.z or end.z != obj.position.z:
        return False
    a, b = side(obj, start), side(obj, end)
    if a * b >= 0:
        return False
    horizontal = obj.component['mount_axis'] == 'h'
    first = start.x if horizontal else start.y
    last = end.x if horizontal else end.y
    hit = first * 100 + 50 + Fraction(-a, b - a) * (last - first) * 100
    lower = (obj.position.x if horizontal else obj.position.y) * 100
    return lower <= hit < lower + 100


def open_threshold(obj):
    return not obj.component.get('blocks') and not obj.component.get('destination_unknown')
