"""Court's printed grapple-only size step is scoped to acting, not resisting."""
from types import SimpleNamespace

from combat.ext import wrestling
from combat.ext.effective_size import rank


class _Engine:
    def __init__(self, actor):
        self.actor_footprints = {
            actor.entity_id: SimpleNamespace(width_cells=1, height_cells=1)
        }

    def _footprint(self, actor):
        return SimpleNamespace(width_cells=1)


def _actor(court):
    return SimpleNamespace(
        entity_id="court-user",
        size_category="Medium",
        transformed_size_category=None,
        conditions={
            "court": SimpleNamespace(condition_id=wrestling.COURT)
        } if court else {},
    )


def test_court_size_step_applies_only_while_acting_on_grapple():
    actor = _actor(True)
    engine = _Engine(actor)
    assert rank(engine, actor, "act", {"grapple"}) == 3
    assert rank(engine, actor, "resist", {"grapple"}) == 2
    assert rank(engine, actor, "act", {"shove"}) == 2

    actor.conditions.clear()
    assert rank(engine, actor, "act", {"grapple"}) == 2
    assert wrestling.court_size_steps(engine, actor, "act", {"grapple"}) is None
