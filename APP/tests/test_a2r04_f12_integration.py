"""Merged-main contracts: declared free fixture action and one Soot result."""
import pytest

from combat.ext.ironclad_smoke import TRACE_CONDITION
from combat.ext.smoke_tracking import TRACK
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, reload, settle, turn


def test_unperceiving_fixture_declares_its_free_primary_action(tmp_path):
    from tests.test_a2_smoke import fight, LUNG, ME, FOE as smoke_foe, use, reload as smoke_reload
    combat, table, mid = fight(tmp_path, [LUNG], unperceiving=True)
    use(combat, table, mid, "Place Smoke Trace", target=smoke_foe)
    engine = smoke_reload(combat, mid, tmp_path)
    action = engine.action_catalog["action:test.blind_deaf"]
    assert action.parameters.get("free_primary") is True
    assert any(c.source_definition_id == action.source_definition_id for c in engine.legal_candidates())
    use(combat, table, mid, "Lose sight and hearing")
    engine = smoke_reload(combat, mid, tmp_path)
    assert {"condition:typed.blinded", "condition:typed.deafened"} <= {
        c.condition_id for c in engine.state.actors[ME].conditions.values()}


@pytest.mark.parametrize("accept", [False, True])
def test_compiled_extended_follow_has_one_result_and_one_escape(tmp_path, accept):
    foe = sheet([])
    foe["ability_scores_and_statistics"]["skills"] = [{"skill": "Stealth", "bonus": 50}]
    _, table, mid = fixture(tmp_path, ["SMOKE_BASE_SMOKE_TRACE", "SMOKE_BASE_SMOKE_RESPONSES",
                                      "TAL_SMOKE_SOOT_SCENT_TRAIL"], foe_sheet=foe,
                            owner_dc=1, foe_position={"x": 4, "y": 5}, seed="F12-SOOT")
    for name in ("Place Smoke Trace", "Follow the Soot"):
        engine = reload(tmp_path, mid)
        candidate = next(c for c in engine.legal_candidates() if c.display_name == name and FOE in c.target_ids)
        settle(table, mid, candidate.candidate_id)
    engine = reload(tmp_path, mid)
    assert sum(c.condition_id == TRACE_CONDITION for c in engine.state.actors[OWNER].conditions.values()) == 1
    # Preserve main's actual bearing formatter for the extended result too.
    from combat.ext.smoke_tracking import direction
    held = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == TRACE_CONDITION)
    assert direction(engine, engine.state.actors[OWNER], held.model_dump(mode="json"), held.data) == {
        "handling": "Follow the Soot tells its caster the direction: north-east."}
    assert not any(c.condition_id == TRACK for a in engine.state.actors.values() for c in a.conditions.values())
    turn(table, mid, FOE)
    sequence = reload(tmp_path, mid).state.event_sequence
    prompts = settle(table, mid, table.state(mid)["menu"]["end_turn"],
                     picks={"choice:needle.soot_scent_escape": "first" if accept else None})
    assert sum(p["context"]["reaction_source_id"] == "choice:needle.soot_scent_escape" for p in prompts) == 1
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events if e.sequence > sequence and e.event_type == "CHECK_ROLLED"
              and e.payload.get("check") == "Stealth"]
    assert len(checks) == int(accept)
    assert bool([c for c in engine.state.actors[OWNER].conditions.values()
                 if c.condition_id == TRACE_CONDITION]) is (not accept)
