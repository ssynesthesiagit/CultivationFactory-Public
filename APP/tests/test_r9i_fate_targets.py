"""A single-target Auspice stays on the chosen willing creature."""
import pytest

from combat.ext import fate_riders as F
from tests.test_riders_lane9 import _fate_fight, _act, ME, ALLY, THEM


@pytest.mark.parametrize("name,condition", [("Turning Wheel Auspice", F.WHEEL),
                                             ("Guiding Star Auspice", F.AUSPICE),
                                             ("Moving Star Auspice", F.AUSPICE)])
@pytest.mark.parametrize("target", [ME, ALLY])
def test_auspice_exact_recipient_with_a_nearby_ally(name, condition, target):
    engine = _fate_fight([name.upper().replace(" ", "_")])
    _act(engine, name, target)
    for who in (ME, ALLY, THEM):
        assert bool(F._held(engine.state.actors[who], condition)) == (who == target)
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    clone = CombatService._clone_engine(ROOT, engine)
    for who in (ME, ALLY, THEM):
        assert bool(F._held(clone.state.actors[who], condition)) == (who == target)


@pytest.mark.parametrize("auto_turn", [False, True])
def test_self_auspice_table_commit_reload_keeps_chosen_recipient(tmp_path, auto_turn):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_r9i_fate_persistence import fixture, PLAYER, ALLY as A, FOE
    from tests.test_r9i_choices import action, resolve, finish_turn
    from tests.test_r9i_karma_persistence import act

    combat, table, mid = fixture(tmp_path, F.WHEEL_ID)
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        finish_turn(table, mid)
    cid = action(table, mid, "Turning Wheel Auspice", PLAYER)
    if auto_turn:
        real = combat.controller

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode="LOCAL_AUTO")
    resolve(lambda answers: table.auto_step(mid, 0, answers) if auto_turn else act(table, mid, cid, answers), {})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    for who in (PLAYER, A, FOE):
        assert bool(F._held(loaded.engine.state.actors[who], F.WHEEL)) == (who == PLAYER)
    assert loaded.mechanical.replay()["status"] == "PASS"
