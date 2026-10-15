"""Void/Null options through table commit, history and fresh disk reload."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.test_lock2_persistence import act

PLAYER, FOE = "actor:factory.p4-player", "actor:factory.p4-foe"
HIDDEN = "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike"


def cast(tmp_path, monkeypatch, pressure, null, *, failed=True, hidden=False, cl=10, critical=False, payment="Stamina", ruin=False, cancelled=False, extra=()):
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        script(engine, [20 if critical else 19, *([1] * 40)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    if hidden:
        # Isolate the printed unseen qualification; all effects run via shipped hooks.
        monkeypatch.setattr("combat.target_knowledge.can_see", lambda engine, viewer, target: target.entity_id != PLAYER)
    doc = sheet(["TAL_VOID_VOID_NEEDLE", "TAL_VOID_NULLIFYING_STRIKE", *extra] + ([HIDDEN] if hidden else [])
                + (["TAL_UNMAKING_SECOND_RUIN_FORM_BLACK_PALM_VESSEL", "tianxia.path.body_refining.feature.iron_fist",
                    "TAL_IRON_FIST_BREAKING_KNUCKLE"] if ruin else []),
                cl=cl, dc=100 if failed else -100)
    doc["ability_scores_and_statistics"]["primary_resource"]["definitions"] = [{"name": "Stamina", "max": 30}]
    foe = sheet(["tianxia.talent.equipment.helmet_discipline"] if cancelled else [], cl=cl)
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
    bundles = [compile_character(doc, actor_id=PLAYER), compile_character(foe, actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [PLAYER, FOE], {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 4 if ruin else 6, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="P4",
        display_name="P4 regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    if ruin:
        form = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                    if a.owner_id == PLAYER and a.display_name.startswith("Second Ruin Form"))
        assert act(table, mid, form.source_definition_id)["status"] == "COMMITTED"
    name = ("Iron Fist attack" if ruin else f"Void Needle: {pressure}") + f" + Nullifying Strike: {null}"
    if payment == "Stamina":
        name += " (2 Stamina)"
    state = table.state(mid)
    session = combat._load_session(mid)
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
    before = dict(session.engine.state.actors[PLAYER].resources)
    expected_pool = "resource:core.stamina" if payment == "Stamina" else "resource:core.qi"
    assert session.engine.action_catalog[candidate.source_definition_id].costs == ((expected_pool, 2),)
    from tests.iron_fist_support import answering_iron_fist
    strike = answering_iron_fist(lambda answers: table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                                                           state["menu"]["state_version"], state["last_sequence"], answers))
    result = strike([])
    answers = []
    seen_choices = set()
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        source = prompt["context"]["reaction_source_id"]
        assert source not in seen_choices, "the same choice must not repeat"
        seen_choices.add(source)
        # Printed Hidden Strike: "After applying damage, choose one". Retain
        # the original Sever Awareness outcome; an Exploit may be asked first.
        if cancelled and source == 'choice:needle.helmet_discipline':
            # The cancellation fixture explicitly confirms its qualifying
            # head protection; owning the talent alone cannot imply equipment.
            picked = 'protected'
        elif hidden and source == "choice:needle.hidden_strike_rider":
            picked = "sever"
        else:
            assert extra and source == "choice:needle.exploit", prompt
            picked = "TAL_FENCING_CHEST_STRIKE"
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [picked]})
        result = strike(answers)
    assert result["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    boundary = fresh.history(mid)["boundaries"][-1]
    loaded = fresh._load_session(mid)
    conditions = {c.condition_id for c in loaded.engine.state.actors[FOE].conditions.values()}
    assert loaded.engine.state.actors[PLAYER].resources == {
        pool: value - (2 if pool == expected_pool else 0) for pool, value in before.items()
    }
    spent = [e["payload"] for e in boundary["events"] if e["event_type"] == "RESOURCE_SPENT"]
    assert [(e["resource_id"], e["amount"]) for e in spent] == [(expected_pool, 2)]
    for condition in loaded.engine.state.actors[FOE].conditions.values():
        if condition.condition_id.startswith("condition:typed.") and not condition.condition_id.startswith("condition:typed.stance."):
            expected = ("END_OF_MARKER_NEXT_TURN" if condition.condition_id.startswith("condition:typed.mark.") else
                        f"START_OF_TURN_AT:{FOE}:2" if not hidden and condition.condition_id.endswith(".reaction_denied") else "START_OF_SOURCE_NEXT_TURN")
            assert condition.expires_on == expected
    slows = [m for m in loaded.engine.state.actors[FOE].modifiers.values() if m.target_field == "speed_ft"]
    assert len(slows) == int(failed and null == "Speed -10")
    if slows:
        assert slows[0].value == -10
        assert slows[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    return boundary, conditions


@pytest.mark.parametrize("pressure", ["Empty Vitality", "Cost Lock", "Unsettle Invisibility"])
@pytest.mark.parametrize("null", ["Hollowed", "No Reactions", "Speed -10"])
@pytest.mark.parametrize("failed", [True, False])
@pytest.mark.parametrize("payment", ["CP", "Stamina"])
def test_option_isolation_save_order_and_reload(tmp_path, monkeypatch, pressure, null, failed, payment):
    boundary, conditions = cast(tmp_path, monkeypatch, pressure, null, failed=failed, payment=payment)
    events = boundary["events"]
    assert [e["event_type"] for e in events if e["event_type"] in
            {"ATTACK_ROLLED", "DAMAGE_ROLLED", "DAMAGE_COMMITTED", "SAVE_ROLLED"}] == [
                "ATTACK_ROLLED", "DAMAGE_ROLLED", "DAMAGE_COMMITTED", "DAMAGE_ROLLED", "DAMAGE_COMMITTED", "SAVE_ROLLED"]
    # Owner 2026-09-30: Void Needle's main hit adds the Path key modifier (+2 here); Nullifying Strike does not.
    assert [e["payload"]["expression"] for e in events if e["event_type"] == "DAMAGE_ROLLED"] == ["2d8+2", "2d6+0"]
    save_index = next(i for i, e in enumerate(events) if e["event_type"] == "SAVE_ROLLED")
    applied = [(i, e["payload"]["condition_id"]) for i, e in enumerate(events) if e["event_type"] == "CONDITION_APPLIED"]
    for condition, expected in [("hollowed", failed and null == "Hollowed"),
                                ("reaction_denied", failed and null == "No Reactions")]:
        assert (f"condition:typed.{condition}" in conditions) == expected
        assert all(i > save_index for i, cid in applied if cid == f"condition:typed.{condition}")
    assert sum(cid == "condition:typed.no_temp_hp" for _, cid in applied) == (
        int(pressure == "Empty Vitality") + int(not failed or null == "Hollowed"))
    assert ("condition:typed.no_invisible" in conditions) == (pressure == "Unsettle Invisibility" or failed and null == "Hollowed")
    assert all(i < save_index for i, cid in applied[:1] if pressure == "Empty Vitality" and cid == "condition:typed.no_temp_hp")


@pytest.mark.parametrize("cl,critical,expressions", [(10, True, ["4d8+2", "4d6+0", "4d6+0"]),
                                                     (17, False, ["4d8+2", "3d6+0", "4d6+0"])])
def test_hidden_strike_explains_playtest_sequence(tmp_path, monkeypatch, cl, critical, expressions):
    boundary, conditions = cast(tmp_path, monkeypatch, "Empty Vitality", "Hollowed", hidden=True, cl=cl, critical=critical)
    events = boundary["events"]
    assert [e["payload"]["expression"] for e in events if e["event_type"] == "DAMAGE_ROLLED"] == expressions
    relevant = [(e["event_type"], e["payload"].get("condition_id")) for e in events
                if e["event_type"] in {"PASSIVE_TRIGGERED", "CONDITION_APPLIED", "SAVE_ROLLED"}]
    assert relevant == [("PASSIVE_TRIGGERED", None), ("CONDITION_APPLIED", "condition:typed.reaction_denied"),
                        ("CONDITION_APPLIED", "condition:typed.no_temp_hp"), ("SAVE_ROLLED", None),
                        ("CONDITION_APPLIED", "condition:typed.hollowed"),
                        ("CONDITION_APPLIED", "condition:typed.no_temp_hp"),
                        ("CONDITION_APPLIED", "condition:typed.no_invisible")]
    trigger = next(row for row in boundary["feed"] if row["event_type"] == "PASSIVE_TRIGGERED")
    assert "triggered Hidden Strike against" in trigger["summary"]
    assert trigger["detailed_breakdown_recorded"] is True
    assert "condition:typed.hollowed" in conditions


@pytest.mark.parametrize("critical", [False, True])
def test_critical_hit_bonus_dice_and_flat_damage_survive_table_reload(tmp_path, monkeypatch, critical):
    boundary, _ = cast(tmp_path, monkeypatch, "Empty Vitality", "Hollowed", hidden=True,
                       critical=critical, ruin=True)
    rolls = [e["payload"] for e in boundary["events"] if e["event_type"] == "DAMAGE_ROLLED"]
    expected = ["2d10+2", "4d6+0", "4d10+0", "4d6+0"] if critical else ["1d10+2", "2d6+0", "2d10+0", "2d6+0"]
    assert [r["expression"] for r in rolls] == expected
    assert [bool(r.get("critical")) for r in rolls] == [critical] * 4
    # Both flat packets (Centerline Impact and Breaking Knuckle) remain +PB.
    flat, rolled = [], False
    for event in boundary["events"]:
        if event["event_type"] == "DAMAGE_ROLLED":
            rolled = True
        elif event["event_type"] == "DAMAGE_COMMITTED":
            if not rolled:
                flat.append(event["payload"]["hp_damage"])
            rolled = False
    assert flat == [4, 4]


def test_cancelled_critical_does_not_double_bonus_dice_after_table_reload(tmp_path, monkeypatch):
    boundary, _ = cast(tmp_path, monkeypatch, "Empty Vitality", "Hollowed", hidden=True, critical=True, cancelled=True)
    events = boundary["events"]
    assert any(e["payload"].get("critical_turned_normal") for e in events)
    # Native cancellation finalizes the critical before any damage: neither the
    # base strike nor its bonus dice are doubled.
    assert [e["payload"]["expression"] for e in events if e["event_type"] == "DAMAGE_ROLLED"] == ["2d8+2", "2d6+0", "2d6+0"]
