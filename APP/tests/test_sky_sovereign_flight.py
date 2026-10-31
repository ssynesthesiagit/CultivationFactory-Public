"""Sky-Sovereign Incarnation: its printed Fly Speed 60 and Hover, held through a real table cast."""
from combat.flight import profile
from tests.worker2_support import OWNER, candidate, fixture, reload, settle

SKY_SOVEREIGN = 'TAL_AIR_SKY_SOVEREIGN_INCARNATION'


def test_sky_sovereign_incarnation_grants_fly_speed_and_hover_not_walking_speed(tmp_path):
    combat, table, mid = fixture(tmp_path, [SKY_SOVEREIGN], cl=17, owner_speed=30)
    settle(table, mid, candidate(combat, mid, 'Sky-Sovereign Incarnation').candidate_id)
    e = reload(tmp_path, mid)
    actor = e.state.actors[OWNER]
    assert profile(e, actor).speed_ft == 60 and profile(e, actor).hover is True
    assert e._effective_speed(actor) == 30
