"""LOCK26 review finding 1: held Concentration endings restore only the ended copy's suppressed benefit.

Two copies of one technique on different creatures (Nullification Seal shape, via the public benefit_suppression
helper): when the older, held copy ends (REPLACED at a sealed legacy two-copy cap, as in the SOL204 regression), its
target's benefit returns; the newer copy's target keeps its benefit suppressed. CombatService, persisted
execute_intent, cold reload, replay. Deadline delivery and real process restart
are also covered by test_deadline_endings.py (P20261010-07).
"""
from combat import concentration, ext
from combat.ext import benefit_suppression
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition
from tests.test_auto_docket import ME
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from tests.test_auto_docket import ROOT, _sheet
from tests.test_lock26_movement_concentration_seams import _execute
from tests.test_lock_choices import install

SEAL = "action:test.lock26.seal"
OTHER = "action:test.lock26.other"


def _seal(ctx, row):
    target = ctx.target
    mid = ctx.engine._add_modifier(target, "test:lock26.ward", "armor_class", "ADD", 2, "ALWAYS",
                                   expires_on="END_OF_SOURCE_TURN_AT:99")
    benefit_suppression.suppress(ctx.engine, ctx.actor, target, "modifier:" + mid, "concentration", ctx.source)


def _actions(info):
    return [ActionDefinition(source_definition_id=SEAL, display_name="Lock26 Seal", owner_id=info["actor_id"],
        economy="NONE", resolution_kind="TYPED", target_kind="HOSTILE_ENTITY_OR_SELF", range_ft=120,
        parameters={"typed": {"source": "test:lock26.seal", "numbers": info["numbers"],
            "duration": {"kind": "rounds", "amount": 20, "concentration": True},
            "effects": [{"type": "lock26_seal", "applies_to": "target"}]}}),
        ActionDefinition(source_definition_id=OTHER, display_name="Lock26 Other", owner_id=info["actor_id"],
            economy="NONE", resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"source": "test:lock26.other", "numbers": info["numbers"],
                "duration": {"kind": "rounds", "amount": 20, "concentration": True}, "effects": []}})]


def _suppressed(engine, who):
    return [c for c in engine.state.actors[who].conditions.values() if c.condition_id == benefit_suppression.SUPPRESSED]


def _ward(engine, who):
    return [m for m in engine.state.actors[who].modifiers.values() if m.source_definition_id == "test:lock26.ward"]


def test_held_copy_ending_restores_only_its_own_suppression(tmp_path, monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, "lock26_seal", _seal)
    install(monkeypatch, "compile_actions", _actions)
    bundle = compile_character(_sheet([]), actor_id=ME)
    bundle["concentration_rules"] = {"capacity": "cultivation_level", "limits_by_cl": [[1, 2]]}
    session = CombatService(ROOT, tmp_path).persistence.create_match(match_seed="LOCK26-SEAL", typed_bundles=(bundle,),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}})
    mid = session.match_id
    while session.engine.state.current_actor_id != ME:
        session = _execute(tmp_path, mid)
    session = _execute(tmp_path, mid, lambda c: c.source_definition_id == SEAL and c.target_ids == (AN,))
    first = session.engine.state.actors[ME].concentration.started_sequence
    assert _suppressed(session.engine, AN) and not _ward(session.engine, AN)
    session = _execute(tmp_path, mid, lambda c: c.source_definition_id == SEAL and c.target_ids == (ME,))
    me = session.engine.state.actors[ME]
    second = me.concentration.started_sequence
    assert [s.started_sequence for _iid, s in concentration.held(me)] == [first]
    assert concentration.copies(me, SEAL) == [first, second]
    assert _suppressed(session.engine, ME) and not _ward(session.engine, ME)
    assert _suppressed(session.engine, AN)  # both copies' suppressions stand together
    session = _execute(tmp_path, mid, lambda c: c.source_definition_id == OTHER)  # the cap ends the oldest held copy
    engine = session.engine
    me = engine.state.actors[ME]
    assert me.concentration.source_definition_id == OTHER
    assert [s.started_sequence for _iid, s in concentration.held(me)] == [second]
    assert any(e.event_type == "CONCENTRATION_ENDED" and e.payload.get("held") and e.payload.get("started_sequence") == first
               for e in engine.events)
    assert not _suppressed(engine, AN) and _ward(engine, AN)       # the ended copy's target got its benefit back
    assert _suppressed(engine, ME) and not _ward(engine, ME)       # the still-held copy's target stays suppressed
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.mechanical.replay()["status"] == "PASS"
    assert _suppressed(cold.engine, ME) and not _suppressed(cold.engine, AN)
