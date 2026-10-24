"""Flow roll scopes; the live maintenance producer is tested in test_redokensei_severing."""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, turn, reload
from tests.test_a2_body_subpaths_3 import seal
from tests.test_redokensei_acquisition import acquired_kensei
from tests.test_redokensei_severing import IRON, CHOICE, delivery, palm
from tests.hunt12_support import hit_dice


@pytest.mark.parametrize("owned,kind,hazards,expected", [
    (True, "cultivation", ["maintain:manifestation"], "DISADVANTAGE"),
    (True, "cultivation", [], "NORMAL"),
    (True, "check", ["maintain:manifestation"], "NORMAL"),
    (False, "cultivation", ["maintain:manifestation"], "NORMAL"),
])
def test_flow_scopes_survive_acquisition_commit_and_reload(tmp_path, monkeypatch, owned, kind, hazards, expected):
    hit_dice(monkeypatch, save_roll=1)
    doc = (acquired_kensei(tmp_path / "source", level=14) if owned
           else sheet([IRON], cl=14, primary="Stamina"))
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})

    def setup(bundles):
        delivery(bundles)
        seal(bundles[2], "Scoped check", [{"type": "contest_against", "applies_to": "self",
            "actor_check": {"kind": kind, "ability": "WIS", "hazards": hazards},
            "target_check": {"kind": "dc", "dc": 10}, "on_success": [], "on_fail": []}])
        bundles[2]["action_catalog"][-1]["parameters"]["free_primary"] = True
        bundles[2].pop("bundle_sha256", None)
        bundles[2]["bundle_sha256"] = canonical_sha256(bundles[2])

    combat, table, mid = fixture(tmp_path / "fight", [], owner_bundle=bundle, cl=14,
        primary="Stamina", bundle_transform=setup,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6},
                   "actor:factory.worker2-ally": {"x": 3, "y": 7}})
    prompts = palm(combat, table, mid)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts) is owned
    reload(tmp_path / "fight", mid)
    turn(table, mid, FOE)
    check = candidate(combat, mid, "Scoped check")
    settle(table, mid, check.candidate_id)
    engine = reload(tmp_path / "fight", mid)
    rolled = next(e for e in reversed(engine.events) if e.event_type == "CHECK_ROLLED"
                  and e.source_definition_id == check.source_definition_id)
    assert rolled.payload["actor"]["mode"] == expected
