"""Round 24 fog and targeting share viewer-specific exposure after table reload."""
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat import senses, target_knowledge
from tests.r1i_service_support import OWNER, FOE, candidate, fixture


def test_exposed_invisible_target_is_seen_by_its_owner_after_commit_and_reload(tmp_path):
    def expose(bundles):
        # Deliver synthetic condition rows through a real owned table action;
        # this isolates perception from damage rolls and separate talent costs.
        action = next(a for a in bundles[0]["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        action["parameters"]["typed"]["effects"] = [
            {"type": "condition", "condition": "invisible", "applies_to": "target", "expires_on": "UNTIL_REMOVED"},
            {"type": "exposed", "applies_to": "target", "benefits": "invisible", "against": "you", "expires_on": "UNTIL_REMOVED"},
        ]
        bundles[0].pop("bundle_sha256", None)
        bundles[0]["bundle_sha256"] = canonical_sha256(bundles[0])

    combat, table, mid, _, commit = fixture(tmp_path, ["TAL_VERDANT_GROWTH_SEED_THORN_STRIKE"],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}, bundle_transform=expose)
    commit(candidate(table, mid, "Seed-Thorn Strike", FOE))
    for current in (table, TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)):
        engine = current.combat._load_session(mid).engine
        owner, target = engine.state.actors[OWNER], engine.state.actors[FOE]
        assert any(c.condition_id == "condition:typed.invisible" for c in target.conditions.values())
        before = canonical_sha256(engine.state.model_dump(mode="json"))
        assert target_knowledge.can_see(engine, owner, target)
        assert senses.sees_hidden(engine, owner, target)
        assert FOE in current.state(mid, fog=True)["fog_perception"][OWNER]["creatures"]
        assert canonical_sha256(engine.state.model_dump(mode="json")) == before
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"
