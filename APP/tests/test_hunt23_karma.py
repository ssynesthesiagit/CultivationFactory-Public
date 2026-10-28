"""Record the Deed names its cause, action and actual payment at the table."""
import pytest
from tests.hunt23_support import LEFT, RIGHT, act, fight, reload, turn


@pytest.mark.parametrize("ai", [False, True])
def test_record_prompt_and_payment_survive_reload(tmp_path, ai):
    combat, table, mid = fight(tmp_path, ["TAL_KARMA_RECORD_THE_DEED"], effects=[
        {"type": "damage", "damage_type": "PSYCHIC", "flat": 2, "applies_to": "target"}], target="HOSTILE_ENTITY")
    turn(table, mid, RIGHT)
    if ai:
        # Use the accepted test action through the service's normal controller adapter.
        from combat.gate4_adapters import ManualControllerAdapter
        cid = next(g["options"][0]["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Test setup")
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    send = lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers) if ai else act(table, mid, "Test setup", answers)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Record the Deed"
    assert prompt["cost"] == "Reaction; no resource cost"
    assert "meaningful damage to River Keeper" in prompt["trigger"]
    assert "Test setup" in prompt["trigger"] and "Visiting Fighter" in prompt["trigger"]
    assert 'Debt Imprint on Visiting Fighter' in prompt['summary']
    assert 'records this deed' in prompt['summary']
    assert send([{**prompt["context"], "selection": "USE"}])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert not engine.state.actors[LEFT].reaction_available
    from combat.ext.karma_imprints import held
    assert held(engine.state.actors[RIGHT], LEFT, "debt")
