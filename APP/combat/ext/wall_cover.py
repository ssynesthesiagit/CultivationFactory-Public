"""Attack-family wall cover; uses the shared pure attack provenance descriptor.

The rider's wall derivation supplies restricted cells. Old walls without that
opt-in field retain their existing terrain cover; absent cells are inert.
"""
from . import hook


@hook('directional_cover')
def restricted_wall_cover(engine, attacker, target, ray):
    attack = ray.get('attack')
    if not ray.get('ranged') or not attack or attack['delivery'] != 'weapon':
        return None
    cells = engine.__dict__.get('_cover_ranged_weapon', set())
    if not cells:
        return None
    crossed = {tuple(row['cell']) for row in ray.get('crossed_edges') or ()}
    return 5 if cells & crossed else None
