"""Bell-only turn driver; shared Worker 2 fixtures remain manual and strict."""
from tests import worker2_support as worker


def fixture(tmp_path, talents, **kwargs):
    # Start manually so fixture setup cannot silently ring an Alarm on an AI
    # turn before the test begins. Install requested seats through the service.
    modes = kwargs.pop('modes', None)
    combat, table, mid = worker.fixture(tmp_path, talents, **kwargs)
    for aid, mode in (modes or {}).items():
        combat.set_controller_mode(mid, actor_id=aid, controller_mode=mode)
    return combat, table, mid


def turn(table, mid, actor):
    """Drive intervening native AI turns only for Bell's mixed-seat tests."""
    for _ in range(12):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == actor:
            return
        worker.settle(table, mid, menu.get('end_turn'), auto='end_turn' not in menu)
    raise AssertionError('No turn')
