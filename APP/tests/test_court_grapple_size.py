"""Court of the Closed Distance: while its state is on, the Court creature counts one size larger for grapples it initiates.

Table-level: real compiled characters, committed actions and reloads. The foe grows through its own committed
``size_change`` action on its own turn; the Court state is activated through the table's Court action. A refused
grapple is refused by the size gate before any save is rolled (same contract as AUTO51 grapple resistance).
"""
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, FOE, fixture, candidate, reload, settle, turn

COURT = "TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE"
STATE = "condition:typed.state.court_of_the_closed_distance"
GRAPPLED = "condition:typed.grappled"


def _foe_size(size):
    def prepare(bundles):
        for b in bundles:
            if b["actor_id"] == FOE:
                b["actor_template"]["saving_throws"].update(STR=-100, DEX=-100)
                add_action(b, "Grow opponent", [{"type": "size_change", "size": size, "duration": "until_removed"}], target="SELF")
                seal(b)
    return prepare


def _start(tmp_path, talents, size, *, activate=True):
    combat, table, mid = fixture(tmp_path, talents, bundle_transform=_foe_size(size), foe_position={"x": 4, "y": 5})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Grow opponent").candidate_id)
    turn(table, mid, OWNER)
    if activate and talents:
        settle(table, mid, candidate(combat, mid, "Court of the Closed Distance").candidate_id)
    return combat, table, mid


def test_medium_court_user_grapples_a_huge_creature_it_could_not_without_the_talent(tmp_path):
    combat, table, mid = _start(tmp_path, [COURT], "Huge")
    start = len(reload(tmp_path, mid).events)
    settle(table, mid, candidate(combat, mid, "Grapple", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == STATE for c in engine.state.actors[OWNER].conditions.values())
    assert any(e.event_type == "SAVE_ROLLED" for e in engine.events[start:])
    assert any(c.condition_id == GRAPPLED for c in engine.state.actors[FOE].conditions.values())


def test_without_the_talent_a_huge_creature_is_refused_before_any_save(tmp_path):
    combat, table, mid = _start(tmp_path, [], "Huge")
    start = len(reload(tmp_path, mid).events)
    settle(table, mid, candidate(combat, mid, "Grapple", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not any(e.event_type == "SAVE_ROLLED" for e in engine.events[start:])
    assert not any(c.condition_id == GRAPPLED for c in engine.state.actors[FOE].conditions.values())


def test_court_state_off_refuses_the_huge_creature_before_any_save(tmp_path):
    combat, table, mid = _start(tmp_path, [COURT], "Huge", activate=False)
    start = len(reload(tmp_path, mid).events)
    settle(table, mid, candidate(combat, mid, "Grapple", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == STATE for c in engine.state.actors[OWNER].conditions.values())
    assert not any(e.event_type == "SAVE_ROLLED" for e in engine.events[start:])
    assert not any(c.condition_id == GRAPPLED for c in engine.state.actors[FOE].conditions.values())


def test_gargantuan_creature_stays_too_large_with_the_court_step(tmp_path):
    combat, table, mid = _start(tmp_path, [COURT], "Gargantuan")
    start = len(reload(tmp_path, mid).events)
    settle(table, mid, candidate(combat, mid, "Grapple", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == STATE for c in engine.state.actors[OWNER].conditions.values())
    assert not any(e.event_type == "SAVE_ROLLED" for e in engine.events[start:])
    assert not any(c.condition_id == GRAPPLED for c in engine.state.actors[FOE].conditions.values())
