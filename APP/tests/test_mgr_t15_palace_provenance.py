"""Review regressions through table transactions and shipped source producers."""
import pytest

from combat.ext.taiyin_palace import USED, protects
from tests.h1_support import sheet
from tests.test_mgr_t15_true_moon_yin_palace import game, activate, save_mode
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, turn, reload


def test_allied_and_environmental_cold_are_not_hostility_gated(tmp_path):
    combat, table, mid = game(tmp_path)
    activate(combat, table, mid)
    assert save_mode(combat, table, mid, OWNER, 'cold', source=ALLY) == 'ADVANTAGE'
    engine = reload(tmp_path, mid)
    assert protects(engine, engine.state.actors[OWNER], None, {'damage:cold'})
    assert not protects(engine, engine.state.actors[OWNER], None, {'hostile_stilling_pressure'})


def test_shipped_fearful_darkness_save_receives_palace_advantage(tmp_path):
    combat, table, mid = game(
        tmp_path, foe_sheet=sheet(['DARK_BASE_DARKNESS', 'TAL_DARK_FEARFUL_DARKNESS']))
    activate(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Shape Darkness: Fearful Darkness').candidate_id,
           choices={})
    # Shape selection costs the foe's action. Cast on its next turn.
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(3, 6)).candidate_id,
           choices={})
    before = len(combat._load_session(mid).engine.events)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events[before:]
             if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves, 'Starting in the shipped Fearful Darkness must produce a save'
    assert saves[-1].payload['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('cold', [False, True])
def test_brittle_opening_cannot_reclassify_the_primary_hit(tmp_path, cold):
    combat, table, mid = game(tmp_path)
    if cold:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, 'Piercing ward', target=FOE).candidate_id)
        turn(table, mid, OWNER)
    activate(combat, table, mid)
    before = len(combat._load_session(mid).engine.events)
    settle(table, mid, candidate(combat, mid, 'Shard Needle', target=FOE).candidate_id,
           choices={'choice:fracture_response': 'brittle', 'choice:brittle_type': 'COLD'})
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events[before:]
               if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert packets[0].payload['damage_type'].lower() == ('cold' if cold else 'piercing')
    assert any(e.payload['damage_type'].lower() == 'cold' for e in packets[1:])
    # Two primary strikes and one real Fracture response; only an actually Cold
    # technique receives Palace's in-hit bonus and consumes the once-turn allowance.
    assert len(packets) == 3
    assert bool(engine.state.actors[OWNER].turn_flags.get(USED)) is cold
