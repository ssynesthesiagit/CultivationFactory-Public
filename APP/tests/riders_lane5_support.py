"""Shared synthetic rider fixtures used by the rider and simultaneous-victory tests."""
from combat.factory_compiler import compile_character
from tests import test_auto_lane1 as L1
from tests.test_auto_lane1 import ME


def _bundle(mids, **kw):
    """A character owning the sphere's base abilities and every talent in ``mids``."""
    sheet = L1._sheet(mids[0], **kw)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(mids)
    return compile_character(sheet, actor_id=ME)



def _place(engine, prefix, near):
    """A cell-targeted action's candidate at ``near`` (any cell when it has no such square)."""
    # Round 24 labels include altitude/movement details. Use the candidate's
    # coordinates rather than parsing its player-facing label.
    choices = [c for c in engine.legal_candidates() if c.display_name.startswith(prefix)]
    return min(choices, key=lambda c: (0 if c.destination is None else
               abs(c.destination.x - near.x) + abs(c.destination.y - near.y), c.display_name)).display_name


