"""Real AI-owned Flaw reaction protects only the affected ally, with both sides visible."""
from tests.test_auto2_glass import BASES, FLAW, RESIST_EFFECT, owner_setup, foe_turn, conditions, prepare
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload
from tests.cw2_service_support import seal


def test_ai_flaw_success_protects_the_ally_and_never_the_nearby_enemy(tmp_path):
    def setup(bundles):
        prepare(bundles)
        bundles[2]['actor_template']['saving_throws']['WIS'] = 100
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, BASES + [FLAW], cl=15, bundle_transform=setup,
                                  foe_position={'x': 4, 'y': 5}, ask=False)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    settle(table, mid, candidate(combat, mid, 'Foe Technique', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert conditions(engine, ALLY, RESIST_EFFECT)
    assert not conditions(engine, FOE, RESIST_EFFECT)
    assert not conditions(engine, OWNER, RESIST_EFFECT)


def test_flaw_resistance_lasts_through_the_triggering_turn_and_ends_when_it_ends(tmp_path):
    """GLASSR8/R9: Flaw's "Resistance ... until the end of the current turn" is present for the rest of the foe's
    turn and gone once that turn is committed, not held until the Glass owner's own turn ends."""
    def setup(bundles):
        prepare(bundles)
        bundles[2]['actor_template']['saving_throws']['WIS'] = 100
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, BASES + [FLAW], cl=15, bundle_transform=setup,
                                  foe_position={'x': 4, 'y': 5}, ask=False)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    settle(table, mid, candidate(combat, mid, 'Foe Technique', target=ALLY).candidate_id)
    assert conditions(reload(tmp_path, mid), ALLY, RESIST_EFFECT), "during the triggering turn"

    assert table.state(mid)["menu"]["actor_id"] == FOE
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id != FOE
    assert not conditions(engine, ALLY, RESIST_EFFECT), "gone once the foe's turn has ended"
