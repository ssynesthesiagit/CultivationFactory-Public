"""Free fixture actions must remain available through the real table menu."""
from tests.r1i_service_support import OWNER, FOE, candidate, fixture
from tests.test_a2_ink import CORRECTION, setup


def test_ink_free_setup_actions_are_offered(tmp_path):
    _, table, mid, _, _ = fixture(
        tmp_path, [CORRECTION], bundle_transform=setup,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6},
                   'actor:factory.r1i-second': {'x': 5, 'y': 6}})
    assert candidate(table, mid, 'Press Mark', FOE)
    assert candidate(table, mid, 'Small hit', FOE)
