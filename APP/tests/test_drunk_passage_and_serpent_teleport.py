"""Heavenly Drunk passes through hostile spaces as difficult terrain and steps after an enemy misses; the Seventh Coil makes a Grappled creature's teleport cost a Cultivation Check."""
from types import SimpleNamespace

from combat import creature_passage, ext
from combat.ext import drunken_fist, rider_choices
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
    # An ally passes as difficult through passable() on every build, with or without Heavenly Drunk; the hook adds nothing.
    foe.team_id = me.team_id
    assert drunken_fist.hostile_spaces_are_difficult(engine, me, foe) is None
    assert creature_passage.permission(engine, me, foe) == "difficult"


def _miss(engine, attacker, me):
    """The after_miss hook as the engine calls it: `attacker` missed `me`."""
    ctx = SimpleNamespace(engine=engine, actor=attacker, source="test:miss", intent=None)
    return drunken_fist.heavenly_drunk_miss_step(ctx, me)


def _recorded_steps(monkeypatch):
    calls = []

    def fake_step(engine, mover, key, name, subject, feet, source, intent=None, *, trigger="", ignored_oa=None, **kwargs):
        calls.append({"key": key, "mover": mover.entity_id, "subject": subject.entity_id, "feet": feet,
                      "ignored_oa": list(ignored_oa or [])})
        return True

    monkeypatch.setattr(rider_choices, "step", fake_step)
    return calls


def test_heavenly_drunk_miss_step_is_up_to_ten_feet_and_once_per_round(monkeypatch):
    calls = _recorded_steps(monkeypatch)
    engine = fight(bundle([DRUNK]), foe=_typed_foe())
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Heavenly Drunk")
    _miss(engine, foe, me)
    assert len(calls) == 1
    assert calls[0]["mover"] == ME and calls[0]["subject"] == FOE and calls[0]["feet"] == 10
    assert FOE in calls[0]["ignored_oa"]  # the enemy that missed cannot Opportunity-Attack the step
    _miss(engine, foe, me)
    assert len(calls) == 1  # a second miss in the same round does not move the owner again
    engine.state.round_number += 1
    _miss(engine, foe, me)
    assert len(calls) == 2  # the next round allows one more step


def test_heavenly_drunk_miss_step_needs_the_state_and_an_enemy(monkeypatch):
    calls = _recorded_steps(monkeypatch)
    engine = fight(bundle([DRUNK]), foe=_typed_foe())
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    _miss(engine, foe, me)
    assert calls == []  # without the state a miss moves nothing
    use(engine, "Heavenly Drunk")
    foe.team_id = me.team_id
    _miss(engine, foe, me)
    assert calls == []  # an ally's miss does not qualify


def test_heavenly_drunk_step_offers_every_legal_destination(monkeypatch):
    from combat.ext import needle
    engine = fight(bundle([DRUNK]), foe=_typed_foe(), me_at=(10, 7), foe_at=(15, 7), width=30, height=20)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    use(engine, "Heavenly Drunk")
    captured = {}
    from combat.ext import rider_choices
    monkeypatch.setattr(rider_choices, "pick",
                        lambda _e, _o, _k, _n, options, **kw: captured.update(options=list(options)) or [])
    rider_choices.step(engine, me, "test", "Heavenly Drunk", foe, 10, "test:miss",
                       ignored_oa=[FOE])
    assert len(captured["options"]) > 16
    far = type(me.position)(x=me.position.x + 2, y=me.position.y, z=me.position.z)
    assert needle.cell_id(far) in captured["options"]


def test_heavenly_drunk_enrolls_manual_owner_for_off_turn_choice():
    engine = fight(bundle([DRUNK]), foe=_typed_foe())
    me = engine.state.actors[ME]
    use(engine, "Heavenly Drunk")
    engine.typed_control_modes = {ME: "MANUAL", FOE: "AI"}
    assert ME in drunken_fist.heavenly_drunk_choice_reactors(engine)
    me.conditions.clear()
    assert ME not in drunken_fist.heavenly_drunk_choice_reactors(engine)


def test_heavenly_drunk_two_legacy_attackers_can_trigger_a_saved_table_step(tmp_path):
    from combat.gate2_runtime_content import AN, LEE
    from tests.auto8f1_table_support import OWNER as TABLE_OWNER, candidate_id, fixture

    def certain_miss(bundles):
        for value in bundles:
            if value["actor_id"].endswith("auto8-owner"):
                value["actor_template"]["armor_class"] = 100

    f = fixture(
        tmp_path, [DRUNK], seed="drunk-two-legacy", cl=18,
        bundle_transform=certain_miss,
        places={TABLE_OWNER: {"x": 3, "y": 6},
                "actor:factory.auto8-foe": {"x": 8, "y": 8},
                "actor:factory.auto8-second": {"x": 15, "y": 8}},
        legacy_foes={AN: {"x": 4, "y": 6}, LEE: {"x": 4, "y": 7}},
    )
    menu = f["menu"]
    owner = TABLE_OWNER
    # Activate through the table, then let the two legacy enemies make real attacks.
    f["commit"](candidate_id(menu(), "Heavenly Drunk"))
    f["turn_of"](AN)
    def choose_far_step(prompt, choice):
        offered = {option["id"] for option in choice["options"]}
        assert "cell:1,6" in offered, f"the legal 10-foot destination was not offered: {offered}"
        return ["cell:1,6"]

    f["commit"](candidate_id(menu(), "Paired Bi Shou Assault"), chooser=choose_far_step)
    engine = f["stored_engine"]()
    assert (engine.state.actors[owner].position.x, engine.state.actors[owner].position.y) == (1, 6)
    assert engine.state.actors[owner].turn_flags.get("once_per_round:heavenly_drunk") == engine.state.round_number
    assert not any(e.event_type == "GM_RIDER" and "cannot yet automate together" in str(e.payload)
                   for e in engine.events)

    f["turn_of"](LEE)
    f["commit"](candidate_id(menu(), "Lightning Lash"))
    reloaded = f["stored_engine"]()
    assert (reloaded.state.actors[owner].position.x, reloaded.state.actors[owner].position.y) == (1, 6)
    assert reloaded.state.actors[owner].turn_flags.get("once_per_round:heavenly_drunk") == reloaded.state.round_number
