"""Shadow Exchange tests the triggering attack's cone, not just weapon range."""
from combat.gate2_runtime_models import ActionIntent, DiceSpec, ReactionDecision
from tests.test_mmx_auto_shadow1 import (
    _ally_duel, _ally_provider, _slip_question, _slip_duel, _cp,
    DIM_MAP, ALLY, EXCHANGE, REVERSAL,
)
from tests import test_auto_lane4 as L4


def _ranged_hit(engine):
    attacker = engine.state.actors[L4.ME]
    target = engine.state.actors[L4.SUBJ]
    target.armor_class = -50
    intent = ActionIntent(intent_id="bow", decision_id="bow", candidate_id="bow",
                          state_version=engine.state.state_version, actor_id=L4.ME,
                          target_ids=(L4.SUBJ,))
    engine._active_intent = intent
    L4._script(engine, [15, 6])
    engine._resolve_attack_spec(attacker, target, {
        "attack_bonus": 100, "range_ft": 600,
        "damage": DiceSpec(count=1, sides=6), "damage_type": "PIERCING",
    }, intent, source_definition_id="test:bow", attack_index=1)


def test_automatic_reactors_decline_when_no_landing_escapes_and_manual_has_no_bad_default():
    for talent in (EXCHANGE, REVERSAL, "ally"):
        if talent == "ally":
            engine = _ally_duel(DIM_MAP)
            reactor = engine.state.actors[ALLY]
        else:
            engine, reactor = _slip_duel(talent)
            engine.battlefield_document = DIM_MAP
        engine.typed_control_modes = {}
        target = engine.state.actors[L4.SUBJ]
        start, hp, resources = target.position, target.current_hp, _cp(reactor)
        _ranged_hit(engine)
        assert target.position == start
        assert target.current_hp < hp
        assert reactor.reaction_available
        assert _cp(reactor) == resources

    engine = _ally_duel(DIM_MAP)
    asked = []
    engine._gate4_reaction_provider = _ally_provider(asked, None)
    _ranged_hit(engine)
    question = _slip_question(asked)
    assert question["needle_options"]
    assert not question.get("preferred")

    # An unanswered manual choice must not fall back to a futile square either.
    engine = _ally_duel(DIM_MAP)
    reactor = engine.state.actors[ALLY]
    target = engine.state.actors[L4.SUBJ]
    start, resources = target.position, _cp(reactor)
    _ranged_hit(engine)
    assert target.position == start
    assert reactor.reaction_available and _cp(reactor) == resources


def test_declining_self_shadow_landing_costs_no_reaction_or_pool():
    for talent in (EXCHANGE, REVERSAL):
        engine, reactor = _slip_duel(talent)
        engine.battlefield_document = DIM_MAP
        asked = []

        def provider(request):
            source = str(request["reaction_source_id"])
            asked.append(source)
            use = source.endswith("shadow_slip")
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"],
                                    selection="USE" if use else "DECLINE",
                                    option_ids=("use",) if use else ()), None

        engine._gate4_reaction_provider = provider
        start, hp, resources = reactor.position, reactor.current_hp, _cp(reactor)
        _ranged_hit(engine)
        assert any(source.endswith("teleport_destination") for source in asked)
        assert reactor.position == start and reactor.current_hp < hp
        assert reactor.reaction_available and _cp(reactor) == resources
        assert not reactor.turn_flags.get(f"shadow_round_reversal:{engine.state.round_number}")


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
