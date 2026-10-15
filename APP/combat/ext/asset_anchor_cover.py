"""One physical cover consumer for source-created and GM-authored profiles."""
from . import hook
from ..asset_anchor_geometry import partial_cover


@hook('effect_cover')
def declared_partial_object_cover(engine,source,target,ray):
    if ray.get('purpose') not in ('attack','effect') or not ray.get('origin_cells'):return
    value=partial_cover(engine,ray['origin_cells'],target)
    return value or None
