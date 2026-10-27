"""Shadow Exchange tests the triggering attack's cone, not just weapon range."""
from combat.gate2_runtime_models import ActionIntent, DiceSpec
from tests.test_mmx_auto_shadow1 import _ally_duel, _ally_provider, _slip_question, DIM_MAP, ALLY
from tests import test_auto_lane4 as L4


def test_cone_escape_and_inside_landing_both_remain_choices():
    for landing, escapes in (("cell:4,4", True), ("cell:5,5", False)):
        engine = _ally_duel(DIM_MAP)
        attacker = engine.state.actors[L4.ME]
        target = engine.state.actors[L4.SUBJ]
        target.armor_class = -50
        asked = []
        engine._gate4_reaction_provider = _ally_provider(asked, landing)
        intent = ActionIntent(intent_id="cone", decision_id="cone", candidate_id="cone",
                              state_version=engine.state.state_version, actor_id=L4.ME,
                              target_ids=(L4.SUBJ,))
        engine._active_intent = intent
        before = target.current_hp
        L4._script(engine, [15, 6])
        engine._resolve_attack_spec(attacker, target, {
            "attack_bonus": 100, "range_ft": 60 if escapes else 5,
            "damage": DiceSpec(count=1, sides=6), "damage_type": "PIERCING",
            "typed": {"area": {"shape": "cone", "size_ft": 30}, "_area_aim": (9, 6)},
        }, intent, source_definition_id="test:cone", attack_index=1)
        options = _slip_question(asked)["needle_options"]
        assert "cell:4,4" in options and "cell:5,5" in options
        assert (target.position.x, target.position.y) == tuple(map(int, landing[5:].split(",")))
        assert (target.current_hp == before) is escapes
        assert not engine.state.actors[ALLY].reaction_available
