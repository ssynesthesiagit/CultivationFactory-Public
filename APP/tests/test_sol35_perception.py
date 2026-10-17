"""Shared perception consumers through real committed table transactions."""
import pytest

from combat.canonical import canonical_sha256
from tests.h49_fog_support import assert_roundtrip, option, turn_to
from tests.r1i_service_support import OWNER, FOE, candidate, fixture


@pytest.mark.parametrize("sense,expected", [(None, "DISADVANTAGE"), ("blindsight", "NORMAL")])
def test_unblinded_alternate_sense_ignores_false_obstruction(tmp_path, sense, expected):
    def grant(bundles):
        if sense:
            bundles[0]["senses"] = {"rows": [{"sense": sense, "range_ft": 60, "when": "always"}]}
            bundles[0].pop("bundle_sha256", None)
            bundles[0]["bundle_sha256"] = canonical_sha256(bundles[0])

    combat, table, mid, _, commit = fixture(tmp_path,
        ["TAL_ILLUSION_FALSE_OBSTRUCTION", "TAL_ILLUSION_PHANTOM_STING"],
        positions={OWNER: {"x": 1, "y": 6}, FOE: {"x": 4, "y": 6},
                   "actor:factory.r1i-second": {"x": 5, "y": 6}}, bundle_transform=grant)
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"].startswith("False Obstruction"))
    commit(next(o["candidate_id"] for o in group["options"] if o.get("destination") == {"x": 4, "y": 6}))
    commit(table.state(mid)["menu"]["end_turn"])
    turn_to(table, mid, commit, OWNER)
    commit(candidate(table, mid, "Phantom Sting", FOE))
    engine = combat._load_session(mid).engine
    assert not any(c.condition_id == "condition:typed.blinded" for c in engine.state.actors[OWNER].conditions.values())
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
    assert attacks and attacks[-1].payload["mode"] == expected
    assert_roundtrip(combat, tmp_path, mid)


@pytest.mark.parametrize("mode", ["manual", "ai_attacker", "ai_both"])
def test_blinded_teleport_position_copy_keeps_destinations(tmp_path, mode):
    from tests.test_c4_teleport_sight_review import test_reaction_step_visible_destinations_pause_commit_reload
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT

    test_reaction_step_visible_destinations_pause_commit_reload(tmp_path, "blinded__blindsight", mode)
    combat = CombatService(ROOT, tmp_path)
    import base64
    (match,) = (tmp_path / "Combat" / "Matches").iterdir()
    encoded = match.name.removeprefix("m1_")
    mid = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    assert_roundtrip(combat, tmp_path, mid)
