"""An unconfigured model driver leaves persisted player turns byte-identical."""
import json
import shutil

from agent_seats import SeatRunner
from agent_seats.providers import ProviderRegistry
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_hunt5_player_choices import fixture


def test_no_providers_preserves_player_turn_commit_and_reload(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _, _, mid, *_ = fixture(origin, "AIR_BASE_GATHER_CURRENT")
    registry_path = tmp_path / "providers.json"
    registry_path.write_text(json.dumps({"providers": []}))
    captures = []
    for enabled in (False, True):
        data = tmp_path / ("driver" if enabled else "plain")
        shutil.copytree(origin, data)
        combat = CombatService(ROOT, data)
        table = TabletopService(combat, data)
        if enabled:
            def forbidden(*args):
                raise AssertionError("An unconfigured controller must never call a model")
            runner = SeatRunner(table, registry=ProviderRegistry(registry_path), provider=forbidden)
            assert runner.registry.public() == []
        state = table.state(mid)
        menu = state["menu"]
        result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
        reloaded = CombatService(ROOT, data)._load_session(mid)
        assert reloaded.verify()["status"] == reloaded.mechanical.replay()["status"] == "PASS"
        captures.append(json.dumps({"before": state, "result": result,
            "state": reloaded.engine.state.model_dump(mode="json"),
            "events": [e.model_dump(mode="json") for e in reloaded.engine.events]}, sort_keys=True))
        assert not list(table._match_dir(mid).glob("Agent_*"))
    assert captures[0] == captures[1]
