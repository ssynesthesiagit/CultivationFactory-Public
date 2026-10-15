"""Small subprocess capture for genuine pre-fix saves; no GUI or live data."""
import json
from pathlib import Path
import sys

root, data, phase, scenario = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
sys.path.insert(0, str(root))

from combat.gate4_persistence import Gate4Persistence
from combat.gate4_context import build_decision_context
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_tabletop_hunt6 as fixtures
from tests.test_friendly_fire_area_table import _commit_area_action
from tests.r10_fixup_support import fixed_dice
import pytest

fixtures.ROOT = root
if phase == "prepare":
    if scenario == "stock":
        session = Gate4Persistence(root, data).create_match(match_seed="SOL176-LEGACY", maximum_rounds=4)
        session.mechanical.explicit_snapshot()
        mid = session.match_id
    else:
        ability = "TAL_VOID_COLLAPSING_GAP" if scenario == "gap" else "tianxia.talent.space.spatial_displacement"
        combat, table, mid = fixtures.table_fight(data, [ability], ally_talents=[])
    print(mid)
else:
    mid = sys.argv[5]
    if scenario == "stock":
        persistence = Gate4Persistence(root, data)
        session = persistence.load_match(mid)
        for _ in range(6):
            policy, _ = persistence.policy_library.for_actor(session.engine.state.current_actor_id)
            context = build_decision_context(session.engine, policy, for_ai=True)
            choice = persistence.local_controller.choose_primary_action(context)
            session.execute_controller_choice(choice, controller=persistence.local_controller,
                                              policy_library=persistence.policy_library)
        loaded = persistence.load_match(mid)
    else:
        combat = CombatService(root, data)
        table = TabletopService(combat, data)
        if scenario == "gap":
            result, option = _commit_area_action(table, mid, "Collapsing Gap", {"x": 4, "y": 4})
        else:
            patch = pytest.MonkeyPatch()
            fixed_dice(patch, [1 if scenario == "fail" else 20] * 80)
            state = table.state(mid)
            group = next(g for g in state["menu"]["actions"] if g["label"] == "Spatial Displacement")
            option = next(o for o in group["options"] if fixtures.RIGHT in o["target_ids"])
            menu = state["menu"]
            result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], [])
        answers = []
        for _ in range(20):
            if result["status"] == "COMMITTED":
                break
            assert result["status"] == "REACTION_REQUIRED", result
            answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
            state = table.state(mid)
            menu = state["menu"]
            result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        assert result["status"] == "COMMITTED", result
        loaded = CombatService(root, data)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    print(json.dumps({"state": loaded.engine.state.model_dump(mode="json"),
                      "events": [event.model_dump(mode="json") for event in loaded.engine.events],
                      "rolls": [roll.model_dump(mode="json") for roll in loaded.engine.rolls]}, sort_keys=True, separators=(",", ":")))
