"""Indexed Body schools get the martial default in shared area geometry."""
from types import SimpleNamespace

from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.typed_executor import _area_targets
from combat.typed_numbers import authority_mechanics


BREATH = 'tianxia.subpath.body.ryujin.feature.dragon_s_breath'


def test_dragon_breath_authority_geometry_excludes_adjacent_ally():
    # Work on the authority record, before Ryūjin's explicit compiler hook.
    breath = authority_mechanics()[BREATH]

    def creature(entity_id, team_id, x):
        return SimpleNamespace(entity_id=entity_id, team_id=team_id, active=True,
                               position=Position(x=x, y=4))

    user, ally, foe = creature('user', 'a', 3), creature('ally', 'a', 4), creature('foe', 'b', 5)
    grid = SquareGrid({'width_squares': 8, 'height_squares': 8, 'square_size_ft': 5,
                       'starting_positions': {}, 'terrain_regions': []})
    engine = SimpleNamespace(grid=grid,
                             state=SimpleNamespace(actors={a.entity_id: a for a in (user, ally, foe)}),
                             _actor_volume=lambda actor, at=None: ((actor.position.x, actor.position.y, 0),))
    area = breath['area']
    assert _area_targets(engine, user, foe.position, area) == [ally, foe]
    typed = {'source': BREATH, 'effects': breath['effects']}
    assert _area_targets(engine, user, foe.position, area, typed=typed) == [foe]
