"""Heavenly Drunk passes through hostile spaces as difficult terrain; the Seventh Coil makes a Grappled creature's teleport cost a Cultivation Check."""
from combat import creature_passage, ext
from tests.test_riders_c7 import FOE, ME, _grapple, _typed_foe, bundle, fight, use

DRUNK = "tianxia.subpath.body.drunken_fist.feature.heavenly_drunk"
SERPENT = "tianxia.subpath.body.seven_coiled_serpent_spine.feature."
COILS = "condition:typed.serpent_coils"


def test_heavenly_drunk_lets_you_pass_through_a_hostile_space_as_difficult_terrain():
    engine = fight(bundle([DRUNK]), foe=_typed_foe())
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert creature_passage.permission(engine, me, foe) is None
    use(engine, "Heavenly Drunk")
    assert creature_passage.permission(engine, me, foe) == "difficult"


def _serpent(open_coils, grappled=True):
    engine = fight(bundle([SERPENT + "seventh_coil_heaven_swallowing_serpent"]), foe=_typed_foe())
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    held = next(c for c in me.conditions.values() if c.condition_id == COILS)  # the fight opened some Coils already
    held.data["open"] = open_coils
    if grappled:
        assert _grapple(engine, FOE)
        foe_held = [c for c in foe.conditions.values() if c.condition_id.endswith(".grappled")]
        assert foe_held and foe_held[0].source_actor_id == ME
    return engine, foe


def _teleport_replies(engine, foe):
    return ext.run("teleport_check", engine, foe, foe.position, foe.position)


def test_a_creature_grappled_by_an_open_seventh_coil_must_pass_a_check_to_teleport():
    engine, foe = _serpent(7)
    assert False in _teleport_replies(engine, foe)  # DC 50: the check fails, so the teleport fails
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == FOE]
    assert checks and checks[-1].payload["dc"] == 50 and checks[-1].payload["success"] is False


def test_without_the_seventh_coil_open_or_a_grapple_the_teleport_is_free():
    engine, foe = _serpent(6)
    assert False not in _teleport_replies(engine, foe)
    engine, foe = _serpent(7, grappled=False)
    assert False not in _teleport_replies(engine, foe)


def test_heavenly_drunk_does_not_make_neutral_or_allied_spaces_difficult():
    # "Hostile creature spaces" are enemies by relation(), not by a raw team-id mismatch.
    engine = fight(bundle([DRUNK]), foe=_typed_foe())
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Heavenly Drunk")
    foe.team_id = "team:neutral"
    assert creature_passage.permission(engine, me, foe) is None
    foe.team_id = me.team_id
    assert creature_passage.permission(engine, me, foe) is None
