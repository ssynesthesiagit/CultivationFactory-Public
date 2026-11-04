"""Prior-knowledge confirmation through real critical-hit service transactions."""
import pytest

from combat import ext
from combat.ext.maximum_hp_riders import MODIFY
from combat.ext.mind_hidden_eye import FOCUS, known_characteristic, mark_analyzed
from combat.ext.riders14_research import NOTICE
from combat.gate5_service import CombatService
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle


@pytest.mark.parametrize("ai", [False, True], ids=["manual-target", "computer-target"])
def test_modify_confirms_prior_unrecorded_knowledge_without_notice(tmp_path, monkeypatch, ai):
    def attacks(info):
        return [ActionDefinition(source_definition_id="test:critical:" + info["actor_id"], owner_id=info["actor_id"],
            display_name="Test critical attack", economy=EconomyKind.ACTION, resolution_kind="ATTACK",
            target_kind="HOSTILE_ENTITY", range_ft=60, attack_bonus=100)]

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "compile_actions", [*ext._HOOKS.get("compile_actions", []), attacks])
    install(monkeypatch, "d20_result", lambda *args: {"source_id": "test:roll", "operation": "replace", "natural_result": 20})
    def prepare(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs.get("actor_id") == OWNER:
            owner, target = (engine.state.actors[k] for k in (OWNER, FOE))
            mark_analyzed(engine, owner, target, "test:prior_analysis")
            for actor in (owner, target):
                engine._gain_resource(actor, FOCUS, 1, "test:focus")

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), prepare])
    combat, ui, mid = fixture(tmp_path, [MODIFY], seed="A2-PRIOR-KNOWLEDGE",
        foe_sheet=sheet(["TAL_THE_HIDDEN_EYE_BASE_SPHERE_FEATURES", "TAL_THE_HIDDEN_EYE_NOTICE_PROFILING"]))
    owner, target = OWNER, FOE
    turn(ui, mid, owner)
    assert act(ui, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    if ai:
        combat.set_controller_mode(mid, actor_id=target, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.actors[target]
    focus, hp = before.resources[FOCUS], before.maximum_hp
    from combat.ext.riders14_eye import has
    assert has(combat._load_session(mid).engine, before, "notice_profiling")
    assert focus > 0
    assert not known_characteristic(before, owner, "maximum_hp")
    first = act(ui, mid, "test:critical:")
    assert first["status"] == "REACTION_REQUIRED"
    assert "previously learned" in str(first["reaction"])
    # Resume the real Modify Characteristics choice after a cold service load.
    cold = CombatService(ROOT, tmp_path)
    ui = TabletopService(cold, tmp_path)
    chosen = candidate(cold, mid, "Test critical attack", target=target)
    prompts = settle(ui, mid, chosen.candidate_id, picks={"choice:needle.modify_maximum": "maximum_hp"})
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    affected = loaded.engine.state.actors[target]
    assert affected.maximum_hp == hp - 10
    assert known_characteristic(affected, owner, "maximum_hp")
    assert affected.resources[FOCUS] == focus
    assert not any(c.condition_id == NOTICE for c in affected.conditions.values())
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.eye_profile" for p in prompts)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
