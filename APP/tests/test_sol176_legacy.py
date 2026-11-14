"""SOL176 continuations of saves without the new genesis policies."""
import pytest

from combat import ext
from combat.ext import subject_repositioning
from combat.gate4_context import build_decision_context
from combat.gate4_persistence import Gate4Persistence
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests import test_tabletop_hunt6 as fixtures
from tests.test_friendly_fire_area_table import _commit_area_action
from tests.r10_fixup_support import fixed_dice


@pytest.mark.parametrize("scenario", ["fail", "success", "gap", "stock"])
def test_pre_fix_saved_fight_continues_identically(tmp_path, monkeypatch, scenario):
    # Remove only the SOL176 stamps during real genesis creation, before its
    # immutable hashes are written. Other recorded policies remain intact.
    def unstamped(engine):
        event = next(e for e in engine.events if e.event_type == "MATCH_CREATED")
        for key in ("subject_repositioning_policy", "cover_anchor_expiry_policy"):
            event.payload.pop(key, None)

    # Registrations must be complete before replacing the hook list temporarily.
    ext.load_plug_ins()
    with monkeypatch.context() as creation:
        creation.setitem(ext._HOOKS, "match_start", [*ext._HOOKS["match_start"], unstamped])
        if scenario == "stock":
            session = Gate4Persistence(ROOT, tmp_path).create_match(match_seed="SOL176-LEGACY", maximum_rounds=4)
            session.mechanical.explicit_snapshot()
            mid = session.match_id
        else:
            ability = "TAL_VOID_COLLAPSING_GAP" if scenario == "gap" else "tianxia.talent.space.spatial_displacement"
            _, table, mid = fixtures.table_fight(tmp_path, [ability], ally_talents=[])

    if scenario == "stock":
        persistence = Gate4Persistence(ROOT, tmp_path)
        session = persistence.load_match(mid)
        assert not subject_repositioning.enabled(session.engine)
        for _ in range(6):
            policy, _ = persistence.policy_library.for_actor(session.engine.state.current_actor_id)
            context = build_decision_context(session.engine, policy, for_ai=True)
            choice = persistence.local_controller.choose_primary_action(context)
            session.execute_controller_choice(choice, controller=persistence.local_controller,
                                              policy_library=persistence.policy_library)
        loaded = persistence.load_match(mid)
    else:
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
        assert not subject_repositioning.enabled(combat._load_session(mid).engine)
        if scenario == "gap":
            hp_before = combat._load_session(mid).engine.state.actors[fixtures.RIGHT].current_hp
            result, option = _commit_area_action(table, mid, "Collapsing Gap", {"x": 4, "y": 4})
        else:
            fixed_dice(monkeypatch, [1 if scenario == "fail" else 20] * 80)
            state = table.state(mid)
            group = next(g for g in state["menu"]["actions"] if g["label"] == "Spatial Displacement")
            option = next(o for o in group["options"] if fixtures.RIGHT in o["target_ids"])
            menu = state["menu"]
            result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], [])
        answers = []
        saw_area_recipients = False
        for _ in range(20):
            if result["status"] == "COMMITTED":
                break
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            context = prompt["context"]
            source = context["reaction_source_id"]
            assert source != "choice:needle.subject_destination"
            choice = prompt.get("choice") or {}
            if source == "choice:needle.area_recipients":
                saw_area_recipients = True
                answers.append({**context, "selection": "USE", "option_ids": [fixtures.RIGHT]})
            elif choice and not choice.get("allow_decline"):
                minimum = int(choice.get("minimum") or 1)
                preferred = choice.get("preferred") or [row["id"] for row in choice["options"]]
                answers.append({**context, "selection": "USE", "option_ids": preferred[:minimum]})
            else:
                answers.append({**context, "selection": "DECLINE"})
            state = table.state(mid)
            menu = state["menu"]
            result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        assert result["status"] == "COMMITTED", result
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        if scenario == "gap":
            assert saw_area_recipients
            assert loaded.engine.state.actors[fixtures.RIGHT].current_hp < hp_before
    assert not subject_repositioning.enabled(loaded.engine)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
