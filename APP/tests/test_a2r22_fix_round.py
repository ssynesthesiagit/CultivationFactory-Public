"""A2R22FF1: actual table checks, isolated storage and cold reloads.

The shared A2R22 offline fixture disables embedding clients; verification also
blocks network transports in the detached runner and its replay children.
"""
from types import SimpleNamespace

import pytest

from combat import ext
from combat.ext import athletics, blacksmith_forge as forge, riders14_eye as eye
from combat.ext.scoped_checks import receipt_check_pairs
from tests.auto8f1_table_support import fixture, zero_martial_focus, OWNER, FOE
from tests.cw2_service_support import seal
from tests.test_a2r22_review import (
    add_action, use, held, finish, fake_menu_embeddings, COORDINATED, MERIDIAN,
)


def last_check(g):
    return next(e for e in reversed(g["stored_engine"]().events) if e.event_type == "CHECK_ROLLED")


@pytest.mark.parametrize("hold", ["grapple", "net"])
@pytest.mark.parametrize("success,dc", [(False, 99), (True, 1)])
def test_ordinary_escape_spends_meridian_even_on_failure_after_reload(tmp_path, hold, success, dc):
    def prepare(bundles):
        zero_martial_focus(bundles)
        for b in bundles:
            if b["actor_id"] == FOE:
                effects = ([{"type": "condition", "condition": "grappled", "until_escape": True}]
                           if hold == "grapple" else
                           [{"type": "condition", "condition": "restrained", "until_escape": True},
                            {"type": "trap_netted"}])
                add_action(b, "Apply hold", effects, hostile=True)
                b["action_catalog"][-1]["parameters"]["typed"]["numbers"]["save_dc"] = dc
            if b["actor_id"] == OWNER and hold == "net":
                add_action(b, "Escape the net", [{"type": "trap_escape", "bonus": 0}])
                b["action_catalog"][-1]["parameters"]["requires_condition"] = "condition:typed.netted"
            seal(b)
    g = fixture(tmp_path, [COORDINATED, MERIDIAN], seed=f"FF1-{hold}-{success}", bundle_transform=prepare)
    use(g, "Dash")
    g["turn_of"](FOE)
    use(g, "Apply hold", target=OWNER)
    g["to_owner"]()
    assert held(g["reload_owner"]())
    g["menu"]()
    assert held(g["reload_owner"]()), "preview must preserve the benefit"
    label = "Escape grapple" if hold == "grapple" else "Escape the net"
    use(g, label)
    receipt = last_check(g).payload
    assert receipt["mode_skills"] == ["Athletics", "Acrobatics"]
    assert receipt["success"] is success
    assert receipt["actor"]["mode"] == "ADVANTAGE"
    assert not held(g["reload_owner"]()), "the first actual escape must spend Meridian"
    g["commit"](g["menu"]()["end_turn"])
    if success:
        g["turn_of"](FOE)
        use(g, "Apply hold", target=OWNER)
    g["to_owner"]()
    use(g, label)
    assert last_check(g).payload["actor"]["mode"] == "NORMAL"
    finish(g)


@pytest.mark.parametrize("purpose", ["repair", "crafting", "modification", "disarm"])
def test_softening_preserves_unrelated_checks_and_spends_only_qualified_roll(tmp_path, purpose):
    context = {"purpose": purpose, "workpiece_id": OWNER}
    skill_route = purpose in ("modification", "disarm")
    check_target = OWNER if skill_route else FOE
    def prepare(bundles):
        b = bundles[0]
        for label, metadata in (("Unrelated check", {}),
                                ("Wrong workpiece", {"purpose": purpose, "workpiece_id": FOE}),
                                ("Unrelated purpose", {"purpose": "climb", "workpiece_id": OWNER}),
                                ("Repair workpiece", context)):
            check = {"ability": "STR", "skill": "Athletics",
                     **({"check_context": metadata} if metadata else {})}
            effects = ([{"type": "skill_check", **check}] if skill_route else
                       [{"type": "contest_against", "actor_check": {"kind": "check", **check},
                         "target_check": {"kind": "dc", "dc": 99}}])
            add_action(b, label, effects, hostile=True)
            if skill_route:
                b["action_catalog"][-1]["target_kind"] = "ANY_CREATURE"
            b["action_catalog"][-1]["parameters"]["typed"]["numbers"]["save_dc"] = 99
        for b in bundles:
            seal(b)
    g = fixture(tmp_path, ["BLACKSMITH_BASE_HAMMER_THE_MARK", forge.TEMPERING_SEQUENCE],
                seed="FF1-softening-" + purpose, bundle_transform=prepare)
    for index in range(3):
        use(g, "Hammer the Mark")
        if index < 2:
            g["commit"](g["menu"]()["end_turn"])
            g["to_owner"]()
    use(g, "Tempering Sequence: Softening Sequence")
    assert forge.held_condition(g["reload_owner"](), forge.SOFTENED)
    for label in ("Unrelated check", "Wrong workpiece", "Unrelated purpose"):
        g["commit"](g["menu"]()["end_turn"])
        g["to_owner"]()
        use(g, label, target=check_target)
        assert last_check(g).payload["actor"]["mode"] == "NORMAL"
        assert forge.held_condition(g["reload_owner"](), forge.SOFTENED)
    e = g["stored_engine"]()
    actor = e.state.actors[OWNER]
    # Queries and previews are pure, even when the workpiece/purpose qualifies.
    before = e.state.model_dump(mode="json")
    assert forge.softening_advantage_on_checks(SimpleNamespace(engine=e, check_context=context),
                                              actor, "STR", "Athletics") == "ADVANTAGE"
    assert e.state.model_dump(mode="json") == before
    g["commit"](g["menu"]()["end_turn"])
    g["to_owner"]()
    use(g, "Repair workpiece", target=check_target)
    receipt = last_check(g).payload
    assert receipt["check_context"] == context
    assert receipt["actor"]["mode"] == "ADVANTAGE"
    assert receipt["success"] is False
    assert not forge.held_condition(g["reload_owner"](), forge.SOFTENED)
    g["commit"](g["menu"]()["end_turn"])
    g["to_owner"]()
    use(g, "Repair workpiece", target=check_target)
    assert last_check(g).payload["actor"]["mode"] == "NORMAL"
    finish(g)


def test_eye_null_opponent_is_inert_and_does_not_emit_a_skipped_hook_error():
    from tests.test_auto_athletics import _engine, _me
    from combat.typed_executor import check_modes
    e = _engine([])
    actor = _me(e)
    foe = next(a for a in e.state.actors.values() if a.entity_id != actor.entity_id)
    e._apply_condition(actor, eye.THOUGHTS, "test:thoughts", actor.entity_id,
                       expires_on="UNTIL_REMOVED", data={"target_id": foe.entity_id})
    before = len(e.events)
    assert eye.qualified_eye_check(e, actor, "WIS", "Insight", None) is None
    assert "ADVANTAGE" not in check_modes(actor, "WIS", "Insight", engine=e)
    assert eye.qualified_eye_check(e, actor, "STR", "Athletics", foe) == "ADVANTAGE"
    assert not any("qualified_eye_check" in str(x.payload) for x in e.events[before:])


def test_actual_unopposed_difficult_climb_keeps_softening():
    from combat import roof_movement
    from tests.test_roof_movement import engine_at_wall
    e, actor = engine_at_wall(climb_check="slippery")
    e._apply_condition(actor, forge.SOFTENED, forge.TEMPERING_SEQUENCE, actor.entity_id,
                       expires_on="UNTIL_REMOVED", data={"label": "Softening Sequence"})
    assert roof_movement.needs_check(e, actor, actor.position, actor.position.model_copy(update={"z": 1}))
    roof_movement.climb_check(e, actor, actor.position, actor.position.model_copy(update={"z": 1}), None)
    assert e.rolls[-1].mode == "NORMAL"
    assert forge.held_condition(actor, forge.SOFTENED)


def test_unyielding_spends_next_check_on_real_combined_escape(tmp_path):
    from combat.ext import berserker
    def prepare(bundles):
        for b in bundles:
            if b["actor_id"] == OWNER:
                add_action(b, "Escape after damage", [
                    {"type": "damage", "applies_to": "self", "flat": 7, "damage_types": ["force"]},
                    {"type": "escape_grapple", "bonus": 0}])
            if b["actor_id"] == FOE:
                add_action(b, "Apply hold", [{"type": "condition", "condition": "grappled", "until_escape": True}], hostile=True)
                b["action_catalog"][-1]["parameters"]["typed"]["numbers"]["save_dc"] = 99
            seal(b)
    g = fixture(tmp_path, ["TAL_BERSERKER_BATTER", "TAL_BERSERKER_UNYIELDING_ADVANCE"],
                seed="FF1-Unyielding", bundle_transform=prepare)
    use(g, "Adrenaline: Unyielding Advance")
    g["turn_of"](FOE)
    use(g, "Apply hold", target=OWNER)
    g["to_owner"]()
    use(g, "Escape after damage")
    receipt = last_check(g).payload
    assert receipt["mode_skills"] == ["Athletics", "Acrobatics"]
    assert receipt["actor"]["mode"] == "ADVANTAGE"
    assert not g["reload_owner"]().turn_flags.get(berserker.UNYIELDING_CHECK)
    g["commit"](g["menu"]()["end_turn"])
    g["to_owner"]()
    use(g, "Escape grapple")
    assert last_check(g).payload["actor"]["mode"] == "NORMAL"
    finish(g)


@pytest.mark.parametrize("payload,defending,expected", [
    ({"mode_skills": ["Athletics", "Acrobatics"]}, False, (("STR", "Athletics"), ("DEX", "Acrobatics"))),
    ({"ability": "DEX", "skill": "Athletics", "mode_skills": ["Acrobatics"]}, False, (("DEX", "Athletics"),)),
    ({"ability": "STR", "skill": None, "mode_skills": ["Athletics"]}, False, ()),
    ({"target_check_kind": "save", "target_skill": "Athletics"}, True, ()),
    ({"roll_kind": "dc_check", "target_skill": "Athletics"}, True, ()),
])
def test_receipt_helper_preserves_actual_check_scope(payload, defending, expected):
    assert receipt_check_pairs(payload, defending=defending) == expected
